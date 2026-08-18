param(
    [switch]$Reload
)

$isWin = $IsWindows
if ($null -eq $isWin) {
    $isWin = [bool]$env:windir
}

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

# Ensure venv: prefer existing .venv or venv; create .venv if neither exists
$venvDir = if (Test-Path ".venv") { ".venv" } elseif (Test-Path "venv") { "venv" } else { $null }
if (-not $venvDir) {
    Write-Output "No virtualenv found. Creating .venv..."
    python -m venv .venv
    $venvDir = ".venv"
}

# Activate venv for this session
$activate = Join-Path "$venvDir/Scripts" "Activate.ps1"
if (-not (Test-Path $activate)) { $activate = Join-Path "$venvDir/bin" "Activate.ps1" }
if (Test-Path $activate) {
    . $activate
} else {
    Write-Output "Unable to find Activate.ps1 in $venvDir. Ensure the venv was created and PowerShell execution policy allows running scripts."
}

if (Test-Path "requirements.txt") {
    Write-Output "Installing requirements into $venvDir..."
    $venvPython = Join-Path $venvDir "Scripts\python.exe"
    if (-not (Test-Path $venvPython)) { $venvPython = Join-Path $venvDir "bin/python" }

    # If pip not available, try ensurepip, otherwise download get-pip.py
    $pipOk = $false
    try { & $venvPython -m pip --version *> $null; $pipOk = $true } catch {}
    if (-not $pipOk) {
        Write-Output "pip not found in venv; attempting to bootstrap with ensurepip..."
        $ensOk = $false
        try { & $venvPython -m ensurepip --upgrade *> $null; $ensOk = $true } catch {}
        if (-not $ensOk) {
            Write-Output "ensurepip failed; trying to download get-pip.py"
            $tempPath = [System.IO.Path]::GetTempPath()
            if (-not $tempPath) { $tempPath = if ($env:TEMP) { $env:TEMP } elseif ($env:TMPDIR) { $env:TMPDIR } else { "/tmp" } }
            $tmp = Join-Path $tempPath "get-pip.py"
            try {
                Invoke-WebRequest -UseBasicParsing -Uri https://bootstrap.pypa.io/get-pip.py -OutFile $tmp -ErrorAction Stop
                & $venvPython $tmp
            } catch {
                Write-Error "Failed to bootstrap pip: $_"
                exit 1
            }
        }
    }

    & $venvPython -m pip install --upgrade pip setuptools wheel
    
    if ($isWin) {
        $reqTmp = Join-Path ([System.IO.Path]::GetTempPath()) "requirements_nouvloop.txt"
        Get-Content requirements.txt | Where-Object { $_ -notmatch 'uvloop' } | Set-Content $reqTmp
        & $venvPython -m pip install -r $reqTmp
        Remove-Item $reqTmp -ErrorAction SilentlyContinue
    } else {
        & $venvPython -m pip install -r requirements.txt
    }
}

if (-not (Test-Path "logs")) { New-Item -ItemType Directory logs | Out-Null }
if (-not (Test-Path "run")) { New-Item -ItemType Directory run | Out-Null }
$pidfile = "run\uvicorn.pid"
$log = "logs\server.log"

# Stop existing processes that look like our app (search command line for main:app or uvicorn)
if ($isWin) {
    $procs = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -and ($_.CommandLine -like '*main:app*' -or $_.CommandLine -like '*uvicorn*') }
    foreach ($p in $procs) {
        try { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue } catch {}
    }
} else {
    if (Test-Path $pidfile) {
        $pidStr = Get-Content $pidfile -ErrorAction SilentlyContinue
        if ([int]::TryParse($pidStr, [ref]$null)) {
            try { Stop-Process -Id $pidStr -Force -ErrorAction SilentlyContinue } catch {}
        }
    }
}

# Build argument string
$uvicornArgs = "main:app --host 0.0.0.0 --port 8000"
if ($Reload) { $uvicornArgs = "--reload $uvicornArgs" }
# Use the venv python to run uvicorn so we avoid relying on system python
$venvPython = Join-Path $venvDir "Scripts\python.exe"
if (-not (Test-Path $venvPython)) { $venvPython = Join-Path $venvDir "bin/python" }
$cmd = "$venvPython -m uvicorn $uvicornArgs > $log 2>&1"

if ($isWin) {
    $proc = Start-Process -FilePath "cmd.exe" -ArgumentList "/c", $cmd -WindowStyle Hidden -PassThru
} else {
    $proc = Start-Process -FilePath "sh" -ArgumentList "-c", "`"$cmd`"" -PassThru -NoNewWindow
}
# Save PID
$proc.Id | Out-File -FilePath $pidfile -Encoding ascii

Write-Output "Started process id: $($proc.Id)"
Write-Output "Logs: $log"
try { Start-Process "http://localhost:8000" } catch { Write-Output "Please open http://localhost:8000 in your browser manually." }
Write-Output "Opened browser to http://localhost:8000. If it did not open, please navigate manually."
