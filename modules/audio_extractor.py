from __future__ import annotations

import os
import subprocess
import time
from threading import Event
from typing import Callable

from modules.config import find_ffmpeg, setup_logging

logger = setup_logging()


def _run_process(command: list[str], cancel_event: Event | None = None) -> tuple[bool, str]:
    try:
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
                return False, "Cancelled"
            time.sleep(0.15)

        stdout, stderr = process.communicate()
        if process.returncode != 0:
            return False, stderr.strip() or stdout.strip() or f"Process exited with {process.returncode}"
        return True, ""
    except OSError as exc:
        return False, str(exc)


def extract_audio(
    video_path: str,
    output_audio_path: str,
    cancel_event: Event | None = None,
    progress_callback: Callable[[float, str], None] | None = None,
) -> tuple[bool, str]:
    """Extract mono 16 kHz audio suitable for speech-to-text."""
    if not os.path.isfile(video_path):
        return False, "Video file does not exist."

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return False, "FFmpeg was not found. Bundle ffmpeg.exe or install FFmpeg for development."

    os.makedirs(os.path.dirname(output_audio_path), exist_ok=True)
    if progress_callback:
        progress_callback(0.0, "Preparing audio extraction")

    command = [
        ffmpeg,
        "-y",
        "-i",
        video_path,
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        output_audio_path,
    ]
    logger.info("Extracting audio", extra={"stage": "Audio"})
    ok, error = _run_process(command, cancel_event)
    if not ok:
        try:
            if os.path.exists(output_audio_path):
                os.remove(output_audio_path)
        except OSError:
            pass
        if error == "Cancelled":
            return False, "Cancelled"
        logger.error("Audio extraction failed: %s", error, extra={"stage": "Audio"})
        return False, f"Audio extraction failed: {error}"

    if progress_callback:
        progress_callback(1.0, "Audio extraction completed")
    return True, output_audio_path
