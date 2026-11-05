@echo off
setlocal
cd /d "%~dp0"
echo Creating an isolated Python environment. Internet access is required.
if not exist ".venv\Scripts\python.exe" python -m venv --without-pip .venv
if errorlevel 1 goto fail
python -m pip --python ".venv\Scripts\python.exe" install pip -r requirements.txt
if errorlevel 1 goto fail
echo.
echo Setup complete. Run Start.cmd, then open http://127.0.0.1:8765
pause
exit /b 0
:fail
echo Setup failed. Install Python 3.14 for Windows with pip, then try again.
pause
exit /b 1
