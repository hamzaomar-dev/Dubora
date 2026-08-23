@echo off
setlocal
cd /d "%~dp0"

if not exist "ffmpeg\bin\ffmpeg.exe" (
  echo ERROR: ffmpeg\bin\ffmpeg.exe is missing.
  exit /b 1
)
if not exist "ffmpeg\bin\ffprobe.exe" (
  echo ERROR: ffmpeg\bin\ffprobe.exe is missing.
  exit /b 1
)
if not exist "gateway_url.txt" (
  echo ERROR: gateway_url.txt is missing.
  exit /b 1
)

python -m pip install -r requirements-dev.txt
if errorlevel 1 exit /b 1

python -m PyInstaller --noconfirm --clean --windowed --name Dubora --icon assets\dubora.ico ^
  --add-data "ui;ui" ^
  --add-data "ffmpeg\bin;ffmpeg\bin" ^
  --add-data "gateway_url.txt;." ^
  app.py

if errorlevel 1 exit /b 1

echo.
echo Build complete: dist\Dubora\Dubora.exe
endlocal
