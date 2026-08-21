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
