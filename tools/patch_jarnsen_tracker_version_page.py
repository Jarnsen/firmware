"""Expose the Jarnsen Tracker firmware version on normal display pages and diagnostics.

The user-facing version is the JARN-MESH semantic version (for example v1.9.1).
The internal Meshtastic APP_VERSION and exact build SHA remain available as
separate technical fields.
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

# Put the same semantic version into both USB and BLE diagnostic headers.  The
# BLE header splits '# ' and 'firmware=' across adjacent C++ string literals,
# therefore match the common firmware/build substring rather than requiring the
# '# ' prefix to be in the same literal.
diag_path = Path("src/vehicle/TrackerDiagnosticLog.cpp")
diag = diag_path.read_text(encoding="utf-8")
if "# jarnsen_version=%s" not in diag:
    format_anchor = 'firmware=%s\\r\\n# build=%s\\r\\n'
    format_count = diag.count(format_anchor)
    if format_count != 2:
        raise SystemExit(f"Tracker diagnostic firmware-header anchor expected twice, got {format_count}")
    diag = diag.replace(
        format_anchor,
        'firmware=%s\\r\\n# jarnsen_version=%s\\r\\n# build=%s\\r\\n',
    )
    args_anchor = 'xstr(APP_VERSION), JARNSEN_BUILD_SHA,'
    args_count = diag.count(args_anchor)
    if args_count != 2:
        raise SystemExit(f"Tracker diagnostic firmware-args anchor expected twice, got {args_count}")
    diag = diag.replace(
        args_anchor,
        'xstr(APP_VERSION), JARNSEN_FIRMWARE_SEMVER, JARNSEN_BUILD_SHA,',
    )

after_format = diag.count("# jarnsen_version=%s")
after_args = diag.count("JARNSEN_FIRMWARE_SEMVER, JARNSEN_BUILD_SHA")
if after_format != 2 or after_args != 2:
    raise SystemExit(f"Tracker diagnostic semantic version validation failed format={after_format} args={after_args}")
diag_path.write_text(diag, encoding="utf-8")

print("Tracker semantic version exposed on normal pages and USB/BLE diagnostic headers")
