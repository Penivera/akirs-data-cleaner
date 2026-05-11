param(
    [switch]$Reload
)

# Pull latest changes and start the FastAPI app (uvicorn) on Windows (PowerShell)
# Run this from an elevated PowerShell if you need to bind to low ports, or just double-click the script.

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir
Set-Location ..
$repo = Get-Location
Write-Output "Repo root: $repo"

Write-Output "Fetching latest from origin..."
git fetch origin
try {
    git pull --ff-only
} catch {
    Write-Output "Fast-forward failed, doing normal pull"
    git pull
}

# Ensure venv
if (-not (Test-Path -Path "venv")) {
    Write-Output "Creating virtualenv..."
    python -m venv venv
}

# Activate venv for this session
$activate = Join-Path "venv/Scripts" "Activate.ps1"
if (Test-Path $activate) {
    . $activate
} else {
    Write-Output "Unable to find Activate.ps1. Ensure the venv was created and PowerShell execution policy allows running scripts."
}

if (Test-Path "requirements.txt") {
    Write-Output "Installing requirements..."
    pip install -r requirements.txt
}

if (-not (Test-Path "logs")) { New-Item -ItemType Directory logs | Out-Null }
if (-not (Test-Path "run")) { New-Item -ItemType Directory run | Out-Null }
$pidfile = "run\uvicorn.pid"
$log = "logs\server.log"

# Stop existing processes that look like our app (search command line for main:app or uvicorn)
$procs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and ($_.CommandLine -like '*main:app*' -or $_.CommandLine -like '*uvicorn*') }
foreach ($p in $procs) {
    try { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue } catch {}
}

# Build argument string
$uvicornArgs = "main:app --host 0.0.0.0 --port 8000"
if ($Reload) { $uvicornArgs = "--reload $uvicornArgs" }
# Launch via cmd.exe so we can redirect to a log file reliably
$cmd = "python -m uvicorn $uvicornArgs > $log 2>&1"
$proc = Start-Process -FilePath "cmd.exe" -ArgumentList "/c", $cmd -WindowStyle Hidden -PassThru
# Save PID
$proc.Id | Out-File -FilePath $pidfile -Encoding ascii

Write-Output "Started process id: $($proc.Id)"
Write-Output "Logs: $log"
