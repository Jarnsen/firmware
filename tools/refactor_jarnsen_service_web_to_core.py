#!/usr/bin/env python3
from pathlib import Path

PATH = Path("src/mesh/http/JarnsenServiceWeb.cpp")
text = PATH.read_text(encoding="utf-8")
original = text

# The portal is intentionally large because the complete offline/iOS UI lives
# in PROGMEM. Refactor only known C++ seams and fail closed if upstream text
# differs, so map/UI code cannot be silently damaged by this migration.
replacements = [
    (
'''#if defined(_VARIANT_HELTEC_V3)\n#include "infrastructure/HeltecV3DiagnosticLog.h"\n#else\n#include "vehicle/TrackerDiagnosticLog.h"\n#endif''',
'''#include "jarnsen/core/service/JarnsenServiceDiagnostics.h"\n#include "jarnsen/core/service/JarnsenServicePlatform.h"'''
    ),
    (
'''#if defined(_VARIANT_HELTEC_V3)\nconstexpr const char *DEVICE_CODE = "HELTEC_V3_REPEATER";\nconstexpr const char *DEVICE_TITLE = "Heltec V3";\nconstexpr const char *SSID_PREFIX = "Jarnsen-V3";\nconstexpr const char *GITHUB_TAG = "jarnsen-v3-latest";\nconstexpr const char *FIRMWARE_ASSET = "heltec-v3-repeater-light-sleep.update.bin";\n#else\nconstexpr const char *DEVICE_CODE = "HELTEC_TRACKER_V1.1";\nconstexpr const char *DEVICE_TITLE = "Tracker V1.1";\nconstexpr const char *SSID_PREFIX = "Jarnsen-Tracker";\nconstexpr const char *GITHUB_TAG = "jarnsen-tracker-latest";\nconstexpr const char *FIRMWARE_ASSET = "heltec-tracker-v11-vehicle-motion-wake.update.bin";\n#endif''',
'''constexpr auto SERVICE_DESCRIPTOR = jarnsen::platformServiceDescriptor();\nstatic_assert(SERVICE_DESCRIPTOR.profile.hardware.kind != jarnsen::HardwareKind::UNKNOWN,\n              "Jarnsen ServiceWeb requires a known Unified Core hardware descriptor");\nconstexpr const char *DEVICE_CODE = SERVICE_DESCRIPTOR.protocolDeviceCode;\nconstexpr const char *DEVICE_TITLE = SERVICE_DESCRIPTOR.profile.hardware.displayName;\nconstexpr const char *SSID_PREFIX = SERVICE_DESCRIPTOR.serviceSsidPrefix;\nconstexpr const char *GITHUB_TAG = SERVICE_DESCRIPTOR.update.releaseTag;\nconstexpr const char *FIRMWARE_ASSET = SERVICE_DESCRIPTOR.update.assetName;'''
    ),
    (
'''bool startDiagExport()\n{\n#if defined(_VARIANT_HELTEC_V3)\n    return heltecV3DiagStartBleExport();\n#else\n    return trackerDiagStartBleExport();\n#endif\n}\n\nsize_t readDiagExport(uint8_t *buffer, size_t capacity)\n{\n#if defined(_VARIANT_HELTEC_V3)\n    return heltecV3DiagReadBleExport(buffer, capacity);\n#else\n    return trackerDiagReadBleExport(buffer, capacity);\n#endif\n}\n\nvoid cancelDiagExport()\n{\n#if defined(_VARIANT_HELTEC_V3)\n    heltecV3DiagCancelBleExport();\n#else\n    trackerDiagCancelBleExport();\n#endif\n}\n\nvoid logEvent(const char *event, const char *detail)\n{\n#if defined(_VARIANT_HELTEC_V3)\n    heltecV3DiagLog(event, "%s", detail);\n#else\n    trackerDiagLog(event, "%s", detail);\n#endif\n}''',
'''bool startDiagExport()\n{\n    return jarnsen::serviceDiagStartExport();\n}\n\nsize_t readDiagExport(uint8_t *buffer, size_t capacity)\n{\n    return jarnsen::serviceDiagReadExport(buffer, capacity);\n}\n\nvoid cancelDiagExport()\n{\n    jarnsen::serviceDiagCancelExport();\n}\n\nvoid logEvent(const char *event, const char *detail)\n{\n    jarnsen::serviceDiagLog(event, detail);\n}'''
    ),
]

for index, (old, new) in enumerate(replacements, start=1):
    count = text.count(old)
    if count == 0 and new in text:
        continue
    if count != 1:
        raise SystemExit(f"ServiceWeb migration seam {index} expected once, found {count}")
    text = text.replace(old, new, 1)

required_portal_fingerprints = [
    '<h2>Taktische Lage</h2>',
    "const BASEMAPS={",
    "satellite:{name:'SATELLIT'",
    "hybrid:{name:'HYBRID'",
    "function selectMapPoint",
    "function enableCompass",
    "setInterval(loadSituation,10000)",
]
for needle in required_portal_fingerprints:
    if needle not in text:
        raise SystemExit(f"Portal safeguard failed; missing {needle!r}")

for legacy in [
    '#include "infrastructure/HeltecV3DiagnosticLog.h"',
    '#include "vehicle/TrackerDiagnosticLog.h"',
    'constexpr const char *DEVICE_CODE = "HELTEC_V3_REPEATER"',
    'constexpr const char *DEVICE_CODE = "HELTEC_TRACKER_V1.1"',
    'heltecV3DiagStartBleExport()',
    'trackerDiagStartBleExport()',
]:
    if legacy in text:
        raise SystemExit(f"Legacy ServiceWeb dependency remains: {legacy}")

if text == original:
    print("JarnsenServiceWeb already uses Unified Core service seams")
else:
    PATH.write_text(text, encoding="utf-8")
    print("Migrated JarnsenServiceWeb identity/update/diagnostics to Unified Core")
