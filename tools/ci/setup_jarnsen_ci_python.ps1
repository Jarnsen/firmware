param(
    [string]$PythonVersion = '3.12.10'
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$logDir = Join-Path $env:GITHUB_WORKSPACE 'ci-logs'
New-Item -ItemType Directory -Force $logDir | Out-Null
$logPath = Join-Path $logDir 'python-setup.log'
Start-Transcript -Path $logPath -Force | Out-Null

try {
    Write-Host "Jarnsen CI Python bootstrap $PythonVersion"
    Write-Host "Runner: $env:RUNNER_NAME / $env:RUNNER_OS / $env:RUNNER_ARCH"

    $python = $null
    $candidates = New-Object System.Collections.Generic.List[string]

    if (Get-Command py.exe -ErrorAction SilentlyContinue) {
        try {
            $resolved = & py.exe -3.12 -c "import sys; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $resolved) {
                $candidate = [string](@($resolved) | Select-Object -Last 1)
                if ($candidate) { $candidates.Add($candidate.Trim()) }
            }
        } catch {
            Write-Warning "py.exe discovery failed: $($_.Exception.Message)"
        }
    }

    foreach ($candidate in @(
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "C:\Python312\python.exe",
        "C:\Program Files\Python312\python.exe"
    )) {
        if (Test-Path $candidate) { $candidates.Add($candidate) }
    }

    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        Write-Host "Testing installed Python candidate: $candidate"
        try {
            & $candidate -c "import ctypes, ssl, sys, sysconfig; assert sys.version_info[:2] == (3, 12); print(sys.executable); print(sys.version)"
            if ($LASTEXITCODE -ne 0) { throw "runtime health check exit $LASTEXITCODE" }
            & $candidate -m pip --version
            if ($LASTEXITCODE -ne 0) { throw "pip health check exit $LASTEXITCODE" }
            $python = $candidate
            break
        } catch {
            Write-Warning "Rejecting broken Python candidate '$candidate': $($_.Exception.Message)"
        }
    }

    if (!$python) {
        $installRoot = Join-Path $env:RUNNER_TEMP 'jarnsen-python312-portable'
        $archive = Join-Path $env:RUNNER_TEMP "python-$PythonVersion-embed-amd64.zip"
        $getPip = Join-Path $env:RUNNER_TEMP 'get-pip.py'
        $python = Join-Path $installRoot 'python.exe'

        if (Test-Path $installRoot) { Remove-Item -Recurse -Force $installRoot }
        New-Item -ItemType Directory -Force $installRoot | Out-Null

        $url = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
        Write-Host "Installed Python is unhealthy; downloading portable CI runtime: $url"
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $archive -TimeoutSec 60
        Expand-Archive -Path $archive -DestinationPath $installRoot -Force
        if (!(Test-Path $python)) { throw "Portable Python missing after extraction: $python" }

        $pth = Get-ChildItem $installRoot -Filter 'python312._pth' -File | Select-Object -First 1
        if (!$pth) { throw 'Portable Python ._pth file missing' }
        $pthContent = Get-Content $pth.FullName
        $pthContent = $pthContent | ForEach-Object {
            if ($_ -match '^#\s*import site') { 'import site' } else { $_ }
        }
        if ($pthContent -notcontains 'Lib\site-packages') { $pthContent += 'Lib\site-packages' }
        $pthContent | Set-Content -Encoding ascii $pth.FullName
        New-Item -ItemType Directory -Force (Join-Path $installRoot 'Lib\site-packages') | Out-Null

        & $python -c "import ctypes, ssl, sys, sysconfig; print(sys.executable); print(sys.version)"
        if ($LASTEXITCODE -ne 0) { throw 'Portable Python runtime health check failed before pip bootstrap' }

        $pipUrl = 'https://bootstrap.pypa.io/get-pip.py'
        Write-Host "Bootstrapping pip from $pipUrl"
        Invoke-WebRequest -UseBasicParsing -Uri $pipUrl -OutFile $getPip -TimeoutSec 60
        & $python $getPip --disable-pip-version-check --no-warn-script-location
        if ($LASTEXITCODE -ne 0) { throw 'get-pip.py failed for portable Python' }
    }

    Write-Host "Selected Python: $python"
    & $python -c "import ctypes, ssl, sys, sysconfig; assert sys.version_info[:2] == (3, 12); print(sys.executable); print(sys.version)"
    if ($LASTEXITCODE -ne 0) { throw 'Selected Python failed runtime health check' }
    & $python -m pip --version
    if ($LASTEXITCODE -ne 0) { throw 'Selected Python has no working pip' }
    & $python -m pip install --disable-pip-version-check --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw 'pip upgrade failed' }

    "JARNSEN_PY=$python" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
    (Split-Path -Parent $python) | Out-File -FilePath $env:GITHUB_PATH -Encoding utf8 -Append
    Write-Host 'Python bootstrap complete.'
} catch {
    $message = $_ | Out-String
    $message | Set-Content -Encoding utf8 (Join-Path $logDir 'python-setup-error.txt')
    Write-Error $message
    throw
} finally {
    try { Stop-Transcript | Out-Null } catch {}
}
