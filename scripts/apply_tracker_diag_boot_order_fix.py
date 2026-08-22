from pathlib import Path

PATH = Path("src/vehicle/TrackerCommonPolicy.cpp")
text = PATH.read_text()

old = '''    trackerServiceSettingsInit();\n    trackerDiagInit();\n    trackerDiagLog("BOOT", "role=%s wake=%s park=%umin effective=%us",\n                   config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER ? "TAK_TRACKER" : "TAK",\n                   trackerBootWakeReason(), (unsigned)trackerParkIntervalMinutes(),\n                   (unsigned)trackerEffectiveParkIntervalSecs());\n    setupTrackerEnhancements();\n'''
new = '''    trackerServiceSettingsInit();\n    setupTrackerEnhancements();\n    trackerDiagInit();\n    trackerDiagLog("BOOT", "role=%s wake=%s park=%umin effective=%us",\n                   config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER ? "TAK_TRACKER" : "TAK",\n                   trackerBootWakeReason(), (unsigned)trackerParkIntervalMinutes(),\n                   (unsigned)trackerEffectiveParkIntervalSecs());\n'''

if new in text:
    print("Tracker diagnostic boot wake ordering: already applied")
elif old in text:
    text = text.replace(old, new, 1)
    print("Tracker diagnostic boot wake ordering: applied")
else:
    raise SystemExit("Tracker diagnostic boot wake ordering: anchor not found")

PATH.write_text(text)
