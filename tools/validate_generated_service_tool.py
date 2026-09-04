from __future__ import annotations

import py_compile
import subprocess
import sys
from pathlib import Path


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "tools/JARNSEN_NODE_SERVICE_TOOL.py")
    tools = path.parent

    # Physical beta.12 testing exposed three runtime-only defects that syntax-only
    # validation could not catch: BLE scan resolving a missing Tk variable as a
    # callable placeholder, Series navigation being swallowed by the capture
    # router, and Settings being rebuilt on every state poll. Apply and validate
    # the runtime interaction repair after all normal Framework7 build patchers.
    interaction = tools / "patch_framework7_runtime_interaction_v318.py"
    app = tools / "service_tool_web" / "app-v31.js"
    completed = subprocess.run(
        [sys.executable, str(interaction), str(app)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.stdout:
        print(completed.stdout.strip())
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "runtime interaction patch failed").strip())

    try:
        py_compile.compile(str(path), doraise=True)
        py_compile.compile(str(tools / "JARNSEN_FRAMEWORK7_HEADLESS_CORE.py"), doraise=True)
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

    headless = (tools / "JARNSEN_FRAMEWORK7_HEADLESS_CORE.py").read_text(encoding="utf-8")
    for marker in (
        "self.auto_ble_enabled_v2132 = HeadlessValue(True)",
        "self.auto_ble_status_v2132 = HeadlessLabel",
        "self.auto_usb_log_var = HeadlessValue(True)",
    ):
        if marker not in headless:
            raise RuntimeError(f"Headless runtime marker missing: {marker}")

    app_source = app.read_text(encoding="utf-8")
    if "JarnsenSeries?.open" not in app_source:
        raise RuntimeError("Series capture-route repair missing")
    if "state.view === 'settings') renderPage()" in app_source:
        raise RuntimeError("Settings still participates in 3-second full redraw")

    series = tools / "service_tool_web" / "series-v37.js"
    if "window.JarnsenSeries" not in series.read_text(encoding="utf-8"):
        raise RuntimeError("Series renderer bridge missing")

    for javascript in (app, series):
        checked = subprocess.run(["node", "--check", str(javascript)], capture_output=True, text=True, timeout=30, check=False)
        if checked.returncode != 0:
            raise RuntimeError((checked.stderr or checked.stdout or f"JavaScript validation failed: {javascript}").strip())

    print("Generated Service Tool source and physical-interaction runtime contract validate cleanly")


if __name__ == "__main__":
    main()
