#!/usr/bin/env python3
from pathlib import Path

PATH = Path("src/mesh/http/JarnsenServiceWeb.cpp")
text = PATH.read_text(encoding="utf-8")

# The ServiceWeb migration is complete on Unified Core. Keep this build-time
# guard as a fail-closed verifier instead of mutating the checked-out source on
# every build. That makes local builds and CI deterministic and protects the
# large PROGMEM portal from stale text-replacement migrations.
required_portal_fingerprints = [
    '<h2>Taktische Lage</h2>',
    "const BASEMAPS={",
    "satellite:{name:'SATELLIT'",
    "hybrid:{name:'HYBRID'",
    "function selectMapPoint",
    "function enableCompass",
    "setInterval(loadSituation,10000)",
    "setInterval(loadLive,2000)",
    "/live.json",
]

required_core_fingerprints = [
    'JarnsenServiceDiagnostics.h',
    'JarnsenServicePlatform.h',
    'JarnsenServiceSecurity.h',
    'JarnsenStatusProvider.h',
    'SERVICE_DESCRIPTOR = jarnsen::platformServiceDescriptor()',
    'jarnsen::serviceDiagStartExport()',
    'jarnsen::readNodeStatus(SERVICE_DESCRIPTOR.profile)',
    'serviceSecurityWifiAllowed()',
    'serviceSecurityVerifyPin',
    'WIFI_AP',
    'WiFi.mode(WIFI_OFF)',
    'CAPTIVE_DNS_GRACE_MS',
    'X-Jarnsen-Pin',
    'JARN_SESSION',
    '\\"board_capabilities\\"',
    '\\"supported_roles\\"',
]

for needle in required_portal_fingerprints:
    if needle not in text:
        raise SystemExit(f"Portal safeguard failed; missing {needle!r}")

for needle in required_core_fingerprints:
    if needle not in text:
        raise SystemExit(f"Core service safeguard failed; missing {needle!r}")

for legacy in [
    '#include "infrastructure/HeltecV3DiagnosticLog.h"',
    '#include "vehicle/TrackerDiagnosticLog.h"',
    'constexpr const char *DEVICE_CODE = "HELTEC_V3_REPEATER"',
    'constexpr const char *DEVICE_CODE = "HELTEC_TRACKER_V1.1"',
    'heltecV3DiagStartBleExport()',
    'trackerDiagStartBleExport()',
    'WiFi.mode(hadStation ? WIFI_STA : WIFI_OFF)',
]:
    if legacy in text:
        raise SystemExit(f"Legacy ServiceWeb dependency remains: {legacy}")

print("Verified JarnsenServiceWeb Unified Core service/security migration")
