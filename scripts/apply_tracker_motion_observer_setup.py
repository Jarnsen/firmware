from pathlib import Path

p = Path('src/vehicle/HeltecTrackerV11VehicleMotionTracker.cpp')
s = p.read_text()
old = '''void setupHeltecTrackerV11VehicleMotionTracker()\n{\n    if (vehicleTrackerModeEnabled() && vehicleMotionThread == nullptr) {\n        LOG_INFO("Tracker V1.1 TAK_TRACKER vehicle motion profile enabled; Bluetooth only via GPIO0 service");\n        vehicleMotionThread = new HeltecTrackerV11VehicleMotionThread();\n    }\n}\n'''
new = '''void setupHeltecTrackerV11VehicleMotionTracker()\n{\n    if (!vehicleTrackerModeEnabled())\n        return;\n\n    if (!motionLightSleepObserversInstalled) {\n        trackerMotionLightSleepBeginObserver.observe(&notifyLightSleep);\n        trackerMotionLightSleepEndObserver.observe(&notifyLightSleepEnd);\n        motionLightSleepObserversInstalled = true;\n    }\n\n    if (vehicleMotionThread == nullptr)\n        vehicleMotionThread = new HeltecTrackerV11VehicleMotionThread();\n}\n'''
if new in s:
    print('motion observer setup already normalized')
elif old in s:
    p.write_text(s.replace(old, new, 1))
    print('motion observer setup normalized')
else:
    raise SystemExit('motion observer setup anchor not found')
