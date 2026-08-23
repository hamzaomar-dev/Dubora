from __future__ import annotations

import json
import os
import re
from typing import Any

SYSTEM_PROMPT = (
    "You are a professional Arabic subtitle translator. "
    "Translate naturally and cinematically into Arabic, respecting context, emotion, gender, and number. "
    "You will receive JSON objects containing only subtitle IDs and text. "
    "Return ONLY a JSON array with the same IDs and a 'translation' string for every item. "
    "Do not add, remove, merge, split, renumber, or explain items."
)


class GroqProvider:
    name = "groq"

    def __init__(self) -> None:
        api_key = (os.getenv("GROQ_API_KEY") or "").strip()
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is not configured on the server.")
        try:
            from groq import Groq  # type: ignore
        except ImportError as exc:
            raise RuntimeError("The groq package is not installed on the server.") from exc

        self.client = Groq(api_key=api_key)
        self.transcription_model = os.getenv("DUBORA_TRANSCRIPTION_MODEL", "whisper-large-v3-turbo")
        self.translation_model = os.getenv("DUBORA_TRANSLATION_MODEL", "llama-3.3-70b-versatile")

    @staticmethod
    def _extract_json(text: str) -> Any:
        cleaned = (text or "").strip()
        cleaned = re.sub(r"<think>.*?</think>", "", cleaned, flags=re.DOTALL | re.IGNORECASE).strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("[")
            end = cleaned.rfind("]")
            if start >= 0 and end > start:
                return json.loads(cleaned[start : end + 1])
            raise

    def transcribe(self, filename: str, content: bytes) -> list[dict]:
        transcript = self.client.audio.transcriptions.create(
            file=(filename, content),
            model=self.transcription_model,
            response_format="verbose_json",
        )
        segments = getattr(transcript, "segments", None)
        if segments is None and isinstance(transcript, dict):
            segments = transcript.get("segments")
        if segments is None:
            raise RuntimeError("Provider transcription response contained no segments.")

        result: list[dict] = []
        for segment in segments:
            if isinstance(segment, dict):
                start = segment.get("start", 0.0)
                end = segment.get("end", 0.0)
                text = segment.get("text", "")
            else:
                start = getattr(segment, "start", 0.0)
                end = getattr(segment, "end", 0.0)
                text = getattr(segment, "text", "")
            result.append({"start": float(start), "end": float(end), "text": str(text)})
        return result

    def translate(self, items: list[dict]) -> list[dict]:
        completion = self.client.chat.completions.create(
            model=self.translation_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(items, ensure_ascii=False)},
            ],
            temperature=0.2,
            max_tokens=4096,
        )
        raw = completion.choices[0].message.content
        payload = self._extract_json(raw)
        if not isinstance(payload, list):
            raise RuntimeError("Provider translation response is not a JSON array.")
        return payload
