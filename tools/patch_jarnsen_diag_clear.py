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

# The Tracker V1.1 has a 160x80 TFT. The stock shared PIN screen uses the
# 24-point FONT_LARGE, which leaves the six-digit passkey unnecessarily small.
# Keep the common screen for every other target, but use a compact 7-segment
# renderer on the Tracker so the digits consume most of the available height.
pairing_pin_anchor = '''                    display->setFont(FONT_LARGE);
                    char pin[8];
                    snprintf(pin, sizeof(pin), "%.3s %.3s", btPIN, btPIN + 3);
                    y_offset = display->height() == 64 ? y_offset + FONT_HEIGHT_SMALL - 5 : y_offset + FONT_HEIGHT_SMALL + 5;
                    display->drawString(x_offset + x, y_offset + y, pin);

                    display->setFont(FONT_SMALL);
                    char deviceName[64];
                    snprintf(deviceName, sizeof(deviceName), "Name: %s", getDeviceName());
                    y_offset = display->height() == 64 ? y_offset + FONT_HEIGHT_LARGE - 6 : y_offset + FONT_HEIGHT_LARGE + 5;
                    display->drawString(x_offset + x, y_offset + y, deviceName);
'''
pairing_pin_new = '''#if defined(HELTEC_TRACKER_V1_1)
                    constexpr int16_t pinDigitWidth = 21;
                    constexpr int16_t pinDigitHeight = 42;
                    constexpr int16_t pinSegmentThickness = 4;
                    constexpr int16_t pinDigitGap = 2;
                    constexpr int16_t pinGroupGap = 6;
                    constexpr int16_t pinTotalWidth = 6 * pinDigitWidth + 5 * pinDigitGap + pinGroupGap;
                    const int16_t pinTop = 28;
                    int16_t pinLeft = (display->width() - pinTotalWidth) / 2;

                    display->setTextAlignment(TEXT_ALIGN_CENTER);
                    display->setFont(FONT_SMALL);
                    display->drawString(display->width() / 2 + x, 2 + y, "Bluetooth PIN");

                    auto drawPinDigit = [display, x, y](char value, int16_t left, int16_t top) {
                        static const uint8_t masks[10] = {0x3f, 0x06, 0x5b, 0x4f, 0x66, 0x6d, 0x7d, 0x07, 0x7f, 0x6f};
                        if (value < '0' || value > '9')
                            return;
                        const uint8_t mask = masks[value - '0'];
                        constexpr int16_t w = pinDigitWidth;
                        constexpr int16_t h = pinDigitHeight;
                        constexpr int16_t t = pinSegmentThickness;
                        const int16_t half = h / 2;
                        auto segment = [display, x, y](int16_t sx, int16_t sy, int16_t sw, int16_t sh) {
                            display->fillRect(sx + x, sy + y, sw, sh);
                        };
                        if (mask & 0x01)
                            segment(left + t, top, w - 2 * t, t);
                        if (mask & 0x02)
                            segment(left + w - t, top + t, t, half - t);
                        if (mask & 0x04)
                            segment(left + w - t, top + half, t, half - t);
                        if (mask & 0x08)
                            segment(left + t, top + h - t, w - 2 * t, t);
                        if (mask & 0x10)
                            segment(left, top + half, t, half - t);
                        if (mask & 0x20)
                            segment(left, top + t, t, half - t);
                        if (mask & 0x40)
                            segment(left + t, top + half - t / 2, w - 2 * t, t);
                    };

                    for (uint8_t digit = 0; digit < 6; ++digit) {
                        drawPinDigit(btPIN[digit], pinLeft, pinTop);
                        pinLeft += pinDigitWidth;
                        if (digit != 5)
                            pinLeft += pinDigitGap;
                        if (digit == 2)
                            pinLeft += pinGroupGap;
                    }
#else
                    display->setFont(FONT_LARGE);
                    char pin[8];
                    snprintf(pin, sizeof(pin), "%.3s %.3s", btPIN, btPIN + 3);
                    y_offset = display->height() == 64 ? y_offset + FONT_HEIGHT_SMALL - 5 : y_offset + FONT_HEIGHT_SMALL + 5;
                    display->drawString(x_offset + x, y_offset + y, pin);

                    display->setFont(FONT_SMALL);
                    char deviceName[64];
                    snprintf(deviceName, sizeof(deviceName), "Name: %s", getDeviceName());
                    y_offset = display->height() == 64 ? y_offset + FONT_HEIGHT_LARGE - 6 : y_offset + FONT_HEIGHT_LARGE + 5;
                    display->drawString(x_offset + x, y_offset + y, deviceName);
#endif
'''
if "constexpr int16_t pinDigitHeight = 42;" not in source:
    if source.count(pairing_pin_anchor) != 1:
        raise SystemExit("Tracker Bluetooth PIN display anchor not found exactly once")
    source = source.replace(pairing_pin_anchor, pairing_pin_new, 1)

for marker in (
    "static void clearJarnsenDiagLog()",
    "trackerDiagClear();",
    "heltecV3DiagClear();",
    'memcmp(data, "CLEARLOG", 8)',
    '"CLEARED", 7',
    "constexpr int16_t pinDigitHeight = 42;",
    'display->drawString(display->width() / 2 + x, 2 + y, "Bluetooth PIN");',
):
    if marker not in source:
        raise SystemExit(f"missing clear-log/PIN marker: {marker}")

TARGET.write_text(source, encoding="utf-8")
print("Jarnsen BLE CLEARLOG command and large Tracker pairing PIN enabled")

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

# TrackerDiagnosticLog.cpp currently carries NodeDB.h once globally and once
# inside the HELTEC_TRACKER_V1_1 block. The access patcher deliberately adds
# JarnsenAccessPolicy next to the Tracker-specific include, so remove only the
# redundant global include before the exact-one anchor check runs.
diag_path = Path("src/vehicle/TrackerDiagnosticLog.cpp")
diag_source = diag_path.read_text(encoding="utf-8")
node_db_include = '#include "NodeDB.h"\n'
node_db_count = diag_source.count(node_db_include)
if node_db_count == 2:
    diag_source = diag_source.replace(node_db_include, "", 1)
    diag_path.write_text(diag_source, encoding="utf-8")
elif node_db_count != 1:
    raise SystemExit(f"unexpected Tracker NodeDB include count: {node_db_count}")

runpy.run_path(str(access_patch), run_name="__main__")

# Apply the final native-serial sleep/session fix after mesh-sync and access
# patching so it sees the completed JARNSEN_TOOL_* parser and both StreamAPI
# receive hooks.
serial_session_patch = Path("tools/patch_jarnsen_tracker_serial_session.py")
if not serial_session_patch.exists():
    raise SystemExit("Tracker native-serial session patcher is missing")
runpy.run_path(str(serial_session_patch), run_name="__main__")

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
