from __future__ import annotations

import os
from threading import Event
from typing import Any, Callable

from modules.config import setup_logging
from modules.gateway_client import GatewayClient, RETRYABLE_STATUS
from modules.srt_utils import SubtitleBlock, assert_integrity, build_srt, parse_srt, replace_text

logger = setup_logging()
TRANSLATION_CHUNK_SIZE = 15


def _status_code(exc: Exception) -> int | None:
    value = getattr(exc, "status_code", None)
    return value if isinstance(value, int) else None


def _should_retry(exc: Exception) -> bool:
    code = _status_code(exc)
    if code in RETRYABLE_STATUS:
        return True
    text = str(exc).lower()
    return any(term in text for term in ("timeout", "connection", "temporarily", "rate limit"))


def validate_translation_payload(payload: Any, expected_ids: list[int]) -> dict[int, str]:
    if not isinstance(payload, list):
        raise ValueError("Translation response must be a JSON array.")
    if len(payload) != len(expected_ids):
        raise ValueError(f"Translation item count mismatch: {len(payload)} != {len(expected_ids)}")

    translations: dict[int, str] = {}
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("Every translation item must be an object.")
        try:
            subtitle_id = int(item["id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Translation item is missing a valid id.") from exc
        if subtitle_id in translations:
            raise ValueError(f"Duplicate translation id: {subtitle_id}")
        translation = item.get("translation")
        if not isinstance(translation, str):
            raise ValueError(f"Translation for id {subtitle_id} must be a string.")
        if not translation.strip():
            raise ValueError(f"Translation for id {subtitle_id} is empty.")
        translations[subtitle_id] = translation.strip()

    if set(translations) != set(expected_ids):
        missing = sorted(set(expected_ids) - set(translations))
        extra = sorted(set(translations) - set(expected_ids))
        raise ValueError(f"Translation IDs mismatch. Missing={missing}, extra={extra}")
    return translations


def _request_translation(
    gateway: Any,
    items: list[dict[str, Any]],
    cancel_event: Event | None,
) -> dict[int, str]:
    if cancel_event and cancel_event.is_set():
        raise InterruptedError("Cancelled")
    expected_ids = [int(item["id"]) for item in items]
    payload = gateway.translate(items, cancel_event=cancel_event)
    return validate_translation_payload(payload, expected_ids)


def _translate_one_by_one(
    gateway: Any,
    blocks: list[SubtitleBlock],
    cancel_event: Event | None,
) -> dict[int, str]:
    result: dict[int, str] = {}
    for block in blocks:
        if cancel_event and cancel_event.is_set():
            raise InterruptedError("Cancelled")
        if not block.text.strip():
            result[block.index] = ""
            continue
        result.update(
            _request_translation(
                gateway,
                [{"id": block.index, "text": block.text}],
                cancel_event,
            )
        )
    return result


def translate_srt(
    srt_path: str,
    output_srt_path: str,
    *,
    gateway_client: GatewayClient | None = None,
    chunk_size: int = TRANSLATION_CHUNK_SIZE,
    progress_callback: Callable[[float, str], None] | None = None,
    cancel_event: Event | None = None,
    resume_data: dict[str, Any] | None = None,
    save_resume_callback: Callable[[int, dict[int, str]], None] | None = None,
) -> tuple[bool, str]:
    """Translate text through the gateway while Python exclusively owns SRT metadata."""
    if not os.path.isfile(srt_path):
        return False, "SRT file does not exist."

    gateway = gateway_client or GatewayClient()
    try:
        with open(srt_path, "r", encoding="utf-8-sig") as handle:
            original_blocks = parse_srt(handle.read())
        if not original_blocks:
            raise ValueError("Input SRT is empty.")

        completed: dict[str, Any] = dict(resume_data or {})
        translations: dict[int, str] = {}
        total_chunks = (len(original_blocks) + chunk_size - 1) // chunk_size

        for chunk_index in range(total_chunks):
            if cancel_event and cancel_event.is_set():
                return False, "Cancelled"

            chunk = original_blocks[chunk_index * chunk_size : (chunk_index + 1) * chunk_size]
            key = str(chunk_index)
            chunk_translation: dict[int, str] = {}

            if key in completed and isinstance(completed[key], dict):
                for k, v in completed[key].items():
                    try:
                        chunk_translation[int(k)] = str(v)
                    except (TypeError, ValueError):
                        pass

            expected_nonempty = [block for block in chunk if block.text.strip()]
            expected_ids = [block.index for block in expected_nonempty]
            if set(chunk_translation) != set(expected_ids):
                items = [{"id": block.index, "text": block.text} for block in expected_nonempty]
                try:
                    chunk_translation = _request_translation(gateway, items, cancel_event) if items else {}
                except InterruptedError:
                    raise
                except Exception:
                    logger.warning(
                        "Chunk %s failed validation; falling back to block-by-block translation",
                        chunk_index + 1,
                        extra={"stage": "Translation"},
                    )
                    chunk_translation = _translate_one_by_one(gateway, chunk, cancel_event)
                    chunk_translation = {k: v for k, v in chunk_translation.items() if v != ""}

                if save_resume_callback:
                    save_resume_callback(chunk_index, chunk_translation)

            for block in chunk:
                translations[block.index] = chunk_translation[block.index] if block.text.strip() else ""

            if progress_callback:
                done = min((chunk_index + 1) * chunk_size, len(original_blocks))
                progress_callback(
                    (chunk_index + 1) / total_chunks,
                    f"Translated {done}/{len(original_blocks)} subtitles (chunk {chunk_index + 1}/{total_chunks})",
                )

        translated_blocks = replace_text(original_blocks, translations)
        assert_integrity(original_blocks, translated_blocks)
        os.makedirs(os.path.dirname(output_srt_path), exist_ok=True)
        with open(output_srt_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(build_srt(translated_blocks))

        with open(output_srt_path, "r", encoding="utf-8") as handle:
            written_blocks = parse_srt(handle.read())
        assert_integrity(original_blocks, written_blocks)

        logger.info("Translation completed with verified SRT integrity", extra={"stage": "Translation"})
        return True, output_srt_path
    except InterruptedError:
        return False, "Cancelled"
    except Exception as exc:
        logger.exception("Translation failed", extra={"stage": "Translation"})
        return False, f"Translation failed: {exc}"
