"""v2.1.0 final overview layout: two prioritized 1080p pages, no dashboard scrolling."""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "2.1.0"


def method_span(text: str, name: str) -> tuple[int, int]:
    start = text.find(f"    def {name}(")
    if start < 0:
        raise SystemExit(f"method {name} not found")
    next_method = text.find("\n    def ", start + 1)
    return start, next_method if next_method >= 0 else len(text)


def replace_method(text: str, name: str, replacement: str) -> str:
    start, end = method_span(text, name)
    return text[:start] + replacement.rstrip() + "\n" + text[end:]


def patch(source: str) -> str:
    source = re.sub(r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{APP_VERSION}"', source, count=1)

    # The v2.1 base patch introduced a scrollbar as a safety net. For the final
    # 1080p UX we deliberately remove it and split the dashboard across two
    # prioritized fixed pages instead.
    install_start, install_end = method_span(source, "_install_workflow_ui")
    install = source[install_start:install_end]

    if "self.overview_detail_tab" not in install:
        tab_anchor = '''        self.all_nodes_tab = ttk.Frame(self.notebook, padding=10)\n        self.service_tab = ttk.Frame(self.notebook, padding=12)\n'''
        replacement = '''        self.all_nodes_tab = ttk.Frame(self.notebook, padding=10)\n        self.overview_detail_tab = ttk.Frame(self.notebook, padding=10)\n        self.service_tab = ttk.Frame(self.notebook, padding=12)\n'''
        if install.count(tab_anchor) != 1:
            raise SystemExit("overview detail tab anchor not found")
        install = install.replace(tab_anchor, replacement, 1)

        add_anchor = '''        self.notebook.add(self.all_nodes_tab, text="Alle Nodes")\n        self.notebook.add(self.service_tab, text="Service")\n'''
        add_new = '''        self.notebook.add(self.all_nodes_tab, text="Alle Nodes")\n        self.notebook.add(self.overview_detail_tab, text="Node 2 · Diagnose")\n        self.notebook.add(self.service_tab, text="Service")\n'''
        if install.count(add_anchor) != 1:
            raise SystemExit("overview detail add anchor not found")
        install = install.replace(add_anchor, add_new, 1)

        order_anchor = '''            self.all_nodes_tab,\n            self.overview_tab,\n            self.service_tab,\n'''
        order_new = '''            self.all_nodes_tab,\n            self.overview_tab,\n            self.overview_detail_tab,\n            self.service_tab,\n'''
        if install.count(order_anchor) != 1:
            raise SystemExit("overview detail order anchor not found")
        install = install.replace(order_anchor, order_new, 1)

        label_anchor = '        self.notebook.tab(self.overview_tab, text="Node-Übersicht")\n'
        labels = (
            '        self.notebook.tab(self.overview_tab, text="Node 1 · Status")\n'
            '        self.notebook.tab(self.overview_detail_tab, text="Node 2 · Diagnose")\n'
        )
        if install.count(label_anchor) != 1:
            raise SystemExit("overview page label anchor not found")
        install = install.replace(label_anchor, labels, 1)

        service_anchor = '        ttk.Label(self.service_tab, text="Schnellaktionen", style="Section.TLabel").pack(anchor="w")\n'
        detail_ui = r'''        detail_header = ttk.Frame(self.overview_detail_tab)
        detail_header.pack(fill="x", pady=(0, 6))
        ttk.Label(
            detail_header,
            text="Diagnose & Optimierung",
            style="Section.TLabel",
        ).pack(side="left")
        ttk.Label(
            detail_header,
            text="Strom · Laufzeiten · Lernen · Verlauf",
            style="Subtitle.TLabel",
        ).pack(side="left", padx=(10, 0))
        ttk.Button(
            detail_header,
            text="← Status",
            command=lambda: self.notebook.select(self.overview_tab),
        ).pack(side="right")
        detail_body = ttk.Frame(self.overview_detail_tab)
        detail_body.pack(fill="both", expand=True)
        self.dashboard2_canvas = tk.Canvas(detail_body, highlightthickness=0)
        self.dashboard2_canvas.pack(fill="both", expand=True)
        self.dashboard2 = ttk.Frame(self.dashboard2_canvas)
        self.dashboard2_window = self.dashboard2_canvas.create_window(
            (0, 0), window=self.dashboard2, anchor="nw"
        )
        self.dashboard2_canvas.bind(
            "<Configure>", self._resize_dashboard2
        )

'''
        if install.count(service_anchor) != 1:
            raise SystemExit("detail UI insertion anchor not found")
        install = install.replace(service_anchor, detail_ui + service_anchor, 1)

    source = source[:install_start] + install + source[install_end:]

    # Disable/remove the scrollbar created by the base v2.1 patch. It remains
    # allocated only if the earlier patch created it, but is never mapped.
    build_start, build_end = method_span(source, "_build_ui")
    build = source[build_start:build_end]
    if "self.dashboard_scrollbar.pack_forget()" not in build:
        anchor = '        self.dashboard_canvas.configure(yscrollcommand=self.dashboard_scrollbar.set)\n'
        if anchor in build:
            build = build.replace(
                anchor,
                '        self.dashboard_canvas.configure(yscrollcommand="")\n        self.dashboard_scrollbar.pack_forget()\n',
                1,
            )
        wheel_block = '''        self.dashboard_canvas.bind(\n            "<MouseWheel>",\n            lambda event: self.dashboard_canvas.yview_scroll(\n                int(-event.delta / 120) if event.delta else 0, "units"\n            ),\n            add="+",\n        )\n'''
        build = build.replace(wheel_block, "", 1)
    source = source[:build_start] + build + source[build_end:]

    if "    def _resize_dashboard2(self" not in source:
        anchor_start, _ = method_span(source, "apply_theme")
        helper = r'''    def _resize_dashboard2(self, event: tk.Event) -> None:
        if hasattr(self, "dashboard2_canvas") and hasattr(self, "dashboard2_window"):
            self.dashboard2_canvas.itemconfigure(self.dashboard2_window, width=event.width)
        self.after_idle(self.render_dashboard)

    def _render_dashboard_page(
        self,
        target: ttk.Frame,
        canvas: tk.Canvas,
        cards: dict[str, object],
    ) -> None:
        for child in target.winfo_children():
            child.destroy()
        palette = THEMES.get(self.theme.get(), THEMES["Modern"])
        available_width = max(canvas.winfo_width(), 420)
        # 1920x1080 maximized: four columns x two rows. Smaller windows fall
        # back to three/two columns, but never add a vertical dashboard scroll.
        columns = 4 if available_width >= 1180 else (3 if available_width >= 860 else (2 if available_width >= 560 else 1))
        card_wrap = max(210, int(available_width / columns) - 52)
        compact = columns >= 3
        for index, (key, card) in enumerate(cards.items()):
            row, column = divmod(index, columns)
            ios = self.theme.get() == "iOS"
            frame = tk.Frame(
                target,
                background=palette["panel"],
                highlightthickness=(
                    0 if ios else (2 if self.theme.get() in ("Retro 90er", "Matrix") else 1)
                ),
                highlightbackground=palette.get(str(card["level"]), palette["muted"]),
                bd=2 if self.theme.get() == "Retro 90er" else 0,
                relief="raised" if self.theme.get() == "Retro 90er" else "flat",
                padx=7 if compact else (12 if ios else 9),
                pady=5 if compact else (10 if ios else 7),
            )
            frame.grid(row=row, column=column, sticky="nsew", padx=4, pady=4)
            label = key.replace("_", " ")
            label = label.title() if ios else label.upper()
            tk.Label(
                frame,
                text=label,
                background=palette["panel"],
                foreground=palette["muted"],
                font=(palette["mono"] if self.theme.get() == "Matrix" else palette["font"], 8, "bold"),
            ).pack(anchor="w")
            tk.Label(
                frame,
                text=str(card["title"]),
                background=palette["panel"],
                foreground=palette.get(str(card["level"]), palette["fg"]),
                font=(palette["font"], 12 if compact else (14 if ios else 13), "bold"),
                wraplength=card_wrap,
                justify="left",
            ).pack(anchor="w", pady=(1, 3))
            for line in list(card["lines"])[:6]:
                tk.Label(
                    frame,
                    text=str(line),
                    background=palette["panel"],
                    foreground=palette["fg"],
                    font=(palette["mono"] if self.theme.get() == "Matrix" else palette["font"], 8 if compact else 9),
                    wraplength=card_wrap,
                    justify="left",
                ).pack(anchor="w", pady=0 if compact else 1)
        for column in range(columns):
            target.columnconfigure(column, weight=1, uniform="cards")
        rows = max(1, (len(cards) + columns - 1) // columns)
        for row in range(rows):
            target.rowconfigure(row, weight=1, uniform="card_rows")

'''
        source = source[:anchor_start] + helper + source[anchor_start:]

    new_render = r'''    def render_dashboard(self) -> None:
        if not hasattr(self, "dashboard"):
            return
        if self.last_payload:
            cards = diagnostic_snapshot(self.last_payload, self.last_comparison)
            firmware_card = self.firmware_card(
                header_value(self.last_payload, b"device"),
                header_value(self.last_payload, b"build"),
            )
            power_logs = self.node_logs if isinstance(self.node_logs, list) else []
            cards = add_power_analysis_cards(cards, power_logs, self.last_payload)
            cards = add_v15_analysis_cards(cards, power_logs)
            cards = {"softwarestand": firmware_card, **cards}
        else:
            cards = {
                "welcome": {
                    "title": "Bereit für den ersten Download",
                    "lines": [
                        "Oben + Node oder Bluetooth verwenden",
                        "Log herunterladen – Gerät wird automatisch erkannt",
                        "Danach stehen Status, Position und Historie bereit",
                    ],
                    "level": "accent",
                },
                "connection": {
                    "title": "Direkte Wege",
                    "lines": [
                        "Bluetooth und Seriell sind oben dauerhaft erreichbar",
                        "Firmwarestände lassen sich direkt über GitHub prüfen",
                        "Service-WLAN befindet sich im Service-Bereich",
                    ],
                    "level": "normal",
                },
            }

        # Seite 1 is intentionally operational: the six cards needed to decide
        # whether a node is healthy and what should be done next.
        page1_order = (
            "softwarestand",
            "node",
            "battery",
            "health",
            "position",
            "events",
        )
        # Seite 2 is intentionally diagnostic/engineering-focused.
        page2_order = (
            "power",
            "runtime",
            "akku_lernen",
            "power_analyse",
            "duty_cycle",
            "anomalien",
            "firmware_vergleich",
            "history",
        )
        page1 = {key: cards[key] for key in page1_order if key in cards}
        page2 = {key: cards[key] for key in page2_order if key in cards}
        assigned = set(page1) | set(page2)
        for key, value in cards.items():
            if key not in assigned:
                if len(page1) < 6:
                    page1[key] = value
                elif len(page2) < 8:
                    page2[key] = value

        self._render_dashboard_page(self.dashboard, self.dashboard_canvas, page1)
        if hasattr(self, "dashboard2") and hasattr(self, "dashboard2_canvas"):
            self._render_dashboard_page(self.dashboard2, self.dashboard2_canvas, page2)
'''
    source = replace_method(source, "render_dashboard", new_render)

    # Theme the second dashboard canvas exactly like the first.
    theme_start, theme_end = method_span(source, "apply_theme")
    theme = source[theme_start:theme_end]
    if 'hasattr(self, "dashboard2_canvas")' not in theme:
        anchor = '''        if hasattr(self, "dashboard_canvas"):\n            self.dashboard_canvas.configure(background=bg)\n'''
        addition = anchor + '''        if hasattr(self, "dashboard2_canvas"):\n            self.dashboard2_canvas.configure(background=bg)\n'''
        if theme.count(anchor) != 1:
            raise SystemExit("dashboard2 theme anchor not found")
        theme = theme.replace(anchor, addition, 1)
    source = source[:theme_start] + theme + source[theme_end:]

    required = (
        'APP_VERSION = "2.1.0"',
        "self.overview_detail_tab",
        'text="Node 1 · Status"',
        'text="Node 2 · Diagnose"',
        "self.dashboard2_canvas",
        "def _render_dashboard_page(",
        "page1_order = (",
        '"softwarestand"',
        '"position"',
        "page2_order = (",
        '"power_analyse"',
        '"firmware_vergleich"',
        "self.dashboard_scrollbar.pack_forget()",
    )
    for marker in required:
        if marker not in source:
            raise SystemExit(f"missing v2.1 page marker: {marker}")
    return source


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "tools/JARNSEN_NODE_SERVICE_TOOL.py")
    target.write_text(patch(target.read_text(encoding="utf-8")), encoding="utf-8")
    print("Service tool v2.1.0: two prioritized no-scroll node overview pages")


if __name__ == "__main__":
    main()
