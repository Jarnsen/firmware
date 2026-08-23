from pathlib import Path
import configparser

core = Path("scripts/apply_v3_antenna_swap_tx_lock_core.py")
if not core.exists():
    raise SystemExit("V3 antenna swap TX lock core script missing")
exec(compile(core.read_text(), str(core), "exec"), {"__name__": "__main__"})

# ---------------------------------------------------------------------------
# Diagnostic log metadata is applied LAST so the earlier observability patch
# cannot overwrite it. version.properties is the single source for the
# Meshtastic semantic version; the workflow-generated build header supplies
# the exact Git commit SHA at compile time.
# ---------------------------------------------------------------------------
version_cfg = configparser.ConfigParser()
if not version_cfg.read("version.properties"):
    raise SystemExit("V3 diagnostic metadata: version.properties missing")
try:
    meshtastic_version = ".".join(
        version_cfg["VERSION"][key].strip() for key in ("major", "minor", "build")
    )
except KeyError as exc:
    raise SystemExit(f"V3 diagnostic metadata: malformed version.properties: {exc}")

meta_header = Path("src/infrastructure/HeltecV3DiagMetadataGenerated.h")
meta_header.write_text(
    '#pragma once\n'
    f'#define JARNSEN_MESHTASTIC_VERSION "{meshtastic_version}"\n'
    '#define JARNSEN_DIAG_FEATURE_VERSION "diag-meta-v1"\n'
    '#define JARNSEN_DIAG_LOG_FORMAT 2U\n'
)

DIAG = Path("src/infrastructure/HeltecV3DiagnosticLog.cpp")
diag = DIAG.read_text()


def patch_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"{label}: already applied")
        return text
    if old not in text:
        raise SystemExit(f"{label}: anchor not found")
    print(f"{label}: applied")
    return text.replace(old, new, 1)


diag = patch_once(
    diag,
    '#include "infrastructure/HeltecV3DiagnosticLog.h"\n',
    '#include "infrastructure/HeltecV3DiagnosticLog.h"\n'
    '#include "HeltecV3BuildGenerated.h"\n'
    '#include "HeltecV3DiagMetadataGenerated.h"\n',
    "V3 diagnostic build/version includes",
)

diag = patch_once(
    diag,
    'constexpr uint32_t USB_SETTLE_MS = 1000UL;\n',
    'constexpr uint32_t USB_SETTLE_MS = 1000UL;\n\n'
    'const char *diagRoleText()\n'
    '{\n'
    '    switch (config.device.role) {\n'
    '    case meshtastic_Config_DeviceConfig_Role_ROUTER_LATE: return "ROUTER_LATE";\n'
    '    case meshtastic_Config_DeviceConfig_Role_REPEATER: return "REPEATER";\n'
    '    default: return "OTHER";\n'
    '    }\n'
    '}\n',
    "V3 diagnostic runtime role text",
)

diag = patch_once(
    diag,
    '    heltecV3DiagLog("BOOT", "count=%u reset=%s crashCount=%u", (unsigned)stats.bootCount,\n'
    '                    heltecV3DiagResetReasonText(), (unsigned)stats.crashResetCount);\n',
    '    heltecV3DiagLog("BOOT",\n'
    '                    "count=%u reset=%s crashCount=%u role=%s firmware=%s build=%s built=%s %s feature=%s logFormat=%u",\n'
    '                    (unsigned)stats.bootCount, heltecV3DiagResetReasonText(), (unsigned)stats.crashResetCount,\n'
    '                    diagRoleText(), JARNSEN_MESHTASTIC_VERSION, JARNSEN_V3_BUILD_SHA, __DATE__, __TIME__,\n'
    '                    JARNSEN_DIAG_FEATURE_VERSION, (unsigned)JARNSEN_DIAG_LOG_FORMAT);\n',
    "V3 BOOT firmware/build breadcrumb",
)

legacy_begin = (
    '        Serial.print("\\r\\n===V3_LOG_BEGIN===\\r\\n");\n'
    '        Serial.printf("# bytes=%u\\r\\n", (unsigned)exportTotalBytes);\n'
)
shared_begin_minimal = (
    '        Serial.print("\\r\\n===JARNSEN_DIAG_LOG_BEGIN===\\r\\n");\n'
    '        Serial.printf("# bytes=%u\\r\\n", (unsigned)exportTotalBytes);\n'
)
metadata_begin = (
    '        char exportTime[32] = {};\n'
    '        makeTimestamp(exportTime, sizeof(exportTime));\n'
    '        Serial.print("\\r\\n===JARNSEN_DIAG_LOG_BEGIN===\\r\\n");\n'
    '        Serial.print("# device=HELTEC_V3_REPEATER\\r\\n");\n'
    '        Serial.printf("# firmware=%s\\r\\n", JARNSEN_MESHTASTIC_VERSION);\n'
    '        Serial.printf("# build=%s\\r\\n", JARNSEN_V3_BUILD_SHA);\n'
    '        Serial.printf("# build_time=%s %s\\r\\n", __DATE__, __TIME__);\n'
    '        Serial.printf("# role=%s\\r\\n", diagRoleText());\n'
    '        Serial.printf("# feature=%s\\r\\n", JARNSEN_DIAG_FEATURE_VERSION);\n'
    '        Serial.printf("# log_format=%u\\r\\n", (unsigned)JARNSEN_DIAG_LOG_FORMAT);\n'
    '        Serial.printf("# export=%s\\r\\n", exportTime);\n'
    '        Serial.printf("# bytes=%u\\r\\n", (unsigned)exportTotalBytes);\n'
)
if metadata_begin not in diag:
    if legacy_begin in diag:
        diag = diag.replace(legacy_begin, metadata_begin, 1)
        print("V3 diagnostic export metadata header: applied from legacy marker")
    elif shared_begin_minimal in diag:
        diag = diag.replace(shared_begin_minimal, metadata_begin, 1)
        print("V3 diagnostic export metadata header: applied from shared marker")
    else:
        raise SystemExit("V3 diagnostic export metadata header: begin anchor not found")
else:
    print("V3 diagnostic export metadata header: already applied")

diag = diag.replace('===V3_LOG_END===', '===JARNSEN_DIAG_LOG_END===')

for needle in [
    'JARNSEN_V3_BUILD_SHA',
    'JARNSEN_MESHTASTIC_VERSION',
    '# device=HELTEC_V3_REPEATER',
    '# build=%s',
    '# build_time=%s %s',
    '# role=%s',
    '# feature=%s',
    '# log_format=%u',
    '# export=%s',
    '===JARNSEN_DIAG_LOG_BEGIN===',
    '===JARNSEN_DIAG_LOG_END===',
    'firmware=%s build=%s',
]:
    if needle not in diag:
        raise SystemExit(f"V3 diagnostic metadata verification failed: {needle}")

DIAG.write_text(diag)
print(f"V3 diagnostic metadata ready: Meshtastic {meshtastic_version}, build SHA stamped by workflow")
