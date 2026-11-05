@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run Setup.cmd first to install the local environment.
  pause
  exit /b 1
)
echo.
echo Excitement Finder: http://127.0.0.1:8765
echo Open that address in your browser. Keep this window open.
echo Press Ctrl+C to stop the local server.
echo.
".venv\Scripts\python.exe" -m uvicorn app:app --host 127.0.0.1 --port 8765
pause
