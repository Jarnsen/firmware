$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'

$errorDir = Join-Path $env:GITHUB_WORKSPACE 'errors'
New-Item -ItemType Directory -Force $errorDir | Out-Null

@"
JARNSEN Service Tool CI failure diagnostics
Run ID: $env:GITHUB_RUN_ID
Run number: $env:GITHUB_RUN_NUMBER
Attempt: $env:GITHUB_RUN_ATTEMPT
Repository: $env:GITHUB_REPOSITORY
SHA: $env:GITHUB_SHA
Ref: $env:GITHUB_REF
Runner: $env:RUNNER_NAME
OS: $env:RUNNER_OS
Arch: $env:RUNNER_ARCH
Generated: $(Get-Date -Format o)
"@ | Set-Content -Encoding utf8 (Join-Path $errorDir 'summary.txt')

$sourceDirs = @(
    (Join-Path $env:GITHUB_WORKSPACE 'ci-logs'),
    $env:GITHUB_WORKSPACE
)
foreach ($sourceDir in $sourceDirs) {
    if (!(Test-Path $sourceDir)) { continue }
    Get-ChildItem -Path $sourceDir -File -Recurse -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Name -match '(?i)(error|failure|bootstrap|self-test|diagnostic)' -or
            ($_.DirectoryName -like '*ci-logs*' -and $_.Extension -in @('.log','.txt'))
        } |
        ForEach-Object {
            $safeName = ($_.FullName.Substring($env:GITHUB_WORKSPACE.Length).TrimStart('\','/') -replace '[\\/:*?"<>|]', '_')
            Copy-Item $_.FullName (Join-Path $errorDir $safeName) -Force -ErrorAction SilentlyContinue
        }
}

try {
    if ($env:GITHUB_TOKEN) {
        $headers = @{
            Authorization = "Bearer $env:GITHUB_TOKEN"
            Accept = 'application/vnd.github+json'
            'X-GitHub-Api-Version' = '2022-11-28'
        }
        $jobsUri = "https://api.github.com/repos/$env:GITHUB_REPOSITORY/actions/runs/$env:GITHUB_RUN_ID/jobs?filter=latest&per_page=100"
        $jobs = Invoke-RestMethod -Uri $jobsUri -Headers $headers -Method Get -TimeoutSec 20
        $job = @($jobs.jobs | Where-Object { $_.name -eq 'build-windows-app' } | Select-Object -First 1)
        if ($job.Count -gt 0) {
            $jobId = $job[0].id
            "Detected job id: $jobId" | Add-Content -Encoding utf8 (Join-Path $errorDir 'summary.txt')
            $logsUri = "https://api.github.com/repos/$env:GITHUB_REPOSITORY/actions/jobs/$jobId/logs"
            try {
                Invoke-WebRequest -UseBasicParsing -Uri $logsUri -Headers $headers -OutFile (Join-Path $errorDir 'github-job.log') -MaximumRedirection 5 -TimeoutSec 30
            } catch {
                ($_ | Out-String) | Set-Content -Encoding utf8 (Join-Path $errorDir 'github-job-log-download-error.txt')
            }
        } else {
            'Could not resolve current build-windows-app job id.' | Set-Content -Encoding utf8 (Join-Path $errorDir 'github-job-log-download-error.txt')
        }
    } else {
        'GITHUB_TOKEN not available.' | Set-Content -Encoding utf8 (Join-Path $errorDir 'github-job-log-download-error.txt')
    }
} catch {
    ($_ | Out-String) | Set-Content -Encoding utf8 (Join-Path $errorDir 'github-api-error.txt')
}

Write-Host 'Collected failure diagnostics:'
Get-ChildItem $errorDir -File | Select-Object Name, Length | Format-Table -AutoSize
