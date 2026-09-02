"""Fix physical Windows interaction issues found with beta.12.

- provide real headless Tk-style values used by legacy USB auto-log code
- route the Series navigation through its own renderer even under capture-phase clicks
- stop rebuilding the Settings page on every 3 second state poll
"""
from __future__ import annotations

import pathlib
import sys


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_app(app: pathlib.Path) -> None:
    text = app.read_text(encoding="utf-8")
    if "JarnsenSeries?.open" not in text:
        text = replace_once(
            text,
            "    const nav = target.closest('[data-view]');\n    if (nav) { handled(); setView(nav.dataset.view); return; }\n",
            "    const nav = target.closest('[data-view]');\n"
            "    if (nav) {\n"
            "      handled();\n"
            "      if (nav.dataset.view === 'series') {\n"
            "        state.view = 'series';\n"
            "        document.querySelectorAll('.nav-item').forEach(item => item.classList.toggle('active', item.dataset.view === 'series'));\n"
            "        window.JarnsenSeries?.open?.();\n"
            "        return;\n"
            "      }\n"
            "      setView(nav.dataset.view);\n"
            "      return;\n"
            "    }\n",
            "series capture routing",
        )
    if "state.view === 'settings') renderPage()" in text:
        text = text.replace(
            "if (state.view === 'overview' || state.view === 'details' || state.view === 'firmware' || state.view === 'diagnostics' || state.view === 'settings') renderPage();",
            "if (state.view === 'overview' || state.view === 'details' || state.view === 'firmware' || state.view === 'diagnostics') renderPage();",
            1,
        )
    app.write_text(text, encoding="utf-8")


def patch_series(series: pathlib.Path) -> None:
    text = series.read_text(encoding="utf-8")
    if "window.JarnsenSeries" not in text:
        text = replace_once(
            text,
            "  window.addEventListener('beforeunload', () => clearTimeout(memory.pollTimer));\n  ensureNav();\n",
            "  window.addEventListener('beforeunload', () => clearTimeout(memory.pollTimer));\n"
            "  window.JarnsenSeries = {\n"
            "    open: () => renderSeries(),\n"
            "    refresh: () => renderSeries(true),\n"
            "  };\n"
            "  ensureNav();\n",
            "series global renderer",
        )
    series.write_text(text, encoding="utf-8")


def patch_headless(core: pathlib.Path) -> None:
    text = core.read_text(encoding="utf-8")
    if "self.auto_usb_log_var = HeadlessValue(True)" not in text:
        text = replace_once(
            text,
            "            self.status_var = self.status_text_var\n\n            # Profile/service state formerly created as a side effect of old tabs.\n",
            "            self.status_var = self.status_text_var\n\n"
            "            # Legacy USB auto-log controls must be real Tk-like value/widget proxies.\n"
            "            # Missing attributes can resolve through the declaration-only Tk shim as\n"
            "            # callable placeholders; legacy code then fails on placeholder.get().\n"
            "            self.auto_usb_log_var = HeadlessValue(True)\n"
            "            self.start_button = HeadlessLabel('Start')\n"
            "            self.cancel_button = HeadlessLabel('Abbrechen')\n"
            "            self._auto_usb_seen = set()\n"
            "            self._auto_usb_last_poll = 0.0\n"
            "            self._auto_usb_after = None\n\n"
            "            # Profile/service state formerly created as a side effect of old tabs.\n",
            "headless USB auto-log proxies",
        )
    core.write_text(text, encoding="utf-8")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_framework7_runtime_interaction_v318.py <app-v31.js>", file=sys.stderr)
        return 2
    app = pathlib.Path(sys.argv[1])
    root = app.parent.parent
    patch_app(app)
    patch_series(app.parent / "series-v37.js")
    patch_headless(root / "JARNSEN_FRAMEWORK7_HEADLESS_CORE.py")
    for path in (app, app.parent / "series-v37.js"):
        source = path.read_text(encoding="utf-8")
        if path.name == "app-v31.js" and ("JarnsenSeries?.open" not in source or "state.view === 'settings') renderPage()" in source):
            raise RuntimeError("v3.18 app interaction markers missing")
        if path.name == "series-v37.js" and "window.JarnsenSeries" not in source:
            raise RuntimeError("v3.18 series renderer marker missing")
    core_source = (root / "JARNSEN_FRAMEWORK7_HEADLESS_CORE.py").read_text(encoding="utf-8")
    if "self.auto_usb_log_var = HeadlessValue(True)" not in core_source:
        raise RuntimeError("v3.18 headless USB proxy marker missing")
    print("Framework7 runtime interaction v3.18 installed: Series route, stable Settings redraw, USB headless proxies")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
