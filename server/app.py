from __future__ import annotations

import logging
import os
import threading
import time
from collections import defaultdict, deque
from typing import Annotated

from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from server.providers.factory import create_provider

APP_NAME = "Dubora AI Gateway"
MAX_AUDIO_BYTES = int(os.getenv("DUBORA_MAX_AUDIO_BYTES", str(24 * 1024 * 1024)))
MAX_TRANSLATION_ITEMS = int(os.getenv("DUBORA_MAX_TRANSLATION_ITEMS", "30"))
MAX_TRANSLATION_CHARS = int(os.getenv("DUBORA_MAX_TRANSLATION_CHARS", "20000"))
RATE_PER_MINUTE = int(os.getenv("DUBORA_RATE_LIMIT_PER_MINUTE", "30"))
RATE_PER_DAY = int(os.getenv("DUBORA_RATE_LIMIT_PER_DAY", "500"))

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("dubora.gateway")
app = FastAPI(title=APP_NAME, docs_url=None, redoc_url=None)


class TranslationItem(BaseModel):
    id: int
    text: str = Field(max_length=5000)


class TranslationRequest(BaseModel):
    items: list[TranslationItem]


class InMemoryRateLimiter:
    """Small Beta limiter. Replace with Redis/DB for multi-instance production."""

    def __init__(self) -> None:
        self._minute: dict[str, deque[float]] = defaultdict(deque)
        self._day: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    @staticmethod
    def _trim(bucket: deque[float], cutoff: float) -> None:
        while bucket and bucket[0] < cutoff:
            bucket.popleft()

    def check(self, key: str) -> None:
        now = time.time()
        with self._lock:
            minute = self._minute[key]
            day = self._day[key]
            self._trim(minute, now - 60)
            self._trim(day, now - 86_400)
            if len(minute) >= RATE_PER_MINUTE or len(day) >= RATE_PER_DAY:
                raise HTTPException(status_code=429, detail="Dubora AI usage limit reached. Please try again later.")
            minute.append(now)
            day.append(now)


limiter = InMemoryRateLimiter()
_provider = None
_provider_lock = threading.Lock()


def get_provider():
    global _provider
    if _provider is None:
        with _provider_lock:
            if _provider is None:
                _provider = create_provider()
    return _provider


def _client_key(request: Request, client_id: str | None) -> str:
    ip = request.client.host if request.client else "unknown"
    clean_id = (client_id or "anonymous").strip()[:80]
    return f"{ip}:{clean_id}"


def _provider_status_code(exc: Exception) -> int:
    code = getattr(exc, "status_code", None)
    if isinstance(code, int) and 400 <= code <= 599:
        return code
    response = getattr(exc, "response", None)
    code = getattr(response, "status_code", None)
    return code if isinstance(code, int) and 400 <= code <= 599 else 502


@app.get("/health")
def health():
    try:
        provider = get_provider()
        return {"ok": True, "service": "Dubora AI", "provider": provider.name, "message": "AI service is ready."}
    except Exception as exc:
        logger.error("Provider is not ready: %s", exc)
        return {"ok": False, "service": "Dubora AI", "message": "AI provider is not configured."}


@app.post("/v1/transcribe")
async def transcribe(
    request: Request,
    file: Annotated[UploadFile, File(...)],
    x_dubora_client: Annotated[str | None, Header()] = None,
):
    limiter.check(_client_key(request, x_dubora_client))
    filename = os.path.basename(file.filename or "audio.wav")
    extension = os.path.splitext(filename)[1].lower()
    if extension not in {".wav", ".mp3", ".m4a", ".ogg", ".flac"}:
        raise HTTPException(status_code=415, detail="Unsupported audio format.")

    content = await file.read(MAX_AUDIO_BYTES + 1)
    if len(content) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio chunk is too large for the Dubora AI service.")
    if not content:
        raise HTTPException(status_code=400, detail="Audio file is empty.")

    try:
        segments = get_provider().transcribe(filename, content)
        return {"segments": segments}
    except HTTPException:
        raise
    except Exception as exc:
        status = _provider_status_code(exc)
        logger.warning("Transcription provider failure: %s", type(exc).__name__)
        detail = "AI transcription service is temporarily unavailable." if status >= 500 else "AI transcription request was rejected."
        raise HTTPException(status_code=status, detail=detail) from exc


@app.post("/v1/translate")
def translate(
    payload: TranslationRequest,
    request: Request,
    x_dubora_client: Annotated[str | None, Header()] = None,
):
    limiter.check(_client_key(request, x_dubora_client))
    if not payload.items:
        raise HTTPException(status_code=400, detail="No subtitle items were provided.")
    if len(payload.items) > MAX_TRANSLATION_ITEMS:
        raise HTTPException(status_code=413, detail="Too many subtitle items in one request.")

    items = [{"id": item.id, "text": item.text} for item in payload.items]
    if len({item["id"] for item in items}) != len(items):
        raise HTTPException(status_code=400, detail="Duplicate subtitle IDs are not allowed.")
    total_chars = sum(len(item["text"]) for item in items)
    if total_chars > MAX_TRANSLATION_CHARS:
        raise HTTPException(status_code=413, detail="Translation payload is too large.")

    try:
        translated = get_provider().translate(items)
    except Exception as exc:
        status = _provider_status_code(exc)
        logger.warning("Translation provider failure: %s", type(exc).__name__)
        detail = "AI translation service is temporarily unavailable." if status >= 500 else "AI translation request was rejected."
        raise HTTPException(status_code=status, detail=detail) from exc

    expected = {item["id"] for item in items}
    normalized: list[dict] = []
    seen: set[int] = set()
    for item in translated:
        if not isinstance(item, dict):
            raise HTTPException(status_code=502, detail="AI provider returned malformed translation data.")
        try:
            subtitle_id = int(item["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=502, detail="AI provider returned invalid subtitle IDs.") from exc
        text = item.get("translation")
        if subtitle_id in seen or subtitle_id not in expected or not isinstance(text, str) or not text.strip():
            raise HTTPException(status_code=502, detail="AI provider returned incomplete translation data.")
        seen.add(subtitle_id)
        normalized.append({"id": subtitle_id, "translation": text.strip()})

    if seen != expected:
        raise HTTPException(status_code=502, detail="AI provider returned missing subtitle translations.")
    return {"items": normalized}
