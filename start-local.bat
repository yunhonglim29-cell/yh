@echo off
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Install Python 3.13, including the Python launcher, then try again.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 goto failed
)
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo.
echo Open http://localhost:8000 in your browser.
echo Organiser dashboard: http://localhost:8000/admin
echo Save the first-run password printed below.
echo Keep this window open while playing. Ctrl+C stops the server.
echo.
.venv\Scripts\python.exe run.py
pause
exit /b
:failed
echo Setup did not finish. Check Python and your internet connection, then retry.
pause
exit /b 1
