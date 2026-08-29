"""Compatibility wrapper for the v2.2.0 macOS-style shell.

Earlier UI patches changed the exact constructor used for the legacy left controls
pane. v2.2.0 keeps that pane alive only as a hidden compatibility surface, so
normalize its constructor before applying the new shell patch.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import patch_jarnsen_service_tool_v220 as v220


def patch(source: str) -> str:
    expected = (
        '        controls = ttk.Frame(body, padding=(0, 0, 12, 0), width=365)\n'
        '        body.add(controls, weight=0)\n'
    )
    if expected not in source:
        pattern = re.compile(
            r'^        controls = ttk\.Frame\(body[^\n]*\)\n'
            r'        body\.add\(controls, weight=0\)\n',
            re.MULTILINE,
        )
        match = pattern.search(source)
        if not match:
            raise SystemExit("v2.2.0 compatibility: legacy controls pane not found")
        source = source[: match.start()] + expected + source[match.end() :]
    return v220.patch(source)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v220_fix.py <source.py>")
    path = Path(sys.argv[1])
    path.write_text(patch(path.read_text(encoding="utf-8")), encoding="utf-8")
    print("Applied v2.2.0 compatibility wrapper for legacy controls pane")


if __name__ == "__main__":
    main()
