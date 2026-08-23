from __future__ import annotations

import math
import os
import subprocess
import time
from threading import Event
from typing import Any, Callable

from modules.config import find_ffmpeg, find_ffprobe, get_temp_dir, setup_logging
from modules.gateway_client import GatewayClient
from modules.srt_utils import SubtitleBlock, build_srt

logger = setup_logging()
CHUNK_SECONDS = 600


def format_timestamp(seconds: float) -> str:
    total_ms = max(0, int(round(float(seconds) * 1000)))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def _probe_duration(path: str) -> float:
    ffprobe = find_ffprobe()
    if not ffprobe:
        raise RuntimeError("ffprobe was not found. Bundle ffprobe.exe or install FFmpeg for development.")
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            path,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Could not read media duration.")
    return float(result.stdout.strip())


def _create_chunk(
    audio_path: str,
    chunk_path: str,
    start_seconds: float,
    duration_seconds: float,
    cancel_event: Event | None,
) -> None:
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("FFmpeg was not found.")

    command = [
        ffmpeg,
        "-y",
        "-ss",
        f"{start_seconds:.3f}",
        "-i",
        audio_path,
        "-t",
        f"{duration_seconds:.3f}",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        chunk_path,
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    while process.poll() is None:
        if cancel_event and cancel_event.is_set():
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
            try:
                if os.path.exists(chunk_path):
                    os.remove(chunk_path)
            except OSError:
                pass
            raise InterruptedError("Cancelled")
        time.sleep(0.1)
    _, stderr = process.communicate()
    if process.returncode != 0:
        raise RuntimeError(stderr.strip() or "Audio chunk creation failed.")


def transcribe_audio(
    audio_path: str,
    output_srt_path: str,
    *,
    gateway_client: GatewayClient | None = None,
    progress_callback: Callable[[float, str], None] | None = None,
    cancel_event: Event | None = None,
    resume_data: dict[str, Any] | None = None,
    save_resume_callback: Callable[[int, list[dict[str, Any]]], None] | None = None,
    chunk_seconds: int = CHUNK_SECONDS,
) -> tuple[bool, str]:
    """Chunk long audio locally, transcribe through Dubora Gateway, and merge exact offsets."""
    if not os.path.isfile(audio_path):
        return False, "Audio file does not exist."

    gateway = gateway_client or GatewayClient()
    try:
        duration = _probe_duration(audio_path)
        safe_chunk_seconds = max(120, min(900, int(chunk_seconds or CHUNK_SECONDS)))
        total_chunks = max(1, int(math.ceil(duration / safe_chunk_seconds)))
        task_name = os.path.splitext(os.path.basename(audio_path))[0]
        chunk_dir = os.path.join(get_temp_dir(), f"{task_name}_audio_chunks")
        os.makedirs(chunk_dir, exist_ok=True)
        completed: dict[str, Any] = dict(resume_data or {})
        merged_segments: list[dict[str, Any]] = []

        for index in range(total_chunks):
            if cancel_event and cancel_event.is_set():
                return False, "Cancelled"

            start = index * safe_chunk_seconds
            chunk_duration = min(safe_chunk_seconds, max(0.001, duration - start))
            key = str(index)
            if key in completed and isinstance(completed[key], list):
                local_segments = completed[key]
            else:
                chunk_path = os.path.join(chunk_dir, f"chunk_{index:04d}.wav")
                if not os.path.isfile(chunk_path):
                    _create_chunk(audio_path, chunk_path, start, chunk_duration, cancel_event)
                local_segments = gateway.transcribe(chunk_path, cancel_event=cancel_event)
                completed[key] = local_segments
                if save_resume_callback:
                    save_resume_callback(index, local_segments)

            for segment in local_segments:
                try:
                    seg_start = float(segment.get("start", 0.0))
                    seg_end = float(segment.get("end", 0.0))
                except (TypeError, ValueError):
                    continue
                merged_segments.append(
                    {
                        "start": seg_start + start,
                        "end": seg_end + start,
                        "text": str(segment.get("text", "")).strip(),
                    }
                )

            if progress_callback:
                progress_callback(
                    (index + 1) / total_chunks,
                    f"Transcribed chunk {index + 1}/{total_chunks}",
                )

        blocks: list[SubtitleBlock] = []
        for segment in merged_segments:
            text = str(segment["text"]).strip()
            if not text:
                continue
            blocks.append(
                SubtitleBlock(
                    index=len(blocks) + 1,
                    start=format_timestamp(float(segment["start"])),
                    end=format_timestamp(float(segment["end"])),
                    text=text,
                )
            )

        if not blocks:
            raise RuntimeError("AI transcription service returned no subtitle segments.")

        os.makedirs(os.path.dirname(output_srt_path), exist_ok=True)
        with open(output_srt_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(build_srt(blocks))

        import shutil

        shutil.rmtree(chunk_dir, ignore_errors=True)
        logger.info("Transcription completed with %s subtitle blocks", len(blocks), extra={"stage": "Transcription"})
        return True, output_srt_path
    except InterruptedError:
        return False, "Cancelled"
    except Exception as exc:
        logger.exception("Transcription failed", extra={"stage": "Transcription"})
        return False, f"Transcription failed: {exc}"
