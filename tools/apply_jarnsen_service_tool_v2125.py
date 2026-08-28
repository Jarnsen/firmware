"""Apply v2.1.25 compatibility, USB ACK telemetry and sticky auto USB retry.

The long patch chain contains two top-level log_metrics definitions. Python uses
the later one. Temporarily rename only the first definition so the v2.1.25 patch
can deterministically target the later runtime definition. Then apply the small
post-v2.1.25 native-USB ACK observer and the v2.1.27 sticky auto-USB session fix.
"""
from __future__ import annotations

import sys
from pathlib import Path

import patch_jarnsen_service_tool_v2125 as v2125
import patch_jarnsen_service_tool_v2126 as v2126
import patch_jarnsen_service_tool_v2127 as v2127


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

    # v2.1.25 owns the packaged self-test guard. Promote that guard along with
    # the final APP_VERSION so the built EXE validates the actual release.
    source = source.replace('APP_VERSION != "2.1.25"', 'APP_VERSION != "2.1.27"')
    source = source.replace("App-Version ist nicht v2.1.25", "App-Version ist nicht v2.1.27")

    path.write_text(source, encoding="utf-8")
    print("Applied Service Tool v2.1.25 compatibility + USB ACK + v2.1.27 sticky auto USB session")


if __name__ == "__main__":
    main()
