"""Compatibility wrapper for the v2.2.1 rounded Liquid Desktop patch."""
from __future__ import annotations

import sys
from pathlib import Path

import patch_jarnsen_service_tool_v221 as v221


def patch(source: str) -> str:
    if "import customtkinter as ctk" not in source:
        anchor = "import tkinter as tk\n"
        if anchor not in source:
            raise SystemExit("v2.2.1 compatibility: tkinter module import not found")
        source = source.replace(anchor, anchor + "import customtkinter as ctk\n", 1)
    return v221.patch(source)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v221_fix.py <source.py>")
    path = Path(sys.argv[1])
    path.write_text(patch(path.read_text(encoding="utf-8")), encoding="utf-8")
    print("Applied v2.2.1 robust CustomTkinter compatibility wrapper")


if __name__ == "__main__":
    main()
