"""Route Framework7 map/settings pages and validate additive service modules.

The large app-v31.js remains the proven shell. This build-time patch only renames
its legacy map/settings renderers and adds tiny delegating wrappers. If the new
module is ever missing the old renderer is still available as a fallback.

Because this script is already a mandatory Framework7 build step, it also performs
static validation for the additive v3.7 serial-series workflow. This keeps the
large PowerShell build stable while ensuring the new Python/JS/CSS modules cannot
silently disappear or ship with invalid JavaScript syntax.

It also hardens the Framework7 headless USB startup path. The packaged application
must be able to start with a Tracker/V3 already attached, and all startup/tool logs
must land below Downloads/Meshtastic-Logs/Tool-Logs.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_usb_startup(root: pathlib.Path) -> None:
    runtime_path = root / "JARNSEN_FRAMEWORK7_RUNTIME_FIXES_V312.py"
    headless_path = root / "JARNSEN_FRAMEWORK7_HEADLESS_CORE.py"
    parity_path = root / "JARNSEN_FRAMEWORK7_PARITY_FIXES.py"
    for required in (runtime_path, headless_path, parity_path):
        if not required.is_file():
            raise RuntimeError(f"Framework7 USB startup source missing: {required}")

    runtime = runtime_path.read_text(encoding="utf-8")
    # v3.13 full diagnostics runs before this patch and intentionally replaces the
    # fixed startup filename with one timestamped session log. Treat either form
    # as already hardened instead of trying to patch the removed legacy anchor.
    diagnostic_path = 'Downloads" / "Meshtastic-Logs" / "Tool-Logs" / f"Jarnsen-Service-Tool_{stamp}.log"'
    fixed_path = 'Downloads" / "Meshtastic-Logs" / "Tool-Logs" / "Jarnsen-Service-Tool-startup.log"'
    if diagnostic_path not in runtime and fixed_path not in runtime:
        old = '''    candidates: list[Path] = []\n    local = str(os.environ.get("LOCALAPPDATA") or "").strip()\n    if local:\n        candidates.append(Path(local) / "Jarnsen" / "NodeServiceTool" / "Jarnsen-Service-Tool-startup.log")\n    candidates.append(Path.home() / "Jarnsen-Service-Tool-startup.log")\n    candidates.append(Path.cwd() / "Jarnsen-Service-Tool-startup.log")\n'''
        new = '''    candidates: list[Path] = [\n        Path.home() / "Downloads" / "Meshtastic-Logs" / "Tool-Logs" / "Jarnsen-Service-Tool-startup.log",\n    ]\n    local = str(os.environ.get("LOCALAPPDATA") or "").strip()\n    if local:\n        candidates.append(Path(local) / "Jarnsen" / "NodeServiceTool" / "Jarnsen-Service-Tool-startup.log")\n    candidates.append(Path.home() / "Jarnsen-Service-Tool-startup.log")\n    candidates.append(Path.cwd() / "Jarnsen-Service-Tool-startup.log")\n'''
        runtime = replace_once(runtime, old, new, "startup log directory")
        runtime_path.write_text(runtime, encoding="utf-8")

    headless = headless_path.read_text(encoding="utf-8")
    if "def set_result(self, text: Any)" not in headless and "def set_result(self, text: str)" not in headless:
        anchor = '''    def set_status(self, text: str, level: str = "normal") -> None:\n        self.status_text_var.set(str(text or ""))\n        self.status_level = str(level or "normal")\n\n'''
        replacement = anchor + '''    def set_result(self, text: Any) -> None:\n        self.last_result = str(text or "")\n        result = self.__dict__.get("result_text")\n        if result is not None:\n            with contextlib.suppress(Exception):\n                result.delete("1.0", "end")\n                result.insert("end", self.last_result)\n\n'''
        headless = replace_once(headless, anchor, replacement, "headless set_result")

    marker = '''            self.status_text_var = HeadlessValue("Bereit")\n            self.status_var = self.status_text_var\n'''
    if "self.auto_usb_log_var = HeadlessValue(True)" not in headless:
        replacement = marker + '''            # Legacy USB auto-log code still references these presentation controls.\n            # Real Framework7 has no Tk widgets, so provide safe headless equivalents.\n            self.auto_usb_log_var = HeadlessValue(True)\n            self._auto_usb_seen: set[str] = set()\n            self._auto_usb_last_poll = 0.0\n            self.start_button = HeadlessLabel("Start")\n            self.cancel_button = HeadlessLabel("Abbrechen")\n            self.result_text = HeadlessText()\n            self.last_result = ""\n'''
        headless = replace_once(headless, marker, replacement, "headless USB controls")
    headless_path.write_text(headless, encoding="utf-8")

    parity = parity_path.read_text(encoding="utf-8")
    old_output = '            output = pathlib.Path(legacy.output_directory())\n            output.mkdir(parents=True, exist_ok=True)\n'
    new_output = '            output = pathlib.Path(legacy.output_directory()) / "Tool-Logs"\n            output.mkdir(parents=True, exist_ok=True)\n'
    if 'pathlib.Path(legacy.output_directory()) / "Tool-Logs"' not in parity:
        count = parity.count(old_output)
        if count != 2:
            raise RuntimeError(f"tool log directory: expected two output anchors, found {count}")
        parity = parity.replace(old_output, new_output)
        parity_path.write_text(parity, encoding="utf-8")

    runtime_check = runtime_path.read_text(encoding="utf-8")
    headless_check = headless_path.read_text(encoding="utf-8")
    parity_check = parity_path.read_text(encoding="utf-8")
    if 'Meshtastic-Logs" / "Tool-Logs"' not in runtime_check:
        raise RuntimeError("Framework7 USB startup hardening marker missing: startup log path")
    for marker_text, source, label in (
        ("self.auto_usb_log_var = HeadlessValue(True)", headless_check, "USB auto-log state"),
        ("self.start_button = HeadlessLabel", headless_check, "USB start control"),
        ('pathlib.Path(legacy.output_directory()) / "Tool-Logs"', parity_check, "service log path"),
    ):
        if marker_text not in source:
            raise RuntimeError(f"Framework7 USB startup hardening marker missing: {label}")
    if "def set_result(self, text: Any)" not in headless_check and "def set_result(self, text: str)" not in headless_check:
        raise RuntimeError("Framework7 USB startup hardening marker missing: headless result sink")

    print("Framework7 USB-attached startup + Tool-Logs hardening installed")


def validate_series(root: pathlib.Path) -> None:
    series_py = root / "JARNSEN_FRAMEWORK7_SERIES.py"
    series_js = root / "service_tool_web" / "series-v37.js"
    series_css = root / "service_tool_web" / "series-v37.css"
    index = root / "service_tool_web" / "index.html"

    for path in (series_py, series_js, series_css, index):
        if not path.is_file():
            raise RuntimeError(f"Framework7 series asset missing: {path}")

    py_source = series_py.read_text(encoding="utf-8")
    compile(py_source, str(series_py), "exec")
    for marker in (
        "def install_series(",
        'critical["series_provisioning"]',
        '"/api/series/status"',
        '"/api/series/action"',
        '"/api/series/github"',
        "_framework7_series_bundle_override",
        "postcondition_verify",
    ):
        if marker not in py_source:
            raise RuntimeError(f"Framework7 series backend marker missing: {marker}")

    js_source = series_js.read_text(encoding="utf-8")
    for marker in (
        "/api/series/status",
        "/api/series/action",
        "/api/series/github",
        "seriesFirmwareSource",
        "seriesTemplateSave",
        "seriesTemplateDelete",
        "seriesStart",
        "seriesCancel",
        "seriesLocalFile",
        "SHA-256",
        "Soll/Ist",
        "Neue Nodes / Serienbereitstellung",
    ):
        if marker not in js_source:
            raise RuntimeError(f"Framework7 series UI marker missing: {marker}")

    css_source = series_css.read_text(encoding="utf-8")
    for marker in (".series-page", ".series-grid", ".series-job-card", ".series-result"):
        if marker not in css_source:
            raise RuntimeError(f"Framework7 series CSS marker missing: {marker}")

    html = index.read_text(encoding="utf-8")
    for marker in (
        'data-view="series"',
        'href="series-v37.css"',
        'src="series-v37.js"',
    ):
        if marker not in html:
            raise RuntimeError(f"Framework7 series index wiring missing: {marker}")

    try:
        checked = subprocess.run(
            ["node", "--check", str(series_js)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"node --check for series-v37.js could not run: {exc}") from exc
    if checked.returncode != 0:
        detail = (checked.stderr or checked.stdout or "unknown JavaScript syntax error").strip()
        raise RuntimeError(f"series-v37.js syntax validation failed: {detail}")

    print("Framework7 series v3.7 validation OK")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_framework7_map_settings_v32.py <app-v31.js>", file=sys.stderr)
        return 2
    path = pathlib.Path(sys.argv[1])
    text = path.read_text(encoding="utf-8")

    if "JarnsenMapSettings.renderMap" not in text:
        text = replace_once(text, "  async function renderMap() {", "  async function renderMapLegacy() {", "map renderer")
        text = replace_once(text, "  function renderSettings() {", "  function renderSettingsLegacy() {", "settings renderer")
        anchor = "  function emptyPage(title, text) {"
        wrapper = """  async function renderMap() {\n    if (window.JarnsenMapSettings && typeof window.JarnsenMapSettings.renderMap === 'function') {\n      return window.JarnsenMapSettings.renderMap({ app, state, request, pageHost, esc, chip, getNode, VERSION, toast, apiAction, renderPage });\n    }\n    return renderMapLegacy();\n  }\n\n  function renderSettings() {\n    if (window.JarnsenMapSettings && typeof window.JarnsenMapSettings.renderSettings === 'function') {\n      return window.JarnsenMapSettings.renderSettings({ app, state, request, pageHost, esc, chip, getNode, VERSION, toast, apiAction, renderPage });\n    }\n    return renderSettingsLegacy();\n  }\n\n"""
        text = replace_once(text, anchor, wrapper + anchor, "wrapper insertion")
        path.write_text(text, encoding="utf-8")
        print("Framework7 enhanced map/settings routing installed")
    else:
        print("Framework7 map/settings v3.2 delegation already present")

    root = path.parent.parent
    patch_usb_startup(root)
    validate_series(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
