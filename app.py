from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import subprocess
import sys
from datetime import datetime
from typing import Any

import webview

from modules.audio_extractor import extract_audio
from modules.config import (
    cleanup_old_temp_files,
    find_ffmpeg,
    find_ffprobe,
    get_gateway_url,
    get_logs_dir,
    get_temp_dir,
    load_settings,
    resource_path,
    save_settings,
    setup_logging,
)
from modules.gateway_client import GatewayClient
from modules.session import clear_session, load_session, save_session
from modules.transcriber import transcribe_audio
from modules.translator import translate_srt
from modules.video_burner import burn_subtitles

logger = setup_logging()
SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov"}
PIPELINE_VERSION = "gateway-v1"


class Api:
    def __init__(self) -> None:
        self._cancel_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def _window(self):
        return webview.windows[0] if webview.windows else None

    def _call_js(self, function_name: str, *args: Any) -> None:
        window = self._window
        if not window:
            return
        payload = json.dumps(args, ensure_ascii=False)
        try:
            window.evaluate_js(f"{function_name}(...{payload})")
        except Exception:
            logger.debug("UI callback failed", exc_info=True, extra={"stage": "UI"})

    def _send_progress(self, percent: float, text: str, status: str) -> None:
        safe_percent = max(0, min(100, int(round(percent))))
        self._call_js("updateProgress", safe_percent, str(text), str(status))

    def select_video(self):
        try:
            result = self._window.create_file_dialog(
                webview.OPEN_DIALOG,
                file_types=("Video Files (*.mp4;*.mkv;*.avi;*.mov)",),
            )
            if not result:
                return None
            path = os.path.abspath(result[0])
            extension = os.path.splitext(path)[1].lower()
            if extension not in SUPPORTED_VIDEO_EXTENSIONS or not os.path.isfile(path):
                return "ERROR: Unsupported or missing video file."
            return path
        except Exception as exc:
            logger.exception("Video selection failed", extra={"stage": "UI"})
            return f"ERROR: {exc}"

    def set_video_path(self, path: str):
        try:
            candidate = os.path.abspath(str(path or ""))
            extension = os.path.splitext(candidate)[1].lower()
            if extension not in SUPPORTED_VIDEO_EXTENSIONS or not os.path.isfile(candidate):
                return {"success": False, "message": "Unsupported or missing video file."}
            return {"success": True, "path": candidate}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def open_path(self, path: str):
        try:
            candidate = os.path.abspath(str(path or ""))
            if not os.path.exists(candidate):
                return {"success": False, "message": "Path does not exist."}
            if os.name == "nt":
                os.startfile(candidate)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", candidate])
            else:
                subprocess.Popen(["xdg-open", candidate])
            return {"success": True}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def open_output_folder(self):
        return self.open_path(load_settings()["output_dir"])

    def get_projects(self):
        output_dir = load_settings()["output_dir"]
        projects: list[dict[str, Any]] = []
        try:
            for entry in os.scandir(output_dir):
                if not entry.is_file() or not entry.name.lower().endswith("_subtitled.mp4"):
                    continue
                stat = entry.stat()
                base = entry.name[:-len("_subtitled.mp4")]
                projects.append({
                    "name": base,
                    "video_path": entry.path,
                    "folder": output_dir,
                    "size": f"{stat.st_size / (1024 * 1024):.1f} MB",
                    "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                })
            projects.sort(key=lambda item: item["modified"], reverse=True)
        except OSError:
            logger.exception("Could not read projects", extra={"stage": "Projects"})
        return projects[:50]

    def get_recent_logs(self, lines: int = 300):
        try:
            log_path = os.path.join(get_logs_dir(), "Dubora.log")
            if not os.path.isfile(log_path):
                return ""
            safe_lines = max(20, min(1000, int(lines or 300)))
            with open(log_path, "r", encoding="utf-8", errors="replace") as handle:
                content = handle.readlines()
            return "".join(content[-safe_lines:])
        except Exception as exc:
            return f"Could not read log: {exc}"

    def clear_logs(self):
        try:
            log_path = os.path.join(get_logs_dir(), "Dubora.log")
            if os.path.isfile(log_path):
                with open(log_path, "w", encoding="utf-8"):
                    pass
            return {"success": True}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def window_minimize(self):
        if self._window:
            self._window.minimize()
        return True

    def window_toggle_maximize(self):
        if self._window:
            try:
                self._window.toggle_fullscreen()
            except Exception:
                self._window.maximize()
        return True

    def window_close(self):
        if self._window:
            self._window.destroy()
        return True

    def select_output_folder(self):
        try:
            result = self._window.create_file_dialog(webview.FOLDER_DIALOG)
            if not result:
                return None
            path = os.path.abspath(result[0])
            os.makedirs(path, exist_ok=True)
            save_settings({"output_dir": path})
            return path
        except Exception as exc:
            logger.exception("Output folder selection failed", extra={"stage": "Settings"})
            return f"ERROR: {exc}"

    def get_settings(self):
        settings = load_settings()
        health = GatewayClient().health()
        return {
            "output_dir": settings["output_dir"],
            "ai_service_ready": bool(health.get("ok")),
            "ai_service_message": str(health.get("message") or ""),
            "ffmpeg_ready": bool(find_ffmpeg()),
            "ffprobe_ready": bool(find_ffprobe()),
            "gateway_host": get_gateway_url(),
            "auto_open_output": bool(settings.get("auto_open_output", False)),
            "translation_chunk_size": int(settings.get("translation_chunk_size", 15)),
            "transcription_chunk_minutes": int(settings.get("transcription_chunk_minutes", 10)),
            "subtitle_font_name": str(settings.get("subtitle_font_name", "Arial")),
            "subtitle_font_size": int(settings.get("subtitle_font_size", 24)),
        }

    def save_preferences(self, preferences):
        try:
            if isinstance(preferences, str):
                payload: dict[str, Any] = {"output_dir": os.path.abspath(preferences)} if preferences else {}
            elif isinstance(preferences, dict):
                payload = dict(preferences)
                if isinstance(payload.get("output_dir"), str) and payload["output_dir"].strip():
                    payload["output_dir"] = os.path.abspath(payload["output_dir"].strip())
            else:
                payload = {}
            return {"success": True, "settings": save_settings(payload)}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def test_ai_service(self):
        result = GatewayClient().health()
        if result.get("ok"):
            return {"success": True, "message": "Dubora AI service is online and ready."}
        return {
            "success": False,
            "message": str(result.get("message") or "Dubora AI service is unavailable."),
        }

    def has_resumable_session(self, video_path: str):
        if not video_path:
            return False
        state = load_session(video_path)
        return bool(state and state.get("status") not in {"completed", "discarded"})

    def discard_session(self, video_path: str):
        state = load_session(video_path) or {}
        temp_dir = state.get("task_temp_dir")
        if isinstance(temp_dir, str) and os.path.isdir(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        clear_session(video_path)
        return {"success": True}

    def start_full_pipeline(self, video_path: str, resume: bool = True):
        if not video_path or not os.path.isfile(video_path):
            return {"success": False, "message": "Video file is missing."}
        if os.path.splitext(video_path)[1].lower() not in SUPPORTED_VIDEO_EXTENSIONS:
            return {"success": False, "message": "Unsupported video format."}
        if not find_ffmpeg() or not find_ffprobe():
            return {
                "success": False,
                "message": "FFmpeg and ffprobe are required. Bundle both binaries or install them for development.",
            }
        with self._lock:
            if self._worker and self._worker.is_alive():
                return {"success": False, "message": "Another task is already running."}
            self._cancel_event.clear()
            self._worker = threading.Thread(
                target=self._run_pipeline,
                args=(os.path.abspath(video_path), bool(resume)),
                daemon=True,
            )
            self._worker.start()
        return {"success": True, "message": "Pipeline started."}

    def cancel_operation(self):
        self._cancel_event.set()
        return {"success": True, "message": "Cancellation requested. Your resumable session will be kept."}

    def _run_pipeline(self, video_path: str, resume: bool) -> None:
        settings = load_settings()
        gateway = GatewayClient()
        base = os.path.splitext(os.path.basename(video_path))[0]
        task_id = hashlib.sha256(video_path.lower().encode("utf-8", errors="ignore")).hexdigest()[:16]
        task_temp_dir = os.path.join(get_temp_dir(), task_id)

        state = load_session(video_path) if resume else None
        if not isinstance(state, dict):
            state = {}

        # Direct-provider sessions from older builds are intentionally invalidated.
        if state and state.get("pipeline_version") != PIPELINE_VERSION:
            old_temp = state.get("task_temp_dir")
            if isinstance(old_temp, str) and os.path.isdir(old_temp):
                shutil.rmtree(old_temp, ignore_errors=True)
            state = {}

        source_stat = os.stat(video_path)
        source_signature = {"size": source_stat.st_size, "mtime_ns": source_stat.st_mtime_ns}
        if state and state.get("source_signature") != source_signature:
            old_temp = state.get("task_temp_dir")
            if isinstance(old_temp, str) and os.path.isdir(old_temp):
                shutil.rmtree(old_temp, ignore_errors=True)
            state = {}

        output_dir = state.get("output_dir") or settings["output_dir"]
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(task_temp_dir, exist_ok=True)

        state.update(
            {
                "pipeline_version": PIPELINE_VERSION,
                "video_path": video_path,
                "source_signature": source_signature,
                "output_dir": output_dir,
                "task_temp_dir": task_temp_dir,
                "status": "running",
            }
        )

        audio_path = state.get("audio_path") or os.path.join(task_temp_dir, f"{base}.wav")
        original_srt = state.get("original_srt_path") or os.path.join(output_dir, f"{base}_original.srt")
        translated_srt = state.get("translated_srt_path") or os.path.join(output_dir, f"{base}_translated.srt")
        final_video = state.get("final_video_path") or os.path.join(output_dir, f"{base}_subtitled.mp4")
        state.update(
            {
                "audio_path": audio_path,
                "original_srt_path": original_srt,
                "translated_srt_path": translated_srt,
                "final_video_path": final_video,
            }
        )
        save_session(video_path, state)

        def fail(message: str) -> None:
            state["status"] = "cancelled" if message == "Cancelled" else "failed"
            state["last_error"] = "" if message == "Cancelled" else message
            save_session(video_path, state)
            if message == "Cancelled":
                self._send_progress(state.get("last_percent", 0), "Cancelled. Session saved for resume.", "Cancelled")
            else:
                self._send_progress(state.get("last_percent", 0), message, "Failed")

        try:
            audio_ready_stages = {
                "audio_ready",
                "transcribing",
                "transcription_ready",
                "translating",
                "translation_ready",
                "completed",
            }
            audio_is_reusable = os.path.isfile(audio_path) and state.get("stage") in audio_ready_stages
            if not audio_is_reusable:
                try:
                    if os.path.exists(audio_path):
                        os.remove(audio_path)
                except OSError:
                    pass
                self._send_progress(3, "Extracting audio...", "Extracting")
                ok, message = extract_audio(video_path, audio_path, cancel_event=self._cancel_event)
                if not ok:
                    fail(message)
                    return
                state["stage"] = "audio_ready"
                state["last_percent"] = 15
                save_session(video_path, state)
            self._send_progress(15, "Audio ready.", "Extracting")

            transcription_resume = state.setdefault("transcription_chunks", {})

            def save_transcription_chunk(index: int, segments: list[dict[str, Any]]) -> None:
                transcription_resume[str(index)] = segments
                state["stage"] = "transcribing"
                save_session(video_path, state)

            def transcription_progress(fraction: float, text: str) -> None:
                percent = 15 + fraction * 40
                state["last_percent"] = percent
                self._send_progress(percent, text, "Transcribing")

            should_transcribe = not os.path.isfile(original_srt) or state.get("stage") in {"audio_ready", "transcribing"}
            if should_transcribe:
                ok, message = transcribe_audio(
                    audio_path,
                    original_srt,
                    gateway_client=gateway,
                    progress_callback=transcription_progress,
                    cancel_event=self._cancel_event,
                    resume_data=transcription_resume,
                    save_resume_callback=save_transcription_chunk,
                    chunk_seconds=int(settings.get("transcription_chunk_minutes", 10)) * 60,
                )
                if not ok:
                    fail(message)
                    return
                state["stage"] = "transcription_ready"
                state["last_percent"] = 55
                save_session(video_path, state)

            translation_resume = state.setdefault("translation_chunks", {})

            def save_translation_chunk(index: int, translations: dict[int, str]) -> None:
                translation_resume[str(index)] = {str(k): v for k, v in translations.items()}
                state["stage"] = "translating"
                save_session(video_path, state)

            def translation_progress(fraction: float, text: str) -> None:
                percent = 55 + fraction * 30
                state["last_percent"] = percent
                self._send_progress(percent, text, "Translating")

            should_translate = not os.path.isfile(translated_srt) or state.get("stage") in {"transcription_ready", "translating"}
            if should_translate:
                ok, message = translate_srt(
                    original_srt,
                    translated_srt,
                    gateway_client=gateway,
                    progress_callback=translation_progress,
                    cancel_event=self._cancel_event,
                    resume_data=translation_resume,
                    save_resume_callback=save_translation_chunk,
                    chunk_size=int(settings.get("translation_chunk_size", 15)),
                )
                if not ok:
                    fail(message)
                    return
                state["stage"] = "translation_ready"
                state["last_percent"] = 85
                save_session(video_path, state)

            def rendering_progress(fraction: float, text: str) -> None:
                percent = 85 + fraction * 14
                state["last_percent"] = percent
                self._send_progress(percent, text, "Rendering")

            ok, message = burn_subtitles(
                video_path,
                translated_srt,
                final_video,
                cancel_event=self._cancel_event,
                progress_callback=rendering_progress,
                font_name=str(settings.get("subtitle_font_name", "Arial")),
                font_size=int(settings.get("subtitle_font_size", 24)),
            )
            if not ok:
                fail(message)
                return

            state["stage"] = "completed"
            state["status"] = "completed"
            state["last_percent"] = 100
            save_session(video_path, state)
            self._send_progress(100, os.path.abspath(final_video), "Completed")
            if settings.get("auto_open_output"):
                self.open_path(output_dir)

            clear_session(video_path)
            shutil.rmtree(task_temp_dir, ignore_errors=True)
        except Exception as exc:
            logger.exception("Pipeline failed", extra={"stage": "Pipeline"})
            fail(f"Pipeline failed: {exc}")


def main() -> None:
    cleanup_old_temp_files()
    api = Api()
    webview.create_window(
        "Dubora - AI Video Translator",
        resource_path(os.path.join("ui", "index.html")),
        js_api=api,
        width=1180,
        height=820,
        min_size=(980, 700),
        frameless=True,
        easy_drag=False,
        background_color="#020b10",
    )
    webview.start(debug=False, icon=resource_path(os.path.join("assets", "dubora.ico")))


if __name__ == "__main__":
    main()
