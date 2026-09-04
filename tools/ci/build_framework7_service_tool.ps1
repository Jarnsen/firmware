$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

if (!$env:JARNSEN_PY) { throw 'JARNSEN_PY is not set' }
$python = $env:JARNSEN_PY
$version = if ($env:JARNSEN_TOOL_VERSION) { $env:JARNSEN_TOOL_VERSION } else { '3.1.1' }

$logDir = Join-Path $env:GITHUB_WORKSPACE 'ci-logs'
New-Item -ItemType Directory -Force $logDir | Out-Null
$logPath = Join-Path $logDir 'framework7-build.log'
Start-Transcript -Path $logPath -Force | Out-Null

function Assert-ExitCode([string]$label) {
    if ($LASTEXITCODE -ne 0) { throw "$label failed with exit code $LASTEXITCODE" }
}

try {
    Write-Host "=== JARNSEN Framework7 Service Tool build ==="
    Write-Host "Version: $version"
    Write-Host "Python: $python"
    Write-Host "SHA: $env:GITHUB_SHA"

    Write-Host '=== Install Python desktop dependencies ==='
    & $python -m pip install --disable-pip-version-check pyinstaller pyserial bleak send2trash esptool tkintermapview customtkinter pywebview meshtastic==2.7.11
    Assert-ExitCode 'Python dependency installation'

    Write-Host '=== Bundle Framework7 and map libraries offline ==='
    & npm install --no-save --ignore-scripts framework7@9.1.3 leaflet@1.9.4 mgrs@2.1.0
    Assert-ExitCode 'npm install'
    New-Item -ItemType Directory -Force tools/service_tool_web/vendor | Out-Null
    Copy-Item node_modules/framework7/framework7-bundle.min.css tools/service_tool_web/vendor/framework7-bundle.min.css
    Copy-Item node_modules/framework7/framework7-bundle.min.js tools/service_tool_web/vendor/framework7-bundle.min.js
    Copy-Item node_modules/leaflet/dist/leaflet.css tools/service_tool_web/vendor/leaflet.css
    Copy-Item node_modules/leaflet/dist/leaflet.js tools/service_tool_web/vendor/leaflet.js
    Copy-Item node_modules/mgrs/dist/mgrs.min.js tools/service_tool_web/vendor/mgrs.min.js
    foreach ($asset in @(
        'tools/service_tool_web/vendor/framework7-bundle.min.css',
        'tools/service_tool_web/vendor/framework7-bundle.min.js',
        'tools/service_tool_web/vendor/leaflet.css',
        'tools/service_tool_web/vendor/leaflet.js',
        'tools/service_tool_web/vendor/mgrs.min.js'
    )) {
        if (!(Test-Path $asset)) { throw "Bundled UI asset missing: $asset" }
    }

    Write-Host '=== Patch proven Python service core ==='
    $patchers = @(
        'tools/patch_jarnsen_service_tool.py',
        'tools/patch_jarnsen_service_tool_v14.py',
        'tools/patch_jarnsen_service_tool_v15.py',
        'tools/patch_jarnsen_service_tool_v16.py',
        'tools/patch_jarnsen_service_tool_v17.py',
        'tools/patch_jarnsen_service_tool_v18.py',
        'tools/patch_jarnsen_service_tool_v19.py',
        'tools/patch_jarnsen_service_tool_v20_metrics.py',
        'tools/patch_jarnsen_service_tool_v20_ui.py',
        'tools/patch_jarnsen_service_tool_v20_finalize.py',
        'tools/patch_jarnsen_service_tool_v20_history.py',
        'tools/patch_jarnsen_service_tool_v201_access.py',
        'tools/patch_jarnsen_service_tool_v21.py',
        'tools/patch_jarnsen_service_tool_v21_pages.py',
        'tools/patch_jarnsen_service_tool_v21_fix.py',
        'tools/apply_jarnsen_service_tool_v211.py',
        'tools/patch_jarnsen_service_tool_v212.py',
        'tools/patch_jarnsen_service_tool_v213.py',
        'tools/patch_jarnsen_service_tool_v214.py',
        'tools/patch_jarnsen_service_tool_v215.py',
        'tools/patch_jarnsen_service_tool_v216.py',
        'tools/patch_jarnsen_service_tool_v217.py',
        'tools/patch_jarnsen_service_tool_v218.py',
        'tools/patch_jarnsen_service_tool_v218_errors.py',
        'tools/patch_jarnsen_service_tool_v218_ble_busy.py',
        'tools/patch_jarnsen_service_tool_v218_map_safety.py',
        'tools/patch_jarnsen_service_tool_v219.py',
        'tools/patch_jarnsen_service_tool_v2111.py',
        'tools/patch_jarnsen_service_tool_v2112.py',
        'tools/patch_jarnsen_service_tool_v2113.py',
        'tools/patch_jarnsen_service_tool_v2115.py',
        'tools/patch_jarnsen_service_tool_v2116.py',
        'tools/patch_jarnsen_service_tool_v2116_fix.py',
        'tools/patch_jarnsen_service_tool_v2117.py',
        'tools/patch_jarnsen_service_tool_v2118.py',
        'tools/patch_jarnsen_service_tool_v2119_pre.py',
        'tools/patch_jarnsen_service_tool_v2119.py',
        'tools/patch_jarnsen_service_tool_v2120.py',
        'tools/patch_jarnsen_service_tool_v2121.py',
        'tools/patch_jarnsen_service_tool_v2122_compat.py',
        'tools/patch_jarnsen_service_tool_v2123.py',
        'tools/patch_jarnsen_service_tool_v2124.py',
        'tools/apply_jarnsen_service_tool_v2125.py'
    )
    foreach ($patcher in $patchers) {
        Write-Host "Patch: $patcher"
        & $python $patcher tools/JARNSEN_NODE_SERVICE_TOOL.py
        Assert-ExitCode $patcher
    }
    & $python tools/patch_framework7_map_settings_v32.py tools/service_tool_web/app-v31.js
    Assert-ExitCode 'patch_framework7_map_settings_v32.py'

    Write-Host '=== Validate Python and complete Framework7 parity shell ==='
    $compileFiles = @(
        'tools/JARNSEN_FRAMEWORK7_SERVICE_TOOL.py',
        'tools/JARNSEN_FRAMEWORK7_FEATURES.py',
        'tools/JARNSEN_FRAMEWORK7_FIXES.py',
        'tools/JARNSEN_FRAMEWORK7_RADIO_AUTH.py',
        'tools/JARNSEN_FRAMEWORK7_LEGACY_COMPAT.py',
        'tools/JARNSEN_FRAMEWORK7_PARITY.py',
        'tools/JARNSEN_FRAMEWORK7_PARITY_FIXES.py',
        'tools/JARNSEN_FRAMEWORK7_RUNTIME_FIXES.py',
        'tools/JARNSEN_FRAMEWORK7_RUNTIME_FIXES_V312.py',
        'tools/JARNSEN_FRAMEWORK7_HEADLESS_CORE.py',
        'tools/JARNSEN_FRAMEWORK7_HEADLESS_BOOT.py',
        'tools/JARNSEN_FRAMEWORK7_PERF_FOCUS.py',
        'tools/JARNSEN_FRAMEWORK7_SERVICE_TOOL_V31.py',
        'tools/patch_framework7_map_settings_v32.py'
    )
    & $python -m py_compile @compileFiles
    Assert-ExitCode 'Python compile validation'
    & $python tools/validate_generated_service_tool.py tools/JARNSEN_NODE_SERVICE_TOOL.py
    Assert-ExitCode 'Generated service tool validation'

    foreach ($js in @(
        'tools/service_tool_web/app-v31.js',
        'tools/service_tool_web/map-settings-v32.js',
        'tools/service_tool_web/radio-auth-v33.js',
        'tools/service_tool_web/legacy-compat-v34.js',
        'tools/service_tool_web/parity-v35.js',
        'tools/service_tool_web/parity-enhance-v36.js'
    )) {
        & node --check $js
        Assert-ExitCode "node --check $js"
    }

    foreach ($asset in @(
        'tools/service_tool_web/v31.css',
        'tools/service_tool_web/focus.css',
        'tools/service_tool_web/map-settings-v32.css',
        'tools/service_tool_web/radio-auth-v33.css',
        'tools/service_tool_web/parity-v35.css',
        'tools/service_tool_web/parity-enhance-v36.css',
        'tools/service_tool_web/vendor/leaflet.css',
        'tools/service_tool_web/vendor/leaflet.js',
        'tools/service_tool_web/vendor/mgrs.min.js'
    )) {
        if (!(Test-Path $asset)) { throw "Framework7 asset missing: $asset" }
    }

    $index = Get-Content tools/service_tool_web/index.html -Raw
    foreach ($reference in @(
        'framework7-bundle.min.css','leaflet.css','v31.css','focus.css','map-settings-v32.css','radio-auth-v33.css','parity-v35.css','parity-enhance-v36.css','leaflet.js','mgrs.min.js','map-settings-v32.js','radio-auth-v33.js','app-v31.js','legacy-compat-v34.js','parity-v35.js','parity-enhance-v36.js'
    )) {
        if ($index -notmatch [regex]::Escape($reference)) { throw "index.html reference missing: $reference" }
    }

    $appJs = Get-Content tools/service_tool_web/app-v31.js -Raw
    if ($appJs -notmatch "theme: 'ios'") { throw 'Framework7 iOS theme missing' }
    if ($appJs -notmatch '/api/profile/action') { throw 'Profile bridge UI missing' }
    if ($appJs -notmatch '/api/live/action') { throw 'Live bridge UI missing' }
    if ($appJs -notmatch '/positions') { throw 'Historical positions bridge missing' }
    if ($appJs -notmatch 'JarnsenMapSettings\.renderMap') { throw 'Enhanced map delegation missing' }
    if ($appJs -notmatch 'JarnsenMapSettings\.renderSettings') { throw 'Bundled settings delegation missing' }

    $mapJs = Get-Content tools/service_tool_web/map-settings-v32.js -Raw
    foreach ($marker in @('OpenTopoMap','World_Imagery','mgrs.forward','override_frequency','channel_num','FUNK & MESH')) {
        if ($mapJs -notmatch [regex]::Escape($marker)) { throw "Enhanced map/settings marker missing: $marker" }
    }

    $radioJs = Get-Content tools/service_tool_web/radio-auth-v33.js -Raw
    foreach ($marker in @('/api/radio-authorization','Jarnsen 1','Jarnsen 2','max. 20','Duty Cycle','is_licensed')) {
        if ($radioJs -notmatch [regex]::Escape($marker)) { throw "Radio authorization marker missing: $marker" }
    }

    $parityJs = Get-Content tools/service_tool_web/parity-v35.js -Raw
    foreach ($marker in @('/api/service-status','/api/service/action','serial_monitor_start','full_log_resync','diagnostic_bundle','serial_flash','app_update_check','save_security_policy')) {
        if ($parityJs -notmatch [regex]::Escape($marker)) { throw "v2.1.28 parity marker missing: $marker" }
    }
    $parityEnhanceJs = Get-Content tools/service_tool_web/parity-enhance-v36.js -Raw
    foreach ($marker in @('serial_monitor_export','serialViewFilter','serialViewSearch','serialPauseButton','serialPowerCanvas','jarnsen-ui-zoom')) {
        if ($parityEnhanceJs -notmatch [regex]::Escape($marker)) { throw "Enhanced serial parity marker missing: $marker" }
    }

    Write-Host '=== Build Framework7 portable Windows app ==='
    $pyInstallerArgs = @(
        '-m','PyInstaller',
        '--noconfirm','--clean','--onefile','--windowed',
        '--name','Jarnsen-Node-Service-Tool',
        '--add-data','tools/service_tool_web;service_tool_web',
        '--collect-all','webview',
        '--collect-submodules','serial',
        '--collect-all','bleak',
        '--collect-all','esptool',
        '--collect-submodules','send2trash',
        '--collect-all','tkintermapview',
        '--collect-all','customtkinter',
        '--collect-all','meshtastic',
        '--hidden-import','JARNSEN_FRAMEWORK7_HEADLESS_CORE',
        '--hidden-import','JARNSEN_FRAMEWORK7_HEADLESS_BOOT',
        '--hidden-import','_tkinter',
        '--hidden-import','winrt.windows.devices.enumeration',
        '--hidden-import','winrt.windows.devices.bluetooth',
        'tools/JARNSEN_FRAMEWORK7_SERVICE_TOOL_V31.py'
    )
    & $python @pyInstallerArgs
    Assert-ExitCode 'PyInstaller build'

    Write-Host '=== Test packaged Framework7 assets ==='
    Remove-Item Jarnsen-Node-Service-Tool-self-test.txt -Force -ErrorAction SilentlyContinue
    $process = Start-Process -FilePath dist/Jarnsen-Node-Service-Tool.exe -ArgumentList '--self-test' -Wait -PassThru
    if (!(Test-Path Jarnsen-Node-Service-Tool-self-test.txt)) { throw 'Packaged self-test output file missing' }
    $selfTest = Get-Content Jarnsen-Node-Service-Tool-self-test.txt -Raw
    Write-Host $selfTest
    if ($process.ExitCode -ne 0) { throw 'Framework7 packaged self-test failed' }
    if ($selfTest -notmatch "version=$([regex]::Escape($version))") { throw "Packaged version is not $version" }
    if ($selfTest -notmatch 'functional_reference=v2.1.28-cumulative') { throw 'Packaged functional reference is not v2.1.28' }
    if ($selfTest -notmatch 'map-settings-v32') { throw 'Packaged enhanced map/settings UI missing' }
    if ($selfTest -notmatch 'global-radio-authorization') { throw 'Packaged global radio authorization missing' }
    if ($selfTest -notmatch 'standard-max7') { throw 'Packaged standard hop policy missing' }
    if ($selfTest -notmatch 'exact-A-B-max20') { throw 'Packaged authorized hop policy missing' }
    if ($selfTest -notmatch 'parity=v2.1.28-cumulative-or-improved') { throw 'Packaged v2.1.28 parity marker missing' }
    if ($selfTest -notmatch 'backend=headless-service-core-no-tk-mainloop') { throw 'Headless backend marker missing' }
    if ($selfTest -notmatch 'serial-filter-search-pause') { throw 'Packaged enhanced serial monitor parity missing' }

    Write-Host '=== Smoke test headless backend and complete parity API ==='
    $token = 'ci-framework7-token'
    $port = 17891
    Remove-Item Framework7-backend-bootstrap-error.txt -Force -ErrorAction SilentlyContinue
    $backend = Start-Process -FilePath dist/Jarnsen-Node-Service-Tool.exe -ArgumentList "--f7-backend --port $port --token $token" -PassThru -WindowStyle Hidden
    try {
        $healthy = $false
        $lastStage = 'process-starting'
        for ($i=0; $i -lt 240; $i++) {
            Start-Sleep -Milliseconds 250
            try {
                $health = Invoke-RestMethod -Uri "http://127.0.0.1:$port/health" -TimeoutSec 1
                $lastStage = [string]$health.stage
                if ($health.error) { throw "Headless backend bootstrap error: $($health.error)" }
                if ($health.ok -and $health.ready) { $healthy = $true; break }
            } catch {
                if ($_.Exception.Message -like 'Headless backend bootstrap error:*') { throw }
            }
        }
        if (!$healthy) {
            if (Test-Path Framework7-backend-bootstrap-error.txt) {
                $bootstrapError = Get-Content Framework7-backend-bootstrap-error.txt -Raw
                throw "Framework7 headless backend failed at $lastStage`: $bootstrapError"
            }
            throw "Framework7 headless backend did not become ready; last stage=$lastStage"
        }

        $ui = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$port/ui/index.html?api=http%3A%2F%2F127.0.0.1%3A$port&token=$token&version=$version" -TimeoutSec 10
        if ($ui.StatusCode -ne 200) { throw "Framework7 UI returned HTTP $($ui.StatusCode)" }
        foreach ($reference in @('app-v31.js','map-settings-v32.js','radio-auth-v33.js','legacy-compat-v34.js','parity-v35.js','parity-enhance-v36.js','leaflet.js','mgrs.min.js')) {
            if ($ui.Content -notmatch [regex]::Escape($reference)) { throw "Framework7 UI reference missing: $reference" }
        }

        $criticalAssets = @(
            @{ Path='/ui/app-v31.js'; Marker="theme: 'ios'" },
            @{ Path='/ui/map-settings-v32.js'; Marker='OpenTopoMap' },
            @{ Path='/ui/map-settings-v32.css'; Marker='interactive-map' },
            @{ Path='/ui/radio-auth-v33.js'; Marker='/api/radio-authorization' },
            @{ Path='/ui/radio-auth-v33.css'; Marker='radio-auth-global-card' },
            @{ Path='/ui/legacy-compat-v34.js'; Marker='usb-log' },
            @{ Path='/ui/parity-v35.js'; Marker='/api/service-status' },
            @{ Path='/ui/parity-v35.css'; Marker='parity-overlay' },
            @{ Path='/ui/parity-enhance-v36.js'; Marker='serial_monitor_export' },
            @{ Path='/ui/parity-enhance-v36.css'; Marker='serial-enhance-tools' },
            @{ Path='/ui/vendor/leaflet.js'; Marker='Leaflet' },
            @{ Path='/ui/vendor/mgrs.min.js'; Marker='forward' }
        )
        foreach ($asset in $criticalAssets) {
            $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$port$($asset.Path)" -TimeoutSec 10
            if ($response.StatusCode -ne 200) { throw "UI asset returned HTTP $($response.StatusCode): $($asset.Path)" }
            if ($response.Content -notmatch [regex]::Escape($asset.Marker)) { throw "UI asset marker missing: $($asset.Path)" }
        }

        $headers = @{ 'X-Jarnsen-Token' = $token }
        $state = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/state" -Headers $headers -TimeoutSec 15
        if ($state.version -ne $version) { throw "Unexpected API version $($state.version)" }
        if ($null -eq $state.connections) { throw 'USB compatibility state missing' }
        $profiles = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/profiles" -Headers $headers -TimeoutSec 15
        if ($null -eq $profiles.profiles) { throw 'Framework7 profile endpoint missing' }
        $radioAuth = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/radio-authorization" -Headers $headers -TimeoutSec 15
        if ($radioAuth.standard_max_hops -ne 7) { throw 'Standard max hop policy is not 7' }
        if ($radioAuth.authorized_max_hops -ne 20) { throw 'Authorized max hop policy is not 20' }
        if (!$radioAuth.frequency_bound) { throw 'Radio authorization is not frequency-bound' }
        if (!$radioAuth.unlock_duty_cycle) { throw 'Duty-cycle authorization missing' }
        if (!$radioAuth.unlock_tx_power) { throw 'Transmit-power authorization missing' }

        $service = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/service-status" -Headers $headers -TimeoutSec 20
        if (!$service.ok) { throw 'v2.1.28 parity status is not complete' }
        foreach ($capability in @('serial_monitor','serial_flash','full_usb_resync','diagnostic_bundle','config_snapshot','app_self_update','ble_ota','profile_policy','serial_filter_search_pause','serial_power_view','serial_session_export','ui_zoom')) {
            if (!$service.critical.$capability) { throw "v2.1.28 parity capability missing: $capability" }
        }
        if ($null -eq $service.parity -or $service.parity.Count -lt 7) { throw 'v2.1.28 feature parity matrix incomplete' }
    } finally {
        Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
    }

    Write-Host '=== Collect preview artifact ==='
    New-Item -ItemType Directory -Force artifact | Out-Null
    Copy-Item dist/Jarnsen-Node-Service-Tool.exe artifact/
    @{
        schema = 3
        app = 'Jarnsen Node Service Tool'
        version = $version
        functional_reference = 'v2.1.28 cumulative'
        ui = 'Framework7 9.1.3 / iOS'
        architecture = 'Framework7 WebView + loopback HTTP UI/API + true headless service core; no Tk mainloop'
        fixes = @('no file:// WebView path','no hidden Tk root/mainloop','HTTP readiness stages','deduplicated rendering','unique serial node usable without managed DB selection')
        features = @('v2.1.28 cumulative function parity or improvement','native profile editor','profile apply/readback','USB provisioning','pixel live display','interactive OpenTopo/satellite/hybrid map','MGRS point pick','bundled radio settings','global Jarnsen A/B radio authorization','standard max 7 hops','authorized max 20 hops','frequency-bound duty-cycle override','frequency-bound transmit-power authorization','serial monitor with filter/search/pause/power/export','full USB log resync','USB firmware plus OTA-loader recovery','Bluetooth recovery','diagnostic bundle','config snapshot','tool self-update','Jarnsen full-lock policy','80-125 percent UI zoom')
        source_sha = $env:GITHUB_SHA
    } | ConvertTo-Json | Set-Content -Encoding utf8 artifact/jarnsen-node-service-tool.json

    Write-Host 'Framework7 build and smoke tests completed successfully.'
} catch {
    $message = $_ | Out-String
    $message | Set-Content -Encoding utf8 (Join-Path $logDir 'framework7-build-error.txt')
    Write-Error $message
    throw
} finally {
    try { Stop-Transcript | Out-Null } catch {}
}
