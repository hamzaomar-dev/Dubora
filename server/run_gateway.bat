@echo off
setlocal
cd /d "%~dp0\.."
python -m uvicorn server.app:app --host 127.0.0.1 --port 8787
endlocal
