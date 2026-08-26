"""v1.8 layout and completion-state additions for the shared Service Tool.

Replaces the permanently stacked left control column with four compact pages
selected by fixed buttons. The navigation and action footer stay visible while
the canvas remains only as a small-window fallback. Completed transfers reset
the progress display without replacing the result shown in the status line.
Runs after the v1.7 patcher.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "1.8.0"


def method_span(text: str, name: str) -> tuple[int, int]:
    start = text.find(f"    def {name}(")
    if start < 0:
        raise SystemExit(f"method {name} not found")
    next_method = text.find("\n    def ", start + 1)
    return start, next_method if next_method >= 0 else len(text)


def insert_before_method(text: str, name: str, code: str) -> str:
    start, _ = method_span(text, name)
    return text[:start] + code.rstrip() + "\n\n" + text[start:]


def patch(source: str) -> str:
    source = re.sub(
        r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{APP_VERSION}"', source, count=1
    )
    source = source.replace('APP_VERSION != "1.7.0"', 'APP_VERSION != "1.8.0"')
    source = source.replace(
        "App-Version ist nicht v1.7.0", "App-Version ist nicht v1.8.0"
    )

    host_anchor = """        controls_host = ttk.Frame(body, width=380)
        body.add(controls_host, weight=0)
        self.controls_canvas = tk.Canvas(
"""
    if "self.controls_nav = ttk.Frame" not in source:
        host_new = """        controls_host = ttk.Frame(body, width=380)
        body.add(controls_host, weight=0)
        self.controls_nav = ttk.Frame(controls_host, padding=(0, 0, 8, 0))
        self.controls_nav.pack(side="top", fill="x", pady=(0, 6))
        self.controls_footer = ttk.Frame(controls_host, padding=(0, 0, 8, 0))
        self.controls_footer.pack(side="bottom", fill="x", pady=(6, 0))
        self.controls_canvas = tk.Canvas(
"""
        if source.count(host_anchor) != 1:
            raise SystemExit("controls host anchor not found")
        source = source.replace(host_anchor, host_new, 1)

    nodes_anchor = """        nodes = ttk.LabelFrame(controls, text="Nodes", padding=6)
"""
    if "self.controls_pages =" not in source:
        pages = """        self.controls_page_buttons: dict[str, ttk.Button] = {}
        for page_name in ("Nodes", "USB", "Bluetooth", "Werkzeuge"):
            button = ttk.Button(
                self.controls_nav,
                text=page_name,
                command=lambda selected=page_name: self.show_controls_page(selected),
            )
            button.pack(side="left", fill="x", expand=True, padx=(0, 4))
            self.controls_page_buttons[page_name] = button

        self.controls_page_host = ttk.Frame(controls)
        self.controls_page_host.pack(fill="both", expand=True)
        self.controls_pages = {
            page_name: ttk.Frame(self.controls_page_host)
            for page_name in ("Nodes", "USB", "Bluetooth", "Werkzeuge")
        }
        self.controls_page_name = ""

        nodes = ttk.LabelFrame(self.controls_pages["Nodes"], text="Nodes", padding=6)
"""
        if source.count(nodes_anchor) != 1:
            raise SystemExit("nodes page anchor not found")
        source = source.replace(nodes_anchor, pages, 1)

    page_parents = {
        'service = ttk.LabelFrame(controls, text="Service / Recovery", padding=6)': 'service = ttk.LabelFrame(self.controls_pages["Werkzeuge"], text="Service / Recovery", padding=6)',
        'setup = ttk.LabelFrame(controls, text="USB / seriell", padding=6)': 'setup = ttk.LabelFrame(self.controls_pages["USB"], text="USB / seriell", padding=6)',
        'ble = ttk.LabelFrame(controls, text="Bluetooth Low Energy", padding=6)': 'ble = ttk.LabelFrame(self.controls_pages["Bluetooth"], text="Bluetooth Low Energy", padding=6)',
        'guide = ttk.LabelFrame(controls, text="Kurzablauf", padding=6)': 'guide = ttk.LabelFrame(self.controls_pages["Werkzeuge"], text="Kurzablauf", padding=6)',
    }
    for old, new in page_parents.items():
        if old in source:
            source = source.replace(old, new, 1)
        elif new not in source:
            raise SystemExit(f"page parent anchor not found: {old}")

    actions_anchor = """        actions = ttk.Frame(controls)
        actions.pack(fill="x", pady=6)
"""
    if "actions = self.controls_footer" not in source:
        if source.count(actions_anchor) != 1:
            raise SystemExit("controls footer anchor not found")
        source = source.replace(
            actions_anchor, "        actions = self.controls_footer\n", 1
        )

    notebook_anchor = """        self.notebook = ttk.Notebook(workspace)
"""
    if 'self.show_controls_page("Nodes")' not in source:
        if source.count(notebook_anchor) != 1:
            raise SystemExit("notebook anchor not found")
        source = source.replace(
            notebook_anchor,
            '        self.show_controls_page("Nodes")\n\n' + notebook_anchor,
            1,
        )

    if "    def show_controls_page(self, page_name: str)" not in source:
        page_method = """    def show_controls_page(self, page_name: str) -> None:
        if not hasattr(self, "controls_pages") or page_name not in self.controls_pages:
            return
        for name, frame in self.controls_pages.items():
            if name == page_name:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()
        self.controls_page_name = page_name
        for name, button in self.controls_page_buttons.items():
            button.configure(style="Primary.TButton" if name == page_name else "TButton")
        self.update_idletasks()
        self.controls_canvas.yview_moveto(0.0)
        self.after_idle(self._update_controls_scroll_state)
"""
        source = insert_before_method(source, "_resize_dashboard", page_method)

    # Selecting the monitor transport also reveals the matching connection page.
    start, end = method_span(source, "update_serial_monitor_source_ui")
    source_method = source[start:end]
    transport_anchor = "        self.serial_monitor_transport = source_name\n"
    page_switch = """        self.serial_monitor_transport = source_name
        if hasattr(self, "controls_pages"):
            self.show_controls_page("Bluetooth" if source_name == "Bluetooth" else "USB")
"""
    if 'self.show_controls_page("Bluetooth" if source_name' not in source_method:
        if source_method.count(transport_anchor) != 1:
            raise SystemExit("serial transport page anchor not found")
        source_method = source_method.replace(transport_anchor, page_switch, 1)
        source = source[:start] + source_method + source[end:]

    if "    def reset_transfer_progress(self)" not in source:
        reset_method = """    def reset_transfer_progress(self) -> None:
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress["value"] = 0
        self.progress_percent.configure(text="")
        self.progress_text.configure(text="")
"""
        source = insert_before_method(source, "set_transfer_progress", reset_method)

    done_anchor = """                    self.ble_pair_button.configure(state="normal")
                    self.cancel_button.configure(state="disabled")
"""
    done_new = """                    self.ble_pair_button.configure(state="normal")
                    self.cancel_button.configure(state="disabled")
                    self.reset_transfer_progress()
"""
    if "                    self.reset_transfer_progress()" not in source:
        if source.count(done_anchor) != 1:
            raise SystemExit("done progress-reset anchor not found")
        source = source.replace(done_anchor, done_new, 1)

    selftest_anchor = """        if APP_VERSION != "1.8.0":
            raise RuntimeError("App-Version ist nicht v1.8.0")
"""
    if '"show_controls_page"' not in source[source.find("def packaged_self_test") :]:
        addition = (
            selftest_anchor
            + """        for method_name in (
            "show_controls_page",
            "reset_transfer_progress",
        ):
            if not hasattr(ServiceTool, method_name):
                raise RuntimeError(f"v1.8-Funktion fehlt: {method_name}")
"""
        )
        if source.count(selftest_anchor) != 1:
            raise SystemExit("v1.8 self-test anchor not found")
        source = source.replace(selftest_anchor, addition, 1)

    required = (
        'APP_VERSION = "1.8.0"',
        "self.controls_nav = ttk.Frame",
        "self.controls_footer = ttk.Frame",
        'for page_name in ("Nodes", "USB", "Bluetooth", "Werkzeuge")',
        'self.controls_pages["Bluetooth"]',
        "def show_controls_page(self, page_name: str)",
        "def reset_transfer_progress(self)",
        "self.reset_transfer_progress()",
    )
    for marker in required:
        if marker not in source:
            raise SystemExit(f"missing v1.8 marker: {marker}")
    return source


def main() -> None:
    target = Path(
        sys.argv[1] if len(sys.argv) > 1 else "tools/JARNSEN_NODE_SERVICE_TOOL.py"
    )
    source = target.read_text(encoding="utf-8")
    target.write_text(patch(source), encoding="utf-8")
    print(
        "Service tool patched to v1.8.0: compact control pages + cleared completion progress"
    )


if __name__ == "__main__":
    main()
