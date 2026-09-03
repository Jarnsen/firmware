from __future__ import annotations

import os
import runpy
import sys


def _enable_live_output() -> None:
    """Make CLI output visible to the GUI while a packaged helper is running."""
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(line_buffering=True, write_through=True)
        except Exception:
            pass


def _run_module(module: str, argv: list[str]) -> int:
    _enable_live_output()
    sys.argv = [module, *argv]
    try:
        runpy.run_module(module, run_name="__main__")
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        print(code, file=sys.stderr, flush=True)
        return 1
    return 0


def main() -> int:
    _enable_live_output()
    if len(sys.argv) < 2 or sys.argv[1] in {"-h", "--help"}:
        print("Usage: _JarnsenMeshHelper.exe meshtastic|esptool [args...]", flush=True)
        return 0

    tool = sys.argv[1].lower()
    args = sys.argv[2:]
    if tool == "meshtastic":
        return _run_module("meshtastic", args)
    if tool == "esptool":
        return _run_module("esptool", args)

    print(f"Unknown helper tool: {tool}", file=sys.stderr, flush=True)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
