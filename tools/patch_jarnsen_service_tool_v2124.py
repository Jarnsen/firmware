"""v2.1.24: clearer node overview, screenshot clock, BLE auth guidance and LoRa-policy verification."""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "2.1.24"


def method_span(text: str, name: str) -> tuple[int, int]:
    normal = text.find(f"    def {name}(")
    asynchronous = text.find(f"    async def {name}(")
    starts = [value for value in (normal, asynchronous) if value >= 0]
    if not starts:
        raise SystemExit(f"v2.1.24 method {name} not found")
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
        raise SystemExit(f"v2.1.24 {label} anchor missing or ambiguous ({count})")
    return text.replace(old, new, 1)


def patch(source: str) -> str:
    if "PATCH_V2124_USABILITY" in source:
        return source

    source = re.sub(r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{APP_VERSION}"', source, count=1)
    source = source.replace('APP_VERSION != "2.1.23"', 'APP_VERSION != "2.1.24"')
    source = source.replace("App-Version ist nicht v2.1.23", "App-Version ist nicht v2.1.24")

    # STANDARD means normal Meshtastic/region behavior: no frequency or duty-cycle
    # override. Store that normalized state as the expected state too, otherwise
    # the readback correctly enforced by JarnsenAccessPolicy looks like a false
    # "Config lora" mismatch forever.
    apply_start, apply_end = method_span(source, "_config_profile_apply_worker")
    apply_method = source[apply_start:apply_end]
    lora_anchor = '''                    if name == "lora" and frequency_override is not None:\n                        if not hasattr(desired, "override_frequency"):\n                            raise RuntimeError("Die Ziel-Firmware unterstützt override_frequency nicht.")\n                        desired.override_frequency = float(frequency_override)\n'''
    lora_replacement = '''                    if name == "lora":\n                        if frequency_override is not None:\n                            if not hasattr(desired, "override_frequency"):\n                                raise RuntimeError("Die Ziel-Firmware unterstützt override_frequency nicht.")\n                            desired.override_frequency = float(frequency_override)\n                        else:\n                            if hasattr(desired, "override_frequency"):\n                                desired.override_frequency = 0.0\n                            if hasattr(desired, "override_duty_cycle"):\n                                desired.override_duty_cycle = False\n'''
    if "desired.override_duty_cycle = False" not in apply_method:
        if apply_method.count(lora_anchor) != 1:
            raise SystemExit("v2.1.24 LoRa normalization anchor missing or ambiguous")
        apply_method = apply_method.replace(lora_anchor, lora_replacement, 1)
    source = source[:apply_start] + apply_method + source[apply_end:]

    # GATT error 5 is not a generic "busy" state. It means the encrypted GATT
    # characteristic needs a valid Windows bond/authentication. Tell the operator
    # what to fix instead of misclassifying the node as occupied elsewhere.
    ble_reason = r'''    def _ble_unavailable_reason(self, label: str, exc: BaseException) -> str:
        text = str(exc).strip()
        lowered = text.lower()
        error_type = type(exc).__name__
        auth_required = (
            "insufficient authentication" in lowered
            or "authentication required" in lowered
            or "not authenticated" in lowered
            or (error_type == "BleakGATTProtocolError" and lowered.startswith("(5,"))
        )
        if auth_required:
            state = "Authentifizierung erforderlich – in Windows koppeln/neu koppeln"
            tool_log(
                "BLE_AUTH_REQUIRED_V2124",
                node=label,
                state=state,
                error_type=error_type,
                error=text or "--",
            )
            return f"{label}: {state}"

        busy_tokens = (
            "timeout",
            "timed out",
            "not connected",
            "could not connect",
            "failed to connect",
            "connection failed",
            "connection refused",
            "connection aborted",
            "connection reset",
            "device not found",
            "unreachable",
            "gatt",
            "att error",
            "operation already in progress",
            "busy",
            "resource in use",
        )
        likely_busy = any(token in lowered for token in busy_tokens)
        state = "anderweitig verwendet / derzeit nicht frei" if likely_busy else "derzeit nicht frei"
        tool_log(
            "BLE_NODE_NOT_FREE_V218",
            node=label,
            state=state,
            error_type=error_type,
            error=text or "--",
        )
        return f"{label}: {state}"
'''
    source = replace_method(source, "_ble_unavailable_reason", ble_reason)

    # Let the BLE list consume the vertical room of the advanced left pane. The
    # old fixed height=3 was the reason only two or three nodes were visible while
    # a large empty area remained below it.
    build_start, build_end = method_span(source, "_build_ui")
    build = source[build_start:build_end]
    build = replace_once(
        build,
        '        ble.pack(fill="x", pady=(6, 0))\n',
        '        ble.pack(fill="both", expand=True, pady=(6, 0))\n',
        "BLE frame expansion",
    )
    ble_list_anchor = '''        self.ble_device = tk.Listbox(\n            ble,\n            height=3,\n            selectmode="extended",\n            exportselection=False,\n            activestyle="dotbox",\n        )\n        self.ble_device.grid(row=0, column=0, columnspan=2, sticky="ew")\n'''
    ble_list_replacement = '''        self.ble_device = tk.Listbox(\n            ble,\n            height=10,\n            selectmode="extended",\n            exportselection=False,\n            activestyle="dotbox",\n        )\n        self.ble_device.grid(row=0, column=0, columnspan=2, sticky="nsew")\n        ble.rowconfigure(0, weight=1)\n        ble.columnconfigure(0, weight=1)\n        ble.columnconfigure(1, weight=1)\n'''
    build = replace_once(build, ble_list_anchor, ble_list_replacement, "BLE list height")
    source = source[:build_start] + build + source[build_end:]

    # Persistent clock/date in the workflow header makes screenshots self-ordering.
    # Also modernize the all-node page with compact KPI cards and a scrollable,
    # roomier table instead of one dense flat list.
    ui_start, ui_end = method_span(source, "_install_workflow_ui")
    ui = source[ui_start:ui_end]
    clock_anchor = '''        self.advanced_button = ttk.Button(header, text="Erweitert", command=self.toggle_advanced_controls)\n        self.advanced_button.pack(side="right")\n'''
    clock_replacement = '''        self.advanced_button = ttk.Button(header, text="Erweitert", command=self.toggle_advanced_controls)\n        self.advanced_button.pack(side="right")\n        self.workflow_clock = ttk.Label(header, text="", style="Subtitle.TLabel", anchor="e")\n        self.workflow_clock.pack(side="right", padx=(8, 10))\n        self._update_workflow_clock_v2124()\n'''
    ui = replace_once(ui, clock_anchor, clock_replacement, "workflow clock")

    stats_anchor = '''        ttk.Button(\n            all_header, text="Aktualisieren", command=self.refresh_all_nodes_overview\n        ).pack(side="right", padx=(0, 6))\n\n        self.all_nodes_tree = ttk.Treeview(\n            self.all_nodes_tab,\n'''
    stats_replacement = '''        ttk.Button(\n            all_header, text="Aktualisieren", command=self.refresh_all_nodes_overview\n        ).pack(side="right", padx=(0, 6))\n\n        all_stats = ttk.Frame(self.all_nodes_tab)\n        all_stats.pack(fill="x", pady=(0, 9))\n        self.all_nodes_stat_total = tk.StringVar(value="0")\n        self.all_nodes_stat_tracker = tk.StringVar(value="0")\n        self.all_nodes_stat_v3 = tk.StringVar(value="0")\n        self.all_nodes_stat_attention = tk.StringVar(value="0")\n        for index, (title, variable) in enumerate((\n            ("Nodes gesamt", self.all_nodes_stat_total),\n            ("Tracker V1.1", self.all_nodes_stat_tracker),\n            ("Heltec V3", self.all_nodes_stat_v3),\n            ("Updates / Hinweise", self.all_nodes_stat_attention),\n        )):\n            card = ttk.LabelFrame(all_stats, text=title, padding=(10, 5))\n            card.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 4, 0))\n            ttk.Label(card, textvariable=variable, style="Section.TLabel", anchor="center").pack(fill="x")\n            all_stats.columnconfigure(index, weight=1, uniform="all_node_stats")\n\n        all_tree = ttk.Frame(self.all_nodes_tab)\n        all_tree.pack(fill="both", expand=True)\n        all_tree.rowconfigure(0, weight=1)\n        all_tree.columnconfigure(0, weight=1)\n        ttk.Style(self).configure("AllNodes.Treeview", rowheight=28)\n        self.all_nodes_tree = ttk.Treeview(\n            all_tree,\n'''
    ui = replace_once(ui, stats_anchor, stats_replacement, "all-node stats")
    ui = ui.replace('            height=15,\n', '            height=19,\n            style="AllNodes.Treeview",\n', 1)
    ui = ui.replace('            ("name", "Node", 185, True),\n', '            ("name", "Node", 220, True),\n', 1)
    ui = ui.replace('            ("firmware", "Firmware / Build", 150, True),\n', '            ("firmware", "Firmware / Build", 175, True),\n', 1)
    ui = ui.replace('            ("position", "Position / Status", 140, True),\n', '            ("position", "Position / Status", 165, True),\n', 1)
    tree_pack_anchor = '        self.all_nodes_tree.pack(fill="both", expand=True)\n'
    tree_pack_replacement = '''        self.all_nodes_tree.grid(row=0, column=0, sticky="nsew")\n        all_tree_scroll_y = ttk.Scrollbar(all_tree, orient="vertical", command=self.all_nodes_tree.yview)\n        all_tree_scroll_y.grid(row=0, column=1, sticky="ns")\n        all_tree_scroll_x = ttk.Scrollbar(all_tree, orient="horizontal", command=self.all_nodes_tree.xview)\n        all_tree_scroll_x.grid(row=1, column=0, sticky="ew")\n        self.all_nodes_tree.configure(yscrollcommand=all_tree_scroll_y.set, xscrollcommand=all_tree_scroll_x.set)\n'''
    ui = replace_once(ui, tree_pack_anchor, tree_pack_replacement, "all-node scrollbars")
    source = source[:ui_start] + ui + source[ui_end:]

    # Update the KPI cards every time the overview refreshes.
    refresh_start, refresh_end = method_span(source, "refresh_all_nodes_overview")
    refresh = source[refresh_start:refresh_end]
    summary_anchor = '''        self.all_nodes_summary.configure(\n            text=(\n                f"{len(rows)} Nodes · {tracker_count} Tracker · {v3_count} V3 · "\n                f"{update_count} Update(s) · {warning_count} Hinweis(e) · {low_battery_count} Akku ≤20 %"\n            )\n        )\n'''
    summary_replacement = '''        self.all_nodes_summary.configure(\n            text=f"Alle Nodes · {len(rows)} Gerät(e) · Stand aus den zuletzt gespeicherten Logs"\n        )\n        if hasattr(self, "all_nodes_stat_total"):\n            self.all_nodes_stat_total.set(str(len(rows)))\n            self.all_nodes_stat_tracker.set(str(tracker_count))\n            self.all_nodes_stat_v3.set(str(v3_count))\n            attention = update_count + warning_count\n            self.all_nodes_stat_attention.set(\n                f"{attention} · {update_count} Update · {warning_count} Hinweis"\n            )\n'''
    refresh = replace_once(refresh, summary_anchor, summary_replacement, "all-node KPI refresh")
    source = source[:refresh_start] + refresh + source[refresh_end:]

    clock_method = r'''    def _update_workflow_clock_v2124(self) -> None:
        if not hasattr(self, "workflow_clock"):
            return
        now = now_local()
        weekdays = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
        self.workflow_clock.configure(
            text=f"{weekdays[now.weekday()]} {now:%d.%m.%Y · %H:%M:%S}"
        )
        self.after(1000, self._update_workflow_clock_v2124)
'''
    insert_at, _ = method_span(source, "refresh_node_selector")
    source = source[:insert_at] + clock_method.rstrip() + "\n\n" + source[insert_at:]

    source += "\n# PATCH_V2124_USABILITY\n"
    required = (
        'APP_VERSION = "2.1.24"',
        'desired.override_duty_cycle = False',
        'BLE_AUTH_REQUIRED_V2124',
        'height=10',
        'ble.pack(fill="both", expand=True',
        'self.workflow_clock',
        'def _update_workflow_clock_v2124',
        'self.all_nodes_stat_total',
        'AllNodes.Treeview',
        'all_tree_scroll_y',
        'PATCH_V2124_USABILITY',
    )
    missing = [marker for marker in required if marker not in source]
    if missing:
        raise SystemExit("v2.1.24 validation failed: " + ", ".join(missing))
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v2124.py <source.py>")
    path = Path(sys.argv[1])
    path.write_text(patch(path.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"Patched {path} to v{APP_VERSION}: modern all-node UI + clock + taller BLE list + auth/LoRa fixes")


if __name__ == "__main__":
    main()
