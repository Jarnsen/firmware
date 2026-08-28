"""Apply v2.1.25 to the effective generated metrics helper.

The long patch chain contains two top-level log_metrics definitions. Python uses
the later one. Temporarily rename only the first definition so the v2.1.25 patch
can deterministically target the later runtime definition. The firmware/build
metric pair itself occurs only once in the final generated source.
"""
from __future__ import annotations

import sys
from pathlib import Path

import patch_jarnsen_service_tool_v2125 as v2125


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

    path.write_text(source, encoding="utf-8")
    print("Applied Service Tool v2.1.25 to effective metrics definition")


if __name__ == "__main__":
    main()
