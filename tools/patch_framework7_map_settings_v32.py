"""Route Framework7 map/settings pages and validate additive service modules.

The large app-v31.js remains the proven shell. This build-time patch only renames
its legacy map/settings renderers and adds tiny delegating wrappers. If the new
module is ever missing the old renderer is still available as a fallback.

Because this script is already a mandatory Framework7 build step, it also performs
static validation for the additive v3.7 serial-series workflow. This keeps the
large PowerShell build stable while ensuring the new Python/JS/CSS modules cannot
silently disappear or ship with invalid JavaScript syntax.
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
        text = replace_once(
            text,
            "  async function renderMap() {",
            "  async function renderMapLegacy() {",
            "map renderer",
        )
        text = replace_once(
            text,
            "  function renderSettings() {",
            "  function renderSettingsLegacy() {",
            "settings renderer",
        )

        anchor = "  function emptyPage(title, text) {"
        wrapper = """  async function renderMap() {\n    if (window.JarnsenMapSettings && typeof window.JarnsenMapSettings.renderMap === 'function') {\n      return window.JarnsenMapSettings.renderMap({ app, state, request, pageHost, esc, chip, getNode, VERSION, toast, apiAction, renderPage });\n    }\n    return renderMapLegacy();\n  }\n\n  function renderSettings() {\n    if (window.JarnsenMapSettings && typeof window.JarnsenMapSettings.renderSettings === 'function') {\n      return window.JarnsenMapSettings.renderSettings({ app, state, request, pageHost, esc, chip, getNode, VERSION, toast, apiAction, renderPage });\n    }\n    return renderSettingsLegacy();\n  }\n\n"""
        text = replace_once(text, anchor, wrapper + anchor, "wrapper insertion")
        path.write_text(text, encoding="utf-8")
        print("Framework7 enhanced map/settings routing installed")
    else:
        print("Framework7 map/settings v3.2 delegation already present")

    # app-v31.js lives under tools/service_tool_web; the validator expects the
    # tools directory so it can see both JARNSEN_FRAMEWORK7_SERIES.py and web assets.
    validate_series(path.parent.parent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
