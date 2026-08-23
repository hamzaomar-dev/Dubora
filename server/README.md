# Dubora AI Gateway

This service keeps the AI provider key on the server. Desktop users do **not** enter or receive a Groq/API key.

## Local development

```bat
python -m venv .venv-server
.venv-server\Scripts\activate
pip install -r server\requirements.txt
set GROQ_API_KEY=YOUR_NEW_SERVER_KEY
python -m uvicorn server.app:app --host 127.0.0.1 --port 8787
```

The desktop build currently reads `gateway_url.txt`. For local development it points to `http://127.0.0.1:8787`.

## Public deployment

Deploy the `server/` package to a server that supports Python/FastAPI and HTTPS. Store `GROQ_API_KEY` as a server-side environment secret. Then replace the contents of root `gateway_url.txt` with the public HTTPS URL **before building the EXE**.

Example:

```text
https://api.your-domain.com
```

Never place `GROQ_API_KEY` in `gateway_url.txt`, desktop source, GitHub, JavaScript, or the EXE.

## Provider switching

The desktop talks only to Dubora Gateway. Provider logic lives under `server/providers/`. Groq is implemented now. A future Gemini/OpenAI/other provider can be added server-side without changing the desktop request contract.

## Production note

The included limiter is intentionally simple and in-memory. Before a large public launch, use persistent rate limiting (for example Redis), real user/device authentication if needed, monitoring, HTTPS, and provider spending limits. A public anonymous AI endpoint can otherwise be abused and consume your provider quota.
