from __future__ import annotations

import py_compile
import sys
from pathlib import Path


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "tools/JARNSEN_NODE_SERVICE_TOOL.py")
    try:
        py_compile.compile(str(path), doraise=True)
    except py_compile.PyCompileError as exc:
        cause = exc.exc_value
        lineno = int(getattr(cause, "lineno", 0) or 0)
        lines = path.read_text(encoding="utf-8").splitlines()
        start = max(1, lineno - 12)
        end = min(len(lines), lineno + 12)
        print(f"Generated source syntax error around line {lineno}:")
        for number in range(start, end + 1):
            marker = ">>" if number == lineno else "  "
            print(f"{marker} {number:5}: {lines[number - 1]}")
        raise
    print("Generated Service Tool source compiles cleanly")


if __name__ == "__main__":
    main()
