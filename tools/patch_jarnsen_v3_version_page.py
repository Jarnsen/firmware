#!/usr/bin/env python3
from pathlib import Path

PATH = Path("src/infrastructure/HeltecV3ServicePage.cpp")
text = PATH.read_text(encoding="utf-8")

include_anchor = '#include "infrastructure/HeltecV3DiagnosticLog.h"\n'
include_line = '#include "infrastructure/HeltecV3BuildInfo.h"\n'
if include_line not in text:
    if text.count(include_anchor) != 1:
        raise SystemExit(f"V3 version include anchor expected once, got {text.count(include_anchor)}")
    text = text.replace(include_anchor, include_anchor + include_line, 1)

service_old = '    graphics::drawCommonHeader(display, x, y, "Service");\n'
service_new = (
    '    char title[32] = {};\n'
    '    snprintf(title, sizeof(title), "Service %s", JARNSEN_V3_FIRMWARE_SEMVER);\n'
    '    graphics::drawCommonHeader(display, x, y, title);\n'
)
if service_new not in text:
    if text.count(service_old) != 1:
        raise SystemExit(f"V3 Service header anchor expected once, got {text.count(service_old)}")
    text = text.replace(service_old, service_new, 1)

setup_old = '    graphics::drawCommonHeader(display, x, y, "Repeater Setup");\n'
setup_new = (
    '    char title[32] = {};\n'
    '    snprintf(title, sizeof(title), "Repeater %s", JARNSEN_V3_FIRMWARE_SEMVER);\n'
    '    graphics::drawCommonHeader(display, x, y, title);\n'
)
if setup_new not in text:
    if text.count(setup_old) != 1:
        raise SystemExit(f"V3 Repeater header anchor expected once, got {text.count(setup_old)}")
    text = text.replace(setup_old, setup_new, 1)

for needle in (
    '"Service %s", JARNSEN_V3_FIRMWARE_SEMVER',
    '"Repeater %s", JARNSEN_V3_FIRMWARE_SEMVER',
):
    if needle not in text:
        raise SystemExit(f"V3 version page validation failed: {needle}")

PATH.write_text(text, encoding="utf-8")
print("V3 firmware version exposed on normal display headers")
