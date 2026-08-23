from __future__ import annotations

import hashlib
import json
import os
import tempfile
from typing import Any

from modules.config import get_sessions_dir


def _session_id(video_path: str) -> str:
    normalized = os.path.abspath(video_path).lower().encode("utf-8", errors="ignore")
    return hashlib.sha256(normalized).hexdigest()[:24]


def session_path(video_path: str) -> str:
    return os.path.join(get_sessions_dir(), f"{_session_id(video_path)}.json")


def load_session(video_path: str) -> dict[str, Any] | None:
    path = session_path(video_path)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError):
        return None
    return None


def save_session(video_path: str, data: dict[str, Any]) -> None:
    path = session_path(video_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix="dubora_session_", suffix=".json", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def clear_session(video_path: str) -> None:
    path = session_path(video_path)
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
