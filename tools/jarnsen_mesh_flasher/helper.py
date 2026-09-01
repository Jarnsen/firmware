from __future__ import annotations

import runpy
import sys


def _run_module(module: str, argv: list[str]) -> int:
    sys.argv = [module, *argv]
    try:
        runpy.run_module(module, run_name="__main__")
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        print(code, file=sys.stderr)
        return 1
    return 0


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in {"-h", "--help"}:
        print("Usage: _JarnsenMeshHelper.exe meshtastic|esptool [args...]")
        return 0

    tool = sys.argv[1].lower()
    args = sys.argv[2:]
    if tool == "meshtastic":
        return _run_module("meshtastic", args)
    if tool == "esptool":
        return _run_module("esptool", args)

    print(f"Unknown helper tool: {tool}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
