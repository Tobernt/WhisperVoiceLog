$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$pythonCandidates = @("3.11", "3.12", "3.10")
$pythonExe = $null

foreach ($version in $pythonCandidates) {
    try {
        $candidate = (& py "-$version" -c "import sys; print(sys.executable)" 2>$null)
        $candidatePath = $candidate.Trim()
        if ($LASTEXITCODE -eq 0 -and $candidatePath -and (Test-Path $candidatePath)) {
            $pythonExe = $candidatePath
            break
        }
    } catch {
    }
}

if (-not $pythonExe) {
    throw "Could not find Python 3.10, 3.11, or 3.12 through the Windows py launcher."
}

Write-Host "Using Python: $pythonExe"

if (-not (Test-Path ".venv")) {
    & $pythonExe -m venv .venv
}

& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -e .

Write-Host ""
Write-Host "Setup complete."
Write-Host "Run: .\transcribe.ps1 ""C:\path\to\audio-or-video.mp4"""
