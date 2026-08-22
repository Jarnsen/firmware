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
runpy.run_path("scripts/apply_tracker_clean_settings_menu_fix.py", run_name="__main__")
runpy.run_path("scripts/apply_tracker_artifact_extras.py", run_name="__main__")
