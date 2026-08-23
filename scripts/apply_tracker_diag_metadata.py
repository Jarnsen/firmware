from pathlib import Path

DIAG_PATH = Path("src/vehicle/TrackerDiagnosticLog.cpp")
COMMON_PATH = Path("src/vehicle/TrackerCommonPolicy.cpp")
diag = DIAG_PATH.read_text()
common = COMMON_PATH.read_text()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"{label}: already applied")
        return text
    if old not in text:
        raise SystemExit(f"{label}: anchor not found")
    print(f"{label}: applied")
    return text.replace(old, new, 1)


meta_header = Path("src/vehicle/JarnsenDiagMetadataGenerated.h")
meta_header.write_text(
    '#pragma once\n'
    '#define JARNSEN_DIAG_FEATURE_VERSION "diag-meta-v1"\n'
    '#define JARNSEN_DIAG_LOG_FORMAT 2U\n'
)

diag = replace_once(
    diag,
    '#include "TrackerDiagnosticLog.h"\n',
    '#include "TrackerDiagnosticLog.h"\n'
    '#include "NodeDB.h"\n'
    '#include "JarnsenBuildGenerated.h"\n'
    '#include "JarnsenDiagMetadataGenerated.h"\n',
    "Tracker diagnostic build/version includes",
)

diag = replace_once(
    diag,
    'constexpr uint32_t USB_SETTLE_MS = 1000UL;\n',
    'constexpr uint32_t USB_SETTLE_MS = 1000UL;\n\n'
    'const char *trackerDiagRoleText()\n'
    '{\n'
    '    return config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER ? "TAK_TRACKER" : "TAK";\n'
    '}\n',
    "Tracker diagnostic runtime role text",
)

common = replace_once(
    common,
    '#include "configuration.h"\n',
    '#include "configuration.h"\n'
    '#include "vehicle/JarnsenBuildGenerated.h"\n'
    '#include "vehicle/JarnsenDiagMetadataGenerated.h"\n',
    "Tracker BOOT build/version includes",
)

old_boot = (
    '    trackerDiagLog("BOOT", "role=%s wake=%s park=%umin effective=%us",\n'
    '                   config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER ? "TAK_TRACKER" : "TAK",\n'
    '                   trackerBootWakeReason(), (unsigned)trackerParkIntervalMinutes(),\n'
    '                   (unsigned)trackerEffectiveParkIntervalSecs());\n'
)
new_boot = (
    '    trackerDiagLog("BOOT",\n'
    '                   "role=%s wake=%s park=%umin effective=%us firmware=%s build=%s built=%s %s feature=%s logFormat=%u",\n'
    '                   config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER ? "TAK_TRACKER" : "TAK",\n'
    '                   trackerBootWakeReason(), (unsigned)trackerParkIntervalMinutes(),\n'
    '                   (unsigned)trackerEffectiveParkIntervalSecs(), APP_VERSION, JARNSEN_BUILD_SHA,\n'
    '                   __DATE__, __TIME__, JARNSEN_DIAG_FEATURE_VERSION, (unsigned)JARNSEN_DIAG_LOG_FORMAT);\n'
)
common = replace_once(common, old_boot, new_boot, "Tracker BOOT firmware/build breadcrumb")

# Earlier Tracker patches already normalize markers and may add a device-only
# line. Normalize both legacy markers and replace only the unique bytes line,
# so the metadata patch does not depend on exact header ordering.
diag = diag.replace('===TRACKER_LOG_BEGIN===', '===JARNSEN_DIAG_LOG_BEGIN===')
diag = diag.replace('===TRACKER_LOG_END===', '===JARNSEN_DIAG_LOG_END===')
for old_device in [
    '        Serial.print("# device=HELTEC_TRACKER_V1_1\\r\\n");\n',
    '        Serial.print("# device=HELTEC_TRACKER_V1.1\\r\\n");\n',
]:
    diag = diag.replace(old_device, '')

bytes_line = '        Serial.printf("# bytes=%u\\r\\n", (unsigned)exportTotalBytes);\n'
metadata_lines = (
    '        char exportTime[32] = {};\n'
    '        makeTimestamp(exportTime, sizeof(exportTime));\n'
    '        Serial.print("# device=HELTEC_TRACKER_V1.1\\r\\n");\n'
    '        Serial.printf("# firmware=%s\\r\\n", APP_VERSION);\n'
    '        Serial.printf("# build=%s\\r\\n", JARNSEN_BUILD_SHA);\n'
    '        Serial.printf("# build_time=%s %s\\r\\n", __DATE__, __TIME__);\n'
    '        Serial.printf("# role=%s\\r\\n", trackerDiagRoleText());\n'
    '        Serial.printf("# feature=%s\\r\\n", JARNSEN_DIAG_FEATURE_VERSION);\n'
    '        Serial.printf("# log_format=%u\\r\\n", (unsigned)JARNSEN_DIAG_LOG_FORMAT);\n'
    '        Serial.printf("# export=%s\\r\\n", exportTime);\n'
)
if metadata_lines not in diag:
    if bytes_line not in diag:
        raise SystemExit("Tracker diagnostic export metadata: bytes anchor not found")
    diag = diag.replace(bytes_line, metadata_lines + bytes_line, 1)
    print("Tracker diagnostic export metadata header: applied around bytes anchor")
else:
    print("Tracker diagnostic export metadata header: already applied")

for needle in [
    '#include "NodeDB.h"', 'APP_VERSION', 'JARNSEN_BUILD_SHA',
    '# device=HELTEC_TRACKER_V1.1', '# build=%s', '# build_time=%s %s',
    '# role=%s', '# feature=%s', '# log_format=%u', '# export=%s',
    '===JARNSEN_DIAG_LOG_BEGIN===', '===JARNSEN_DIAG_LOG_END===',
]:
    if needle not in diag:
        raise SystemExit(f"Tracker diagnostic metadata verification failed: {needle}")

for needle in ['firmware=%s build=%s', 'APP_VERSION', 'JARNSEN_BUILD_SHA', 'JARNSEN_DIAG_LOG_FORMAT']:
    if needle not in common:
        raise SystemExit(f"Tracker BOOT metadata verification failed: {needle}")

DIAG_PATH.write_text(diag)
COMMON_PATH.write_text(common)
print("Tracker diagnostic metadata ready: APP_VERSION + exact workflow build SHA")
