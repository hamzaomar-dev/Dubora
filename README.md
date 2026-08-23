# Dubora

Dubora is a Windows desktop application that transcribes video audio, translates subtitle text into Arabic, verifies SRT integrity, and renders translated subtitles with FFmpeg.

## AI architecture

Dubora now uses a **server-side AI gateway**:

```text
Dubora Desktop -> Dubora AI Gateway -> AI Provider (Groq today)
```

End users do **not** enter an API key. The provider key exists only as a secret on the gateway server. This also lets the server switch AI providers later without rebuilding the desktop app.

## Desktop Beta features

- Python + pywebview desktop shell
- Offline HTML/CSS/JavaScript interface
- 10-minute local audio chunking
- Server-side transcription and translation
- Python-owned subtitle indices/timestamps; AI receives subtitle IDs + text only
- Exact SRT integrity validation
- Automatic retries and block-by-block translation fallback
- Resume state for interrupted jobs
- Cancel support with resumable sessions
- Rotating logs under user AppData
- Writable data outside `Program Files`
- FFmpeg/ffprobe discovery
- PyInstaller resource-path support

## Development setup

Desktop:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Gateway (separate terminal):

```bat
python -m venv .venv-server
.venv-server\Scripts\activate
pip install -r server\requirements.txt
set GROQ_API_KEY=YOUR_NEW_SERVER_KEY
python -m uvicorn server.app:app --host 127.0.0.1 --port 8787
```

`gateway_url.txt` points to the gateway. It is set to localhost for development. Before a public EXE build, replace it with your deployed HTTPS gateway URL.

## Security

- Never place a Groq/OpenAI/Gemini/provider key in desktop source, JS, `gateway_url.txt`, GitHub, or the EXE.
- Store provider secrets only in the server hosting environment.
- Any old Groq key that was previously distributed or committed should be revoked/rotated.
- The included gateway has payload limits and a basic in-memory rate limiter. A larger public launch should use persistent rate limiting, monitoring, and optionally user authentication.

## FFmpeg / ffprobe

Before a Windows distributable build, place:

```text
ffmpeg/bin/ffmpeg.exe
ffmpeg/bin/ffprobe.exe
```

## Tests

```bat
pip install -r requirements-dev.txt
pytest -q
```

## Windows EXE

After the public gateway is deployed and `gateway_url.txt` contains its HTTPS URL:

```bat
build_windows.bat
```

The script creates the EXE build, not a Setup installer.
