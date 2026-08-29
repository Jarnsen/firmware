"""v2.2.0: macOS/iOS-inspired desktop shell while preserving Service Tool functionality."""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "2.2.0"


def method_span(text: str, name: str) -> tuple[int, int]:
    normal = text.find(f"    def {name}(")
    asynchronous = text.find(f"    async def {name}(")
    starts = [value for value in (normal, asynchronous) if value >= 0]
    if not starts:
        raise SystemExit(f"v2.2.0 method {name} not found")
    start = min(starts)
    candidates = [
        value
        for value in (
            text.find("\n    def ", start + 1),
            text.find("\n    async def ", start + 1),
            text.find("\n    @", start + 1),
        )
        if value >= 0
    ]
    return start, min(candidates) if candidates else len(text)


def replace_method(text: str, name: str, replacement: str) -> str:
    start, end = method_span(text, name)
    return text[:start] + replacement.rstrip() + "\n" + text[end:]


def patch(source: str) -> str:
    if "PATCH_V220_MAC_DESKTOP_SHELL" in source:
        return source

    source = re.sub(r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{APP_VERSION}"', source, count=1)
    source = source.replace('APP_VERSION != "2.1.33"', 'APP_VERSION != "2.2.0"')
    source = source.replace("App-Version ist nicht v2.1.33", "App-Version ist nicht v2.2.0")

    build_start, build_end = method_span(source, "_build_ui")
    build = source[build_start:build_end]
    if "self.main_pane_v220" not in build:
        anchor = '        body = ttk.Panedwindow(self.root, orient="horizontal")\n        body.pack(fill="both", expand=True)\n'
        if anchor not in build:
            raise SystemExit("v2.2.0 main panedwindow anchor missing")
        build = build.replace(
            anchor,
            anchor + '        self.main_pane_v220 = body\n',
            1,
        )
        anchor = '        controls = ttk.Frame(body, padding=(0, 0, 12, 0), width=365)\n        body.add(controls, weight=0)\n'
        if anchor not in build:
            raise SystemExit("v2.2.0 controls pane anchor missing")
        build = build.replace(anchor, anchor + '        self.legacy_controls_v220 = controls\n', 1)
        anchor = '        workspace = ttk.Frame(body)\n        body.add(workspace, weight=1)\n'
        if anchor not in build:
            raise SystemExit("v2.2.0 workspace pane anchor missing")
        build = build.replace(anchor, anchor + '        self.workspace_v220 = workspace\n', 1)
        build = build.replace('        self.theme.set("Modern")\n', '        self.theme.set("iOS")\n', 1)
        build = build.replace('        self.geometry("1240x860")\n', '        self.geometry("1480x920")\n', 1)
        build = build.replace('        self.minsize(1000, 720)\n', '        self.minsize(1120, 720)\n', 1)
    source = source[:build_start] + build + source[build_end:]

    render_start, _render_end = method_span(source, "render_node_tiles_v2132")
    helpers = r'''    # PATCH_V220_MAC_DESKTOP_SHELL
    def _mac_palette_v220(self) -> dict[str, str]:
        dark = bool(getattr(self, "mac_dark_v220", None) and self.mac_dark_v220.get())
        if dark:
            return {
                "bg": "#111214", "sidebar": "#18191C", "surface": "#1F2024",
                "surface2": "#292A2F", "line": "#383A40", "fg": "#F5F5F7",
                "muted": "#A1A1A6", "blue": "#0A84FF", "green": "#30D158",
                "orange": "#FF9F0A", "red": "#FF453A", "purple": "#BF5AF2",
                "selection": "#173B66", "shadow": "#0A0A0B",
            }
        return {
            "bg": "#F5F5F7", "sidebar": "#ECECEF", "surface": "#FFFFFF",
            "surface2": "#F2F2F7", "line": "#D9D9DE", "fg": "#1D1D1F",
            "muted": "#6E6E73", "blue": "#007AFF", "green": "#34C759",
            "orange": "#FF9500", "red": "#FF3B30", "purple": "#AF52DE",
            "selection": "#E8F2FF", "shadow": "#D1D1D6",
        }

    def _mac_button_v220(
        self, parent: tk.Misc, text: str, command: object,
        primary: bool = False, danger: bool = False, compact: bool = False,
    ) -> tk.Button:
        palette = self._mac_palette_v220()
        if danger:
            bg, fg, active = palette["surface2"], palette["red"], palette["line"]
        elif primary:
            bg, fg, active = palette["blue"], "#FFFFFF", "#3395FF"
        else:
            bg, fg, active = palette["surface2"], palette["blue"], palette["line"]
        return tk.Button(
            parent, text=text, command=command, bg=bg, fg=fg,
            activebackground=active, activeforeground=fg, relief="flat", bd=0,
            highlightthickness=0, cursor="hand2", padx=10 if compact else 14,
            pady=5 if compact else 8, font=("Segoe UI Variable", 9, "bold"),
        )

    def _mac_label_chip_v220(
        self, parent: tk.Misc, text: str, tone: str = "neutral"
    ) -> tk.Label:
        palette = self._mac_palette_v220()
        colors = {
            "blue": ("#E8F2FF" if palette["bg"] == "#F5F5F7" else "#163A63", palette["blue"]),
            "green": ("#EAF8EE" if palette["bg"] == "#F5F5F7" else "#193B25", palette["green"]),
            "orange": ("#FFF4E5" if palette["bg"] == "#F5F5F7" else "#493319", palette["orange"]),
            "red": ("#FFEDEC" if palette["bg"] == "#F5F5F7" else "#4A2422", palette["red"]),
            "purple": ("#F5ECFB" if palette["bg"] == "#F5F5F7" else "#392349", palette["purple"]),
            "neutral": (palette["surface2"], palette["muted"]),
        }
        bg, fg = colors.get(tone, colors["neutral"])
        return tk.Label(
            parent, text=text, bg=bg, fg=fg, padx=8, pady=3,
            font=("Segoe UI Variable", 8, "bold"),
        )

    def _toggle_node_selection_v220(self, node_id: str) -> None:
        states = getattr(self, "node_selection_v2133", {})
        variable = states.get(node_id)
        if variable is None:
            variable = tk.BooleanVar(value=False)
            states[node_id] = variable
            self.node_selection_v2133 = states
        variable.set(not bool(variable.get()))
        self._update_batch_bar_v2133()
        self.render_node_tiles_v2132()

    def _set_filter_v220(self, value: str) -> None:
        if hasattr(self, "node_filter_var_v2133"):
            self.node_filter_var_v2133.set(value)
            self.render_node_tiles_v2132()
        self._refresh_filter_segments_v220()

    def _refresh_filter_segments_v220(self) -> None:
        palette = self._mac_palette_v220()
        selected = self.node_filter_var_v2133.get() if hasattr(self, "node_filter_var_v2133") else "Alle"
        mapping = getattr(self, "mac_filter_buttons_v220", {})
        for value, button in mapping.items():
            active = value == selected
            button.configure(
                bg=palette["blue"] if active else palette["surface2"],
                fg="#FFFFFF" if active else palette["fg"],
                activebackground=palette["blue"] if active else palette["line"],
                activeforeground="#FFFFFF" if active else palette["fg"],
            )

    def _select_page_v220(self, page_attr: str, label: str = "") -> None:
        page = getattr(self, page_attr, None)
        if page is None:
            messagebox.showinfo("Bereich", f"{label or page_attr} ist in diesem Gerätestand nicht verfügbar.")
            return
        self.notebook.select(page)
        self._set_mac_nav_active_v220(page_attr)

    def _set_mac_nav_active_v220(self, page_attr: str) -> None:
        palette = self._mac_palette_v220()
        self.mac_active_page_v220 = page_attr
        for attr, button in getattr(self, "mac_nav_buttons_v220", {}).items():
            active = attr == page_attr
            button.configure(
                bg=palette["selection"] if active else palette["sidebar"],
                fg=palette["blue"] if active else palette["fg"],
            )

    def _candidate_page_v220(self, *names: str) -> str:
        for name in names:
            if getattr(self, name, None) is not None:
                return name
        return "all_nodes_tab"

    def _show_mac_activity_v220(self) -> None:
        panel = getattr(self, "mac_activity_window_v220", None)
        if panel is not None and panel.winfo_exists():
            panel.lift()
            return
        palette = self._mac_palette_v220()
        win = tk.Toplevel(self)
        self.mac_activity_window_v220 = win
        win.title("Aktivität & Automatik")
        win.geometry("520x620")
        win.minsize(440, 420)
        win.configure(bg=palette["bg"])
        body = tk.Frame(win, bg=palette["bg"], padx=22, pady=20)
        body.pack(fill="both", expand=True)
        tk.Label(body, text="Aktivität & Automatik", bg=palette["bg"], fg=palette["fg"], font=("Segoe UI Variable Display", 20, "bold")).pack(anchor="w")
        tk.Label(body, text="BLE-Erkennung, Pairing, Log-Queue und Firmwareaktionen", bg=palette["bg"], fg=palette["muted"], font=("Segoe UI Variable", 10)).pack(anchor="w", pady=(2, 14))
        listbox = tk.Listbox(body, activestyle="none", bd=0, relief="flat", highlightthickness=0, bg=palette["surface"], fg=palette["fg"], selectbackground=palette["selection"], selectforeground=palette["fg"], font=("Segoe UI Variable", 10))
        listbox.pack(fill="both", expand=True)
        for item in getattr(self, "mac_activity_events_v220", [])[-100:]:
            listbox.insert("end", item)
        controls = tk.Frame(body, bg=palette["bg"])
        controls.pack(fill="x", pady=(14, 0))
        self._mac_button_v220(controls, "BLE jetzt prüfen", lambda: self.auto_ble_refresh_v2132(False), primary=True).pack(side="left")
        self._mac_button_v220(controls, "Schließen", win.destroy).pack(side="right")

    def _append_activity_v220(self, text: str) -> None:
        events = getattr(self, "mac_activity_events_v220", None)
        if not isinstance(events, list):
            events = []
            self.mac_activity_events_v220 = events
        events.append(str(text))
        if len(events) > 200:
            del events[:-200]
        if hasattr(self, "mac_activity_count_v220"):
            self.mac_activity_count_v220.configure(text=str(min(len(events), 99)))
        win = getattr(self, "mac_activity_window_v220", None)
        if win is not None and win.winfo_exists():
            for child in win.winfo_children():
                pass

    def _single_node_ota_v220(self, node_id: str) -> None:
        entries, missing = self._ble_entries_for_nodes_v2133([node_id])
        if missing or len(entries) != 1:
            messagebox.showinfo("OTA", "Diese Node ist aktuell nicht über BLE sichtbar/zugeordnet.")
            self.auto_ble_refresh_v2132(False)
            return
        self._select_ble_entries_v2133(entries)
        self.start_ble_update()

    def _delete_single_node_v220(self, node_id: str) -> None:
        if self._delete_node_ids_v2131([node_id]):
            if getattr(self, "mac_inspector_node_v220", "") == node_id:
                self.mac_inspector_node_v220 = ""
            self.refresh_all_nodes_overview()

    def _node_menu_v220(self, node_id: str, widget: tk.Misc) -> None:
        palette = self._mac_palette_v220()
        menu = tk.Menu(widget, tearoff=False, bg=palette["surface"], fg=palette["fg"], activebackground=palette["selection"], activeforeground=palette["fg"], bd=0, relief="flat")
        menu.add_command(label="Öffnen", command=lambda: self.show_mac_inspector_v220(node_id))
        menu.add_command(label="Bearbeiten …", command=lambda: self.open_node_actions_v2132(node_id))
        menu.add_command(label="Log laden", command=lambda: self.batch_log_download_v2133([node_id]))
        menu.add_command(label="OTA Update", command=lambda: self._single_node_ota_v220(node_id))
        menu.add_separator()
        menu.add_command(label="Grunddaten / Service", command=lambda: self.open_node_from_tile_v2132(node_id, "service"))
        menu.add_command(label="Log-Historie", command=lambda: self.open_node_from_tile_v2132(node_id, "history"))
        menu.add_separator()
        menu.add_command(label="Node entfernen …", command=lambda: self._delete_single_node_v220(node_id))
        try:
            menu.tk_popup(widget.winfo_rootx(), widget.winfo_rooty() + widget.winfo_height())
        finally:
            menu.grab_release()

    def show_mac_inspector_v220(self, node_id: str) -> None:
        self.mac_inspector_node_v220 = normalize_node_id(node_id)
        self.render_mac_inspector_v220()

    def render_mac_inspector_v220(self) -> None:
        host = getattr(self, "mac_inspector_v220", None)
        if host is None:
            return
        palette = self._mac_palette_v220()
        host.configure(bg=palette["surface"])
        for child in host.winfo_children():
            child.destroy()
        node_id = normalize_node_id(getattr(self, "mac_inspector_node_v220", ""))
        if not node_id:
            tk.Label(host, text="Node auswählen", bg=palette["surface"], fg=palette["fg"], font=("Segoe UI Variable Display", 17, "bold")).pack(anchor="w", padx=20, pady=(24, 5))
            tk.Label(host, text="Details, Aktionen und Automatik erscheinen hier, ohne die Nodeübersicht zu verlassen.", bg=palette["surface"], fg=palette["muted"], justify="left", wraplength=285, font=("Segoe UI Variable", 10)).pack(anchor="w", padx=20)
            return
        latest = self.repository.latest_log(node_id)
        metrics = latest.get("metrics", {}) if latest else {}
        if not isinstance(metrics, dict):
            metrics = {}
        name = str(metrics.get("long_name") or node_id)
        short = str(metrics.get("short_name") or "")
        device_key = str(metrics.get("device") or "")
        device = "Tracker V1.1" if device_key == "HELTEC_TRACKER_V1.1" else ("Heltec V3" if device_key == "HELTEC_V3_REPEATER" else DEVICE_NAMES.get(device_key, device_key or "--"))
        battery_value = metrics.get("battery_pct")
        battery = f"{float(battery_value):.0f} %" if isinstance(battery_value, (int, float)) else "--"
        firmware = str(latest.get("firmware") or "--") if latest else "--"
        ble_state = self.repository.ble_status_for_node_v2132(node_id)
        due = self._node_is_due_v2133(node_id)
        warning_count = int(metrics.get("warning_count") or 0)

        head = tk.Frame(host, bg=palette["surface"])
        head.pack(fill="x", padx=20, pady=(20, 6))
        tk.Label(head, text=name, bg=palette["surface"], fg=palette["fg"], font=("Segoe UI Variable Display", 17, "bold"), anchor="w", wraplength=260).pack(fill="x")
        tk.Label(head, text=f"{short or '—'}  ·  {node_id}", bg=palette["surface"], fg=palette["muted"], font=("Segoe UI Variable", 9)).pack(anchor="w", pady=(2, 0))

        chips = tk.Frame(host, bg=palette["surface"])
        chips.pack(fill="x", padx=20, pady=(5, 13))
        self._mac_label_chip_v220(chips, device.replace("Heltec ", ""), "purple" if "V3" in device else "blue").pack(side="left", padx=(0, 5))
        self._mac_label_chip_v220(chips, "BLE sichtbar" if ble_state else "Offline", "green" if ble_state else "neutral").pack(side="left", padx=(0, 5))
        self._mac_label_chip_v220(chips, "Log fällig" if due else "Log aktuell", "orange" if due else "green").pack(side="left")

        facts = tk.Frame(host, bg=palette["surface"])
        facts.pack(fill="x", padx=20, pady=(0, 14))
        for index, (title, value) in enumerate((("Akku", battery), ("Firmware", firmware), ("Hinweise", str(warning_count)))):
            box = tk.Frame(facts, bg=palette["surface2"], padx=10, pady=9)
            box.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 5, 0))
            facts.columnconfigure(index, weight=1, uniform="inspector-facts-v220")
            tk.Label(box, text=title, bg=palette["surface2"], fg=palette["muted"], font=("Segoe UI Variable", 8)).pack(anchor="w")
            tk.Label(box, text=value, bg=palette["surface2"], fg=palette["fg"], font=("Segoe UI Variable", 11, "bold")).pack(anchor="w", pady=(2, 0))

        tk.Label(host, text="Schnellaktionen", bg=palette["surface"], fg=palette["muted"], font=("Segoe UI Variable", 9, "bold")).pack(anchor="w", padx=20)
        actions = tk.Frame(host, bg=palette["surface"])
        actions.pack(fill="x", padx=20, pady=(7, 15))
        self._mac_button_v220(actions, "Log laden", lambda: self.batch_log_download_v2133([node_id]), primary=True).grid(row=0, column=0, sticky="ew", padx=(0, 5), pady=(0, 5))
        self._mac_button_v220(actions, "Live", lambda: (self._clear_other_selection_v2133(node_id), self.batch_live_v2133())).grid(row=0, column=1, sticky="ew", pady=(0, 5))
        self._mac_button_v220(actions, "OTA", lambda: self._single_node_ota_v220(node_id)).grid(row=1, column=0, sticky="ew", padx=(0, 5))
        self._mac_button_v220(actions, "Bearbeiten", lambda: self.open_node_actions_v2132(node_id)).grid(row=1, column=1, sticky="ew")
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)

        tk.Label(host, text="BLE & Log-Automatik", bg=palette["surface"], fg=palette["muted"], font=("Segoe UI Variable", 9, "bold")).pack(anchor="w", padx=20)
        auto = tk.Frame(host, bg=palette["surface2"], padx=12, pady=10)
        auto.pack(fill="x", padx=20, pady=(7, 15))
        sync_state = str(getattr(self, "node_sync_state_v2132", {}).get(node_id) or "")
        rows = [
            ("BLE", "Erkannt" if ble_state else "Nicht in Reichweite", palette["green"] if ble_state else palette["muted"]),
            ("Log", "Fällig" if due else "Aktuell", palette["orange"] if due else palette["green"]),
            ("Status", sync_state or "Bereit", palette["blue"]),
        ]
        for index, (title, value, color) in enumerate(rows):
            row = tk.Frame(auto, bg=palette["surface2"])
            row.pack(fill="x", pady=3)
            tk.Label(row, text=title, bg=palette["surface2"], fg=palette["muted"], font=("Segoe UI Variable", 9)).pack(side="left")
            tk.Label(row, text=value, bg=palette["surface2"], fg=color, font=("Segoe UI Variable", 9, "bold"), anchor="e", wraplength=190).pack(side="right", fill="x", expand=True)

        tk.Label(host, text="Weitere Bereiche", bg=palette["surface"], fg=palette["muted"], font=("Segoe UI Variable", 9, "bold")).pack(anchor="w", padx=20)
        links = tk.Frame(host, bg=palette["surface"])
        links.pack(fill="x", padx=20, pady=(7, 10))
        for label, target in (("Node-Details", "overview"), ("Log-Historie", "history"), ("Grunddaten / Service", "service"), ("Firmware", "firmware")):
            self._mac_button_v220(links, label, lambda value=target: self.open_node_from_tile_v2132(node_id, value), compact=True).pack(fill="x", pady=2)
        self._mac_button_v220(host, "Node entfernen …", lambda: self._delete_single_node_v220(node_id), danger=True, compact=True).pack(fill="x", padx=20, pady=(6, 18))

    def _rebuild_mac_chrome_colors_v220(self) -> None:
        palette = self._mac_palette_v220()
        self.configure(bg=palette["bg"])
        for widget_name in ("mac_topbar_v220", "mac_sidebar_v220", "mac_dashboard_header_v220", "mac_batchbar_v220"):
            widget = getattr(self, widget_name, None)
            if widget is not None:
                try:
                    widget.configure(bg=palette["sidebar"] if widget_name == "mac_sidebar_v220" else palette["bg"])
                except tk.TclError:
                    pass
        self._set_mac_nav_active_v220(getattr(self, "mac_active_page_v220", "all_nodes_tab"))
        self._refresh_filter_segments_v220()
        self.render_node_tiles_v2132()
        self.render_mac_inspector_v220()

    def toggle_mac_appearance_v220(self) -> None:
        self.mac_dark_v220.set(not self.mac_dark_v220.get())
        self.theme.set("Modern Pro" if self.mac_dark_v220.get() else "iOS")
        self.apply_theme()
        self._rebuild_mac_chrome_colors_v220()

    def _install_mac_shell_v220(self) -> None:
        if getattr(self, "mac_shell_installed_v220", False):
            return
        self.mac_shell_installed_v220 = True
        self.mac_dark_v220 = tk.BooleanVar(value=False)
        self.mac_activity_events_v220 = []
        self.mac_inspector_node_v220 = ""
        palette = self._mac_palette_v220()
        self.configure(bg=palette["bg"])
        self.root.configure(style="MacRootV220.TFrame")
        self.style.configure("MacRootV220.TFrame", background=palette["bg"])

        # Keep all legacy widgets alive for compatibility, but remove the old chrome.
        for child in list(self.root.winfo_children()):
            if child is not getattr(self, "main_pane_v220", None):
                child.pack_forget()
        self.main_pane_v220.pack_forget()
        with contextlib.suppress(tk.TclError):
            self.main_pane_v220.forget(self.legacy_controls_v220)

        top = tk.Frame(self.root, bg=palette["bg"], height=66)
        self.mac_topbar_v220 = top
        top.pack(fill="x", padx=18, pady=(12, 8))
        left = tk.Frame(top, bg=palette["bg"])
        left.pack(side="left")
        tk.Label(left, text="Jarnsen Node Manager", bg=palette["bg"], fg=palette["fg"], font=("Segoe UI Variable Display", 18, "bold")).pack(anchor="w")
        tk.Label(left, text="Service Tool  ·  v2.2.0", bg=palette["bg"], fg=palette["muted"], font=("Segoe UI Variable", 9)).pack(anchor="w")

        center = tk.Frame(top, bg=palette["bg"])
        center.pack(side="left", fill="x", expand=True, padx=35)
        search_shell = tk.Frame(center, bg=palette["surface"], highlightbackground=palette["line"], highlightthickness=1)
        search_shell.pack(fill="x", pady=7)
        tk.Label(search_shell, text="⌕", bg=palette["surface"], fg=palette["muted"], font=("Segoe UI Symbol", 14)).pack(side="left", padx=(12, 5))
        search = tk.Entry(search_shell, textvariable=self.node_search_var_v2133, bg=palette["surface"], fg=palette["fg"], insertbackground=palette["fg"], relief="flat", bd=0, highlightthickness=0, font=("Segoe UI Variable", 10))
        search.pack(side="left", fill="x", expand=True, ipady=9)
        tk.Label(search_shell, text="Strg K", bg=palette["surface2"], fg=palette["muted"], padx=7, pady=3, font=("Segoe UI Variable", 8)).pack(side="right", padx=8)
        self.bind_all("<Control-k>", lambda _event: (search.focus_set(), search.select_range(0, "end")), add="+")

        right = tk.Frame(top, bg=palette["bg"])
        right.pack(side="right")
        self._mac_button_v220(right, "BLE prüfen", lambda: self.auto_ble_refresh_v2132(False), primary=True, compact=True).pack(side="left", padx=(0, 6), pady=8)
        self._mac_button_v220(right, "Aktivität", self._show_mac_activity_v220, compact=True).pack(side="left", padx=(0, 6), pady=8)
        count_shell = tk.Frame(right, bg=palette["surface2"], padx=7, pady=5)
        count_shell.pack(side="left", padx=(0, 6), pady=8)
        tk.Label(count_shell, text="●", bg=palette["surface2"], fg=palette["green"], font=("Segoe UI Variable", 8)).pack(side="left")
        self.mac_activity_count_v220 = tk.Label(count_shell, text="0", bg=palette["surface2"], fg=palette["fg"], font=("Segoe UI Variable", 9, "bold"))
        self.mac_activity_count_v220.pack(side="left", padx=(4, 0))
        self._mac_button_v220(right, "◐", self.toggle_mac_appearance_v220, compact=True).pack(side="left", pady=8)

        sidebar = tk.Frame(self.main_pane_v220, bg=palette["sidebar"], width=190)
        sidebar.pack_propagate(False)
        self.mac_sidebar_v220 = sidebar
        self.main_pane_v220.insert(0, sidebar, weight=0)
        brand = tk.Frame(sidebar, bg=palette["sidebar"])
        brand.pack(fill="x", padx=14, pady=(18, 12))
        tk.Label(brand, text="NODE", bg=palette["sidebar"], fg=palette["fg"], font=("Segoe UI Variable Display", 14, "bold")).pack(anchor="w")
        tk.Label(brand, text="MANAGEMENT", bg=palette["sidebar"], fg=palette["muted"], font=("Segoe UI Variable", 8, "bold")).pack(anchor="w")
        self.mac_nav_buttons_v220 = {}
        navigation = [
            ("Übersicht", "all_nodes_tab"),
            ("Node-Details", "overview_tab"),
            ("Logs & Verlauf", "history_tab"),
            ("Firmware", self._candidate_page_v220("firmware_tab", "service_tab", "overview_tab")),
            ("Karte", "track_tab"),
            ("Live", "live_tab"),
            ("Profile & Service", self._candidate_page_v220("service_tab", "config_tab", "overview_tab")),
            ("Diagnose", self._candidate_page_v220("diagnosis_tab", "diagnose_tab", "details_tab")),
            ("Einstellungen", self._candidate_page_v220("settings_tab", "service_tab", "details_tab")),
        ]
        for label, attr in navigation:
            button = tk.Button(sidebar, text=label, command=lambda value=attr, caption=label: self._select_page_v220(value, caption), bg=palette["sidebar"], fg=palette["fg"], activebackground=palette["selection"], activeforeground=palette["blue"], relief="flat", bd=0, highlightthickness=0, anchor="w", cursor="hand2", padx=14, pady=9, font=("Segoe UI Variable", 10))
            button.pack(fill="x", padx=8, pady=1)
            self.mac_nav_buttons_v220[attr] = button
        tk.Frame(sidebar, bg=palette["sidebar"]).pack(fill="both", expand=True)
        connection = tk.Frame(sidebar, bg=palette["surface"], highlightbackground=palette["line"], highlightthickness=1, padx=11, pady=10)
        connection.pack(fill="x", padx=10, pady=(0, 12))
        tk.Label(connection, text="Verbindung", bg=palette["surface"], fg=palette["muted"], font=("Segoe UI Variable", 8, "bold")).pack(anchor="w")
        self.mac_connection_label_v220 = tk.Label(connection, text="BLE-Automatik aktiv", bg=palette["surface"], fg=palette["green"], font=("Segoe UI Variable", 9, "bold"))
        self.mac_connection_label_v220.pack(anchor="w", pady=(3, 0))

        self.main_pane_v220.pack(fill="both", expand=True, padx=(18, 18), pady=(0, 14))
        self.style.layout("Mac.Hidden.TNotebook", [("Notebook.client", {"sticky": "nswe"})])
        self.style.layout("Mac.Hidden.TNotebook.Tab", [])
        self.notebook.configure(style="Mac.Hidden.TNotebook")

        # Rebuild the first page as a modern macOS-like board with a persistent inspector.
        for child in list(self.all_nodes_tab.winfo_children()):
            if child is not self.node_tiles_body_v2132:
                with contextlib.suppress(tk.TclError):
                    child.pack_forget()
                with contextlib.suppress(tk.TclError):
                    child.grid_remove()
        if hasattr(self, "dashboard_toolbar_v2133"):
            self.dashboard_toolbar_v2133.pack_forget()
        self.node_tiles_canvas_v2132.pack_forget()
        self.node_tiles_scrollbar_v2132.pack_forget()

        dash_header = tk.Frame(self.node_tiles_body_v2132, bg=palette["bg"])
        self.mac_dashboard_header_v220 = dash_header
        dash_header.pack(fill="x", padx=4, pady=(2, 10))
        title_area = tk.Frame(dash_header, bg=palette["bg"])
        title_area.pack(fill="x")
        tk.Label(title_area, text="Node-Übersicht", bg=palette["bg"], fg=palette["fg"], font=("Segoe UI Variable Display", 24, "bold")).pack(side="left")
        tk.Label(title_area, text="Alles Wichtige auf einen Blick. Details erst bei Bedarf.", bg=palette["bg"], fg=palette["muted"], font=("Segoe UI Variable", 10)).pack(side="left", padx=(14, 0), pady=(8, 0))
        self._mac_button_v220(title_area, "Alle auswählen", self._select_visible_nodes_v2133, compact=True).pack(side="right", padx=(5, 0))
        self._mac_button_v220(title_area, "Aktualisieren", self.refresh_all_nodes_overview, compact=True).pack(side="right")

        stats = tk.Frame(dash_header, bg=palette["bg"])
        stats.pack(fill="x", pady=(12, 9))
        for index, (caption, variable, tone) in enumerate((("Nodes", self.dashboard_visible_var_v2133, "blue"), ("BLE in Reichweite", self.dashboard_ble_var_v2133, "green"), ("Logs fällig", self.dashboard_due_var_v2133, "orange"), ("Aufmerksamkeit", self.dashboard_issue_var_v2133, "red"))):
            card = tk.Frame(stats, bg=palette["surface"], highlightbackground=palette["line"], highlightthickness=1, padx=13, pady=10)
            card.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 7, 0))
            stats.columnconfigure(index, weight=1, uniform="mac-stats-v220")
            tk.Label(card, text=caption, bg=palette["surface"], fg=palette["muted"], font=("Segoe UI Variable", 9)).pack(anchor="w")
            fg = palette.get(tone, palette["fg"])
            tk.Label(card, textvariable=variable, bg=palette["surface"], fg=fg, font=("Segoe UI Variable Display", 19, "bold")).pack(anchor="w", pady=(2, 0))

        segments = tk.Frame(dash_header, bg=palette["surface2"], padx=4, pady=4)
        segments.pack(anchor="w")
        self.mac_filter_buttons_v220 = {}
        for value, label in (("Alle", "Alle"), ("BLE sichtbar", "In Reichweite"), ("Log fällig", "Logs fällig"), ("Updates", "Updates"), ("Hinweise", "Warnungen")):
            button = tk.Button(segments, text=label, command=lambda selected=value: self._set_filter_v220(selected), relief="flat", bd=0, highlightthickness=0, cursor="hand2", padx=12, pady=6, font=("Segoe UI Variable", 9, "bold"))
            button.pack(side="left", padx=1)
            self.mac_filter_buttons_v220[value] = button
        self._refresh_filter_segments_v220()

        batchbar = tk.Frame(self.node_tiles_body_v2132, bg=palette["bg"])
        self.mac_batchbar_v220 = batchbar
        batchbar.pack(fill="x", padx=4, pady=(0, 8))
        self.mac_batch_label_v220 = tk.Label(batchbar, text="0 ausgewählt", bg=palette["bg"], fg=palette["muted"], font=("Segoe UI Variable", 9, "bold"))
        self.mac_batch_label_v220.pack(side="left")
        self._mac_button_v220(batchbar, "Logs laden", self.batch_log_download_v2133, primary=True, compact=True).pack(side="left", padx=(10, 4))
        self._mac_button_v220(batchbar, "OTA", self.batch_ota_v2133, compact=True).pack(side="left", padx=2)
        self._mac_button_v220(batchbar, "Wecken", self.batch_wake_v2133, compact=True).pack(side="left", padx=2)
        self._mac_button_v220(batchbar, "Auswahl leeren", self._clear_node_selection_v2133, compact=True).pack(side="right")

        inspector = tk.Frame(self.node_tiles_body_v2132, bg=palette["surface"], width=330, highlightbackground=palette["line"], highlightthickness=1)
        inspector.pack_propagate(False)
        self.mac_inspector_v220 = inspector
        inspector.pack(side="right", fill="y", padx=(10, 0), pady=(0, 2))
        self.node_tiles_scrollbar_v2132.pack(side="right", fill="y")
        self.node_tiles_canvas_v2132.pack(side="left", fill="both", expand=True)
        self.node_tiles_canvas_v2132.configure(bg=palette["bg"], highlightthickness=0)
        try:
            self.node_tiles_host_v2132.configure(style="MacRootV220.TFrame")
        except tk.TclError:
            pass
        self.render_mac_inspector_v220()
        self._set_mac_nav_active_v220("all_nodes_tab")
        self.after(80, self.render_node_tiles_v2132)

'''
    source = source[:render_start] + helpers.rstrip() + "\n\n" + source[render_start:]

    render_tiles = r'''    def render_node_tiles_v2132(self) -> None:
        host = getattr(self, "node_tiles_host_v2132", None)
        if host is None:
            return
        palette = self._mac_palette_v220() if hasattr(self, "_mac_palette_v220") else THEMES.get(self.theme.get(), THEMES["iOS"])
        try:
            host.configure(style="MacRootV220.TFrame")
        except tk.TclError:
            pass
        for child in host.winfo_children():
            child.destroy()
        try:
            rows = self.repository.list_nodes(self.show_archived_var.get())
        except Exception:
            rows = []
        rows = self._filter_sort_rows_v2133(rows)
        self.visible_node_ids_v2133 = [normalize_node_id(str(row["node_id"] or "")) for row in rows]
        width = max(620, int(getattr(self, "node_tiles_canvas_v2132").winfo_width() or 620))
        columns = 3 if width >= 1120 else (2 if width >= 720 else 1)
        states = getattr(self, "node_sync_state_v2132", {})
        selections = getattr(self, "node_selection_v2133", {})
        if not isinstance(states, dict): states = {}
        if not isinstance(selections, dict):
            selections = {}
            self.node_selection_v2133 = selections
        for column in range(columns):
            host.columnconfigure(column, weight=1, uniform="mac-node-card-v220")

        ble_visible = due_count = issue_count = update_count = 0
        for index, row in enumerate(rows):
            node_id = normalize_node_id(str(row["node_id"] or ""))
            latest = self.repository.latest_log(node_id)
            metrics = latest.get("metrics", {}) if latest else {}
            if not isinstance(metrics, dict): metrics = {}
            device_key = str(row["device"] or metrics.get("device") or "")
            device = "Tracker" if device_key == "HELTEC_TRACKER_V1.1" else ("V3" if device_key == "HELTEC_V3_REPEATER" else DEVICE_NAMES.get(device_key, device_key or "--"))
            name = str(metrics.get("long_name") or row["long_name"] or node_id)
            short_name = str(metrics.get("short_name") or row["short_name"] or "")
            battery_value = metrics.get("battery_pct")
            battery = f"{float(battery_value):.0f} %" if isinstance(battery_value, (int, float)) else "--"
            firmware = str(latest.get("firmware") or "--") if latest else "--"
            build = str(latest.get("build") or "") if latest else ""
            github_state, _github_detail, github_level = self.firmware_state(device_key, build)
            warning_count = int(metrics.get("warning_count") or 0)
            low_battery = isinstance(battery_value, (int, float)) and float(battery_value) <= 20
            ble_state = self.repository.ble_status_for_node_v2132(node_id)
            due = self._node_is_due_v2133(node_id)
            update = github_level == "warning" or "Update" in github_state
            if ble_state: ble_visible += 1
            if due: due_count += 1
            if warning_count or low_battery: issue_count += 1
            if update: update_count += 1
            if node_id not in selections:
                selections[node_id] = tk.BooleanVar(value=False)
            selected = bool(selections[node_id].get())
            attention = warning_count or low_battery
            border = palette["blue"] if selected else (palette["red"] if attention else (palette["orange"] if update or due else palette["line"]))
            card_bg = palette["selection"] if selected and palette["bg"] == "#F5F5F7" else palette["surface"]
            card = tk.Frame(host, bg=card_bg, highlightbackground=border, highlightthickness=2 if selected else 1, bd=0, padx=14, pady=12)
            card.grid(row=index // columns, column=index % columns, sticky="nsew", padx=6, pady=6)

            header = tk.Frame(card, bg=card_bg)
            header.pack(fill="x")
            select_btn = tk.Button(header, text="●" if selected else "○", command=lambda value=node_id: self._toggle_node_selection_v220(value), bg=card_bg, fg=palette["blue"] if selected else palette["muted"], activebackground=card_bg, activeforeground=palette["blue"], relief="flat", bd=0, highlightthickness=0, cursor="hand2", font=("Segoe UI Symbol", 13))
            select_btn.pack(side="left", padx=(0, 7))
            title = tk.Frame(header, bg=card_bg)
            title.pack(side="left", fill="x", expand=True)
            name_label = tk.Label(title, text=name, bg=card_bg, fg=palette["fg"], font=("Segoe UI Variable Display", 12, "bold"), anchor="w", wraplength=max(190, int(width / columns) - 150))
            name_label.pack(fill="x")
            tk.Label(title, text=f"{short_name or '—'}   ·   {node_id}", bg=card_bg, fg=palette["muted"], font=("Segoe UI Variable", 8), anchor="w").pack(fill="x", pady=(2, 0))
            more = tk.Button(header, text="•••", bg=card_bg, fg=palette["muted"], activebackground=palette["surface2"], activeforeground=palette["fg"], relief="flat", bd=0, highlightthickness=0, cursor="hand2", font=("Segoe UI Variable", 10, "bold"))
            more.configure(command=lambda value=node_id, button=more: self._node_menu_v220(value, button))
            more.pack(side="right", padx=(6, 0))

            chips = tk.Frame(card, bg=card_bg)
            chips.pack(fill="x", pady=(10, 9))
            self._mac_label_chip_v220(chips, device, "purple" if device == "V3" else "blue").pack(side="left", padx=(0, 4))
            self._mac_label_chip_v220(chips, "BLE" if ble_state else "Offline", "green" if ble_state else "neutral").pack(side="left", padx=(0, 4))
            if due: self._mac_label_chip_v220(chips, "Log fällig", "orange").pack(side="left", padx=(0, 4))
            if update: self._mac_label_chip_v220(chips, "Update", "purple").pack(side="left", padx=(0, 4))
            if attention: self._mac_label_chip_v220(chips, "Hinweis", "red").pack(side="left")

            facts = tk.Frame(card, bg=card_bg)
            facts.pack(fill="x", pady=(1, 8))
            fact_values = (("Akku", battery), ("Letzter Log", self._format_v2132_time(latest.get("captured_at") if latest else "")), ("Firmware", firmware))
            for col, (caption, value) in enumerate(fact_values):
                fact = tk.Frame(facts, bg=card_bg)
                fact.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 8, 0))
                facts.columnconfigure(col, weight=1, uniform="mac-card-facts-v220")
                tk.Label(fact, text=caption, bg=card_bg, fg=palette["muted"], font=("Segoe UI Variable", 8)).pack(anchor="w")
                tk.Label(fact, text=value, bg=card_bg, fg=palette["fg"], font=("Segoe UI Variable", 9, "bold"), anchor="w", wraplength=125).pack(anchor="w", pady=(2, 0))

            sync_text = str(states.get(node_id) or "")
            if not sync_text:
                sync_text = "Automatik bereit" if ble_state else "Nicht in Reichweite"
            tk.Label(card, text=sync_text, bg=card_bg, fg=palette["green"] if "Aktuell" in sync_text or "synchron" in sync_text.lower() else palette["muted"], font=("Segoe UI Variable", 8), anchor="w", wraplength=max(220, int(width / columns) - 55)).pack(fill="x", pady=(2, 10))

            actions = tk.Frame(card, bg=card_bg)
            actions.pack(fill="x")
            self._mac_button_v220(actions, "Öffnen", lambda value=node_id: self.show_mac_inspector_v220(value), primary=True, compact=True).pack(side="left", fill="x", expand=True)
            self._mac_button_v220(actions, "Log", lambda value=node_id: self.batch_log_download_v2133([value]), compact=True).pack(side="left", padx=(5, 0))
            self._mac_button_v220(actions, "Live", lambda value=node_id: (self._clear_other_selection_v2133(value), self.batch_live_v2133()), compact=True).pack(side="left", padx=(5, 0))
            self._mac_button_v220(actions, "OTA", lambda value=node_id: self._single_node_ota_v220(value), compact=True).pack(side="left", padx=(5, 0))

        if hasattr(self, "dashboard_visible_var_v2133"):
            self.dashboard_visible_var_v2133.set(str(len(rows)))
            self.dashboard_ble_var_v2133.set(str(ble_visible))
            self.dashboard_due_var_v2133.set(str(due_count))
            self.dashboard_issue_var_v2133.set(str(issue_count + update_count))
        if not rows:
            empty = tk.Frame(host, bg=palette["surface"], padx=24, pady=28)
            empty.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
            tk.Label(empty, text="Keine Nodes gefunden", bg=palette["surface"], fg=palette["fg"], font=("Segoe UI Variable Display", 15, "bold")).pack(anchor="w")
            tk.Label(empty, text="Suche oder Filter zurücksetzen – oder BLE erneut prüfen.", bg=palette["surface"], fg=palette["muted"], font=("Segoe UI Variable", 10)).pack(anchor="w", pady=(3, 0))
        canvas = getattr(self, "node_tiles_canvas_v2132", None)
        if canvas is not None:
            self.after_idle(lambda: canvas.configure(scrollregion=canvas.bbox("all")))
        self._update_batch_bar_v2133()
        if getattr(self, "mac_inspector_node_v220", ""):
            self.render_mac_inspector_v220()
'''
    source = replace_method(source, "render_node_tiles_v2132", render_tiles)

    edit_sheet = r'''    def open_node_actions_v2132(self, node_id: str) -> None:
        normalized = normalize_node_id(node_id)
        if not normalized:
            return
        latest = self.repository.latest_log(normalized)
        metrics = latest.get("metrics", {}) if latest else {}
        if not isinstance(metrics, dict): metrics = {}
        name = str(metrics.get("long_name") or normalized)
        palette = self._mac_palette_v220()
        win = tk.Toplevel(self)
        win.title(f"{name} · Aktionen")
        win.transient(self)
        win.geometry("470x560")
        win.minsize(430, 500)
        win.configure(bg=palette["bg"])
        body = tk.Frame(win, bg=palette["bg"], padx=24, pady=22)
        body.pack(fill="both", expand=True)
        tk.Label(body, text=name, bg=palette["bg"], fg=palette["fg"], font=("Segoe UI Variable Display", 20, "bold")).pack(anchor="w")
        tk.Label(body, text=f"{normalized}  ·  Aktionen & Verwaltung", bg=palette["bg"], fg=palette["muted"], font=("Segoe UI Variable", 10)).pack(anchor="w", pady=(3, 18))
        section = tk.Frame(body, bg=palette["surface"], highlightbackground=palette["line"], highlightthickness=1, padx=12, pady=12)
        section.pack(fill="x")
        for label, target in (("Node-Details", "overview"), ("Grunddaten / Service", "service"), ("Firmware", "firmware"), ("Log-Historie", "history")):
            self._mac_button_v220(section, label, lambda value=target: (self.open_node_from_tile_v2132(normalized, value), win.destroy())).pack(fill="x", pady=3)
        automation = tk.Frame(body, bg=palette["surface"], highlightbackground=palette["line"], highlightthickness=1, padx=12, pady=12)
        automation.pack(fill="x", pady=(12, 0))
        tk.Label(automation, text="Schnellaktionen", bg=palette["surface"], fg=palette["muted"], font=("Segoe UI Variable", 9, "bold")).pack(anchor="w", pady=(0, 6))
        self._mac_button_v220(automation, "Log jetzt laden", lambda: (self.batch_log_download_v2133([normalized]), win.destroy()), primary=True).pack(fill="x", pady=3)
        self._mac_button_v220(automation, "OTA Update", lambda: (self._single_node_ota_v220(normalized), win.destroy())).pack(fill="x", pady=3)
        danger = tk.Frame(body, bg=palette["surface"], highlightbackground=palette["line"], highlightthickness=1, padx=12, pady=12)
        danger.pack(fill="x", pady=(12, 0))
        tk.Label(danger, text="Verwaltung", bg=palette["surface"], fg=palette["muted"], font=("Segoe UI Variable", 9, "bold")).pack(anchor="w", pady=(0, 6))
        self._mac_button_v220(danger, "Node entfernen …", lambda: (self._delete_single_node_v220(normalized), win.destroy()), danger=True).pack(fill="x")
        self._mac_button_v220(body, "Schließen", win.destroy).pack(fill="x", pady=(14, 0))
'''
    source = replace_method(source, "open_node_actions_v2132", edit_sheet)

    # Install the new shell after all legacy workflow pages exist.
    workflow_start, workflow_end = method_span(source, "_install_workflow_ui")
    workflow = source[workflow_start:workflow_end]
    if "_install_mac_shell_v220" not in workflow:
        workflow = workflow.rstrip() + "\n        self.after(420, self._install_mac_shell_v220)\n"
        source = source[:workflow_start] + workflow + source[workflow_end:]

    # Keep the new selection bar in sync with the existing multi-select logic.
    update_start, update_end = method_span(source, "_update_batch_bar_v2133")
    update_method = source[update_start:update_end]
    if "mac_batch_label_v220" not in update_method:
        update_method = update_method.rstrip() + r'''
        if hasattr(self, "mac_batch_label_v220"):
            self.mac_batch_label_v220.configure(text=f"{len(selected)} ausgewählt")
''' + "\n"
        source = source[:update_start] + update_method + source[update_end:]

    progress_start, progress_end = method_span(source, "set_transfer_progress")
    progress = source[progress_start:progress_end]
    if "mac_connection_label_v220" not in progress:
        progress = progress.rstrip() + r'''
        if hasattr(self, "mac_connection_label_v220"):
            suffix = "" if indeterminate else f" · {max(0, min(100, int(value or 0)))} %"
            self.mac_connection_label_v220.configure(text=f"{text}{suffix}")
''' + "\n"
        source = source[:progress_start] + progress + source[progress_end:]

    pump_start, pump_end = method_span(source, "_pump_events")
    pump = source[pump_start:pump_end]
    trace_anchor = '                elif kind == "auto_ble_trace_v2133":\n'
    if "_append_activity_v220" not in pump and trace_anchor in pump:
        trace_block = (
            '                elif kind == "auto_ble_trace_v2133":\n'
            '                    self._append_activity_v220(str(value))\n'
        )
        pump = pump.replace(trace_anchor, trace_block, 1)
        source = source[:pump_start] + pump + source[pump_end:]

    theme_start, theme_end = method_span(source, "apply_theme")
    theme = source[theme_start:theme_end]
    if "macOS shell styles v220" not in theme:
        theme = theme.rstrip() + r'''
        # macOS shell styles v220
        if hasattr(self, "mac_dark_v220"):
            mac = self._mac_palette_v220()
            self.style.configure("MacRootV220.TFrame", background=mac["bg"])
            self.style.configure("Mac.Horizontal.TProgressbar", troughcolor=mac["surface2"], background=mac["blue"], borderwidth=0)
''' + "\n"
        source = source[:theme_start] + theme + source[theme_end:]

    source += "\n# PATCH_V220_MAC_DESKTOP_SHELL\n"
    required = (
        'APP_VERSION = "2.2.0"',
        'def _install_mac_shell_v220',
        'def render_mac_inspector_v220',
        'def toggle_mac_appearance_v220',
        'PATCH_V220_MAC_DESKTOP_SHELL',
    )
    missing = [marker for marker in required if marker not in source]
    if missing:
        raise SystemExit("v2.2.0 validation failed: " + ", ".join(missing))
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v220.py <source.py>")
    path = Path(sys.argv[1])
    path.write_text(patch(path.read_text(encoding="utf-8")), encoding="utf-8")
    print("Applied Service Tool v2.2.0: macOS/iOS-inspired desktop shell")


if __name__ == "__main__":
    main()
