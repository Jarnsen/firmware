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
'''#include "jarnsen/core/service/JarnsenServiceDiagnostics.h"\n#include "jarnsen/hardware/JarnsenServicePlatform.h"\n#include "jarnsen/core/status/JarnsenStatusProvider.h"'''
    ),
    (
'''#if defined(_VARIANT_HELTEC_V3)\nconstexpr const char *DEVICE_CODE = "HELTEC_V3_REPEATER";\nconstexpr const char *DEVICE_TITLE = "Heltec V3";\nconstexpr const char *SSID_PREFIX = "Jarnsen-V3";\nconstexpr const char *GITHUB_TAG = "jarnsen-v3-latest";\nconstexpr const char *FIRMWARE_ASSET = "heltec-v3-repeater-light-sleep.update.bin";\n#else\nconstexpr const char *DEVICE_CODE = "HELTEC_TRACKER_V1.1";\nconstexpr const char *DEVICE_TITLE = "Tracker V1.1";\nconstexpr const char *SSID_PREFIX = "Jarnsen-Tracker";\nconstexpr const char *GITHUB_TAG = "jarnsen-tracker-latest";\nconstexpr const char *FIRMWARE_ASSET = "heltec-tracker-v11-vehicle-motion-wake.update.bin";\n#endif''',
'''constexpr auto SERVICE_DESCRIPTOR = jarnsen::platformServiceDescriptor();\nstatic_assert(SERVICE_DESCRIPTOR.profile.hardware.kind != jarnsen::HardwareKind::UNKNOWN,\n              "Jarnsen ServiceWeb requires a known Unified Core hardware descriptor");\nconstexpr const char *DEVICE_CODE = SERVICE_DESCRIPTOR.protocolDeviceCode;\nconstexpr const char *DEVICE_TITLE = SERVICE_DESCRIPTOR.profile.hardware.displayName;\nconstexpr const char *SSID_PREFIX = SERVICE_DESCRIPTOR.serviceSsidPrefix;\nconstexpr const char *GITHUB_TAG = SERVICE_DESCRIPTOR.update.releaseTag;\nconstexpr const char *FIRMWARE_ASSET = SERVICE_DESCRIPTOR.update.assetName;'''
    ),
    (
'''bool startDiagExport()\n{\n#if defined(_VARIANT_HELTEC_V3)\n    return heltecV3DiagStartBleExport();\n#else\n    return trackerDiagStartBleExport();\n#endif\n}\n\nsize_t readDiagExport(uint8_t *buffer, size_t capacity)\n{\n#if defined(_VARIANT_HELTEC_V3)\n    return heltecV3DiagReadBleExport(buffer, capacity);\n#else\n    return trackerDiagReadBleExport(buffer, capacity);\n#endif\n}\n\nvoid cancelDiagExport()\n{\n#if defined(_VARIANT_HELTEC_V3)\n    heltecV3DiagCancelBleExport();\n#else\n    trackerDiagCancelBleExport();\n#endif\n}\n\nvoid logEvent(const char *event, const char *detail)\n{\n#if defined(_VARIANT_HELTEC_V3)\n    heltecV3DiagLog(event, "%s", detail);\n#else\n    trackerDiagLog(event, "%s", detail);\n#endif\n}''',
'''bool startDiagExport()\n{\n    return jarnsen::serviceDiagStartExport();\n}\n\nsize_t readDiagExport(uint8_t *buffer, size_t capacity)\n{\n    return jarnsen::serviceDiagReadExport(buffer, capacity);\n}\n\nvoid cancelDiagExport()\n{\n    jarnsen::serviceDiagCancelExport();\n}\n\nvoid logEvent(const char *event, const char *detail)\n{\n    jarnsen::serviceDiagLog(event, detail);\n}'''
    ),
    (
'''void sendJsonStatus(WiFiClient &client)\n{\n    sendStatus(client, 200, "OK", "application/json; charset=utf-8");\n    const meshtastic_NodeInfoLite *self = nodeDB ? nodeDB->getMeshNode(nodeDB->getNodeNum()) : nullptr;''',
'''void sendJsonStatus(WiFiClient &client)\n{\n    sendStatus(client, 200, "OK", "application/json; charset=utf-8");\n    const jarnsen::NodeStatusSnapshot runtimeStatus = jarnsen::readNodeStatus(SERVICE_DESCRIPTOR.profile);\n    const meshtastic_NodeInfoLite *self = nodeDB ? nodeDB->getMeshNode(nodeDB->getNodeNum()) : nullptr;'''
    ),
    (
'''    client.print(",\\\"device\\\":");\n    sendJsonString(client, DEVICE_CODE);\n    client.print(",\\\"name\\\":");''',
'''    client.print(",\\\"device\\\":");\n    sendJsonString(client, DEVICE_CODE);\n    client.print(",\\\"hardware\\\":");\n    sendJsonString(client, runtimeStatus.profile.hardware.code);\n    client.print(",\\\"hardware_name\\\":");\n    sendJsonString(client, runtimeStatus.profile.hardware.displayName);\n    client.print(",\\\"role\\\":");\n    sendJsonString(client, runtimeStatus.activeRoleKnown ? jarnsen::roleName(runtimeStatus.activeRole) : "UNKNOWN");\n    client.printf(",\\\"role_known\\\":%s,\\\"peripherals_known\\\":%s", runtimeStatus.activeRoleKnown ? "true" : "false",\n                  runtimeStatus.peripheralsKnown ? "true" : "false");\n    const auto &boardCaps = runtimeStatus.profile.hardware.capabilities;\n    client.printf(",\\\"board_capabilities\\\":{\\\"internal_gps\\\":%s,\\\"external_gps\\\":%s,\\\"bluetooth\\\":%s,\\\"wifi\\\":%s,\\\"battery\\\":%s,\\\"motion\\\":%s,\\\"ina226\\\":%s}",\n                  boardCaps.internalGps ? "true" : "false", boardCaps.supportsExternalGps ? "true" : "false",\n                  boardCaps.bluetooth ? "true" : "false", boardCaps.wifi ? "true" : "false", boardCaps.battery ? "true" : "false",\n                  boardCaps.supportsMotion ? "true" : "false", boardCaps.supportsIna226 ? "true" : "false");\n    const auto &caps = runtimeStatus.capabilities;\n    client.printf(",\\\"capabilities\\\":{\\\"gps\\\":%s,\\\"bluetooth\\\":%s,\\\"wifi\\\":%s,\\\"battery\\\":%s,\\\"usb_power\\\":%s,\\\"motion\\\":%s,\\\"ina226\\\":%s}",\n                  caps.gps ? "true" : "false", caps.bluetooth ? "true" : "false", caps.wifi ? "true" : "false",\n                  caps.battery ? "true" : "false", caps.usbPowerDetect ? "true" : "false", caps.motion ? "true" : "false",\n                  caps.ina226 ? "true" : "false");\n    const auto &roles = runtimeStatus.profile.roles;\n    client.printf(",\\\"supported_roles\\\":{\\\"tak\\\":%s,\\\"tak_tracker\\\":%s,\\\"tak_repeater\\\":%s,\\\"drone_repeater\\\":%s}",\n                  roles.tak ? "true" : "false", roles.takTracker ? "true" : "false", roles.takRepeater ? "true" : "false",\n                  roles.droneRepeater ? "true" : "false");\n    client.print(",\\\"name\\\":");'''
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

required_core_fingerprints = [
    'JarnsenServiceDiagnostics.h',
    'JarnsenServicePlatform.h',
    'JarnsenStatusProvider.h',
    'SERVICE_DESCRIPTOR = jarnsen::platformServiceDescriptor()',
    'jarnsen::serviceDiagStartExport()',
    'jarnsen::readNodeStatus(SERVICE_DESCRIPTOR.profile)',
    '\\"board_capabilities\\"',
    '\\"supported_roles\\"',
]
for needle in required_core_fingerprints:
    if needle not in text:
        raise SystemExit(f"Core migration safeguard failed; missing {needle!r}")

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
    print("JarnsenServiceWeb already uses Unified Core service/status seams")
else:
    PATH.write_text(text, encoding="utf-8")
    print("Migrated JarnsenServiceWeb identity/update/diagnostics/status to Unified Core")
