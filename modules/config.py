from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
import os
import re
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

DEFAULT_GATEWAY_URL = "http://127.0.0.1:8787"

_SECRET_RE = re.compile(r"gsk_[A-Za-z0-9_-]+")


def resource_path(relative_path: str) -> str:
    """Absolute path to a bundled resource in dev or PyInstaller mode."""
    base_path = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


def _local_app_data() -> str:
    if os.name == "nt":
        return os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or os.path.expanduser("~")
    return os.getenv("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")


def get_app_dir() -> str:
    path = os.path.join(_local_app_data(), "Dubora")
    os.makedirs(path, exist_ok=True)
    return path


def get_temp_dir() -> str:
    path = os.path.join(get_app_dir(), "temp")
    os.makedirs(path, exist_ok=True)
    return path


def get_logs_dir() -> str:
    path = os.path.join(get_app_dir(), "logs")
    os.makedirs(path, exist_ok=True)
    return path


def get_sessions_dir() -> str:
    path = os.path.join(get_app_dir(), "sessions")
    os.makedirs(path, exist_ok=True)
    return path


def get_default_output_dir() -> str:
    documents = Path.home() / "Documents"
    base = documents if documents.exists() else Path.home()
    output = base / "Dubora"
    output.mkdir(parents=True, exist_ok=True)
    return str(output)


def get_gateway_url() -> str:
    """Return the build-time/public Dubora gateway URL.

    Developers can override it with DUBORA_API_BASE_URL. For a public EXE,
    set gateway_url.txt before building so end users never configure AI keys.
    """
    env_url = (os.getenv("DUBORA_API_BASE_URL") or "").strip()
    if env_url:
        return env_url.rstrip("/")
    try:
        with open(resource_path("gateway_url.txt"), "r", encoding="utf-8") as handle:
            bundled = handle.read().strip()
        if bundled.startswith(("http://", "https://")):
            return bundled.rstrip("/")
    except OSError:
        pass
    return DEFAULT_GATEWAY_URL


def _settings_path() -> str:
    return os.path.join(get_app_dir(), "settings.json")


def load_settings() -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "output_dir": get_default_output_dir(),
        "client_id": "",
        "auto_open_output": False,
        "translation_chunk_size": 15,
        "transcription_chunk_minutes": 10,
        "subtitle_font_name": "Arial",
        "subtitle_font_size": 24,
    }
    try:
        with open(_settings_path(), "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            defaults.update({k: data[k] for k in defaults if k in data})
    except (OSError, json.JSONDecodeError):
        pass

    if not isinstance(defaults.get("output_dir"), str) or not defaults["output_dir"].strip():
        defaults["output_dir"] = get_default_output_dir()
    defaults["output_dir"] = os.path.abspath(str(defaults["output_dir"]))

    client_id = defaults.get("client_id")
    if not isinstance(client_id, str) or not client_id.strip():
        defaults["client_id"] = str(uuid.uuid4())

    defaults["auto_open_output"] = bool(defaults.get("auto_open_output", False))
    try:
        defaults["translation_chunk_size"] = max(5, min(30, int(defaults.get("translation_chunk_size", 15))))
    except (TypeError, ValueError):
        defaults["translation_chunk_size"] = 15
    try:
        defaults["transcription_chunk_minutes"] = max(2, min(15, int(defaults.get("transcription_chunk_minutes", 10))))
    except (TypeError, ValueError):
        defaults["transcription_chunk_minutes"] = 10

    allowed_fonts = {"Arial", "Segoe UI", "Tahoma"}
    font = str(defaults.get("subtitle_font_name") or "Arial")
    defaults["subtitle_font_name"] = font if font in allowed_fonts else "Arial"
    try:
        defaults["subtitle_font_size"] = max(18, min(40, int(defaults.get("subtitle_font_size", 24))))
    except (TypeError, ValueError):
        defaults["subtitle_font_size"] = 24

    os.makedirs(defaults["output_dir"], exist_ok=True)
    with open(_settings_path(), "w", encoding="utf-8") as handle:
        json.dump(defaults, handle, ensure_ascii=False, indent=2)
    return defaults


def save_settings(settings: dict[str, Any]) -> dict[str, Any]:
    current = load_settings()
    if not isinstance(settings, dict):
        return current

    output_dir = settings.get("output_dir")
    if isinstance(output_dir, str) and output_dir.strip():
        current["output_dir"] = os.path.abspath(output_dir.strip())

    if "auto_open_output" in settings:
        current["auto_open_output"] = bool(settings["auto_open_output"])

    if "translation_chunk_size" in settings:
        try:
            current["translation_chunk_size"] = max(5, min(30, int(settings["translation_chunk_size"])))
        except (TypeError, ValueError):
            pass

    if "transcription_chunk_minutes" in settings:
        try:
            current["transcription_chunk_minutes"] = max(2, min(15, int(settings["transcription_chunk_minutes"])))
        except (TypeError, ValueError):
            pass

    allowed_fonts = {"Arial", "Segoe UI", "Tahoma"}
    if settings.get("subtitle_font_name") in allowed_fonts:
        current["subtitle_font_name"] = settings["subtitle_font_name"]

    if "subtitle_font_size" in settings:
        try:
            current["subtitle_font_size"] = max(18, min(40, int(settings["subtitle_font_size"])))
        except (TypeError, ValueError):
            pass

    os.makedirs(current["output_dir"], exist_ok=True)
    with open(_settings_path(), "w", encoding="utf-8") as handle:
        json.dump(current, handle, ensure_ascii=False, indent=2)
    return current

def get_client_id() -> str:
    return str(load_settings()["client_id"])


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "stage"):
            record.stage = "General"
        message = super().format(record)
        return _SECRET_RE.sub("gsk_[REDACTED]", message)


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("Dubora")
    logger.setLevel(logging.DEBUG)
    if logger.handlers:
        return logger

    formatter = RedactingFormatter("%(asctime)s - %(levelname)s - [%(stage)s] - %(message)s")
    file_handler = RotatingFileHandler(
        os.path.join(get_logs_dir(), "Dubora.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)

    if not getattr(sys, "frozen", False):
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        stream_handler.setLevel(logging.INFO)
        logger.addHandler(stream_handler)

    return logger


def _first_existing(candidates: list[str | None]) -> str | None:
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return os.path.abspath(candidate)
    return None


def find_ffmpeg() -> str | None:
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    candidates: list[str | None] = [
        resource_path(os.path.join("ffmpeg", "bin", exe)),
        resource_path(exe),
        shutil.which("ffmpeg"),
    ]
    try:
        import imageio_ffmpeg  # type: ignore
        candidates.append(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        pass
    return _first_existing(candidates)


def find_ffprobe() -> str | None:
    exe = "ffprobe.exe" if os.name == "nt" else "ffprobe"
    candidates: list[str | None] = [
        resource_path(os.path.join("ffmpeg", "bin", exe)),
        resource_path(exe),
        shutil.which("ffprobe"),
    ]
    return _first_existing(candidates)


def cleanup_old_temp_files(max_age_hours: int = 24) -> None:
    import time

    cutoff = time.time() - max_age_hours * 3600
    temp_dir = get_temp_dir()
    for entry in os.scandir(temp_dir):
        try:
            if entry.stat(follow_symlinks=False).st_mtime < cutoff:
                if entry.is_dir(follow_symlinks=False):
                    shutil.rmtree(entry.path, ignore_errors=True)
                else:
                    os.remove(entry.path)
        except OSError:
            pass
