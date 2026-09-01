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
        $installRoot = Join-Path $env:RUNNER_TEMP 'jarnsen-python312'
        $installer = Join-Path $env:RUNNER_TEMP "python-$PythonVersion-amd64.exe"
        $python = Join-Path $installRoot 'python.exe'

        if (Test-Path $installRoot) {
            Remove-Item -Recurse -Force $installRoot
        }
        New-Item -ItemType Directory -Force $installRoot | Out-Null

        $url = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-amd64.exe"
        Write-Host "Installed Python is unhealthy; downloading isolated CI runtime: $url"
        Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $installer

        $arguments = @(
            '/quiet',
            'InstallAllUsers=0',
            "TargetDir=$installRoot",
            'Include_pip=1',
            'Include_launcher=0',
            'Include_test=0',
            'Include_doc=0',
            'Shortcuts=0',
            'AssociateFiles=0',
            'PrependPath=0'
        )
        $process = Start-Process -FilePath $installer -ArgumentList $arguments -Wait -PassThru
        if ($process.ExitCode -ne 0) { throw "Python installer failed with exit code $($process.ExitCode)" }
        if (!(Test-Path $python)) { throw "Isolated Python missing after install: $python" }
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
