"""Route Framework7 map/settings pages through the v3.2 enhancement layer.

The large app-v31.js remains the proven shell. This build-time patch only renames
its legacy map/settings renderers and adds tiny delegating wrappers. If the new
module is ever missing the old renderer is still available as a fallback.
"""
from __future__ import annotations

import pathlib
import sys


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_framework7_map_settings_v32.py <app-v31.js>", file=sys.stderr)
        return 2
    path = pathlib.Path(sys.argv[1])
    text = path.read_text(encoding="utf-8")
    if "JarnsenMapSettings.renderMap" in text:
        print("Framework7 map/settings v3.2 delegation already present")
        return 0

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
