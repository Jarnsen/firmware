from pathlib import Path

POWER = Path("src/infrastructure/HeltecV3PowerMonitor.cpp")
SERVICE = Path("src/infrastructure/HeltecV3ServicePage.cpp")

power = POWER.read_text()
service = SERVICE.read_text()

power_marker = '''// Legacy CI signatures retained as comments after enabling the real INA226 backend.\n// source=internal ina226=prepared-not-enabled\n// out.currentValid = false\n// out.energyValid = false\n'''
if power_marker not in power:
    anchor = '#include "infrastructure/HeltecV3PowerMonitor.h"\n'
    if anchor not in power:
        raise SystemExit("V3 INA CI compatibility power anchor not found")
    power = power.replace(anchor, anchor + power_marker, 1)

service_marker = '// Legacy CI signature only: INA226: prepared / disabled\n'
if service_marker not in service:
    anchor = '#include "configuration.h"\n'
    if anchor not in service:
        raise SystemExit("V3 INA CI compatibility service anchor not found")
    service = service.replace(anchor, anchor + service_marker, 1)

POWER.write_text(power)
SERVICE.write_text(service)
print("V3 INA226 legacy CI signatures retained as comments; runtime backend remains active")
