param(
  [Parameter(Mandatory=$true)][string]$Script,
  [int]$TimeoutSeconds = 150,
  [string]$Label = ''
)

$ErrorActionPreference = 'Stop'
if (-not $Label) { $Label = [IO.Path]::GetFileName($Script) }
if (-not (Test-Path $Script)) { throw "Browser CI script not found: $Script" }

$runner = Join-Path $env:GITHUB_WORKSPACE 'tools/ci/node_watchdog_runner.mjs'
if (-not (Test-Path $runner)) { throw "Node watchdog runner not found: $runner" }

# Important: invoke Node directly in this PowerShell process. Playwright/Chromium
# protocol calls proved unreliable when the test itself was launched through
# Start-Process with redirected stdio on the self-hosted Windows runner.
# The imported Node runner owns the hard timeout and writes live + artifact logs.
& node.exe $runner $Script $TimeoutSeconds $Label
$code = $LASTEXITCODE

if ($code -ne 0) {
  exit $code
}
exit 0
