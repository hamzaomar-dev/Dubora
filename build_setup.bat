@echo off
setlocal
cd /d "%~dp0"

if not exist "dist\Dubora\Dubora.exe" (
  echo ERROR: Build Dubora first with build_release.bat.
  pause
  exit /b 1
)

set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"

if not defined ISCC (
  echo ERROR: Inno Setup 6 is not installed.
  echo Install Inno Setup 6, then run this file again.
  pause
  exit /b 1
)

if exist "installer" rmdir /s /q "installer"

echo Building Dubora installer...
"%ISCC%" "Dubora_Setup.iss"
if errorlevel 1 (
  echo.
  echo SETUP BUILD FAILED.
  pause
  exit /b 1
)

echo.
echo ==========================================
echo INSTALLER BUILD SUCCESSFUL
echo ==========================================
echo %CD%\installer\Dubora-Setup.exe
echo.
pause
