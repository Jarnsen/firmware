"""Expose the existing diagnostic-log clear function through Jarnsen BLE control.

This deliberately calls trackerDiagClear()/heltecV3DiagClear() instead of
implementing a second filesystem deletion path.
The firmware package also fetches the current verified shared Node Service Tool.
"""

from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile

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

tracker_fresh_defaults_patch = Path("tools/patch_jarnsen_tracker_fresh_defaults.py")
if not tracker_fresh_defaults_patch.exists():
    raise SystemExit("Tracker fresh-default/USB-export patcher is missing")
runpy.run_path(str(tracker_fresh_defaults_patch), run_name="__main__")

tracker_service_upgrade_patch = Path("tools/patch_jarnsen_tracker_service_upgrade.py")
if not tracker_service_upgrade_patch.exists():
    raise SystemExit("Tracker service-upgrade patcher is missing")
runpy.run_path(str(tracker_service_upgrade_patch), run_name="__main__")

tracker_phone_internet_patch = Path("tools/patch_jarnsen_tracker_phone_internet.py")
if not tracker_phone_internet_patch.exists():
    raise SystemExit("Tracker phone-Internet patcher is missing")
runpy.run_path(str(tracker_phone_internet_patch), run_name="__main__")

tracker_service_experience_patch = Path("tools/patch_jarnsen_tracker_service_experience.py")
if not tracker_service_experience_patch.exists():
    raise SystemExit("Tracker service-experience patcher is missing")
runpy.run_path(str(tracker_service_experience_patch), run_name="__main__")

# One older branch-local patch already owns one of StreamAPI's two receive
# loops. Wire the remaining loop here before the mesh-sync patch runs. This
# makes the hook deterministic whether one or both original anchors remain.
stream_path = Path("src/mesh/StreamAPI.cpp")
stream_text = stream_path.read_text(encoding="utf-8")
stream_anchor = '''        uint8_t c = (uint8_t)cInt;

        // Use the read pointer for a little state machine'''
stream_hook = '''        uint8_t c = (uint8_t)cInt;
#if defined(HELTEC_TRACKER_V1_1)
        if (trackerDiagHandleToolSerialByte(c))
            continue;
#endif

        // Use the read pointer for a little state machine'''
if stream_anchor in stream_text:
    stream_text = stream_text.replace(stream_anchor, stream_hook)
    stream_path.write_text(stream_text, encoding="utf-8")

mesh_sync_patch = Path("tools/patch_jarnsen_mesh_sync_v2120.py")
if not mesh_sync_patch.exists():
    raise SystemExit("Tracker v2.1.20 mesh-sync patcher is missing")
runpy.run_path(str(mesh_sync_patch), run_name="__main__")

# Access/full-lock/RF is deliberately applied after mesh-sync so it extends the
# existing JARNSEN_TOOL_HELLO delta-log parser instead of replacing it.
access_patch = Path("tools/patch_jarnsen_access_lock.py")
if not access_patch.exists():
    raise SystemExit("Tracker Jarnsen access/full-lock patcher is missing")
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

# GitHub-hosted runners have Node.js available. Syntax-check the browser script
after_all = True
node = shutil.which("node")
if node:
    portal_path = Path("src/mesh/http/JarnsenTrackerServicePortalPage.h")
    portal_text = portal_path.read_text(encoding="utf-8")
    start = portal_text.find("<script>")
    end = portal_text.rfind("</script>")
    if start < 0 or end <= start:
        raise SystemExit("Tracker portal script block not found for syntax validation")
    script = portal_text[start + len("<script>"):end]
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False) as handle:
        handle.write(script)
        js_path = Path(handle.name)
    try:
        subprocess.run([node, "--check", str(js_path)], check=True)
    finally:
        js_path.unlink(missing_ok=True)
    print("Tracker service portal JavaScript syntax verified with node --check")