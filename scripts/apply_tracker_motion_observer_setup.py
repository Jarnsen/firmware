from pathlib import Path
import runpy

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

# Tracker and V3 intentionally use one diagnostic-log wire protocol and the
# same PC downloader. The downloader still understands the old marker pairs so
# previously flashed builds remain retrievable.
diag = Path('src/vehicle/TrackerDiagnosticLog.cpp')
d = diag.read_text()
d = d.replace('===TRACKER_LOG_BEGIN===', '===JARNSEN_DIAG_LOG_BEGIN===')
d = d.replace('===TRACKER_LOG_END===', '===JARNSEN_DIAG_LOG_END===')
old_header = '        Serial.printf("# bytes=%u\\r\\n", (unsigned)exportTotalBytes);\n'
new_header = '        Serial.print("# device=HELTEC_TRACKER_V1_1\\r\\n");\n        Serial.printf("# bytes=%u\\r\\n", (unsigned)exportTotalBytes);\n'
if new_header not in d:
    if old_header not in d:
        raise SystemExit('Tracker diagnostic protocol header anchor not found')
    d = d.replace(old_header, new_header, 1)
for needle in ['===JARNSEN_DIAG_LOG_BEGIN===', '===JARNSEN_DIAG_LOG_END===', '# device=HELTEC_TRACKER_V1_1']:
    if needle not in d:
        raise SystemExit(f'Tracker shared diagnostic protocol missing: {needle}')
diag.write_text(d)
print('Tracker shared diagnostic log protocol ready')

# Create artifact extras early; the later Collect firmware step only adds the
# binaries and does not delete this directory.
runpy.run_path('scripts/apply_tracker_artifact_extras.py', run_name='__main__')
