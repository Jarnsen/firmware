"""v2.2.1: true rounded macOS/iOS-style desktop UI using CustomTkinter surfaces.

The v2.2.0 shell improved information architecture but still rendered most visible
controls with classic Tk rectangles.  This patch keeps the proven device/service
logic and replaces the visible shell, cards, inspector, activity window and action
sheets with genuinely rounded CustomTkinter canvas widgets.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "2.2.1"


def method_span(text: str, name: str) -> tuple[int, int]:
    normal = text.find(f"    def {name}(")
    asynchronous = text.find(f"    async def {name}(")
    starts = [value for value in (normal, asynchronous) if value >= 0]
    if not starts:
        raise SystemExit(f"v2.2.1 method {name} not found")
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


def insert_before_method(text: str, name: str, code: str) -> str:
    start, _ = method_span(text, name)
    return text[:start] + code.rstrip() + "\n\n" + text[start:]


def patch(source: str) -> str:
    if "PATCH_V221_LIQUID_ROUNDED_UI" in source:
        return source

    source = re.sub(r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{APP_VERSION}"', source, count=1)
    source = source.replace('APP_VERSION != "2.2.0"', 'APP_VERSION != "2.2.1"')
    source = source.replace("App-Version ist nicht v2.2.0", "App-Version ist nicht v2.2.1")

    import_anchor = "from tkinter import messagebox, ttk\n"
    if "import customtkinter as ctk" not in source:
        if import_anchor not in source:
            raise SystemExit("v2.2.1 tkinter import anchor missing")
        source = source.replace(import_anchor, import_anchor + "\nimport customtkinter as ctk\n", 1)

    helpers = r'''    # PATCH_V221_LIQUID_ROUNDED_UI
    def _liquid_palette_v221(self) -> dict[str, object]:
        return {
            "bg": ("#F4F6FA", "#0E1116"),
            "sidebar": ("#EDF3FA", "#151B23"),
            "surface": ("#FFFFFF", "#171C23"),
            "surface2": ("#F1F4F9", "#20262F"),
            "surface3": ("#E9EEF6", "#28303B"),
            "fg": ("#15171A", "#F5F7FA"),
            "muted": ("#6C7480", "#9EA7B3"),
            "line": ("#E1E6EE", "#303945"),
            "blue": ("#0A84FF", "#409CFF"),
            "blue_soft": ("#EAF4FF", "#17324E"),
            "green": ("#22B95B", "#32D36B"),
            "green_soft": ("#E9F8EF", "#173A27"),
            "orange": ("#F28A00", "#FFA21A"),
            "orange_soft": ("#FFF3E2", "#43301A"),
            "red": ("#F04438", "#FF5A52"),
            "red_soft": ("#FFF0EF", "#432321"),
            "purple": ("#9B51E0", "#BF73FF"),
            "purple_soft": ("#F5EDFF", "#36234A"),
        }

    def _liquid_now_v221(self, value: object) -> object:
        if isinstance(value, tuple) and len(value) == 2:
            return value[1] if bool(getattr(self, "mac_dark_v220", None) and self.mac_dark_v220.get()) else value[0]
        return value

    def _liquid_font_v221(self, size: int, weight: str = "normal") -> ctk.CTkFont:
        return ctk.CTkFont(family="Segoe UI Variable", size=size, weight=weight)

    def _liquid_chip_v221(self, parent: object, text: str, tone: str = "neutral") -> ctk.CTkLabel:
        p = self._liquid_palette_v221()
        mapping = {
            "blue": (p["blue_soft"], p["blue"]),
            "green": (p["green_soft"], p["green"]),
            "orange": (p["orange_soft"], p["orange"]),
            "red": (p["red_soft"], p["red"]),
            "purple": (p["purple_soft"], p["purple"]),
            "neutral": (p["surface2"], p["muted"]),
        }
        bg, fg = mapping.get(tone, mapping["neutral"])
        return ctk.CTkLabel(
            parent,
            text=text,
            fg_color=bg,
            text_color=fg,
            corner_radius=11,
            height=23,
            padx=9,
            font=self._liquid_font_v221(11, "bold"),
        )

    def _liquid_button_v221(
        self,
        parent: object,
        text: str,
        command: object,
        *,
        primary: bool = False,
        danger: bool = False,
        compact: bool = False,
        width: int = 0,
    ) -> ctk.CTkButton:
        p = self._liquid_palette_v221()
        if danger:
            fg, text_color, hover = p["red_soft"], p["red"], p["surface3"]
        elif primary:
            fg, text_color, hover = p["blue"], ("#FFFFFF", "#FFFFFF"), ("#006DE0", "#63AEFF")
        else:
            fg, text_color, hover = p["surface2"], p["blue"], p["surface3"]
        kwargs: dict[str, object] = {}
        if width:
            kwargs["width"] = width
        return ctk.CTkButton(
            parent,
            text=text,
            command=command,
            fg_color=fg,
            text_color=text_color,
            hover_color=hover,
            corner_radius=13 if compact else 15,
            height=32 if compact else 39,
            border_width=0,
            font=self._liquid_font_v221(12, "bold"),
            **kwargs,
        )

    def _liquid_metric_card_v221(self, parent: object, title: str, variable: tk.Variable, tone: str, icon: str) -> ctk.CTkFrame:
        p = self._liquid_palette_v221()
        card = ctk.CTkFrame(parent, fg_color=p["surface"], corner_radius=21, border_width=1, border_color=p["line"])
        card.grid_columnconfigure(1, weight=1)
        accent = p.get(f"{tone}_soft", p["surface2"])
        fg = p.get(tone, p["blue"])
        bubble = ctk.CTkLabel(card, text=icon, width=42, height=42, corner_radius=14, fg_color=accent, text_color=fg, font=self._liquid_font_v221(18, "bold"))
        bubble.grid(row=0, column=0, rowspan=2, padx=(15, 11), pady=15)
        ctk.CTkLabel(card, text=title, text_color=p["muted"], font=self._liquid_font_v221(11), anchor="w").grid(row=0, column=1, sticky="sw", padx=(0, 14), pady=(13, 0))
        ctk.CTkLabel(card, textvariable=variable, text_color=p["fg"], font=self._liquid_font_v221(24, "bold"), anchor="w").grid(row=1, column=1, sticky="nw", padx=(0, 14), pady=(0, 13))
        return card

    def _liquid_apply_legacy_styles_v221(self) -> None:
        p = self._liquid_palette_v221()
        bg = self._liquid_now_v221(p["bg"])
        surface = self._liquid_now_v221(p["surface"])
        surface2 = self._liquid_now_v221(p["surface2"])
        fg = self._liquid_now_v221(p["fg"])
        muted = self._liquid_now_v221(p["muted"])
        blue = self._liquid_now_v221(p["blue"])
        line = self._liquid_now_v221(p["line"])
        with contextlib.suppress(tk.TclError):
            self.style.theme_use("clam")
        self.style.configure("TFrame", background=bg)
        self.style.configure("TLabel", background=bg, foreground=fg, font=("Segoe UI Variable", 10))
        self.style.configure("Subtitle.TLabel", background=bg, foreground=muted, font=("Segoe UI Variable", 9))
        self.style.configure("Section.TLabel", background=bg, foreground=fg, font=("Segoe UI Variable", 12, "bold"))
        self.style.configure("TLabelframe", background=surface, borderwidth=0, relief="flat", padding=12)
        self.style.configure("TLabelframe.Label", background=surface, foreground=fg, font=("Segoe UI Variable", 10, "bold"))
        self.style.configure("TButton", background=surface2, foreground=blue, borderwidth=0, relief="flat", padding=(13, 8), font=("Segoe UI Variable", 9, "bold"))
        self.style.map("TButton", background=[("active", surface2)], foreground=[("disabled", muted)])
        self.style.configure("Primary.TButton", background=blue, foreground="#FFFFFF", borderwidth=0, relief="flat", padding=(13, 8), font=("Segoe UI Variable", 9, "bold"))
        self.style.map("Primary.TButton", background=[("active", blue)], foreground=[("disabled", muted)])
        self.style.configure("TEntry", fieldbackground=surface, foreground=fg, bordercolor=line, lightcolor=line, darkcolor=line, padding=7)
        self.style.configure("TCombobox", fieldbackground=surface, foreground=fg, background=surface2, bordercolor=line, lightcolor=line, darkcolor=line, padding=6)
        self.style.configure("Treeview", background=surface, fieldbackground=surface, foreground=fg, borderwidth=0, rowheight=32, font=("Segoe UI Variable", 9))
        self.style.configure("Treeview.Heading", background=surface2, foreground=muted, borderwidth=0, relief="flat", font=("Segoe UI Variable", 9, "bold"))
        self.style.map("Treeview", background=[("selected", self._liquid_now_v221(p["blue_soft"]))], foreground=[("selected", fg)])
        self.style.configure("TNotebook", background=bg, borderwidth=0)
        self.style.configure("Mac.Hidden.TNotebook", background=bg, borderwidth=0)
        self.style.configure("Horizontal.TProgressbar", background=blue, troughcolor=surface2, borderwidth=0)

    def _liquid_close_inspector_v221(self) -> None:
        self.mac_inspector_node_v220 = ""
        self.render_mac_inspector_v220()

    def _liquid_select_toggle_v221(self, node_id: str) -> None:
        selections = getattr(self, "node_selection_v2133", {})
        variable = selections.get(node_id)
        if variable is None:
            variable = tk.BooleanVar(value=False)
            selections[node_id] = variable
            self.node_selection_v2133 = selections
        variable.set(not bool(variable.get()))
        self._update_batch_bar_v2133()
        self.render_node_tiles_v2132()

    def _liquid_reflow_v221(self, _event: object | None = None) -> None:
        if getattr(self, "_liquid_reflow_pending_v221", None):
            with contextlib.suppress(Exception):
                self.after_cancel(self._liquid_reflow_pending_v221)
        self._liquid_reflow_pending_v221 = self.after(160, self.render_node_tiles_v2132)
'''
    source = insert_before_method(source, "_mac_button_v220", helpers)

    mac_button = r'''    def _mac_button_v220(
        self, parent: object, text: str, command: object,
        primary: bool = False, danger: bool = False, compact: bool = False,
    ) -> ctk.CTkButton:
        return self._liquid_button_v221(parent, text, command, primary=primary, danger=danger, compact=compact)
'''
    source = replace_method(source, "_mac_button_v220", mac_button)

    mac_chip = r'''    def _mac_label_chip_v220(self, parent: object, text: str, tone: str = "neutral") -> ctk.CTkLabel:
        return self._liquid_chip_v221(parent, text, tone)
'''
    source = replace_method(source, "_mac_label_chip_v220", mac_chip)

    refresh_filters = r'''    def _refresh_filter_segments_v220(self) -> None:
        p = self._liquid_palette_v221()
        selected = self.node_filter_var_v2133.get() if hasattr(self, "node_filter_var_v2133") else "Alle"
        for value, button in getattr(self, "mac_filter_buttons_v220", {}).items():
            active = value == selected
            with contextlib.suppress(Exception):
                button.configure(
                    fg_color=p["blue"] if active else "transparent",
                    text_color=("#FFFFFF", "#FFFFFF") if active else p["fg"],
                    hover_color=p["blue"] if active else p["surface3"],
                )
'''
    source = replace_method(source, "_refresh_filter_segments_v220", refresh_filters)

    nav_active = r'''    def _set_mac_nav_active_v220(self, page_attr: str) -> None:
        p = self._liquid_palette_v221()
        self.mac_active_page_v220 = page_attr
        for attr, button in getattr(self, "mac_nav_buttons_v220", {}).items():
            active = attr == page_attr
            with contextlib.suppress(Exception):
                button.configure(
                    fg_color=p["blue_soft"] if active else "transparent",
                    text_color=p["blue"] if active else p["fg"],
                    hover_color=p["surface3"],
                )
'''
    source = replace_method(source, "_set_mac_nav_active_v220", nav_active)

    activity = r'''    def _show_mac_activity_v220(self) -> None:
        panel = getattr(self, "mac_activity_window_v220", None)
        if panel is not None and panel.winfo_exists():
            panel.lift()
            return
        p = self._liquid_palette_v221()
        win = ctk.CTkToplevel(self)
        self.mac_activity_window_v220 = win
        win.title("Aktivität & Automatik")
        win.geometry("620x680")
        win.minsize(520, 520)
        win.transient(self)
        shell = ctk.CTkFrame(win, fg_color=p["bg"], corner_radius=0)
        shell.pack(fill="both", expand=True)
        panel = ctk.CTkFrame(shell, fg_color=p["surface"], corner_radius=26, border_width=1, border_color=p["line"])
        panel.pack(fill="both", expand=True, padx=18, pady=18)
        head = ctk.CTkFrame(panel, fg_color="transparent")
        head.pack(fill="x", padx=22, pady=(20, 12))
        ctk.CTkLabel(head, text="Aktivität & Automatik", text_color=p["fg"], font=self._liquid_font_v221(22, "bold")).pack(anchor="w")
        ctk.CTkLabel(head, text="BLE-Erkennung, Pairing, Log-Queue und Firmwareaktionen", text_color=p["muted"], font=self._liquid_font_v221(12)).pack(anchor="w", pady=(3, 0))
        box = ctk.CTkTextbox(panel, fg_color=p["surface2"], text_color=p["fg"], corner_radius=18, border_width=0, font=self._liquid_font_v221(12), wrap="word")
        self.mac_activity_text_v221 = box
        box.pack(fill="both", expand=True, padx=22, pady=(0, 14))
        for item in getattr(self, "mac_activity_events_v220", [])[-120:]:
            box.insert("end", f"{item}\n")
        box.configure(state="disabled")
        controls = ctk.CTkFrame(panel, fg_color="transparent")
        controls.pack(fill="x", padx=22, pady=(0, 20))
        self._liquid_button_v221(controls, "BLE jetzt prüfen", lambda: self.auto_ble_refresh_v2132(False), primary=True).pack(side="left")
        self._liquid_button_v221(controls, "Schließen", win.destroy).pack(side="right")
'''
    source = replace_method(source, "_show_mac_activity_v220", activity)

    append_activity = r'''    def _append_activity_v220(self, text: str) -> None:
        events = getattr(self, "mac_activity_events_v220", None)
        if not isinstance(events, list):
            events = []
            self.mac_activity_events_v220 = events
        events.append(str(text))
        if len(events) > 200:
            del events[:-200]
        if hasattr(self, "mac_activity_count_v220"):
            with contextlib.suppress(Exception):
                self.mac_activity_count_v220.configure(text=str(min(len(events), 99)))
        box = getattr(self, "mac_activity_text_v221", None)
        if box is not None and box.winfo_exists():
            with contextlib.suppress(Exception):
                box.configure(state="normal")
                box.insert("end", f"{text}\n")
                box.see("end")
                box.configure(state="disabled")
'''
    source = replace_method(source, "_append_activity_v220", append_activity)

    inspector = r'''    def render_mac_inspector_v220(self) -> None:
        host = getattr(self, "mac_inspector_v220", None)
        if host is None:
            return
        p = self._liquid_palette_v221()
        for child in host.winfo_children():
            child.destroy()
        node_id = normalize_node_id(getattr(self, "mac_inspector_node_v220", ""))
        if not node_id:
            empty = ctk.CTkFrame(host, fg_color="transparent")
            empty.pack(fill="both", expand=True, padx=18, pady=20)
            ctk.CTkLabel(empty, text="Node auswählen", text_color=p["fg"], font=self._liquid_font_v221(19, "bold")).pack(anchor="w", pady=(10, 4))
            ctk.CTkLabel(empty, text="Details und Schnellaktionen erscheinen hier, ohne die Übersicht zu verlassen.", text_color=p["muted"], font=self._liquid_font_v221(12), justify="left", wraplength=285).pack(anchor="w")
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

        head = ctk.CTkFrame(host, fg_color="transparent")
        head.pack(fill="x", padx=18, pady=(16, 8))
        close = ctk.CTkButton(head, text="×", width=32, height=32, corner_radius=16, fg_color=p["surface2"], hover_color=p["surface3"], text_color=p["muted"], command=self._liquid_close_inspector_v221, font=self._liquid_font_v221(18, "bold"))
        close.pack(side="right")
        ctk.CTkLabel(head, text="DETAILS", text_color=p["muted"], font=self._liquid_font_v221(10, "bold")).pack(anchor="w", pady=(6, 0))
        title = ctk.CTkFrame(host, fg_color="transparent")
        title.pack(fill="x", padx=18)
        ctk.CTkLabel(title, text="●", text_color=p["green"] if ble_state else p["red"], font=self._liquid_font_v221(12)).pack(side="left", padx=(0, 7))
        ctk.CTkLabel(title, text=name, text_color=p["fg"], font=self._liquid_font_v221(19, "bold"), anchor="w", wraplength=245).pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(host, text=f"{short or '—'}  ·  {node_id}", text_color=p["muted"], font=self._liquid_font_v221(11)).pack(anchor="w", padx=37, pady=(1, 10))

        chips = ctk.CTkFrame(host, fg_color="transparent")
        chips.pack(fill="x", padx=18, pady=(0, 14))
        self._liquid_chip_v221(chips, device.replace("Heltec ", ""), "purple" if "V3" in device else "blue").pack(side="left", padx=(0, 5))
        self._liquid_chip_v221(chips, "BLE sichtbar" if ble_state else "Offline", "green" if ble_state else "neutral").pack(side="left", padx=(0, 5))
        self._liquid_chip_v221(chips, "Log fällig" if due else "Log aktuell", "orange" if due else "green").pack(side="left")

        facts = ctk.CTkFrame(host, fg_color="transparent")
        facts.pack(fill="x", padx=18, pady=(0, 15))
        facts.grid_columnconfigure((0, 1, 2), weight=1, uniform="facts")
        for index, (label, value) in enumerate((("Akku", battery), ("Firmware", firmware), ("Hinweise", str(warning_count)))):
            box = ctk.CTkFrame(facts, fg_color=p["surface2"], corner_radius=15)
            box.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 4, 0))
            ctk.CTkLabel(box, text=label, text_color=p["muted"], font=self._liquid_font_v221(10)).pack(anchor="w", padx=10, pady=(9, 0))
            ctk.CTkLabel(box, text=value, text_color=p["fg"], font=self._liquid_font_v221(11, "bold"), wraplength=95, justify="left").pack(anchor="w", padx=10, pady=(2, 9))

        if isinstance(battery_value, (int, float)):
            battery_bar = ctk.CTkProgressBar(host, height=5, corner_radius=3, progress_color=p["green"] if float(battery_value) > 20 else p["red"], fg_color=p["surface2"])
            battery_bar.pack(fill="x", padx=18, pady=(0, 16))
            battery_bar.set(max(0.0, min(1.0, float(battery_value) / 100.0)))

        ctk.CTkLabel(host, text="Schnellaktionen", text_color=p["muted"], font=self._liquid_font_v221(11, "bold")).pack(anchor="w", padx=18)
        actions = ctk.CTkFrame(host, fg_color="transparent")
        actions.pack(fill="x", padx=18, pady=(7, 16))
        actions.grid_columnconfigure((0, 1), weight=1)
        self._liquid_button_v221(actions, "Log laden", lambda: self.batch_log_download_v2133([node_id]), primary=True).grid(row=0, column=0, sticky="ew", padx=(0, 5), pady=(0, 5))
        self._liquid_button_v221(actions, "Live", lambda: (self._clear_other_selection_v2133(node_id), self.batch_live_v2133())).grid(row=0, column=1, sticky="ew", pady=(0, 5))
        self._liquid_button_v221(actions, "OTA", lambda: self._single_node_ota_v220(node_id)).grid(row=1, column=0, sticky="ew", padx=(0, 5))
        self._liquid_button_v221(actions, "Bearbeiten", lambda: self.open_node_actions_v2132(node_id)).grid(row=1, column=1, sticky="ew")

        ctk.CTkLabel(host, text="BLE & Log-Automatik", text_color=p["muted"], font=self._liquid_font_v221(11, "bold")).pack(anchor="w", padx=18)
        auto = ctk.CTkFrame(host, fg_color=p["surface2"], corner_radius=17)
        auto.pack(fill="x", padx=18, pady=(7, 16))
        sync_state = str(getattr(self, "node_sync_state_v2132", {}).get(node_id) or "Bereit")
        for label, value, tone in (("BLE", "Erkannt" if ble_state else "Nicht in Reichweite", "green" if ble_state else "neutral"), ("Log", "Fällig" if due else "Aktuell", "orange" if due else "green"), ("Status", sync_state, "blue")):
            row = ctk.CTkFrame(auto, fg_color="transparent")
            row.pack(fill="x", padx=12, pady=5)
            ctk.CTkLabel(row, text=label, text_color=p["muted"], font=self._liquid_font_v221(11)).pack(side="left")
            ctk.CTkLabel(row, text=value, text_color=p.get(tone, p["muted"]), font=self._liquid_font_v221(11, "bold"), wraplength=190, justify="right").pack(side="right")

        ctk.CTkLabel(host, text="Weitere Bereiche", text_color=p["muted"], font=self._liquid_font_v221(11, "bold")).pack(anchor="w", padx=18)
        links = ctk.CTkFrame(host, fg_color="transparent")
        links.pack(fill="x", padx=18, pady=(7, 10))
        for label, target in (("Node-Details", "overview"), ("Log-Historie", "history"), ("Grunddaten / Service", "service"), ("Firmware", "firmware")):
            self._liquid_button_v221(links, label, lambda value=target: self.open_node_from_tile_v2132(node_id, value), compact=True).pack(fill="x", pady=2)
        self._liquid_button_v221(host, "Node entfernen …", lambda: self._delete_single_node_v220(node_id), danger=True, compact=True).pack(fill="x", padx=18, pady=(5, 18))
'''
    source = replace_method(source, "render_mac_inspector_v220", inspector)

    rebuild = r'''    def _rebuild_mac_chrome_colors_v220(self) -> None:
        self._liquid_apply_legacy_styles_v221()
        self._set_mac_nav_active_v220(getattr(self, "mac_active_page_v220", "all_nodes_tab"))
        self._refresh_filter_segments_v220()
        self.render_node_tiles_v2132()
        self.render_mac_inspector_v220()
'''
    source = replace_method(source, "_rebuild_mac_chrome_colors_v220", rebuild)

    toggle = r'''    def toggle_mac_appearance_v220(self) -> None:
        dark = not bool(self.mac_dark_v220.get())
        self.mac_dark_v220.set(dark)
        ctk.set_appearance_mode("Dark" if dark else "Light")
        self.theme.set("Modern Pro" if dark else "iOS")
        self._rebuild_mac_chrome_colors_v220()
'''
    source = replace_method(source, "toggle_mac_appearance_v220", toggle)

    install = r'''    def _install_mac_shell_v220(self) -> None:
        if getattr(self, "mac_shell_installed_v220", False):
            return
        self.mac_shell_installed_v220 = True
        self.mac_dark_v220 = tk.BooleanVar(value=False)
        self.mac_activity_events_v220 = []
        self.mac_inspector_node_v220 = ""
        ctk.set_appearance_mode("Light")
        ctk.set_default_color_theme("blue")
        p = self._liquid_palette_v221()
        self._liquid_apply_legacy_styles_v221()

        # Remove every old header/chrome surface while keeping its widgets alive.
        for child in list(self.root.winfo_children()):
            if child is not getattr(self, "main_pane_v220", None):
                with contextlib.suppress(tk.TclError):
                    child.pack_forget()
                with contextlib.suppress(tk.TclError):
                    child.grid_remove()
        self.main_pane_v220.pack_forget()
        with contextlib.suppress(tk.TclError):
            self.main_pane_v220.forget(self.legacy_controls_v220)
        workspace = getattr(self, "workspace_v220", self.notebook.master)
        for child in list(workspace.winfo_children()):
            if child is not self.notebook:
                with contextlib.suppress(tk.TclError):
                    child.pack_forget()
                with contextlib.suppress(tk.TclError):
                    child.grid_remove()

        top = ctk.CTkFrame(self.root, fg_color=p["surface"], corner_radius=22, border_width=1, border_color=p["line"], height=72)
        self.mac_topbar_v220 = top
        top.pack(fill="x", padx=18, pady=(14, 10))
        top.grid_columnconfigure(1, weight=1)

        brand = ctk.CTkFrame(top, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="w", padx=(18, 18), pady=12)
        ctk.CTkLabel(brand, text="Jarnsen", text_color=p["fg"], font=self._liquid_font_v221(17, "bold")).pack(anchor="w")
        ctk.CTkLabel(brand, text="Node Service Tool  ·  v2.2.1", text_color=p["muted"], font=self._liquid_font_v221(10)).pack(anchor="w", pady=(1, 0))

        search = ctk.CTkEntry(top, textvariable=self.node_search_var_v2133, placeholder_text="Suchen nach Node, ID, Status …", fg_color=p["surface2"], border_width=0, corner_radius=18, height=42, text_color=p["fg"], placeholder_text_color=p["muted"], font=self._liquid_font_v221(12))
        self.mac_search_v221 = search
        search.grid(row=0, column=1, sticky="ew", padx=(0, 18), pady=13)
        self.bind_all("<Control-k>", lambda _event: (search.focus_set(), search.select_range(0, "end")), add="+")

        actions = ctk.CTkFrame(top, fg_color="transparent")
        actions.grid(row=0, column=2, sticky="e", padx=(0, 16), pady=10)
        self._liquid_button_v221(actions, "BLE prüfen", lambda: self.auto_ble_refresh_v2132(False), primary=True, compact=True, width=112).pack(side="left", padx=(0, 7))
        self._liquid_button_v221(actions, "Aktivität", self._show_mac_activity_v220, compact=True, width=96).pack(side="left", padx=(0, 7))
        counter = ctk.CTkFrame(actions, fg_color=p["surface2"], corner_radius=15, height=32)
        counter.pack(side="left", padx=(0, 7))
        ctk.CTkLabel(counter, text="●", text_color=p["green"], font=self._liquid_font_v221(10)).pack(side="left", padx=(10, 3))
        self.mac_activity_count_v220 = ctk.CTkLabel(counter, text="0", text_color=p["fg"], font=self._liquid_font_v221(11, "bold"))
        self.mac_activity_count_v220.pack(side="left", padx=(0, 10), pady=6)
        self._liquid_button_v221(actions, "◐", self.toggle_mac_appearance_v220, compact=True, width=42).pack(side="left")

        sidebar = ctk.CTkFrame(self.main_pane_v220, fg_color=p["sidebar"], corner_radius=24, border_width=1, border_color=p["line"], width=220)
        sidebar.pack_propagate(False)
        self.mac_sidebar_v220 = sidebar
        self.main_pane_v220.insert(0, sidebar, weight=0)
        ctk.CTkLabel(sidebar, text="Jarnsen", text_color=p["fg"], font=self._liquid_font_v221(20, "bold")).pack(anchor="w", padx=18, pady=(20, 0))
        ctk.CTkLabel(sidebar, text="NODE MANAGEMENT", text_color=p["muted"], font=self._liquid_font_v221(9, "bold")).pack(anchor="w", padx=18, pady=(4, 15))

        self.mac_nav_buttons_v220 = {}
        navigation = [
            ("⌂   Übersicht", "all_nodes_tab"),
            ("▤   Node-Details", "overview_tab"),
            ("◷   Logs & Verlauf", "history_tab"),
            ("⚙   Firmware", self._candidate_page_v220("firmware_tab", "service_tab", "overview_tab")),
            ("◇   Karte", "track_tab"),
            ("≈   Live", "live_tab"),
            ("◎   Profile & Service", self._candidate_page_v220("service_tab", "config_tab", "overview_tab")),
            ("✓   Diagnose", self._candidate_page_v220("diagnosis_tab", "diagnose_tab", "details_tab")),
            ("⚙   Einstellungen", self._candidate_page_v220("settings_tab", "service_tab", "details_tab")),
        ]
        for label, attr in navigation:
            button = ctk.CTkButton(sidebar, text=label, command=lambda value=attr, caption=label: self._select_page_v220(value, caption), fg_color="transparent", hover_color=p["surface3"], text_color=p["fg"], corner_radius=14, height=40, anchor="w", font=self._liquid_font_v221(12))
            button.pack(fill="x", padx=10, pady=2)
            self.mac_nav_buttons_v220[attr] = button
        ctk.CTkFrame(sidebar, fg_color="transparent").pack(fill="both", expand=True)
        connection = ctk.CTkFrame(sidebar, fg_color=p["surface"], corner_radius=18, border_width=1, border_color=p["line"])
        connection.pack(fill="x", padx=12, pady=(8, 14))
        ctk.CTkLabel(connection, text="Verbindung", text_color=p["muted"], font=self._liquid_font_v221(10, "bold")).pack(anchor="w", padx=13, pady=(11, 0))
        self.mac_connection_label_v220 = ctk.CTkLabel(connection, text="●  BLE-Automatik aktiv", text_color=p["green"], font=self._liquid_font_v221(11, "bold"), anchor="w")
        self.mac_connection_label_v220.pack(fill="x", padx=13, pady=(4, 11))

        self.main_pane_v220.pack(fill="both", expand=True, padx=18, pady=(0, 14))
        with contextlib.suppress(tk.TclError):
            self.style.layout("Mac.Hidden.TNotebook", [("Notebook.client", {"sticky": "nswe"})])
            self.style.layout("Mac.Hidden.TNotebook.Tab", [])
            self.notebook.configure(style="Mac.Hidden.TNotebook")

        # Build a fresh rounded dashboard; the previous rectangular board remains hidden.
        for child in list(self.all_nodes_tab.winfo_children()):
            with contextlib.suppress(tk.TclError):
                child.pack_forget()
            with contextlib.suppress(tk.TclError):
                child.grid_remove()

        board = ctk.CTkFrame(self.all_nodes_tab, fg_color=p["bg"], corner_radius=0)
        self.liquid_board_v221 = board
        board.pack(fill="both", expand=True, padx=14, pady=10)

        header = ctk.CTkFrame(board, fg_color="transparent")
        header.pack(fill="x", pady=(3, 11))
        heading = ctk.CTkFrame(header, fg_color="transparent")
        heading.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(heading, text="Node-Übersicht", text_color=p["fg"], font=self._liquid_font_v221(26, "bold")).pack(anchor="w")
        ctk.CTkLabel(heading, text="Alles Wichtige auf einen Blick. Details erst bei Bedarf.", text_color=p["muted"], font=self._liquid_font_v221(12)).pack(anchor="w", pady=(2, 0))
        self._liquid_button_v221(header, "Aktualisieren", self.refresh_all_nodes_overview, compact=True).pack(side="right", padx=(6, 0), pady=(4, 0))
        self._liquid_button_v221(header, "Alle auswählen", self._select_visible_nodes_v2133, compact=True).pack(side="right", pady=(4, 0))

        stats = ctk.CTkFrame(board, fg_color="transparent")
        stats.pack(fill="x", pady=(0, 12))
        stats.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="stats")
        cards = (
            ("Nodes", self.dashboard_visible_var_v2133, "blue", "▣"),
            ("BLE in Reichweite", self.dashboard_ble_var_v2133, "green", "⌁"),
            ("Logs fällig", self.dashboard_due_var_v2133, "orange", "≡"),
            ("Aufmerksamkeit", self.dashboard_issue_var_v2133, "red", "!"),
        )
        for index, values in enumerate(cards):
            self._liquid_metric_card_v221(stats, *values).grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 5, 0))

        tools = ctk.CTkFrame(board, fg_color="transparent")
        tools.pack(fill="x", pady=(0, 10))
        segments = ctk.CTkFrame(tools, fg_color=p["surface2"], corner_radius=16)
        segments.pack(side="left")
        self.mac_filter_buttons_v220 = {}
        for value, label in (("Alle", "Alle"), ("BLE sichtbar", "In Reichweite"), ("Log fällig", "Logs fällig"), ("Updates", "Updates"), ("Hinweise", "Warnungen")):
            button = ctk.CTkButton(segments, text=label, command=lambda selected=value: self._set_filter_v220(selected), fg_color="transparent", hover_color=p["surface3"], text_color=p["fg"], corner_radius=12, height=32, width=96, font=self._liquid_font_v221(11, "bold"))
            button.pack(side="left", padx=2, pady=3)
            self.mac_filter_buttons_v220[value] = button
        self._refresh_filter_segments_v220()

        batch = ctk.CTkFrame(tools, fg_color=p["surface2"], corner_radius=16)
        batch.pack(side="left", padx=(10, 0))
        self.mac_batch_label_v220 = ctk.CTkLabel(batch, text="0 ausgewählt", text_color=p["muted"], font=self._liquid_font_v221(10, "bold"))
        self.mac_batch_label_v220.pack(side="left", padx=(11, 5))
        self._liquid_button_v221(batch, "Logs laden", self.batch_log_download_v2133, primary=True, compact=True).pack(side="left", padx=2, pady=3)
        self._liquid_button_v221(batch, "OTA", self.batch_ota_v2133, compact=True).pack(side="left", padx=2, pady=3)
        self._liquid_button_v221(batch, "Wecken", self.batch_wake_v2133, compact=True).pack(side="left", padx=2, pady=3)
        self._liquid_button_v221(tools, "Auswahl leeren", self._clear_node_selection_v2133, compact=True).pack(side="right")

        content = ctk.CTkFrame(board, fg_color="transparent")
        content.pack(fill="both", expand=True)
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)
        content.grid_columnconfigure(1, weight=0)

        cards_host = ctk.CTkScrollableFrame(content, fg_color="transparent", corner_radius=0, scrollbar_button_color=p["surface3"], scrollbar_button_hover_color=p["blue_soft"])
        self.rounded_nodes_host_v221 = cards_host
        cards_host.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        cards_host.bind("<Configure>", self._liquid_reflow_v221, add="+")

        inspector_host = ctk.CTkScrollableFrame(content, width=344, fg_color=p["surface"], corner_radius=24, border_width=1, border_color=p["line"], scrollbar_button_color=p["surface3"], scrollbar_button_hover_color=p["blue_soft"])
        self.mac_inspector_v220 = inspector_host
        inspector_host.grid(row=0, column=1, sticky="nsew")

        self.render_mac_inspector_v220()
        self._set_mac_nav_active_v220("all_nodes_tab")
        self.after(100, self.render_node_tiles_v2132)
'''
    source = replace_method(source, "_install_mac_shell_v220", install)

    render = r'''    def render_node_tiles_v2132(self) -> None:
        host = getattr(self, "rounded_nodes_host_v221", None)
        if host is None:
            return
        if getattr(self, "_liquid_rendering_v221", False):
            return
        self._liquid_rendering_v221 = True
        try:
            p = self._liquid_palette_v221()
            for child in host.winfo_children():
                child.destroy()
            try:
                rows = self.repository.list_nodes(self.show_archived_var.get())
            except Exception:
                rows = []
            rows = self._filter_sort_rows_v2133(rows)
            self.visible_node_ids_v2133 = [normalize_node_id(str(row["node_id"] or "")) for row in rows]
            width = max(640, int(host.winfo_width() or 640))
            columns = 2 if width >= 760 else 1
            states = getattr(self, "node_sync_state_v2132", {})
            selections = getattr(self, "node_selection_v2133", {})
            if not isinstance(states, dict):
                states = {}
            if not isinstance(selections, dict):
                selections = {}
                self.node_selection_v2133 = selections
            for column in range(columns):
                host.grid_columnconfigure(column, weight=1, uniform="liquid-node")

            ble_visible = due_count = issue_count = update_count = 0
            for index, row in enumerate(rows):
                node_id = normalize_node_id(str(row["node_id"] or ""))
                latest = self.repository.latest_log(node_id)
                metrics = latest.get("metrics", {}) if latest else {}
                if not isinstance(metrics, dict):
                    metrics = {}
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
                attention = bool(warning_count or low_battery)
                border = p["blue"] if selected else (p["red"] if attention else (p["orange"] if due or update else p["line"]))

                card = ctk.CTkFrame(host, fg_color=p["surface"], corner_radius=20, border_width=2 if selected else 1, border_color=border)
                card.grid(row=index // columns, column=index % columns, sticky="nsew", padx=5, pady=5)
                card.grid_columnconfigure(0, weight=1)

                head = ctk.CTkFrame(card, fg_color="transparent")
                head.grid(row=0, column=0, sticky="ew", padx=14, pady=(13, 5))
                select_btn = ctk.CTkButton(head, text="✓" if selected else "", width=24, height=24, corner_radius=12, border_width=2, border_color=p["blue"] if selected else p["line"], fg_color=p["blue"] if selected else p["surface2"], hover_color=p["blue_soft"], text_color=("#FFFFFF", "#FFFFFF"), command=lambda value=node_id: self._liquid_select_toggle_v221(value), font=self._liquid_font_v221(11, "bold"))
                select_btn.pack(side="left", padx=(0, 9))
                titles = ctk.CTkFrame(head, fg_color="transparent")
                titles.pack(side="left", fill="x", expand=True)
                ctk.CTkLabel(titles, text=name, text_color=p["fg"], font=self._liquid_font_v221(14, "bold"), anchor="w").pack(fill="x")
                ctk.CTkLabel(titles, text=f"{short_name or '—'}  ·  {node_id}", text_color=p["muted"], font=self._liquid_font_v221(10), anchor="w").pack(fill="x", pady=(1, 0))
                self._liquid_button_v221(head, "•••", lambda value=node_id: self.open_node_actions_v2132(value), compact=True, width=42).pack(side="right")
                self._liquid_button_v221(head, "✎", lambda value=node_id: self.open_node_actions_v2132(value), compact=True, width=42).pack(side="right", padx=(0, 5))

                chips = ctk.CTkFrame(card, fg_color="transparent")
                chips.grid(row=1, column=0, sticky="ew", padx=14, pady=(4, 9))
                self._liquid_chip_v221(chips, device, "purple" if device == "V3" else "blue").pack(side="left", padx=(0, 4))
                self._liquid_chip_v221(chips, "BLE" if ble_state else "Offline", "green" if ble_state else "neutral").pack(side="left", padx=(0, 4))
                if due: self._liquid_chip_v221(chips, "Log fällig", "orange").pack(side="left", padx=(0, 4))
                if update: self._liquid_chip_v221(chips, "Update", "purple").pack(side="left", padx=(0, 4))
                if attention: self._liquid_chip_v221(chips, "Hinweis", "red").pack(side="left")

                facts = ctk.CTkFrame(card, fg_color="transparent")
                facts.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 8))
                facts.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="facts")
                log_time = "--"
                if latest:
                    raw_ts = latest.get("created_at") or latest.get("timestamp") or latest.get("logged_at")
                    if raw_ts:
                        log_time = str(raw_ts).replace("T", " ")[:16]
                for col, (label, value) in enumerate((("Akku", battery), ("BLE", "In Reichweite" if ble_state else "Nicht in Reichweite"), ("Letzter Log", log_time), ("Firmware", firmware))):
                    box = ctk.CTkFrame(facts, fg_color=p["surface2"], corner_radius=13)
                    box.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 4, 0))
                    ctk.CTkLabel(box, text=label, text_color=p["muted"], font=self._liquid_font_v221(9)).pack(anchor="w", padx=8, pady=(7, 0))
                    ctk.CTkLabel(box, text=value, text_color=p["fg"], font=self._liquid_font_v221(10, "bold"), wraplength=max(76, int(width / columns / 5)), justify="left").pack(anchor="w", padx=8, pady=(1, 7))

                sync_state = str(states.get(node_id) or "")
                if sync_state:
                    ctk.CTkLabel(card, text=sync_state, text_color=p["muted"], font=self._liquid_font_v221(10), anchor="w").grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 5))

                actions = ctk.CTkFrame(card, fg_color="transparent")
                actions.grid(row=4, column=0, sticky="ew", padx=14, pady=(2, 13))
                actions.grid_columnconfigure(0, weight=1)
                self._liquid_button_v221(actions, "Öffnen", lambda value=node_id: self.show_mac_inspector_v220(value), primary=True, compact=True).grid(row=0, column=0, sticky="ew", padx=(0, 5))
                self._liquid_button_v221(actions, "Log", lambda value=node_id: self.batch_log_download_v2133([value]), compact=True, width=56).grid(row=0, column=1, padx=2)
                self._liquid_button_v221(actions, "Live", lambda value=node_id: (self._clear_other_selection_v2133(value), self.batch_live_v2133()), compact=True, width=56).grid(row=0, column=2, padx=2)
                self._liquid_button_v221(actions, "OTA", lambda value=node_id: self._single_node_ota_v220(value), compact=True, width=56).grid(row=0, column=3, padx=(2, 0))

            if hasattr(self, "dashboard_visible_var_v2133"):
                self.dashboard_visible_var_v2133.set(str(len(rows)))
                self.dashboard_ble_var_v2133.set(str(ble_visible))
                self.dashboard_due_var_v2133.set(str(due_count))
                self.dashboard_issue_var_v2133.set(str(issue_count + update_count))
            if not rows:
                empty = ctk.CTkFrame(host, fg_color=p["surface"], corner_radius=20, border_width=1, border_color=p["line"])
                empty.grid(row=0, column=0, columnspan=max(1, columns), sticky="ew", padx=6, pady=6)
                ctk.CTkLabel(empty, text="Keine Nodes gefunden", text_color=p["fg"], font=self._liquid_font_v221(17, "bold")).pack(anchor="w", padx=18, pady=(16, 2))
                ctk.CTkLabel(empty, text="Suche oder Filter zurücksetzen – oder BLE erneut prüfen.", text_color=p["muted"], font=self._liquid_font_v221(12)).pack(anchor="w", padx=18, pady=(0, 16))
            self._update_batch_bar_v2133()
            if getattr(self, "mac_inspector_node_v220", ""):
                self.render_mac_inspector_v220()
        finally:
            self._liquid_rendering_v221 = False
'''
    source = replace_method(source, "render_node_tiles_v2132", render)

    action_sheet = r'''    def open_node_actions_v2132(self, node_id: str) -> None:
        normalized = normalize_node_id(node_id)
        if not normalized:
            return
        latest = self.repository.latest_log(normalized)
        metrics = latest.get("metrics", {}) if latest else {}
        if not isinstance(metrics, dict):
            metrics = {}
        name = str(metrics.get("long_name") or normalized)
        p = self._liquid_palette_v221()
        win = ctk.CTkToplevel(self)
        win.title(f"{name} · Verwaltung")
        win.geometry("540x650")
        win.minsize(500, 560)
        win.transient(self)
        outer = ctk.CTkFrame(win, fg_color=p["bg"], corner_radius=0)
        outer.pack(fill="both", expand=True)
        sheet = ctk.CTkFrame(outer, fg_color=p["surface"], corner_radius=28, border_width=1, border_color=p["line"])
        sheet.pack(fill="both", expand=True, padx=18, pady=18)
        ctk.CTkLabel(sheet, text=name, text_color=p["fg"], font=self._liquid_font_v221(23, "bold")).pack(anchor="w", padx=22, pady=(22, 0))
        ctk.CTkLabel(sheet, text=f"{normalized}  ·  Aktionen & Verwaltung", text_color=p["muted"], font=self._liquid_font_v221(12)).pack(anchor="w", padx=22, pady=(3, 16))

        section = ctk.CTkFrame(sheet, fg_color=p["surface2"], corner_radius=18)
        section.pack(fill="x", padx=22, pady=(0, 12))
        ctk.CTkLabel(section, text="Öffnen", text_color=p["muted"], font=self._liquid_font_v221(10, "bold")).pack(anchor="w", padx=14, pady=(11, 6))
        for label, target in (("Node-Details", "overview"), ("Grunddaten / Service", "service"), ("Firmware", "firmware"), ("Log-Historie", "history")):
            self._liquid_button_v221(section, label, lambda value=target: (self.open_node_from_tile_v2132(normalized, value), win.destroy()), compact=True).pack(fill="x", padx=10, pady=3)
        ctk.CTkFrame(section, fg_color="transparent", height=6).pack()

        quick = ctk.CTkFrame(sheet, fg_color=p["surface2"], corner_radius=18)
        quick.pack(fill="x", padx=22, pady=(0, 12))
        ctk.CTkLabel(quick, text="Schnellaktionen", text_color=p["muted"], font=self._liquid_font_v221(10, "bold")).pack(anchor="w", padx=14, pady=(11, 6))
        self._liquid_button_v221(quick, "Log jetzt laden", lambda: (self.batch_log_download_v2133([normalized]), win.destroy()), primary=True).pack(fill="x", padx=10, pady=3)
        self._liquid_button_v221(quick, "OTA Update", lambda: (self._single_node_ota_v220(normalized), win.destroy())).pack(fill="x", padx=10, pady=3)
        ctk.CTkFrame(quick, fg_color="transparent", height=6).pack()

        danger = ctk.CTkFrame(sheet, fg_color=p["red_soft"], corner_radius=18)
        danger.pack(fill="x", padx=22, pady=(0, 12))
        ctk.CTkLabel(danger, text="Verwaltung", text_color=p["red"], font=self._liquid_font_v221(10, "bold")).pack(anchor="w", padx=14, pady=(11, 6))
        self._liquid_button_v221(danger, "Node entfernen …", lambda: (self._delete_single_node_v220(normalized), win.destroy()), danger=True).pack(fill="x", padx=10, pady=(0, 10))
        self._liquid_button_v221(sheet, "Schließen", win.destroy).pack(fill="x", padx=22, pady=(4, 20))
'''
    source = replace_method(source, "open_node_actions_v2132", action_sheet)

    # Ensure page navigation also refreshes the softened legacy ttk theme.
    select_start, select_end = method_span(source, "_select_page_v220")
    select_method = source[select_start:select_end]
    if "_liquid_apply_legacy_styles_v221" not in select_method:
        select_method = select_method.rstrip() + "\n        self._liquid_apply_legacy_styles_v221()\n"
        source = source[:select_start] + select_method + source[select_end:]

    source += "\n# PATCH_V221_LIQUID_ROUNDED_UI\n"
    required = (
        'APP_VERSION = "2.2.1"',
        'import customtkinter as ctk',
        'def _liquid_palette_v221',
        'corner_radius=24',
        'CTkScrollableFrame',
        'def render_mac_inspector_v220',
        'def render_node_tiles_v2132',
        'PATCH_V221_LIQUID_ROUNDED_UI',
    )
    missing = [marker for marker in required if marker not in source]
    if missing:
        raise SystemExit("v2.2.1 validation failed: " + ", ".join(missing))
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v221.py <source.py>")
    path = Path(sys.argv[1])
    path.write_text(patch(path.read_text(encoding="utf-8")), encoding="utf-8")
    print("Applied Service Tool v2.2.1: true rounded Liquid Desktop UI")


if __name__ == "__main__":
    main()
