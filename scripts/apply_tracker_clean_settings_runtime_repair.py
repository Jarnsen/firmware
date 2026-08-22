from pathlib import Path

PATH = Path("src/vehicle/TrackerCommonPolicy.cpp")
text = PATH.read_text()

# The menu/timing patch intentionally replaces the runtime uses of these old
# constants/functions. Repair the declaration/preprocessor text that a broad
# textual pass may also have touched before the C++ compiler sees it.
bad_macro = '''#ifndef ((uint32_t)trackerParkGpsSearchSecs() * 1000UL)\n#define ((uint32_t)trackerParkGpsSearchSecs() * 1000UL) (30UL * 1000UL)\n#endif\n'''
good_macro = '''#ifndef TRACKER_COMMON_PARK_GPS_WAIT_MS\n#define TRACKER_COMMON_PARK_GPS_WAIT_MS (30UL * 1000UL)\n#endif\n'''
if bad_macro in text:
    text = text.replace(bad_macro, good_macro, 1)
    print("Tracker timing macro declaration repaired")

bad_decl = 'uint32_t ((uint32_t)trackerParkGpsSearchSecs() * 1000UL);\n'
good_decl = 'uint32_t vehicleAdaptiveTimerGpsWaitMs();\n'
if bad_decl in text:
    text = text.replace(bad_decl, good_decl, 1)
    print("Tracker adaptive GPS declaration repaired")

# Runtime deep-sleep call must remain the configured fixed search time.
old_call = 'if ((uint32_t)(now - bootActivityMs) < vehicleAdaptiveTimerGpsWaitMs())\n'
new_call = 'if ((uint32_t)(now - bootActivityMs) < (uint32_t)trackerParkGpsSearchSecs() * 1000UL)\n'
if old_call in text:
    text = text.replace(old_call, new_call, 1)
    print("Tracker deep-sleep GPS wait made configurable")

for forbidden in [
    '#ifndef ((uint32_t)',
    '#define ((uint32_t)',
    'uint32_t ((uint32_t)trackerParkGpsSearchSecs()',
]:
    if forbidden in text:
        raise SystemExit(f"Tracker timing repair failed: {forbidden}")

for required in [
    'config.position.gps_update_interval = trackerMovingGnssSecs();',
    '(uint32_t)trackerBleIdleTimeoutSecs() * 1000UL',
    '(uint32_t)trackerBleHardTimeoutSecs() * 1000UL',
    'trackerParkGpsSearchSecs()',
]:
    if required not in text:
        raise SystemExit(f"Tracker timing repair verification failed: {required}")

PATH.write_text(text)
