@echo off
setlocal

cd /d "%~dp0"

powershell -NoProfile -Command "$c = New-Object Net.Sockets.TcpClient; try { $c.Connect('127.0.0.1', 8765); $c.Close(); exit 0 } catch { exit 1 }"
if %errorlevel%==0 (
  start "" "http://127.0.0.1:8765"
  exit /b 0
)

if not exist ".venv\Scripts\python.exe" (
  echo First run setup...
  powershell -ExecutionPolicy Bypass -File ".\setup.ps1"
  if errorlevel 1 (
    pause
    exit /b 1
  )
)

echo Starting Whisper Voice Log...
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:8765'"
".venv\Scripts\python.exe" -m whisper_voice_log.web --host 127.0.0.1 --port 8765

pause
