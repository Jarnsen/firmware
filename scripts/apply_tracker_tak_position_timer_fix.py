from pathlib import Path

PATH = Path("src/modules/PositionModule.cpp")
text = PATH.read_text()

old = '''    if (config.device.role != meshtastic_Config_DeviceConfig_Role_TRACKER &&\n        config.device.role != meshtastic_Config_DeviceConfig_Role_TAK_TRACKER) {\n        setIntervalFromNow(setStartDelay());\n    }\n'''
new = '''    if (config.device.role != meshtastic_Config_DeviceConfig_Role_TRACKER &&\n        config.device.role != meshtastic_Config_DeviceConfig_Role_TAK_TRACKER &&\n        config.device.role != meshtastic_Config_DeviceConfig_Role_TAK) {\n        setIntervalFromNow(setStartDelay());\n    }\n'''

if new in text:
    print("TAK generic position timer suppression: already applied")
elif old in text:
    text = text.replace(old, new, 1)
    print("TAK generic position timer suppression: applied")
else:
    raise SystemExit("TAK generic position timer suppression: anchor not found")

if 'config.device.role != meshtastic_Config_DeviceConfig_Role_TAK)' not in text:
    raise SystemExit("TAK generic position timer suppression verification failed")

PATH.write_text(text)
