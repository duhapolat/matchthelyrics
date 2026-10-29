@echo off
cd /d "%~dp0"
rem Veriler (sarkilar, sozler, ogrenme modeli) depo disinda tutulur.
if not defined MTL_DATA_DIR set "MTL_DATA_DIR=%~dp0..\matchthelyrics-local\data"
if not exist ".venv\Scripts\python.exe" (
  echo Once setup.bat calistir.
  pause
  exit /b 1
)
echo Match The Lyrics baslatiliyor: http://127.0.0.1:8765
echo Veri klasoru: %MTL_DATA_DIR%
echo Kapatmak icin bu pencereyi kapat.
start "" http://127.0.0.1:8765
".venv\Scripts\python.exe" -m uvicorn app.server:app --host 127.0.0.1 --port 8765
pause
