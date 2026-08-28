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
    "static void clearJarnsenDiagLog()", "trackerDiagClear();", "heltecV3DiagClear();",
    'memcmp(data, "CLEARLOG", 8)', '"CLEARED", 7',
):
    if marker not in source:
        raise SystemExit(f"missing clear-log marker: {marker}")
TARGET.write_text(source, encoding="utf-8")
print("Jarnsen BLE CLEARLOG command enabled via existing diagnostic clear implementation")

for script, label in (
    ("tools/patch_jarnsen_bt_serial_log.py", "Bluetooth serial-log"),
    ("tools/patch_jarnsen_diag_live_snapshot.py", "diagnostic live-snapshot"),
    ("tools/patch_jarnsen_v3_service_stack.py", "V3 service-stack"),
    ("tools/patch_jarnsen_v3_remote_wlan.py", "V3 remote-WLAN handover"),
    ("tools/patch_jarnsen_v3_service_portal.py", "V3 captive service-portal"),
    ("tools/patch_jarnsen_v3_phone_internet.py", "V3 phone-Internet"),
    ("tools/patch_jarnsen_v3_map_wifi_gps.py", "V3 map/WiFi-GPS"),
    ("tools/patch_jarnsen_v3_live_portal.py", "V3 live-portal"),
    ("tools/patch_jarnsen_v3_factory_defaults.py", "V3 fresh/factory-default"),
    ("tools/patch_jarnsen_mesh_sync_v2120.py", "V3 v2.1.20 mesh-sync"),
):
    path = Path(script)
    if not path.exists():
        raise SystemExit(f"{label} patcher is missing")
    if script.endswith("patch_jarnsen_mesh_sync_v2120.py"):
        # An earlier V3 patch currently owns one of StreamAPI's receive loops.
        # Wire whichever original loop remains before the mesh-sync patch runs;
        # its own hook then sees zero remaining anchors and only adds the header.
        stream_path = Path("src/mesh/StreamAPI.cpp")
        stream_text = stream_path.read_text(encoding="utf-8")
        stream_anchor = '''        uint8_t c = (uint8_t)cInt;

        // Use the read pointer for a little state machine'''
        stream_hook = '''        uint8_t c = (uint8_t)cInt;
#if defined(_VARIANT_HELTEC_V3)
        if (heltecV3DiagHandleToolSerialByte(c))
            continue;
#endif

        // Use the read pointer for a little state machine'''
        if stream_anchor in stream_text:
            stream_text = stream_text.replace(stream_anchor, stream_hook)
            stream_path.write_text(stream_text, encoding="utf-8")
    runpy.run_path(str(path), run_name="__main__")

# Access/full-lock/RF is deliberately applied after mesh-sync so it extends the
# existing JARNSEN_TOOL_HELLO delta-log parser instead of replacing it.
access_patch = Path("tools/patch_jarnsen_access_lock.py")
if not access_patch.exists():
    raise SystemExit("V3 Jarnsen access/full-lock patcher is missing")
# GitHub PR builds are checked out as a detached HEAD.  Make the shared patcher
# infer the target from the source tree when git cannot expose the branch name.
access_source = access_patch.read_text(encoding="utf-8")
detached_anchor = '''BRANCH = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True).strip()
TRACKER = "tracker-v11" in BRANCH
V3 = "v3-repeater" in BRANCH
if not (TRACKER or V3):
    raise SystemExit(f"unsupported Jarnsen access branch: {BRANCH}")
'''
detached_fix = '''BRANCH = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True).strip()
TRACKER = "tracker-v11" in BRANCH
V3 = "v3-repeater" in BRANCH
if BRANCH == "HEAD":
    TRACKER = (ROOT / "src/vehicle/TrackerCommonPolicy.cpp").exists()
    V3 = (ROOT / "src/infrastructure/HeltecV3RepeaterPolicy.cpp").exists()
if TRACKER == V3:
    raise SystemExit(f"unsupported/ambiguous Jarnsen access target: {BRANCH}")
'''
if detached_anchor in access_source:
    access_patch.write_text(access_source.replace(detached_anchor, detached_fix, 1), encoding="utf-8")
runpy.run_path(str(access_patch), run_name="__main__")

# Preserve the established V3 mesh-health snapshot in every USB diagnostic
# export. The delta protocol limits the historical file bytes; the fresh mesh
# snapshot remains a small current-state appendix and is relied on by the V3
# diagnostics/CI contract.
diag_path = Path("src/infrastructure/HeltecV3DiagnosticLog.cpp")
diag_text = diag_path.read_text(encoding="utf-8")
if "heltecV3MeshMonitorPrintSnapshot(Serial);" not in diag_text:
    footer_anchor = '''    case 4: {
        const int footerLength = snprintf((char *)usbTransferBuffer, USB_FILE_BUFFER_BYTES,
'''
    footer_new = '''    case 4: {
        heltecV3MeshMonitorPrintSnapshot(Serial);
        const int footerLength = snprintf((char *)usbTransferBuffer, USB_FILE_BUFFER_BYTES,
'''
    if diag_text.count(footer_anchor) != 1:
        raise SystemExit("V3 mesh snapshot footer anchor missing")
    diag_text = diag_text.replace(footer_anchor, footer_new, 1)
    diag_path.write_text(diag_text, encoding="utf-8")