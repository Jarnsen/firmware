"""Expose the Jarnsen Tracker firmware version on normal display pages.

The Tracker already exposes detailed firmware/build information in System Info.
This patch additionally puts the short semantic version into normal page headers
so the installed version is visible without entering the service menu.
"""
from pathlib import Path

TARGET = Path("src/vehicle/TrackerStatusModule.cpp")
source = TARGET.read_text(encoding="utf-8")

service_anchor = '        graphics::drawCommonHeader(display, x, y, "Service");\n'
service_replacement = '''        char pageTitle[40] = {};
        snprintf(pageTitle, sizeof(pageTitle), "Service %s", JARNSEN_FIRMWARE_SEMVER);
        graphics::drawCommonHeader(display, x, y, pageTitle);
'''

setup_anchor = '        graphics::drawCommonHeader(display, x, y, "Tracker Setup");\n'
setup_replacement = '''        char pageTitle[40] = {};
        snprintf(pageTitle, sizeof(pageTitle), "Tracker %s", JARNSEN_FIRMWARE_SEMVER);
        graphics::drawCommonHeader(display, x, y, pageTitle);
'''

if '"Service %s", JARNSEN_FIRMWARE_SEMVER' not in source:
    if source.count(service_anchor) != 1:
        raise SystemExit(f"service header anchor expected once, got {source.count(service_anchor)}")
    source = source.replace(service_anchor, service_replacement, 1)

if '"Tracker %s", JARNSEN_FIRMWARE_SEMVER' not in source:
    if source.count(setup_anchor) != 1:
        raise SystemExit(f"tracker setup header anchor expected once, got {source.count(setup_anchor)}")
    source = source.replace(setup_anchor, setup_replacement, 1)

for marker in (
    '"Service %s", JARNSEN_FIRMWARE_SEMVER',
    '"Tracker %s", JARNSEN_FIRMWARE_SEMVER',
    'snprintf(version, sizeof(version), "FW: %s", JARNSEN_FIRMWARE_VERSION);',
    'snprintf(build, sizeof(build), "Build: %.8s", JARNSEN_BUILD_SHA);',
):
    if marker not in source:
        raise SystemExit(f"missing version display marker: {marker}")

TARGET.write_text(source, encoding="utf-8")
print("Tracker semantic version exposed on normal Service and Tracker Setup pages")
