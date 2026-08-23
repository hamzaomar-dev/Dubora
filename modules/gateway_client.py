from __future__ import annotations

import os
import time
from threading import Event
from typing import Any

import httpx

from modules.config import get_client_id, get_gateway_url, setup_logging

logger = setup_logging()
RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
DEFAULT_DELAYS = (2, 5, 10)


class GatewayError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _friendly_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            detail = payload.get("detail") or payload.get("message")
            if isinstance(detail, str) and detail.strip():
                return detail.strip()
    except Exception:
        pass
    text = (response.text or "").strip()
    if text and len(text) <= 300:
        return text
    return f"AI service returned HTTP {response.status_code}."


class GatewayClient:
    """Desktop-side client for Dubora's server-side AI gateway.

    No provider API key exists in the desktop app. The gateway owns provider
    credentials and models; the desktop only sends work to the gateway.
    """

    def __init__(self, base_url: str | None = None, *, timeout: float = 120.0) -> None:
        self.base_url = (base_url or get_gateway_url()).rstrip("/")
        self.timeout = timeout
        self.client_id = get_client_id()

    @property
    def headers(self) -> dict[str, str]:
        return {
            "User-Agent": "Dubora-Desktop/1.0",
            "X-Dubora-Client": self.client_id,
        }

    def _request_with_retry(
        self,
        method: str,
        path: str,
        *,
        cancel_event: Event | None = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        last_error: Exception | None = None
        for attempt, delay in enumerate((*DEFAULT_DELAYS, 0)):
            if cancel_event and cancel_event.is_set():
                raise InterruptedError("Cancelled")
            try:
                response = httpx.request(
                    method,
                    f"{self.base_url}{path}",
                    headers={**self.headers, **kwargs.pop("headers", {})},
                    timeout=timeout or self.timeout,
                    follow_redirects=False,
                    **kwargs,
                )
                if response.status_code < 400:
                    return response
                message = _friendly_error(response)
                error = GatewayError(message, response.status_code)
                last_error = error
                if response.status_code not in RETRYABLE_STATUS or attempt >= len(DEFAULT_DELAYS):
                    raise error
            except InterruptedError:
                raise
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                if attempt >= len(DEFAULT_DELAYS):
                    raise GatewayError("Could not reach the Dubora AI service. Check your internet connection.") from exc
            except GatewayError:
                raise

            # Sleep in small intervals so Cancel remains responsive between retries.
            end = time.monotonic() + delay
            while time.monotonic() < end:
                if cancel_event and cancel_event.is_set():
                    raise InterruptedError("Cancelled")
                time.sleep(min(0.1, max(0.0, end - time.monotonic())))

        raise GatewayError(f"AI service request failed: {last_error}")

    def health(self) -> dict[str, Any]:
        try:
            response = httpx.get(
                f"{self.base_url}/health",
                headers=self.headers,
                timeout=12.0,
                follow_redirects=False,
            )
            if response.status_code != 200:
                return {"ok": False, "message": _friendly_error(response)}
            payload = response.json()
            if not isinstance(payload, dict):
                return {"ok": False, "message": "Invalid AI service response."}
            return payload
        except Exception as exc:
            logger.info("Gateway health check unavailable: %s", exc, extra={"stage": "Gateway"})
            return {"ok": False, "message": "AI service is unavailable."}

    def transcribe(self, audio_path: str, cancel_event: Event | None = None) -> list[dict[str, Any]]:
        if not os.path.isfile(audio_path):
            raise GatewayError("Audio chunk does not exist.")
        with open(audio_path, "rb") as handle:
            audio_bytes = handle.read()
        response = self._request_with_retry(
            "POST",
            "/v1/transcribe",
            cancel_event=cancel_event,
            timeout=180.0,
            files={"file": (os.path.basename(audio_path), audio_bytes, "audio/wav")},
        )
        payload = response.json()
        segments = payload.get("segments") if isinstance(payload, dict) else None
        if not isinstance(segments, list):
            raise GatewayError("AI service returned an invalid transcription response.")
        normalized: list[dict[str, Any]] = []
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            text = str(segment.get("text", "")).strip()
            try:
                start = float(segment.get("start", 0.0))
                end = float(segment.get("end", 0.0))
            except (TypeError, ValueError):
                continue
            normalized.append({"start": start, "end": end, "text": text})
        return normalized

    def translate(self, items: list[dict[str, Any]], cancel_event: Event | None = None) -> list[dict[str, Any]]:
        response = self._request_with_retry(
            "POST",
            "/v1/translate",
            cancel_event=cancel_event,
            timeout=120.0,
            json={"items": items},
        )
        payload = response.json()
        result = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(result, list):
            raise GatewayError("AI service returned an invalid translation response.")
        return result
