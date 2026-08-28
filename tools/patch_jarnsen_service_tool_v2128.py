"""v2.1.28: canonical Tracker update manifest and reliable firmware-version history."""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "2.1.28"


def method_span(text: str, name: str) -> tuple[int, int]:
    normal = text.find(f"    def {name}(")
    asynchronous = text.find(f"    async def {name}(")
    starts = [value for value in (normal, asynchronous) if value >= 0]
    if not starts:
        raise SystemExit(f"v2.1.28 method {name} not found")
    start = min(starts)
    next_method = text.find("\n    def ", start + 1)
    next_async = text.find("\n    async def ", start + 1)
    next_decorator = text.find("\n    @", start + 1)
    candidates = [value for value in (next_method, next_async, next_decorator) if value >= 0]
    return start, min(candidates) if candidates else len(text)


def replace_method(text: str, name: str, replacement: str) -> str:
    start, end = method_span(text, name)
    return text[:start] + replacement.rstrip() + "\n" + text[end:]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"v2.1.28 {label}: expected one anchor, got {count}")
    return text.replace(old, new, 1)


def patch(source: str) -> str:
    if "PATCH_V2128_CANONICAL_TRACKER_HISTORY" in source:
        return source

    source = re.sub(r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{APP_VERSION}"', source, count=1)
    source = source.replace('APP_VERSION != "2.1.27"', 'APP_VERSION != "2.1.28"')
    source = source.replace("App-Version ist nicht v2.1.27", "App-Version ist nicht v2.1.28")

    legacy_manifest = '"manifest": "heltec-tracker-v11-vehicle-motion-wake.ota.json"'
    canonical_manifest = '"manifest": "heltec-tracker-v11-jarn-mesh-v1.9.1.ota.json"'
    source = replace_once(source, legacy_manifest, canonical_manifest, "Tracker manifest")

    # Make the visible log/version history independent from stale DB display columns.
    # metrics_json is rebuilt from every saved diagnostic file at startup and carries
    # the dedicated JARN-MESH semantic version added in v2.1.25.  Always render that
    # value first and show a compact transition chain above the table.
    build_start, build_end = method_span(source, "_build_ui")
    build = source[build_start:build_end]
    history_anchor = '''        ttk.Button(\n            history_actions, text="Log öffnen", command=self.open_selected_log\n        ).pack(side="right")\n        self.history_tree = ttk.Treeview(\n'''
    history_replacement = '''        ttk.Button(\n            history_actions, text="Log öffnen", command=self.open_selected_log\n        ).pack(side="right")\n        self.version_history_summary_v2128 = ttk.Label(\n            self.history_tab,\n            text="Versionsverlauf: noch keine Daten",\n            style="Subtitle.TLabel",\n            anchor="w",\n            justify="left",\n        )\n        self.version_history_summary_v2128.pack(fill="x", pady=(0, 7))\n        self.history_tree = ttk.Treeview(\n'''
    build = replace_once(build, history_anchor, history_replacement, "history summary UI")
    source = source[:build_start] + build + source[build_end:]

    refresh_history = r'''    def refresh_history_view(self) -> None:
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)
        title = self.selected_node_id or "Node auswählen"
        if self.node_logs:
            metrics = self.node_logs[-1]["metrics"]
            title = f"{metrics.get('long_name') or title}  ·  {self.selected_node_id}  ·  {len(self.node_logs)} Log(s)"
        self.history_title.configure(text=title)

        transitions: list[tuple[str, str, str]] = []
        previous_key: tuple[str, str] | None = None
        for log in self.node_logs:
            metrics = log.get("metrics") or {}
            firmware = str(metrics.get("firmware") or log.get("firmware") or "--")
            build = str(metrics.get("build") or log.get("build") or "--")
            key = (firmware, build)
            if key == previous_key:
                continue
            stamp = str(log.get("captured_at") or "")[:16].replace("T", " ")
            transitions.append((stamp, firmware, build))
            previous_key = key

        if hasattr(self, "version_history_summary_v2128"):
            if not transitions:
                summary = "Versionsverlauf: noch keine Daten"
            else:
                visible = transitions[-5:]
                chain = "  →  ".join(
                    f"{firmware} [{build}]" if build not in ("", "--") else firmware
                    for _stamp, firmware, build in visible
                )
                prefix = "…  →  " if len(transitions) > len(visible) else ""
                summary = f"Versionsverlauf ({len(transitions)} Stand/stände): {prefix}{chain}"
            self.version_history_summary_v2128.configure(text=summary)

        for log in reversed(self.node_logs):
            metrics = log.get("metrics") or {}
            battery = "--"
            if metrics.get("battery_pct") is not None:
                battery = f"{float(metrics['battery_pct']):.0f} %"
            capacity = "--"
            if metrics.get("capacity") is not None:
                capacity = f"{float(metrics['capacity']):.0f} mAh"
            firmware = str(metrics.get("firmware") or log.get("firmware") or "--")
            build = str(metrics.get("build") or log.get("build") or "--")
            self.history_tree.insert(
                "",
                "end",
                iid=str(log["id"]),
                values=(
                    str(log["captured_at"]).replace("T", " "),
                    firmware,
                    build,
                    battery,
                    capacity,
                    int(metrics.get("warning_count") or 0),
                ),
            )
'''
    source = replace_method(source, "refresh_history_view", refresh_history)

    # Details should use the same product-version label as the history table.
    analyse_start = source.find("def analyse_log(payload: bytes) -> str:")
    if analyse_start < 0:
        raise SystemExit("v2.1.28 analyse_log not found")
    analyse_end = source.find("\ndef ", analyse_start + 1)
    if analyse_end < 0:
        analyse_end = len(source)
    analyse = source[analyse_start:analyse_end]
    analyse = replace_once(
        analyse,
        '    firmware = header_value(payload, b"firmware") or "--"\n',
        '    firmware = jarnsen_firmware_label(payload) or "--"\n',
        "analyse firmware label",
    )
    source = source[:analyse_start] + analyse + source[analyse_end:]

    source += "\n# PATCH_V2128_CANONICAL_TRACKER_HISTORY\n"
    required = (
        'APP_VERSION = "2.1.28"',
        'heltec-tracker-v11-jarn-mesh-v1.9.1.ota.json',
        'self.version_history_summary_v2128',
        'Versionsverlauf (',
        'metrics.get("firmware") or log.get("firmware")',
        'firmware = jarnsen_firmware_label(payload)',
        'PATCH_V2128_CANONICAL_TRACKER_HISTORY',
    )
    missing = [marker for marker in required if marker not in source]
    if missing:
        raise SystemExit("v2.1.28 validation failed: " + ", ".join(missing))
    if "heltec-tracker-v11-vehicle-motion-wake.ota.json" in source:
        raise SystemExit("v2.1.28 legacy Tracker OTA manifest still referenced")
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v2128.py <source.py>")
    path = Path(sys.argv[1])
    path.write_text(patch(path.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"Patched {path} to v{APP_VERSION}: canonical Tracker OTA manifest + version history")


if __name__ == "__main__":
    main()
