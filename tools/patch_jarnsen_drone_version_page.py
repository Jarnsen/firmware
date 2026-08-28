#!/usr/bin/env python3
from pathlib import Path

PATH = Path("src/drone/DroneStatusPages.cpp")
text = PATH.read_text(encoding="utf-8")

old_include = '#include "vehicle/JarnsenBuildInfo.h"\n'
new_include = '#include "drone/DroneBuildInfo.h"\n'
if new_include not in text:
    if text.count(old_include) != 1:
        raise SystemExit(f"Drone build-info include anchor expected once, got {text.count(old_include)}")
    text = text.replace(old_include, new_include, 1)

replacements = {
    '        commonBegin(display, x, y, "Drone Position");\n': (
        '        char title[32] = {};\n'
        '        snprintf(title, sizeof(title), "Position %s", JARNSEN_DRONE_FIRMWARE_SEMVER);\n'
        '        commonBegin(display, x, y, title);\n'
    ),
    '        commonBegin(display, x, y, "Mesh Health");\n': (
        '        char title[32] = {};\n'
        '        snprintf(title, sizeof(title), "Mesh %s", JARNSEN_DRONE_FIRMWARE_SEMVER);\n'
        '        commonBegin(display, x, y, title);\n'
    ),
    '        commonBegin(display, x, y, "Drone System");\n': (
        '        char title[32] = {};\n'
        '        snprintf(title, sizeof(title), "Drone %s", JARNSEN_DRONE_FIRMWARE_SEMVER);\n'
        '        commonBegin(display, x, y, title);\n'
    ),
    '                 JARNSEN_BUILD_SHA);\n': '                 JARNSEN_DRONE_BUILD_SHA);\n',
}

for old, new in replacements.items():
    if new in text:
        continue
    if text.count(old) != 1:
        raise SystemExit(f"Drone version page anchor expected once, got {text.count(old)}: {old.strip()}")
    text = text.replace(old, new, 1)

for needle in (
    '"Position %s", JARNSEN_DRONE_FIRMWARE_SEMVER',
    '"Mesh %s", JARNSEN_DRONE_FIRMWARE_SEMVER',
    '"Drone %s", JARNSEN_DRONE_FIRMWARE_SEMVER',
    'JARNSEN_DRONE_BUILD_SHA',
):
    if needle not in text:
        raise SystemExit(f"Drone version page validation failed: {needle}")

PATH.write_text(text, encoding="utf-8")
print("Drone firmware version exposed on normal display headers")
