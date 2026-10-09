#!/usr/bin/env python3
"""Contract for firmware TLS_BEGIN parsing and actionable failure messages."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    serial = (ROOT / "src/SerialConsole.cpp").read_text(encoding="utf-8")
    impl = (ROOT / "src/jarnsen/core/service/JarnsenTlsProvisioning.cpp").read_text(encoding="utf-8")
    header = (ROOT / "src/jarnsen/core/service/JarnsenTlsProvisioning.h").read_text(encoding="utf-8")
    required = {
        "decimal parser": "strtoul(cursor, &end, 10)" in serial,
        "exactly three arguments": "index < 3U" in serial,
        "reject trailing command data": "if (*cursor != '\\0')" in serial,
        "no legacy sscanf for begin": 'sscanf(command, "JARNSEN_TOOL_TLS_BEGIN' not in serial,
        "explicit serial failure cause": "action=begin reason=" in serial,
        "serial length diagnostics": 'Port.print(" cert=")' in serial,
        "node diagnostics": 'diagnosticLog("TLS_BEGIN_FAIL"' in serial,
        "read-only failure API": "tlsProvisionBeginFailureReason();" in header,
        "reject invalid length": 'lastBeginFailure = "invalid_length"' in impl,
        "reject allocation": 'lastBeginFailure = "allocation_failed"' in impl,
        "success reset": 'lastBeginFailure = "none";' in impl,
        "unsupported platform": 'return "unsupported_platform";' in impl,
        "ESP32 architecture guard": "defined(ARDUINO_ARCH_ESP32)" in impl,
        "unsupported TLS capability returns unreadable": "info = {};\n    return false;" in impl,
    }
    for name, passed in required.items():
        if not passed:
            raise SystemExit(f"TLS_BEGIN contract FAIL: {name}")
    print("TLS_BEGIN firmware parse/diagnostics static contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
