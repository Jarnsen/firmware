from pathlib import Path

PATH = Path("src/vehicle/TrackerCommonPolicy.cpp")
text = PATH.read_text()

old = '''        if (!motionLightSleepWakeArmed)\n            return 0;\n\n        const gpio_num_t pin = (gpio_num_t)VEHICLE_MOTION_WAKE_PIN;\n'''
new = '''        if (!motionLightSleepWakeArmed) {\n            if (!trackerUsesDeepSleep() && parked)\n                trackerPowerMonitorCompleteLightSleep();\n            return 0;\n        }\n\n        const gpio_num_t pin = (gpio_num_t)VEHICLE_MOTION_WAKE_PIN;\n'''

if new in text:
    print("Tracker light-sleep profiler end guard: already applied")
elif old in text:
    text = text.replace(old, new, 1)
    print("Tracker light-sleep profiler end guard: applied")
else:
    raise SystemExit("Tracker light-sleep profiler end guard: anchor not found")

PATH.write_text(text)
