# Dubora Gateway Architecture Upgrade

## What changed

- Removed end-user Groq/API-key entry from the desktop application.
- Removed `keyring` and direct `groq` dependencies from the desktop runtime.
- Added `modules/gateway_client.py`; desktop transcription/translation now go only through Dubora Gateway.
- Added a persistent anonymous installation ID used with IP information for Beta rate limiting. It is not a secret or an authentication credential.
- Added build-time `gateway_url.txt`; users do not configure the provider or its key.
- Added FastAPI service under `server/`.
- Added server-side Groq provider implementation and provider factory so another AI provider can be added without changing the desktop API contract.
- Added server payload limits, audio-size limit, translation validation, and in-memory per-client/IP request limits.
- Provider models and provider credentials are now server-controlled.
- Existing SRT integrity, audio chunking, resume/cancel, FFmpeg rendering, AppData paths, and logging remain in place.
- Old direct-provider sessions are invalidated with a new pipeline version to avoid stale resume data.

## Public-use flow

```text
User -> Dubora.exe -> HTTPS Dubora Gateway -> AI provider
```

The user never sees the provider key.

## Still required before public release

1. Deploy `server/` on an HTTPS-capable Python host.
2. Put a new/rotated `GROQ_API_KEY` in that host's secret environment.
3. Configure provider spending/rate limits in the provider account.
4. Replace `gateway_url.txt` with the deployed HTTPS URL.
5. Test short and long real videos against the deployed service.
6. Put Windows `ffmpeg.exe` and `ffprobe.exe` in `ffmpeg/bin/`.
7. Build/test the Windows EXE on a clean machine.
8. Before significant public scale, move rate limiting to Redis/database and add monitoring/authentication if needed.

## Important limitation

A public anonymous AI gateway cannot make a provider's quota unlimited. All user usage consumes the quota/billing of the server-side provider account. The gateway architecture protects the key and lets you control usage, but provider limits still apply.

## Verification completed in this workspace

- Python syntax compilation: passed.
- Desktop/provider-secret scan: passed; no provider key or direct Groq import remains in desktop runtime files.
- `shell=True` scan: passed.
- External/CDN UI scan: passed.
- Automated tests: **15 passed**.
- Live local gateway smoke test with a fake provider: `/health`, `/v1/translate`, and `/v1/transcribe` all passed through the real HTTP client/server boundary.
