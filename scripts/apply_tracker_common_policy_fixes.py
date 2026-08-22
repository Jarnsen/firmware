from pathlib import Path
import runpy

NIMBLE_CPP_PATH = Path("src/nimble/NimbleBluetooth.cpp")

nimble = NIMBLE_CPP_PATH.read_text()

old = """        // Count only non-empty payload reads. Empty client polling reads\n        // must not make a background connection look actively used.\n        if (numBytes != 0) {\n            meaningfulBleTrafficCount.fetch_add(1);\n            bluetoothPhoneAPI->setIntervalFromNow(0);\n"""
new = """        // Count only non-empty payload reads. Empty client polling reads\n        // must not make a background connection look actively used.\n        if (numBytes != 0) {\n            meaningfulBleTrafficCount.fetch_add(1);\n            if (meshtasticTrackerBleActivity)\n                meshtasticTrackerBleActivity();\n            bluetoothPhoneAPI->setIntervalFromNow(0);\n"""

if new in nimble:
    print("Tracker common BLE read activity hook: already applied")
elif old in nimble:
    nimble = nimble.replace(old, new, 1)
    print("Tracker common BLE read activity hook: applied")
else:
    raise SystemExit("Tracker common BLE read activity hook: anchor not found; run apply_tracker_ble_burst_policy.py first")

NIMBLE_CPP_PATH.write_text(nimble)

# Keep GPIO0 service ownership, deep-sleep button wake and motion ISR debounce
# in the same build-finalization stage as the shared Tracker policy.
runpy.run_path("scripts/apply_tracker_gpio0_service_fix.py", run_name="__main__")

# Fix the Tracker service display-window timestamp underflow and keep GPIO0
# short-press page cycling tied to the actual release time.
runpy.run_path("scripts/apply_tracker_display_service_fix.py", run_name="__main__")

# Native ESP32-S3 USB CDC must veto light sleep while the serial console is
# actually connected, and the GPIO0 service must be allowed to replace the
# boot-only frame with the native Meshtastic/Tracker frame set.
runpy.run_path("scripts/apply_tracker_usb_serial_ui_fix.py", run_name="__main__")

# Add the dedicated Tracker Service page/sub-menu, make BLE service windows
# resumeable without unsafe NimBLE deinit/re-init, and park GNSS independently
# from LoRa so TAK keeps listening while GNSS sleeps between park heartbeats.
runpy.run_path("scripts/apply_tracker_service_menu_power_fix.py", run_name="__main__")

# A short press must be decided on release. Otherwise the press-edge page
# change happens before the 1.2s long-press threshold can ever open/edit the
# Tracker Service menu.
runpy.run_path("scripts/apply_tracker_service_button_gesture_fix.py", run_name="__main__")

# Earlier service hierarchy, retained as a stable intermediate anchor for the
# final original Meshtastic list-menu conversion below.
runpy.run_path("scripts/apply_tracker_service_original_back_menu_fix.py", run_name="__main__")

# TAK uses the shared Tracker policy for movement/final/parked positions, so do
# not also run PositionModule's generic periodic sender in parallel.
runpy.run_path("scripts/apply_tracker_tak_position_timer_fix.py", run_name="__main__")

# Final UX/power/diagnostic layer: use Meshtastic's stock white selection picker,
# long-press only from the Service page, persistent event logging + USB export,
# idempotent BLE suspend, and externally-powered TAK_TRACKER timed wake support.
runpy.run_path("scripts/apply_tracker_service_original_ui_diag_fix.py", run_name="__main__")
