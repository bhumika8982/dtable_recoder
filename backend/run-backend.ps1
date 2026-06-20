# Clean, reliable backend start.
#
# Why this script exists: `uvicorn --reload` on Windows does NOT always reload
# changed code, and killed servers can leave port 8000 stuck. That made fixes
# look like they "didn't work" until a fully clean restart. This script always:
#   1. kills any stale python/uvicorn (frees port 8000 + drops old code),
#   2. starts ONE fresh process that loads the current code + .env.
#
# Usage:  ./run-backend.ps1            (normal, stable)
#         ./run-backend.ps1 -Reload    (auto-reload while editing code)
#         ./run-backend.ps1 -Port 8010 (different port)
param(
  [int]$Port = 8000,
  [switch]$Reload
)

Write-Host "Stopping any running python/uvicorn..." -ForegroundColor Yellow
Get-Process python, uvicorn -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

Set-Location $PSScriptRoot
$py = Join-Path $PSScriptRoot "venv\Scripts\python.exe"

$args = @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$Port")
if ($Reload) { $args += "--reload" }

Write-Host "Starting backend on http://localhost:$Port ..." -ForegroundColor Green
& $py @args
