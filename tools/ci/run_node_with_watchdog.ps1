param(
  [Parameter(Mandatory=$true)][string]$Script,
  [int]$TimeoutSeconds = 150,
  [string]$Label = ''
)

$ErrorActionPreference = 'Stop'
if (-not $Label) { $Label = [IO.Path]::GetFileName($Script) }
if (-not (Test-Path $Script)) { throw "Browser CI script not found: $Script" }

New-Item -ItemType Directory -Force ci-logs | Out-Null
$safe = ($Label -replace '[^A-Za-z0-9_.-]', '_')
$stdout = Join-Path $env:GITHUB_WORKSPACE "ci-logs/browser-$safe.out.log"
$stderr = Join-Path $env:GITHUB_WORKSPACE "ci-logs/browser-$safe.err.log"
Remove-Item $stdout,$stderr -Force -ErrorAction SilentlyContinue

Write-Host "=== START $Label ==="
Write-Host "Script: $Script"
Write-Host "Timeout: ${TimeoutSeconds}s"
$started = Get-Date

$p = Start-Process -FilePath 'node.exe' -ArgumentList @($Script) -WorkingDirectory $env:GITHUB_WORKSPACE -NoNewWindow -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
$finished = $p.WaitForExit($TimeoutSeconds * 1000)

if (-not $finished) {
  $elapsed = [int]((Get-Date) - $started).TotalSeconds
  Write-Host "::error::$Label exceeded hard timeout after ${elapsed}s. Killing process tree."
  try { & taskkill.exe /PID $p.Id /T /F | Out-Host } catch { Write-Warning $_ }
  Start-Sleep -Milliseconds 400
  if (Test-Path $stdout) { Get-Content $stdout -ErrorAction SilentlyContinue | Out-Host }
  if (Test-Path $stderr) { Get-Content $stderr -ErrorAction SilentlyContinue | Out-Host }
  exit 124
}

$p.Refresh()
$elapsed = [int]((Get-Date) - $started).TotalSeconds
if (Test-Path $stdout) { Get-Content $stdout -ErrorAction SilentlyContinue | Out-Host }
if (Test-Path $stderr) { Get-Content $stderr -ErrorAction SilentlyContinue | Out-Host }

if ($p.ExitCode -ne 0) {
  Write-Host "::error::$Label failed after ${elapsed}s with exit code $($p.ExitCode)."
  exit $p.ExitCode
}

Write-Host "=== OK $Label (${elapsed}s) ==="
exit 0
