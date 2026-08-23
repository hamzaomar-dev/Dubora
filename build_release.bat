@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo ==========================================
echo        Dubora Windows Release Build
echo ==========================================
echo.

if not exist "app.py" (
  echo ERROR: app.py is missing. Put this file in the Dubora project root.
  pause
  exit /b 1
)

if not exist "ffmpeg\bin\ffmpeg.exe" (
  echo ERROR: ffmpeg\bin\ffmpeg.exe is missing.
  pause
  exit /b 1
)

if not exist "ffmpeg\bin\ffprobe.exe" (
  echo ERROR: ffmpeg\bin\ffprobe.exe is missing.
  pause
  exit /b 1
)

if not exist "gateway_url.txt" (
  echo ERROR: gateway_url.txt is missing.
  pause
  exit /b 1
)

REM Use a fresh build-only environment.
if not exist ".buildvenv\Scripts\python.exe" (
  echo [1/6] Creating clean build environment...
  python -m venv .buildvenv
  if errorlevel 1 goto :fail
) else (
  echo [1/6] Clean build environment already exists.
)

set "PY=.buildvenv\Scripts\python.exe"

echo [2/6] Installing build dependencies...
"%PY%" -m pip install --upgrade pip
if errorlevel 1 goto :fail
"%PY%" -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto :fail

echo [3/6] Locating Python runtime DLL...
"%PY%" -c "import sys,pathlib; print(pathlib.Path(sys.base_prefix) / f'python{sys.version_info.major}{sys.version_info.minor}.dll')" > ".pydll_path.tmp"
if errorlevel 1 goto :fail

set /p "PYDLL="<".pydll_path.tmp"
del /q ".pydll_path.tmp" >nul 2>&1

if not defined PYDLL (
  echo ERROR: Could not determine Python DLL path.
  goto :fail
)

if not exist "%PYDLL%" (
  echo ERROR: Python runtime DLL was not found:
  echo %PYDLL%
  goto :fail
)

echo Python DLL: %PYDLL%

echo [4/6] Cleaning old build...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "Dubora.spec" del /q "Dubora.spec"

echo [5/6] Building Dubora...
"%PY%" -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --windowed ^
  --onedir ^
  --contents-directory "_internal" ^
  --name "Dubora" ^
  --icon "assets\dubora.ico" ^
  --collect-all "webview" ^
  --add-binary "%PYDLL%;." ^
  --add-data "ui;ui" ^
  --add-data "assets;assets" ^
  --add-data "ffmpeg\bin;ffmpeg\bin" ^
  --add-data "gateway_url.txt;." ^
  app.py

if errorlevel 1 goto :fail

echo [6/6] Verifying build...
if not exist "dist\Dubora\Dubora.exe" (
  echo ERROR: Dubora.exe was not created.
  goto :fail
)

dir /b "dist\Dubora\_internal\python*.dll" >nul 2>&1
if errorlevel 1 (
  echo ERROR: Python runtime DLL is still missing from the build.
  goto :fail
)

echo.
echo ==========================================
echo BUILD SUCCESSFUL
echo ==========================================
echo App:
echo   %CD%\dist\Dubora\Dubora.exe
echo.
echo Test Dubora.exe now.
echo If it opens correctly, run build_setup.bat next.
echo.
pause
exit /b 0

:fail
echo.
echo ==========================================
echo BUILD FAILED
echo ==========================================
echo Copy the last error shown above.
echo.
pause
exit /b 1
