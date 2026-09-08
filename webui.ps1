$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

try {
    $client = [Net.Sockets.TcpClient]::new()
    $client.Connect("127.0.0.1", 8765)
    $client.Close()
    Start-Process "http://127.0.0.1:8765"
    exit 0
} catch {
}

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    & powershell -ExecutionPolicy Bypass -File ".\setup.ps1"
}

Start-Process powershell -WindowStyle Hidden -ArgumentList "-NoProfile", "-Command", "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:8765'"
& ".\.venv\Scripts\python.exe" -m whisper_voice_log.web --host 127.0.0.1 --port 8765
