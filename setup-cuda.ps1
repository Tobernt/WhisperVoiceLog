$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    & powershell -ExecutionPolicy Bypass -File ".\setup.ps1"
}

& ".\.venv\Scripts\python.exe" -m pip install -e ".[cuda]"
& ".\.venv\Scripts\python.exe" -m whisper_voice_log.cuda_check

Write-Host ""
Write-Host "CUDA setup complete. Restart Whisper Voice Log, then choose Device: cuda."
