"""Compatibility fix for the v2.1.31 node lifecycle patch.

NodeRepository is followed by top-level helper functions before the next class.
The original v2.1.31 class_span only stopped at the next class, so method
replacement could accidentally consume top-level function definitions and leave
their bodies at module scope.  Delegate to v2.1.31 with a span function that
also stops at the next top-level function.
"""
from __future__ import annotations

import sys
from pathlib import Path

import patch_jarnsen_service_tool_v2131 as v2131


def class_span(text: str, name: str) -> tuple[int, int]:
    start = text.find(f"class {name}:")
    if start < 0:
        raise SystemExit(f"v2.1.31 class {name} not found")
    next_class = text.find("\nclass ", start + 1)
    next_function = text.find("\ndef ", start + 1)
    candidates = [value for value in (next_class, next_function) if value >= 0]
    return start, min(candidates) if candidates else len(text)


def patch(source: str) -> str:
    original = v2131.class_span
    try:
        v2131.class_span = class_span
        return v2131.patch(source)
    finally:
        v2131.class_span = original


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v2131_fix.py <source.py>")
    path = Path(sys.argv[1])
    path.write_text(patch(path.read_text(encoding="utf-8")), encoding="utf-8")
    print("Applied v2.1.31 class-span fix")


if __name__ == "__main__":
    main()
