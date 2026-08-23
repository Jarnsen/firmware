from pathlib import Path

DIAG = Path("src/infrastructure/HeltecV3DiagnosticLog.cpp")
diag = DIAG.read_text()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"{label}: already applied")
        return text
    if old not in text:
        raise SystemExit(f"{label}: anchor not found")
    print(f"{label}: applied")
    return text.replace(old, new, 1)


diag = replace_once(
    diag,
    '#include "configuration.h"\n',
    '#include "configuration.h"\n#include "NodeDB.h"\n',
    "V3 diagnostic runtime config declaration",
)

diag = replace_once(
    diag,
    '#include "infrastructure/HeltecV3DiagnosticLog.h"\n',
    '#include "infrastructure/HeltecV3DiagnosticLog.h"\n#include "HeltecV3BuildGenerated.h"\n',
    "V3 diagnostic build SHA include",
)

diag = replace_once(
    diag,
    'constexpr uint32_t USB_SETTLE_MS = 1000UL;\n',
    'constexpr uint32_t USB_SETTLE_MS = 1000UL;\n'
    'constexpr const char *DIAG_FEATURE_VERSION = "diag-meta-v1";\n'
    'constexpr uint32_t DIAG_LOG_FORMAT = 2U;\n\n'
    'const char *diagRoleText()\n'
    '{\n'
    '    switch (config.device.role) {\n'
    '    case meshtastic_Config_DeviceConfig_Role_ROUTER_LATE: return "ROUTER_LATE";\n'
    '    case meshtastic_Config_DeviceConfig_Role_REPEATER: return "REPEATER";\n'
    '    default: return "OTHER";\n'
    '    }\n'
    '}\n',
    "V3 diagnostic metadata constants and role",
)

old_boot = (
    '    heltecV3DiagLog("BOOT", "count=%u reset=%s crashCount=%u", (unsigned)stats.bootCount,\n'
    '                    heltecV3DiagResetReasonText(), (unsigned)stats.crashResetCount);\n'
)
new_boot = (
    '    heltecV3DiagLog("BOOT",\n'
    '                    "count=%u reset=%s crashCount=%u role=%s firmware=%s build=%s built=%s %s feature=%s logFormat=%u",\n'
    '                    (unsigned)stats.bootCount, heltecV3DiagResetReasonText(), (unsigned)stats.crashResetCount,\n'
    '                    diagRoleText(), APP_VERSION, JARNSEN_V3_BUILD_SHA, __DATE__, __TIME__,\n'
    '                    DIAG_FEATURE_VERSION, (unsigned)DIAG_LOG_FORMAT);\n'
)
diag = replace_once(diag, old_boot, new_boot, "V3 BOOT firmware/build breadcrumb")

# Earlier patches may already normalize markers or insert a device-only line.
diag = diag.replace('===V3_LOG_BEGIN===', '===JARNSEN_DIAG_LOG_BEGIN===')
diag = diag.replace('===V3_LOG_END===', '===JARNSEN_DIAG_LOG_END===')
for old_device in [
    '        Serial.print("# device=HELTEC_V3_REPEATER\\r\\n");\n',
    '        Serial.print("# device=HELTEC_V3\\r\\n");\n',
]:
    diag = diag.replace(old_device, '')

bytes_line = '        Serial.printf("# bytes=%u\\r\\n", (unsigned)exportTotalBytes);\n'
metadata_lines = (
    '        char exportTime[32] = {};\n'
    '        makeTimestamp(exportTime, sizeof(exportTime));\n'
    '        Serial.print("# device=HELTEC_V3_REPEATER\\r\\n");\n'
    '        Serial.printf("# firmware=%s\\r\\n", APP_VERSION);\n'
    '        Serial.printf("# build=%s\\r\\n", JARNSEN_V3_BUILD_SHA);\n'
    '        Serial.printf("# build_time=%s %s\\r\\n", __DATE__, __TIME__);\n'
    '        Serial.printf("# role=%s\\r\\n", diagRoleText());\n'
    '        Serial.printf("# feature=%s\\r\\n", DIAG_FEATURE_VERSION);\n'
    '        Serial.printf("# log_format=%u\\r\\n", (unsigned)DIAG_LOG_FORMAT);\n'
    '        Serial.printf("# export=%s\\r\\n", exportTime);\n'
)
if metadata_lines not in diag:
    if bytes_line not in diag:
        raise SystemExit("V3 diagnostic export metadata: bytes anchor not found")
    diag = diag.replace(bytes_line, metadata_lines + bytes_line, 1)
    print("V3 diagnostic export metadata header: applied around bytes anchor")
else:
    print("V3 diagnostic export metadata header: already applied")

for needle in [
    '#include "NodeDB.h"', 'APP_VERSION', 'JARNSEN_V3_BUILD_SHA',
    '# device=HELTEC_V3_REPEATER', '# build=%s', '# build_time=%s %s',
    '# role=%s', '# feature=%s', '# log_format=%u', '# export=%s',
    '===JARNSEN_DIAG_LOG_BEGIN===', '===JARNSEN_DIAG_LOG_END===',
    'firmware=%s build=%s',
]:
    if needle not in diag:
        raise SystemExit(f"V3 diagnostic metadata verification failed: {needle}")

DIAG.write_text(diag)
print("V3 diagnostic metadata ready: APP_VERSION + exact workflow build SHA")
