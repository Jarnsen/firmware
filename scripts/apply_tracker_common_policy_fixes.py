from pathlib import Path
import runpy
import configparser

NIMBLE_CPP_PATH = Path("src/nimble/NimbleBluetooth.cpp")

nimble = NIMBLE_CPP_PATH.read_text()

old = """        // Count only non-empty payload reads. Empty client polling reads
        // must not make a background connection look actively used.
        if (numBytes != 0) {
            meaningfulBleTrafficCount.fetch_add(1);
            bluetoothPhoneAPI->setIntervalFromNow(0);
"""
new = """        // Count only non-empty payload reads. Empty client polling reads
        // must not make a background connection look actively used.
        if (numBytes != 0) {
            meaningfulBleTrafficCount.fetch_add(1);
            if (meshtasticTrackerBleActivity)
                meshtasticTrackerBleActivity();
            bluetoothPhoneAPI->setIntervalFromNow(0);
"""

if new in nimble:
    print("Tracker common BLE read activity hook: already applied")
elif old in nimble:
    nimble = nimble.replace(old, new, 1)
    print("Tracker common BLE read activity hook: applied")
else:
    raise SystemExit("Tracker common BLE read activity hook: anchor not found; run apply_tracker_ble_burst_policy.py first")

NIMBLE_CPP_PATH.write_text(nimble)

runpy.run_path("scripts/apply_tracker_gpio0_service_fix.py", run_name="__main__")
runpy.run_path("scripts/apply_tracker_display_service_fix.py", run_name="__main__")
runpy.run_path("scripts/apply_tracker_usb_serial_ui_fix.py", run_name="__main__")
runpy.run_path("scripts/apply_tracker_service_menu_power_fix.py", run_name="__main__")
runpy.run_path("scripts/apply_tracker_service_button_gesture_fix.py", run_name="__main__")
runpy.run_path("scripts/apply_tracker_service_original_back_menu_fix.py", run_name="__main__")
runpy.run_path("scripts/apply_tracker_tak_position_timer_fix.py", run_name="__main__")
runpy.run_path("scripts/apply_tracker_service_original_ui_diag_fix.py", run_name="__main__")
runpy.run_path("scripts/apply_tracker_diag_boot_order_fix.py", run_name="__main__")
runpy.run_path("scripts/apply_tracker_service_visual_export_fix.py", run_name="__main__")
runpy.run_path("scripts/apply_tracker_menu_back_cursor_fix.py", run_name="__main__")
runpy.run_path("scripts/apply_tracker_service_runtime_status_page_fix.py", run_name="__main__")
runpy.run_path("scripts/apply_tracker_service_stock_frame_fix.py", run_name="__main__")
runpy.run_path("scripts/prepare_tracker_clean_settings_patch.py", run_name="__main__")
runpy.run_path("scripts/apply_tracker_clean_settings_menu_fix.py", run_name="__main__")
runpy.run_path("scripts/apply_tracker_clean_settings_runtime_repair.py", run_name="__main__")
runpy.run_path("scripts/apply_tracker_log_clear_confirmation_fix.py", run_name="__main__")
runpy.run_path("scripts/apply_tracker_power_monitor_fix.py", run_name="__main__")
runpy.run_path("scripts/apply_tracker_ina226_capacity_fix.py", run_name="__main__")
runpy.run_path("scripts/apply_tracker_antenna_swap_tx_lock_compat.py", run_name="__main__")
runpy.run_path("scripts/apply_tracker_menu_structure_guard.py", run_name="__main__")
runpy.run_path("scripts/apply_tracker_artifact_extras.py", run_name="__main__")

# ---------------------------------------------------------------------------
# Apply diagnostic build/version metadata LAST, after all Tracker UI/log patches.
# version.properties remains the semantic-version source. The workflow creates
# JarnsenBuildGenerated.h after verification and before compilation, so source
# can safely reference the exact build SHA here.
# ---------------------------------------------------------------------------
version_cfg = configparser.ConfigParser()
if not version_cfg.read("version.properties"):
    raise SystemExit("Tracker diagnostic metadata: version.properties missing")
try:
    meshtastic_version = ".".join(
        version_cfg["VERSION"][key].strip() for key in ("major", "minor", "build")
    )
except KeyError as exc:
    raise SystemExit(f"Tracker diagnostic metadata: malformed version.properties: {exc}")

meta_header = Path("src/vehicle/JarnsenDiagMetadataGenerated.h")
meta_header.write_text(
    '#pragma once\n'
    f'#define JARNSEN_MESHTASTIC_VERSION "{meshtastic_version}"\n'
    '#define JARNSEN_DIAG_FEATURE_VERSION "diag-meta-v1"\n'
    '#define JARNSEN_DIAG_LOG_FORMAT 2U\n'
)

DIAG_PATH = Path("src/vehicle/TrackerDiagnosticLog.cpp")
COMMON_PATH = Path("src/vehicle/TrackerCommonPolicy.cpp")
diag = DIAG_PATH.read_text()
common = COMMON_PATH.read_text()


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
    '#include "TrackerDiagnosticLog.h"\n',
    '#include "TrackerDiagnosticLog.h"\n'
    '#include "JarnsenBuildGenerated.h"\n'
    '#include "JarnsenDiagMetadataGenerated.h"\n',
    "Tracker diagnostic build/version includes",
)

diag = patch_once(
    diag,
    'constexpr uint32_t USB_SETTLE_MS = 1000UL;\n',
    'constexpr uint32_t USB_SETTLE_MS = 1000UL;\n\n'
    'const char *trackerDiagRoleText()\n'
    '{\n'
    '    return config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER ? "TAK_TRACKER" : "TAK";\n'
    '}\n',
    "Tracker diagnostic runtime role text",
)

common = patch_once(
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
    '                   (unsigned)trackerEffectiveParkIntervalSecs(), JARNSEN_MESHTASTIC_VERSION, JARNSEN_BUILD_SHA,\n'
    '                   __DATE__, __TIME__, JARNSEN_DIAG_FEATURE_VERSION, (unsigned)JARNSEN_DIAG_LOG_FORMAT);\n'
)
common = patch_once(common, old_boot, new_boot, "Tracker BOOT firmware/build breadcrumb")

legacy_begin = (
    '        Serial.print("\\r\\n===TRACKER_LOG_BEGIN===\\r\\n");\n'
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
    '        Serial.print("# device=HELTEC_TRACKER_V1.1\\r\\n");\n'
    '        Serial.printf("# firmware=%s\\r\\n", JARNSEN_MESHTASTIC_VERSION);\n'
    '        Serial.printf("# build=%s\\r\\n", JARNSEN_BUILD_SHA);\n'
    '        Serial.printf("# build_time=%s %s\\r\\n", __DATE__, __TIME__);\n'
    '        Serial.printf("# role=%s\\r\\n", trackerDiagRoleText());\n'
    '        Serial.printf("# feature=%s\\r\\n", JARNSEN_DIAG_FEATURE_VERSION);\n'
    '        Serial.printf("# log_format=%u\\r\\n", (unsigned)JARNSEN_DIAG_LOG_FORMAT);\n'
    '        Serial.printf("# export=%s\\r\\n", exportTime);\n'
    '        Serial.printf("# bytes=%u\\r\\n", (unsigned)exportTotalBytes);\n'
)
if metadata_begin not in diag:
    if legacy_begin in diag:
        diag = diag.replace(legacy_begin, metadata_begin, 1)
        print("Tracker diagnostic export metadata header: applied from legacy marker")
    elif shared_begin_minimal in diag:
        diag = diag.replace(shared_begin_minimal, metadata_begin, 1)
        print("Tracker diagnostic export metadata header: applied from shared marker")
    else:
        raise SystemExit("Tracker diagnostic export metadata header: begin anchor not found")
else:
    print("Tracker diagnostic export metadata header: already applied")

diag = diag.replace('===TRACKER_LOG_END===', '===JARNSEN_DIAG_LOG_END===')

for needle in [
    'JARNSEN_BUILD_SHA',
    'JARNSEN_MESHTASTIC_VERSION',
    '# device=HELTEC_TRACKER_V1.1',
    '# build=%s',
    '# build_time=%s %s',
    '# role=%s',
    '# feature=%s',
    '# log_format=%u',
    '# export=%s',
    '===JARNSEN_DIAG_LOG_BEGIN===',
    '===JARNSEN_DIAG_LOG_END===',
]:
    if needle not in diag:
        raise SystemExit(f"Tracker diagnostic metadata verification failed: {needle}")

for needle in ['firmware=%s build=%s', 'JARNSEN_BUILD_SHA', 'JARNSEN_DIAG_LOG_FORMAT']:
    if needle not in common:
        raise SystemExit(f"Tracker BOOT metadata verification failed: {needle}")

DIAG_PATH.write_text(diag)
COMMON_PATH.write_text(common)
print(f"Tracker diagnostic metadata ready: Meshtastic {meshtastic_version}, build SHA stamped by workflow")
