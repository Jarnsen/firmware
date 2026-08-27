"""v2.1.16 build fix: escape the BT-PIN dialog newline in generated source."""
from __future__ import annotations

import sys
from pathlib import Path


def patch(source: str) -> str:
    broken = 'messagebox.showinfo("BT-PIN", f"Modus: {mode_name}\n{pin_text}")'
    fixed = 'messagebox.showinfo("BT-PIN", f"Modus: {mode_name}\\n{pin_text}")'
    if broken not in source:
        raise SystemExit("v2.1.16 BT-PIN newline anchor missing")
    source = source.replace(broken, fixed, 1)
    if fixed not in source:
        raise SystemExit("v2.1.16 BT-PIN newline fix failed")
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v2116_fix.py <source.py>")
    path = Path(sys.argv[1])
    path.write_text(patch(path.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"Fixed v2.1.16 BT-PIN dialog newline in {path}")


if __name__ == "__main__":
    main()
