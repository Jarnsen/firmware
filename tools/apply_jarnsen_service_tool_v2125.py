"""Apply v2.1.25 compatibility plus the post-2.1.25 Service Tool fixes.

The long patch chain contains two top-level log_metrics definitions. Python uses
the later one. Temporarily rename only the first definition so the v2.1.25 patch
can deterministically target the later runtime definition. Then apply native-USB
ACK telemetry, sticky automatic USB retry, the canonical Tracker OTA manifest,
firmware-version history, USB-attach firmware checking, the v2.1.31 virgin
node/bootstrap plus node-history lifecycle fixes, the v2.1.32 tile-first node
dashboard with automatic BLE log maintenance, the v2.1.33 reliable fixed-PIN
BLE automation, the v2.2.0 shell migration, and finally the v2.2.1 true rounded
Liquid Desktop presentation layer.
"""
from __future__ import annotations

import sys
from pathlib import Path

import patch_jarnsen_service_tool_v2125 as v2125
import patch_jarnsen_service_tool_v2126 as v2126
import patch_jarnsen_service_tool_v2127 as v2127
import patch_jarnsen_service_tool_v2128 as v2128
import patch_jarnsen_service_tool_v2129 as v2129
import patch_jarnsen_service_tool_v2130 as v2130
import patch_jarnsen_service_tool_v2131_fix as v2131
import patch_jarnsen_service_tool_v2132_fix as v2132
import patch_jarnsen_service_tool_v2133 as v2133
import patch_jarnsen_service_tool_v220_fix as v220
import patch_jarnsen_service_tool_v221 as v221


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply_jarnsen_service_tool_v2125.py <source.py>")
    path = Path(sys.argv[1])
    source = path.read_text(encoding="utf-8")

    function_anchor = "def log_metrics(payload: bytes) -> dict[str, str]:\n"
    metric_anchor = (
        '        "firmware": header_value(payload, b"firmware"),\n'
        '        "build": header_value(payload, b"build"),\n'
    )
    if source.count(function_anchor) != 2:
        raise SystemExit(f"v2.1.25 wrapper expected two log_metrics definitions, got {source.count(function_anchor)}")
    if source.count(metric_anchor) != 1:
        raise SystemExit(f"v2.1.25 wrapper expected one effective firmware metric anchor, got {source.count(metric_anchor)}")

    source = source.replace(
        function_anchor,
        "def log_metrics_shadow_v2125(payload: bytes) -> dict[str, str]:\n",
        1,
    )

    source = v2125.patch(source)

    source = source.replace(
        "def log_metrics_shadow_v2125(payload: bytes) -> dict[str, str]:\n",
        function_anchor,
        1,
    )

    source = v2126.patch(source)
    source = v2127.patch(source)

    # v2.1.25 owns the packaged self-test guard. Promote that guard before the
    # later patches so the packaged EXE validates the final release version.
    source = source.replace('APP_VERSION != "2.1.25"', 'APP_VERSION != "2.1.27"')
    source = source.replace("App-Version ist nicht v2.1.25", "App-Version ist nicht v2.1.27")

    source = v2128.patch(source)
    source = v2129.patch(source)
    source = v2130.patch(source)
    source = v2131.patch(source)
    source = v2132.patch(source)
    source = v2133.patch(source)
    source = v220.patch(source)
    source = v221.patch(source)

    path.write_text(source, encoding="utf-8")
    print("Applied Service Tool through v2.2.1: rounded Liquid Desktop UI + reliable BLE automation")


if __name__ == "__main__":
    main()
