"""Expose the existing diagnostic-log clear function through Jarnsen BLE control.

This deliberately calls trackerDiagClear()/heltecV3DiagClear() instead of
implementing a second filesystem deletion path.
The firmware package also fetches the current verified shared Node Service Tool.
"""

from pathlib import Path
import runpy

TARGET = Path("src/nimble/NimbleBluetooth.cpp")

source = TARGET.read_text(encoding="utf-8")

helper_anchor = '''static void cancelJarnsenBleExport()
{
#if defined(HELTEC_TRACKER_V1_1)
    trackerDiagCancelBleExport();
#else
    heltecV3DiagCancelBleExport();
#endif
}
'''
helper = helper_anchor + '''
static void clearJarnsenDiagLog()
{
#if defined(HELTEC_TRACKER_V1_1)
    trackerDiagClear();
#else
    heltecV3DiagClear();
#endif
}
'''
if "static void clearJarnsenDiagLog()" not in source:
    if source.count(helper_anchor) != 1:
        raise SystemExit("diagnostic export helper anchor not found exactly once")
    source = source.replace(helper_anchor, helper, 1)

callback_anchor = '''        } else if (length == 6 && memcmp(data, "CANCEL", 6) == 0) {
            cancelJarnsenBleExport();
            characteristic->setValue((const uint8_t *)"IDLE", 4);
        } else if (length == 4 && memcmp(data, "HOLD", 4) == 0) {
'''
callback_new = '''        } else if (length == 6 && memcmp(data, "CANCEL", 6) == 0) {
            cancelJarnsenBleExport();
            characteristic->setValue((const uint8_t *)"IDLE", 4);
        } else if (length == 8 && memcmp(data, "CLEARLOG", 8) == 0) {
            cancelJarnsenBleExport();
            clearJarnsenDiagLog();
            characteristic->setValue((const uint8_t *)"CLEARED", 7);
        } else if (length == 4 && memcmp(data, "HOLD", 4) == 0) {
'''
if 'memcmp(data, "CLEARLOG", 8)' not in source:
    if source.count(callback_anchor) != 1:
        raise SystemExit("Jarnsen diagnostic control callback anchor not found exactly once")
    source = source.replace(callback_anchor, callback_new, 1)

for marker in (
    "static void clearJarnsenDiagLog()",
    "trackerDiagClear();",
    "heltecV3DiagClear();",
    'memcmp(data, "CLEARLOG", 8)',
    '"CLEARED", 7',
):
    if marker not in source:
        raise SystemExit(f"missing clear-log marker: {marker}")

TARGET.write_text(source, encoding="utf-8")
print("Jarnsen BLE CLEARLOG command enabled via existing diagnostic clear implementation")

bt_patch = Path("tools/patch_jarnsen_bt_serial_log.py")
if not bt_patch.exists():
    raise SystemExit("Bluetooth serial-log patcher is missing")
runpy.run_path(str(bt_patch), run_name="__main__")

live_snapshot_patch = Path("tools/patch_jarnsen_diag_live_snapshot.py")
if not live_snapshot_patch.exists():
    raise SystemExit("diagnostic live-snapshot patcher is missing")
runpy.run_path(str(live_snapshot_patch), run_name="__main__")

v3_service_stack_patch = Path("tools/patch_jarnsen_v3_service_stack.py")
if not v3_service_stack_patch.exists():
    raise SystemExit("V3 service-stack patcher is missing")
runpy.run_path(str(v3_service_stack_patch), run_name="__main__")

v3_remote_wlan_patch = Path("tools/patch_jarnsen_v3_remote_wlan.py")
if not v3_remote_wlan_patch.exists():
    raise SystemExit("V3 remote-WLAN handover patcher is missing")
runpy.run_path(str(v3_remote_wlan_patch), run_name="__main__")

v3_service_portal_patch = Path("tools/patch_jarnsen_v3_service_portal.py")
if not v3_service_portal_patch.exists():
    raise SystemExit("V3 captive service-portal patcher is missing")
runpy.run_path(str(v3_service_portal_patch), run_name="__main__")

v3_phone_internet_patch = Path("tools/patch_jarnsen_v3_phone_internet.py")
if not v3_phone_internet_patch.exists():
    raise SystemExit("V3 phone-Internet patcher is missing")
runpy.run_path(str(v3_phone_internet_patch), run_name="__main__")
