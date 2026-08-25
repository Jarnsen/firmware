"""Build-time patcher for Jarnsen Node Service Tool.

Keeps the large portable GUI source stable while adding branch-specific
INA226 status handling and small service controls before packaging.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path


def function_span(text: str, name: str) -> tuple[int, int]:
    start = text.find(f"def {name}(")
    if start < 0:
        raise SystemExit(f"function {name} not found")
    next_def = text.find("\ndef ", start + 1)
    next_class = text.find("\nclass ", start + 1)
    candidates = [value for value in (next_def, next_class) if value >= 0]
    return start, min(candidates) if candidates else len(text)


def replace_ina_assignment(text: str, function_name: str, replacement: str) -> str:
    start, end = function_span(text, function_name)
    block = text[start:end]
    marker = "    ina = ("
    rel = block.find(marker)
    if rel < 0:
        match = re.search(r"(?m)^    ina = .*current_ina_state.*$", block)
        if not match:
            raise SystemExit(f"INA assignment not found in {function_name}")
        block = block[: match.start()] + replacement + block[match.end() :]
        return text[:start] + block + text[end:]

    pos = rel
    scan = block.find("\n", pos)
    if scan < 0:
        scan = len(block)
    depth = block[pos:scan].count("(") - block[pos:scan].count(")")
    while depth > 0 and scan < len(block):
        next_end = block.find("\n", scan + 1)
        if next_end < 0:
            next_end = len(block)
        segment = block[scan + 1 : next_end]
        depth += segment.count("(") - segment.count(")")
        scan = next_end
    block = block[:pos] + replacement + block[scan:]
    return text[:start] + block + text[end:]


def patch(source: str, build_sha: str) -> str:
    if "def current_ina_state(" not in source:
        insert_at = source.find("\ndef log_metrics(")
        if insert_at < 0:
            raise SystemExit("log_metrics anchor not found")
        helper = '''


def current_ina_state(text: str, unknown: str = "--") -> str:
    """Return the newest INA226 state in actual log order."""
    state = unknown
    mapping = {
        "ACTIVE": "ACTIVE",
        "OK": "ACTIVE",
        "WAIT": "WAIT",
        "MISSING": "MISSING",
        "OFF": "OFF",
    }
    for line in text.splitlines():
        upper = line.upper()
        if "BATTERY" in upper:
            match = re.search(
                r"(?:^|\\s)ina=(ACTIVE|OK|WAIT|MISSING|OFF)(?:\\s|$)",
                line,
                re.IGNORECASE,
            )
            if match:
                state = mapping[match.group(1).upper()]
        if "INA226" not in upper:
            continue
        if re.search(r"\\b(?:READY|SAMPLE)\\b", upper):
            state = "ACTIVE"
        elif any(
            token in upper
            for token in (
                "ACK FAIL",
                "SENSOR MISSING",
                "SENSOR NOT READY",
                "ENABLED BUT SENSOR",
            )
        ):
            state = "MISSING"
        elif any(
            token in upper
            for token in ("INA226=OFF", "INA226: OFF", "INA226 | OFF")
        ):
            state = "OFF"
    return state
'''
        source = source[:insert_at] + helper + source[insert_at:]

    source = replace_ina_assignment(
        source,
        "analyse_log",
        '    ina = current_ina_state(text, "nicht ermittelt")',
    )
    source = replace_ina_assignment(
        source,
        "diagnostic_snapshot",
        "    ina = current_ina_state(text)",
    )

    if "APP_VERSION =" not in source:
        anchor = 'GITHUB_REPOSITORY = "Jarnsen/firmware"'
        if source.count(anchor) != 1:
            raise SystemExit("GITHUB_REPOSITORY anchor not found exactly once")
        source = source.replace(
            anchor,
            anchor + '\nAPP_VERSION = "1.2.0"' + f'\nAPP_BUILD = "{build_sha[:8]}"',
            1,
        )

    version_anchor = '        self.title_label.pack(side="left")'
    if "self.app_version_label" not in source:
        if source.count(version_anchor) != 1:
            raise SystemExit("title label anchor not found exactly once")
        version_ui = "\n".join(
            [
                version_anchor,
                '        self.app_version_label = ttk.Label(',
                '            title_row,',
                '            text=f"App v{APP_VERSION} · Build {APP_BUILD}",',
                '            style="Subtitle.TLabel",',
                '        )',
                '        self.app_version_label.pack(side="left", padx=(12, 0))',
            ]
        )
        source = source.replace(version_anchor, version_ui, 1)

    theme_anchor = '        self.theme.pack(side="right")'
    if "self.restart_button" not in source:
        if source.count(theme_anchor) != 1:
            raise SystemExit("theme pack anchor not found exactly once")
        restart_ui = "\n".join(
            [
                theme_anchor,
                '        self.restart_button = ttk.Button(',
                '            title_row, text="App neu starten", command=self.restart_app',
                '        )',
                '        self.restart_button.pack(side="right", padx=(8, 8))',
            ]
        )
        source = source.replace(theme_anchor, restart_ui, 1)

    if "    def restart_app(self)" not in source:
        close_anchor = "    def close_app(self) -> None:\n"
        if source.count(close_anchor) != 1:
            raise SystemExit("close_app anchor not found exactly once")
        restart_method = '''    def restart_app(self) -> None:
        if not messagebox.askyesno(
            "App neu starten",
            "Jarnsen Node Service Tool jetzt neu starten? Laufende Downloads werden beendet.",
        ):
            return
        self.stop_event.set()
        self.live_stop.set()
        self.update_idletasks()
        try:
            if getattr(sys, "frozen", False):
                argv = [sys.executable, *sys.argv[1:]]
            else:
                argv = [sys.executable, os.path.abspath(sys.argv[0]), *sys.argv[1:]]
            os.execv(sys.executable, argv)
        except Exception as exc:
            messagebox.showerror("Neustart fehlgeschlagen", str(exc))

'''
        source = source.replace(close_anchor, restart_method + close_anchor, 1)

    required = (
        'APP_VERSION = "1.2.0"',
        "def current_ina_state(",
        'ina = current_ina_state(text, "nicht ermittelt")',
        "ina = current_ina_state(text)",
        "self.app_version_label",
        'text="App neu starten"',
        "def restart_app(self)",
    )
    for marker in required:
        if marker not in source:
            raise SystemExit(f"missing patched source marker: {marker}")
    return source


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "tools/JARNSEN_NODE_SERVICE_TOOL.py")
    source = target.read_text(encoding="utf-8")
    build_sha = os.environ.get("APP_BUILD_SHA", "unknown")
    target.write_text(patch(source, build_sha), encoding="utf-8")
    print("Service tool patched: INA state, app version/build, restart button")


if __name__ == "__main__":
    main()
