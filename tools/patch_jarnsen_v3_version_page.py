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

# Expose the product semantic version in USB/BLE diagnostic headers too.  Keep
# the upstream/internal APP_VERSION and exact SHA as separate fields.
diag_path = Path("src/infrastructure/HeltecV3DiagnosticLog.cpp")
diag = diag_path.read_text(encoding="utf-8")
if "# jarnsen_version=%s" not in diag:
    format_anchor = '# firmware=%s\\r\\n# build=%s\\r\\n'
    format_count = diag.count(format_anchor)
    if format_count != 2:
        raise SystemExit(f"V3 diagnostic firmware-header anchor expected twice, got {format_count}")
    diag = diag.replace(
        format_anchor,
        '# firmware=%s\\r\\n# jarnsen_version=%s\\r\\n# build=%s\\r\\n',
    )

    boot_anchor = '"count=%u reset=%s crashCount=%u role=%s firmware=%s "\n                    "build=%s built=%s %s feature=%s logFormat=%u",'
    boot_new = '"count=%u reset=%s crashCount=%u role=%s firmware=%s jarnsen=%s "\n                    "build=%s built=%s %s feature=%s logFormat=%u",'
    if diag.count(boot_anchor) != 1:
        raise SystemExit(f"V3 BOOT version anchor expected once, got {diag.count(boot_anchor)}")
    diag = diag.replace(boot_anchor, boot_new, 1)

    args_anchor = 'xstr(APP_VERSION), JARNSEN_V3_BUILD_SHA'
    args_count = diag.count(args_anchor)
    if args_count != 3:
        raise SystemExit(f"V3 firmware args anchor expected three times, got {args_count}")
    diag = diag.replace(
        args_anchor,
        'xstr(APP_VERSION), JARNSEN_V3_FIRMWARE_SEMVER, JARNSEN_V3_BUILD_SHA',
    )

if diag.count("# jarnsen_version=%s") != 2:
    raise SystemExit("V3 diagnostic semantic header validation failed")
if diag.count("JARNSEN_V3_FIRMWARE_SEMVER, JARNSEN_V3_BUILD_SHA") != 3:
    raise SystemExit("V3 diagnostic semantic argument validation failed")
diag_path.write_text(diag, encoding="utf-8")

print("V3 firmware semantic version exposed on display and USB/BLE diagnostics")
