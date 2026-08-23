from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections import deque
from threading import Event
from typing import Callable

from modules.config import find_ffmpeg, find_ffprobe, get_temp_dir, setup_logging

logger = setup_logging()


def _probe_duration_seconds(video_path: str) -> float:
    ffprobe = find_ffprobe()
    if not ffprobe:
        return 0.0

    command = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        os.path.abspath(video_path),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        if completed.returncode != 0:
            return 0.0
        return max(0.0, float((completed.stdout or "").strip()))
    except (OSError, ValueError, subprocess.TimeoutExpired):
        logger.debug("Could not probe video duration", exc_info=True, extra={"stage": "Rendering"})
        return 0.0


def burn_subtitles(
    video_path: str,
    srt_path: str,
    output_video_path: str,
    *,
    cancel_event: Event | None = None,
    progress_callback: Callable[[float, str], None] | None = None,
    font_name: str = "Arial",
    font_size: int = 24,
) -> tuple[bool, str]:
    """Hardcode verified SRT subtitles onto a video without pipe deadlocks."""
    if not os.path.isfile(video_path):
        return False, "Video file does not exist."
    if not os.path.isfile(srt_path):
        return False, "Subtitle file does not exist."

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return False, "FFmpeg was not found."

    os.makedirs(os.path.dirname(output_video_path), exist_ok=True)
    work_dir = tempfile.mkdtemp(prefix="dubora_burn_", dir=get_temp_dir())
    local_srt = os.path.join(work_dir, "subtitles.srt")
    shutil.copy2(srt_path, local_srt)

    duration = _probe_duration_seconds(video_path)

    # Short relative subtitle path from an isolated cwd avoids Windows drive/space escaping issues.
    safe_font = font_name if font_name in {"Arial", "Segoe UI", "Tahoma"} else "Arial"
    safe_size = max(18, min(40, int(font_size or 24)))
    filter_arg = f"subtitles=subtitles.srt:force_style='FontName={safe_font},FontSize={safe_size}'"
    command = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        os.path.abspath(video_path),
        "-vf",
        filter_arg,
        "-c:a",
        "copy",
        "-progress",
        "pipe:1",
        "-nostats",
        os.path.abspath(output_video_path),
    ]

    process: subprocess.Popen[str] | None = None
    recent_output: deque[str] = deque(maxlen=40)

    try:
        if progress_callback:
            progress_callback(0.0, "Rendering translated video...")

        # Merge stderr into stdout and continuously drain it. The previous code
        # piped stdout/stderr but never consumed them while FFmpeg was running,
        # which can deadlock when Windows pipe buffers fill.
        process = subprocess.Popen(
            command,
            cwd=work_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        assert process.stdout is not None

        while True:
            if cancel_event and cancel_event.is_set():
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
                return False, "Cancelled"

            line = process.stdout.readline()

            if line:
                line = line.strip()
                recent_output.append(line)

                if line.startswith("out_time_us=") and duration > 0:
                    try:
                        seconds = int(line.split("=", 1)[1]) / 1_000_000.0
                        fraction = max(0.0, min(0.995, seconds / duration))
                        if progress_callback:
                            progress_callback(
                                fraction,
                                f"Rendering translated video... {int(fraction * 100)}%",
                            )
                    except (TypeError, ValueError):
                        pass

                elif line == "progress=end":
                    if progress_callback:
                        progress_callback(1.0, "Video rendering completed")

            if process.poll() is not None:
                # Drain any final buffered output.
                for remaining in process.stdout:
                    recent_output.append(remaining.strip())
                break

        if process.returncode != 0:
            error = "\n".join(x for x in recent_output if x).strip()
            if not error:
                error = f"FFmpeg exited with {process.returncode}"
            logger.error("Video rendering failed: %s", error, extra={"stage": "Rendering"})
            return False, f"Video rendering failed: {error}"

        if progress_callback:
            progress_callback(1.0, "Video rendering completed")
        return True, output_video_path

    except OSError as exc:
        logger.exception("Video rendering failed", extra={"stage": "Rendering"})
        return False, f"Video rendering failed: {exc}"

    finally:
        if process and process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass
        shutil.rmtree(work_dir, ignore_errors=True)
