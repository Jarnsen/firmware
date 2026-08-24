#!/usr/bin/env python3
"""Portable Windows GUI for Tracker V1.1 and Heltec V3 diagnostic exports."""

from __future__ import annotations

import asyncio
import csv
import datetime as dt
import pathlib
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import zlib
from tkinter import messagebox, ttk

import serial
from serial.tools import list_ports

try:
    from bleak import BleakClient, BleakScanner

    BLE_AVAILABLE = True
except ImportError:
    BleakClient = None
    BleakScanner = None
    BLE_AVAILABLE = False

PROTOCOLS = (
    (b"===JARNSEN_DIAG_LOG_BEGIN===", b"===JARNSEN_DIAG_LOG_END==="),
    (b"===TRACKER_LOG_BEGIN===", b"===TRACKER_LOG_END==="),
)
DEVICE_NAMES = {
    "HELTEC_TRACKER_V1.1": "Tracker V1.1",
    "HELTEC_V3_REPEATER": "Heltec V3",
}
JARNSEN_DIAG_CONTROL_UUID = "8d76a200-7b49-4f39-9f9a-9b934a19a001"
JARNSEN_DIAG_DATA_UUID = "8d76a200-7b49-4f39-9f9a-9b934a19a002"

THEMES = {
    "Modern": {
        "bg": "#F3F6FA",
        "panel": "#FFFFFF",
        "panel_alt": "#EAF1F8",
        "fg": "#17212B",
        "muted": "#617081",
        "accent": "#1463D6",
        "success": "#16834A",
        "warning": "#C26A00",
        "error": "#C93434",
        "font": "Segoe UI",
        "mono": "Consolas",
        "columns": 3,
    },
    "Modern Pro": {
        "bg": "#0B1220",
        "panel": "#121D2F",
        "panel_alt": "#182741",
        "fg": "#EAF2FF",
        "muted": "#91A6C2",
        "accent": "#38BDF8",
        "success": "#3DDC97",
        "warning": "#FFB454",
        "error": "#FF6B77",
        "font": "Segoe UI Variable",
        "mono": "Cascadia Mono",
        "columns": 3,
    },
    "Retro 90er": {
        "bg": "#C0C0C0",
        "panel": "#D4D0C8",
        "panel_alt": "#FFFFFF",
        "fg": "#000000",
        "muted": "#404040",
        "accent": "#000080",
        "success": "#008000",
        "warning": "#9A4D00",
        "error": "#B00000",
        "font": "Tahoma",
        "mono": "Courier New",
        "columns": 2,
    },
    "Matrix": {
        "bg": "#020503",
        "panel": "#07110A",
        "panel_alt": "#0B1C10",
        "fg": "#7CFF94",
        "muted": "#49A75B",
        "accent": "#24FF57",
        "success": "#24FF57",
        "warning": "#E7FF4B",
        "error": "#FF4F68",
        "font": "Consolas",
        "mono": "Consolas",
        "columns": 2,
    },
}


def output_directory() -> pathlib.Path:
    downloads = pathlib.Path.home() / "Downloads"
    target = (
        downloads if downloads.exists() else pathlib.Path.home()
    ) / "Meshtastic-Logs"
    target.mkdir(parents=True, exist_ok=True)
    return target


def header_value(payload: bytes, name: bytes) -> str:
    match = re.search(rb"(?m)^# " + re.escape(name) + rb"=([^\r\n]+)", payload)
    return match.group(1).decode("utf-8", "replace").strip() if match else ""


def safe_filename(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._-")
    return value[:48] or "Node"


def log_metrics(payload: bytes) -> dict[str, str]:
    text = payload.decode("utf-8", "replace")
    latest_battery = list(re.finditer(r"\| BATTERY\s+\| ([^\r\n]+)", text))
    battery = latest_battery[-1].group(1) if latest_battery else ""

    def battery_value(name: str) -> str:
        match = re.search(rf"(?:^|\s){re.escape(name)}=([^\s]+)", battery)
        return match.group(1) if match else ""

    voltage = re.search(r"(?:^|\s)(\d+)mV(?:\s|$)", battery)
    percent = re.search(r"(?:^|\s)(\d+)%", battery)
    return {
        "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
        "node_id": header_value(payload, b"node_id"),
        "long_name": header_value(payload, b"long_name"),
        "short_name": header_value(payload, b"short_name"),
        "device": header_value(payload, b"device"),
        "firmware": header_value(payload, b"firmware"),
        "build": header_value(payload, b"build"),
        "battery_mv": voltage.group(1) if voltage else "",
        "battery_pct": percent.group(1) if percent else "",
        "capacity": battery_value("cap"),
        "confidence": battery_value("conf"),
        "tx": battery_value("tx"),
        "motion": str(len(re.findall(r"\| MOTION\s+\| confirmed", text))),
        "positions": str(len(re.findall(r"\| POSITION_TX\s+\|", text))),
    }


def update_history(payload: bytes) -> str:
    current = log_metrics(payload)
    history_path = output_directory() / "Jarnsen_Node_History.csv"
    fields = list(current)
    previous = None
    if history_path.exists():
        try:
            with history_path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            same_node = [
                row
                for row in rows
                if current["node_id"] and row.get("node_id") == current["node_id"]
            ]
            previous = same_node[-1] if same_node else None
        except (OSError, csv.Error):
            previous = None

    new_file = not history_path.exists()
    with history_path.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter=";")
        if new_file:
            writer.writeheader()
        writer.writerow(current)

    if not previous:
        return "Historie: erster Messpunkt dieser Node gespeichert"

    changes = []
    for key, label in (
        ("firmware", "Firmware"),
        ("build", "Build"),
        ("battery_mv", "Akku mV"),
        ("battery_pct", "Akku %"),
        ("capacity", "Kapazität"),
        ("confidence", "Vertrauen"),
        ("tx", "TX"),
        ("motion", "Motion"),
        ("positions", "Positionen"),
    ):
        old, new = previous.get(key, ""), current.get(key, "")
        if old and new and old != new:
            changes.append(f"{label}: {old} -> {new}")
    return "Vergleich zum letzten Log:\n" + (
        "\n".join(changes) if changes else "keine Änderung der erfassten Werte"
    )


def analyse_log(payload: bytes) -> str:
    text = payload.decode("utf-8", "replace")
    device = header_value(payload, b"device") or "unbekannt"
    firmware = header_value(payload, b"firmware") or "--"
    build = header_value(payload, b"build") or "--"
    role = header_value(payload, b"role") or "--"
    node_id = header_value(payload, b"node_id") or "--"
    long_name = header_value(payload, b"long_name") or "--"
    short_name = header_value(payload, b"short_name") or "--"
    motion = len(re.findall(r"\| MOTION\s+\| confirmed", text))
    positions = len(re.findall(r"\| POSITION_TX\s+\|", text))
    fresh = len(re.findall(r"\| POSITION_TX\s+\|.*fresh=1", text))
    boots = len(re.findall(r"\| BOOT\s+\|", text))
    latest_battery = list(re.finditer(r"\| BATTERY\s+\| ([^\r\n]+)", text))
    battery = latest_battery[-1].group(1) if latest_battery else "keine Batteriedaten"
    ina = (
        "ACTIVE"
        if "ina=ACTIVE" in text or "INA226: ACTIVE" in text
        else ("OFF" if "ina=OFF" in text else "nicht ermittelt")
    )
    warnings = []
    if "incomplete sent=" in text:
        warnings.append("historisch unvollständiger Export im Log")
    antenna_boots = re.findall(r"\| ANT_BOOT\s+\|[^\r\n]*txLock=(\d)", text)
    if antenna_boots and antenna_boots[-1] == "1":
        warnings.append("Antennen-TX-Sperre ist aktuell aktiv")
    return (
        f"Gerät: {DEVICE_NAMES.get(device, device)}\n"
        f"Node: {long_name} ({short_name})  ID: {node_id}\n"
        f"Firmware: {firmware}  Build: {build}  Rolle: {role}\n"
        f"Boot-Einträge: {boots}  Motion: {motion}  Positionen: {positions} ({fresh} frisch)\n"
        f"INA226: {ina}\nLetzte Batteriezeile: {battery}\n"
        f"Hinweise: {', '.join(warnings) if warnings else 'keine offensichtlichen Exportwarnungen'}"
    )


def diagnostic_snapshot(payload: bytes, comparison: str = "") -> dict[str, object]:
    text = payload.decode("utf-8", "replace")
    latest_battery = list(re.finditer(r"\| BATTERY\s+\| ([^\r\n]+)", text))
    battery = latest_battery[-1].group(1) if latest_battery else ""
    tokens = dict(re.findall(r"(?:^|\s)([A-Za-z][A-Za-z0-9]*)=([^\s]+)", battery))
    voltage = re.search(r"(?:^|\s)(\d+)mV(?:\s|$)", battery)
    percent = re.search(r"(?:^|\s)(\d+)%", battery)
    motion = len(re.findall(r"\| MOTION\s+\| confirmed", text))
    positions = len(re.findall(r"\| POSITION_TX\s+\|", text))
    fresh = len(re.findall(r"\| POSITION_TX\s+\|.*fresh=1", text))
    boots = len(re.findall(r"\| BOOT\s+\|", text))
    ina = (
        "ACTIVE"
        if "ina=ACTIVE" in text or "INA226: ACTIVE" in text
        else ("OFF" if "ina=OFF" in text else "--")
    )
    warnings = []
    if "incomplete sent=" in text:
        warnings.append("Historisch unvollständiger Export")
    antenna_boots = re.findall(r"\| ANT_BOOT\s+\|[^\r\n]*txLock=(\d)", text)
    if antenna_boots and antenna_boots[-1] == "1":
        warnings.append("Antennen-TX-Sperre aktiv")
    if not latest_battery:
        warnings.append("Keine Batteriedaten")

    def token(name: str, fallback: str = "--") -> str:
        return tokens.get(name, fallback)

    battery_title = "--"
    if voltage or percent:
        battery_title = " / ".join(
            value
            for value in (
                f"{int(voltage.group(1)) / 1000:.3f} V" if voltage else "",
                f"{percent.group(1)} %" if percent else "",
            )
            if value
        )
    history = comparison.replace("Vergleich zum letzten Log:\n", "").strip()
    return {
        "node": {
            "title": header_value(payload, b"long_name") or "Unbekannte Node",
            "lines": [
                f"ID  {header_value(payload, b'node_id') or '--'}",
                f"Short  {header_value(payload, b'short_name') or '--'}",
                f"Gerät  {DEVICE_NAMES.get(header_value(payload, b'device'), header_value(payload, b'device') or '--')}",
            ],
            "level": "accent",
        },
        "firmware": {
            "title": header_value(payload, b"firmware") or "--",
            "lines": [
                f"Build  {header_value(payload, b'build') or '--'}",
                f"Rolle  {header_value(payload, b'role') or '--'}",
                f"Boots  {boots}",
            ],
            "level": "normal",
        },
        "battery": {
            "title": battery_title,
            "lines": [
                f"Kapazität  {token('cap')}",
                f"Prognose  {token('est')}",
                f"Vertrauen  {token('conf')}",
            ],
            "level": (
                "warning" if percent and int(percent.group(1)) <= 20 else "success"
            ),
        },
        "power": {
            "title": f"INA226 {ina}",
            "lines": [
                f"Strom  {token('current')}",
                f"Verbrauch  {token('total')}",
                f"USB / Laden  {token('usb')} / {token('charge')}",
            ],
            "level": "success" if ina == "ACTIVE" else "warning",
        },
        "runtime": {
            "title": "Laufzeiten",
            "lines": [
                f"Bewegt / Park  {token('move')} / {token('park')}",
                f"GPS / BLE  {token('gps')} / {token('ble')}",
                f"Display / TX  {token('disp')} / {token('tx')}",
                f"Light / Deep  {token('lightSleep')} / {token('deepSleep')}",
            ],
            "level": "normal",
        },
        "events": {
            "title": f"{positions} Positionen",
            "lines": [
                f"Frisch  {fresh}",
                f"Motion  {motion}",
                f"TX-Zähler  {token('tx')}",
            ],
            "level": "success" if positions == 0 or fresh else "warning",
        },
        "health": {
            "title": (
                "Keine Warnungen" if not warnings else f"{len(warnings)} Hinweis(e)"
            ),
            "lines": warnings or ["Export und Prüfsummen plausibel"],
            "level": "success" if not warnings else "warning",
        },
        "history": {
            "title": "Historie",
            "lines": history.splitlines()[:5] if history else ["Noch kein Vergleich"],
            "level": "normal",
        },
    }


class ServiceTool(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Jarnsen Node Service Tool")
        self.geometry("1180x780")
        self.minsize(980, 680)
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.last_output: pathlib.Path | None = None
        self.last_payload: bytes | None = None
        self.last_comparison = ""
        self.expected_device = "Automatisch"
        self.status_level = "normal"
        self.port_map: dict[str, str] = {}
        self.ble_map: dict[str, object] = {}
        self.style = ttk.Style(self)
        self._build_ui()
        self.apply_theme()
        self.refresh_ports()
        self.after(100, self._pump_events)

    def _build_ui(self) -> None:
        self.root = ttk.Frame(self, padding=14)
        self.root.pack(fill="both", expand=True)
        title_row = ttk.Frame(self.root)
        title_row.pack(fill="x")
        self.title_label = ttk.Label(
            title_row, text="Jarnsen Node Service Tool", style="Title.TLabel"
        )
        self.title_label.pack(side="left")
        ttk.Label(title_row, text="Layout").pack(side="right", padx=(8, 4))
        self.theme = ttk.Combobox(
            title_row,
            state="readonly",
            values=tuple(THEMES),
            width=14,
        )
        self.theme.current(0)
        self.theme.pack(side="right")
        self.theme.bind("<<ComboboxSelected>>", lambda _event: self.apply_theme())
        ttk.Label(
            self.root,
            text="Diagnose, Verlauf und Logdownload für Tracker V1.1 und Heltec V3",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(0, 12))

        body = ttk.Panedwindow(self.root, orient="horizontal")
        body.pack(fill="both", expand=True)
        controls = ttk.Frame(body, padding=(0, 0, 12, 0), width=365)
        body.add(controls, weight=0)
        workspace = ttk.Frame(body)
        body.add(workspace, weight=1)

        setup = ttk.LabelFrame(controls, text="USB / seriell", padding=10)
        setup.pack(fill="x")
        ttk.Label(setup, text="Gerät").grid(row=0, column=0, sticky="w")
        self.device = ttk.Combobox(
            setup,
            state="readonly",
            values=("Automatisch", "Tracker V1.1", "Heltec V3"),
            width=16,
        )
        self.device.current(0)
        self.device.grid(row=1, column=0, sticky="ew", padx=(0, 6))
        ttk.Label(setup, text="COM-Port").grid(row=0, column=1, sticky="w")
        self.port = ttk.Combobox(setup, state="readonly", width=22)
        self.port.grid(row=1, column=1, sticky="ew")
        ttk.Button(setup, text="Ports aktualisieren", command=self.refresh_ports).grid(
            row=2, column=0, sticky="ew", pady=(8, 0)
        )
        ttk.Button(setup, text="Blockierer suchen", command=self.find_blocker).grid(
            row=2, column=1, sticky="ew", padx=(6, 0), pady=(8, 0)
        )
        self.start_button = ttk.Button(
            setup,
            text="USB-Port öffnen und warten",
            command=self.start_download,
            style="Primary.TButton",
        )
        self.start_button.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        setup.columnconfigure(1, weight=1)

        ble = ttk.LabelFrame(controls, text="Bluetooth Low Energy", padding=10)
        ble.pack(fill="x", pady=(10, 0))
        self.ble_device = ttk.Combobox(ble, state="readonly", width=38)
        self.ble_device.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Label(ble, text="BLE-PIN").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.ble_pin = ttk.Entry(ble, width=12)
        self.ble_pin.insert(0, "123456")
        self.ble_pin.grid(row=2, column=0, sticky="ew", padx=(0, 6))
        self.auto_repair = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            ble,
            text="Auth-Fehler automatisch reparieren",
            variable=self.auto_repair,
        ).grid(row=2, column=1, sticky="w")
        self.ble_scan_button = ttk.Button(
            ble, text="Nodes suchen", command=self.scan_ble
        )
        self.ble_scan_button.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self.ble_pair_button = ttk.Button(
            ble, text="Kopplung erneuern", command=self.repair_ble_pairing
        )
        self.ble_pair_button.grid(
            row=3, column=1, sticky="ew", padx=(6, 0), pady=(8, 0)
        )
        self.ble_download_button = ttk.Button(
            ble,
            text="BLE-Log laden",
            command=self.start_ble_download,
            style="Primary.TButton",
        )
        self.ble_download_button.grid(
            row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0)
        )
        ble.columnconfigure(1, weight=1)
        if not BLE_AVAILABLE:
            self.ble_scan_button.configure(state="disabled")
            self.ble_pair_button.configure(state="disabled")
            self.ble_download_button.configure(state="disabled")

        actions = ttk.Frame(controls)
        actions.pack(fill="x", pady=10)
        self.cancel_button = ttk.Button(
            actions, text="Abbrechen", command=self.cancel, state="disabled"
        )
        self.cancel_button.pack(side="left", fill="x", expand=True)
        ttk.Button(actions, text="Logordner öffnen", command=self.open_folder).pack(
            side="left", fill="x", expand=True, padx=(6, 0)
        )

        guide = ttk.LabelFrame(controls, text="Ablauf", padding=10)
        guide.pack(fill="x")
        self.guide = ttk.Label(
            guide,
            text="USB\n1. Port wählen und öffnen.\n"
            "2. Service > Diagnostic Log > Export via USB.\n"
            "3. HOLD: EXPORT NOW.\n\n"
            "Bluetooth\n1. Node suchen und PIN prüfen.\n"
            "2. BLE-Log laden. Der Node zeigt BT LOG DOWNLOAD.",
            justify="left",
            wraplength=330,
        )
        self.guide.pack(anchor="w")

        self.notebook = ttk.Notebook(workspace)
        self.notebook.pack(fill="both", expand=True)
        self.overview_tab = ttk.Frame(self.notebook, padding=10)
        self.details_tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(self.overview_tab, text="Übersicht")
        self.notebook.add(self.details_tab, text="Details / Rohdaten")
        self.dashboard = ttk.Frame(self.overview_tab)
        self.dashboard.pack(fill="both", expand=True)
        self.result = tk.Text(
            self.details_tab, height=13, wrap="word", font=("Consolas", 9)
        )
        self.result.pack(fill="both", expand=True)
        self.result.insert("1.0", "Noch kein Log übertragen.")
        self.result.configure(state="disabled")

        status_bar = ttk.Frame(self.root)
        status_bar.pack(fill="x", pady=(10, 0))
        self.status_badge = tk.Label(status_bar, text=" BEREIT ", padx=7, pady=2)
        self.status_badge.pack(side="left", padx=(0, 8))
        self.status = ttk.Label(status_bar, text="Bereit", style="Status.TLabel")
        self.status.pack(side="left", fill="x", expand=True)
        self.progress = ttk.Progressbar(status_bar, maximum=100, length=280)
        self.progress.pack(side="right")
        self.render_dashboard()

    def apply_theme(self) -> None:
        name = self.theme.get() if hasattr(self, "theme") else "Modern"
        palette = THEMES.get(name, THEMES["Modern"])
        retro = name == "Retro 90er"
        try:
            self.style.theme_use(
                "classic" if retro and "classic" in self.style.theme_names() else "clam"
            )
        except tk.TclError:
            self.style.theme_use("clam")
        bg, panel, fg, accent = (
            palette["bg"],
            palette["panel"],
            palette["fg"],
            palette["accent"],
        )
        font = palette["font"]
        self.configure(background=bg)
        self.style.configure(
            ".", background=bg, foreground=fg, fieldbackground=panel, font=(font, 9)
        )
        self.style.configure("TFrame", background=bg)
        self.style.configure("TLabel", background=bg, foreground=fg)
        self.style.configure(
            "Title.TLabel", background=bg, foreground=accent, font=(font, 20, "bold")
        )
        self.style.configure(
            "Subtitle.TLabel", background=bg, foreground=palette["muted"]
        )
        self.style.configure(
            "Status.TLabel", background=bg, foreground=fg, font=(font, 10, "bold")
        )
        self.style.configure(
            "TLabelframe",
            background=bg,
            foreground=fg,
            bordercolor=accent if name == "Matrix" else palette["muted"],
            relief="raised" if retro else "solid",
        )
        self.style.configure(
            "TLabelframe.Label",
            background=bg,
            foreground=accent,
            font=(font, 10, "bold"),
        )
        self.style.configure(
            "TButton", background=panel, foreground=fg, bordercolor=palette["muted"]
        )
        self.style.configure(
            "Primary.TButton",
            background=accent,
            foreground="#FFFFFF" if name != "Matrix" else "#001A05",
            font=(font, 9, "bold"),
        )
        self.style.map(
            "Primary.TButton",
            background=[("active", palette["success"]), ("disabled", panel)],
        )
        self.style.configure(
            "TCombobox",
            fieldbackground=panel,
            background=panel,
            foreground=fg,
            arrowcolor=accent,
        )
        self.style.configure("TEntry", fieldbackground=panel, foreground=fg)
        self.style.configure("TNotebook", background=bg, bordercolor=palette["muted"])
        self.style.configure(
            "TNotebook.Tab",
            background=palette["panel_alt"],
            foreground=fg,
            padding=(12, 6),
        )
        self.style.map(
            "TNotebook.Tab",
            background=[("selected", panel)],
            foreground=[("selected", accent)],
        )
        self.style.configure(
            "Horizontal.TProgressbar",
            troughcolor=palette["panel_alt"],
            background=accent,
            bordercolor=palette["muted"],
        )
        self.result.configure(
            background=palette["panel_alt"],
            foreground=fg,
            insertbackground=fg,
            selectbackground=accent,
            font=(palette["mono"], 9),
        )
        self.render_dashboard()
        self._update_status_badge()

    def render_dashboard(self) -> None:
        if not hasattr(self, "dashboard"):
            return
        for child in self.dashboard.winfo_children():
            child.destroy()
        palette = THEMES.get(self.theme.get(), THEMES["Modern"])
        if self.last_payload:
            cards = diagnostic_snapshot(self.last_payload, self.last_comparison)
        else:
            cards = {
                "welcome": {
                    "title": "Bereit für den ersten Download",
                    "lines": [
                        "USB oder Bluetooth links auswählen",
                        "Tracker V1.1 und Heltec V3 werden automatisch erkannt",
                        "Nach dem Transfer erscheinen hier Statuskarten und Verlauf",
                    ],
                    "level": "accent",
                },
                "connection": {
                    "title": "Zwei sichere Wege",
                    "lines": [
                        "USB: Port vor dem Export öffnen",
                        "BLE: PIN eingeben und Node auswählen",
                        "CRC und Übertragungslänge werden automatisch geprüft",
                    ],
                    "level": "normal",
                },
            }
        columns = int(palette["columns"])
        for index, (key, card) in enumerate(cards.items()):
            row, column = divmod(index, columns)
            frame = tk.Frame(
                self.dashboard,
                background=palette["panel"],
                highlightthickness=(
                    2 if self.theme.get() in ("Retro 90er", "Matrix") else 1
                ),
                highlightbackground=palette.get(str(card["level"]), palette["muted"]),
                bd=2 if self.theme.get() == "Retro 90er" else 0,
                relief="raised" if self.theme.get() == "Retro 90er" else "flat",
                padx=14,
                pady=12,
            )
            frame.grid(row=row, column=column, sticky="nsew", padx=5, pady=5)
            label = key.upper().replace("_", " ")
            tk.Label(
                frame,
                text=label,
                background=palette["panel"],
                foreground=palette["muted"],
                font=(
                    (
                        palette["mono"]
                        if self.theme.get() == "Matrix"
                        else palette["font"]
                    ),
                    8,
                    "bold",
                ),
            ).pack(anchor="w")
            tk.Label(
                frame,
                text=str(card["title"]),
                background=palette["panel"],
                foreground=palette.get(str(card["level"]), palette["fg"]),
                font=(palette["font"], 14, "bold"),
                wraplength=280,
                justify="left",
            ).pack(anchor="w", pady=(4, 8))
            for line in card["lines"]:
                tk.Label(
                    frame,
                    text=str(line),
                    background=palette["panel"],
                    foreground=palette["fg"],
                    font=(
                        (
                            palette["mono"]
                            if self.theme.get() == "Matrix"
                            else palette["font"]
                        ),
                        9,
                    ),
                    wraplength=300,
                    justify="left",
                ).pack(anchor="w", pady=1)
        for column in range(columns):
            self.dashboard.columnconfigure(column, weight=1, uniform="cards")
        for row in range((len(cards) + columns - 1) // columns):
            self.dashboard.rowconfigure(row, weight=1)

    def _update_status_badge(self) -> None:
        if not hasattr(self, "status_badge"):
            return
        palette = THEMES.get(self.theme.get(), THEMES["Modern"])
        colors = {
            "normal": palette["accent"],
            "success": palette["success"],
            "warning": palette["warning"],
            "error": palette["error"],
        }
        labels = {
            "normal": " STATUS ",
            "success": " OK ",
            "warning": " HINWEIS ",
            "error": " FEHLER ",
        }
        color = colors.get(self.status_level, palette["accent"])
        self.status_badge.configure(
            text=labels.get(self.status_level, " STATUS "),
            background=color,
            foreground="#FFFFFF" if self.theme.get() != "Matrix" else "#001A05",
            font=(palette["font"], 9, "bold"),
        )

    def set_result(self, text: str) -> None:
        self.result.configure(state="normal")
        self.result.delete("1.0", "end")
        self.result.insert("1.0", text)
        self.result.configure(state="disabled")

    def refresh_ports(self) -> None:
        ports = list(list_ports.comports())
        self.port_map = {f"{p.device} - {p.description}": p.device for p in ports}
        self.port["values"] = list(self.port_map)
        if ports:
            self.port.current(0)
            self.status.configure(text=f"{len(ports)} Port(s) gefunden")
        else:
            self.port.set("")
            self.status.configure(text="Kein COM-Port gefunden")

    def selected_port(self) -> str:
        return self.port_map.get(self.port.get(), "")

    def start_download(self) -> None:
        port = self.selected_port()
        if not port:
            messagebox.showerror("Kein Port", "Bitte einen COM-Port auswählen.")
            return
        if self.worker and self.worker.is_alive():
            return
        self.stop_event.clear()
        self.expected_device = self.device.get()
        self.start_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.progress["value"] = 0
        self.set_result("Warte auf Exportmarker ...")
        self.worker = threading.Thread(
            target=self._download_worker, args=(port,), daemon=True
        )
        self.worker.start()

    def scan_ble(self) -> None:
        if not BLE_AVAILABLE:
            messagebox.showerror(
                "Bluetooth nicht verfügbar",
                "Diese App-Ausgabe enthält kein Bluetooth-Modul. USB bleibt nutzbar.",
            )
            return
        if self.worker and self.worker.is_alive():
            return
        self.ble_scan_button.configure(state="disabled")
        self.status.configure(text="Suche Bluetooth-Nodes ...")
        self.worker = threading.Thread(target=self._ble_scan_worker, daemon=True)
        self.worker.start()

    def _ble_scan_worker(self) -> None:
        try:
            devices = asyncio.run(BleakScanner.discover(timeout=8.0))
            found = {}
            for device in devices:
                name = device.name or "Unbenanntes BLE-Gerät"
                found[f"{name} - {device.address}"] = device
            self.events.put(("ble_devices", found))
        except Exception as exc:
            self.events.put(("error", f"Bluetooth-Suche fehlgeschlagen: {exc}"))
        finally:
            self.events.put(("ble_scan_done", None))

    def start_ble_download(self) -> None:
        if not BLE_AVAILABLE:
            messagebox.showerror(
                "Bluetooth nicht verfügbar",
                "Diese App-Ausgabe enthält kein Bluetooth-Modul. USB bleibt nutzbar.",
            )
            return
        ble_device = self.ble_map.get(self.ble_device.get())
        if not ble_device:
            messagebox.showerror(
                "Kein Bluetooth-Gerät",
                "Bitte zuerst einen Bluetooth-Node suchen und auswählen.",
            )
            return
        if self.worker and self.worker.is_alive():
            return
        self.stop_event.clear()
        self.expected_device = self.device.get()
        self.start_button.configure(state="disabled")
        self.ble_download_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.progress["value"] = 0
        self.set_result("Verbinde per Bluetooth ...")
        pin = self.ble_pin.get().strip()
        self.worker = threading.Thread(
            target=self._ble_download_worker,
            args=(ble_device, pin, self.auto_repair.get()),
            daemon=True,
        )
        self.worker.start()

    def repair_ble_pairing(self) -> None:
        ble_device = self.ble_map.get(self.ble_device.get())
        if not ble_device:
            messagebox.showerror(
                "Kein Bluetooth-Gerät",
                "Bitte zuerst einen Bluetooth-Node suchen und auswählen.",
            )
            return
        if self.worker and self.worker.is_alive():
            return
        pin = self.ble_pin.get().strip()
        self.ble_pair_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.worker = threading.Thread(
            target=self._ble_repair_worker, args=(ble_device, pin), daemon=True
        )
        self.worker.start()

    def _ble_repair_worker(self, ble_device: object, pin: str) -> None:
        try:
            asyncio.run(self._repair_pairing_async(ble_device, pin))
            self.events.put(
                ("status_success", "Bluetooth-Kopplung authentifiziert und bereit")
            )
            self.events.put(
                (
                    "result",
                    "BLE-KOPPLUNG ERNEUERT\n\n"
                    "Der Node ist jetzt verschlüsselt und mit PIN authentifiziert.\n"
                    "Der Logdownload kann direkt gestartet werden.",
                )
            )
        except Exception as exc:
            self.events.put(("error", f"Bluetooth-Kopplung fehlgeschlagen: {exc}"))
        finally:
            self.events.put(("done", None))

    def _ble_download_worker(
        self, ble_device: object, pin: str, auto_repair: bool
    ) -> None:
        try:
            asyncio.run(self._ble_download_with_repair(ble_device, pin, auto_repair))
        except Exception as exc:
            message = str(exc)
            if self._is_authentication_error(exc):
                message = (
                    "Die BLE-Kopplung ist nicht mit dem Node-PIN authentifiziert. "
                    "PIN prüfen und 'Kopplung erneuern' wählen."
                )
            self.events.put(("error", f"Bluetooth-Download fehlgeschlagen: {message}"))
        finally:
            self.events.put(("done", None))

    @staticmethod
    def _is_authentication_error(exc: Exception) -> bool:
        message = str(exc).lower()
        return any(
            marker in message
            for marker in (
                "insufficient authentication",
                "authentication failure",
                "authentication required",
                "protection level could not be met",
                "access denied",
            )
        )

    async def _ble_download_with_repair(
        self, ble_device: object, pin: str, auto_repair: bool
    ) -> None:
        try:
            await self._ble_download_async(ble_device, pin)
        except Exception as exc:
            if not auto_repair or not self._is_authentication_error(exc):
                raise
            self.events.put(
                (
                    "status_warning",
                    "BLE-Authentifizierung veraltet - Kopplung wird einmalig erneuert",
                )
            )
            await self._repair_pairing_async(ble_device, pin)
            await self._ble_download_async(ble_device, pin)

    async def _ble_download_async(self, ble_device: object, pin: str) -> None:
        address = getattr(ble_device, "address", str(ble_device))
        self.events.put(("status", f"Verbinde verschlüsselt mit {address} ..."))
        async with BleakClient(ble_device, timeout=60.0) as client:
            await self._ensure_authenticated_pairing(client, pin)
            await client.write_gatt_char(
                JARNSEN_DIAG_CONTROL_UUID, b"START", response=True
            )
            self.events.put(
                ("status", "BT LOG DOWNLOAD - authentifiziert, Log wird gelesen")
            )
            captured = bytearray()
            expected = 0
            for _ in range(4096):
                if self.stop_event.is_set():
                    await client.write_gatt_char(
                        JARNSEN_DIAG_CONTROL_UUID, b"CANCEL", response=True
                    )
                    raise RuntimeError("Download abgebrochen")
                chunk = bytes(await client.read_gatt_char(JARNSEN_DIAG_DATA_UUID))
                if not chunk:
                    raise RuntimeError(
                        "Gerät lieferte vor dem Endmarker keine weiteren Daten"
                    )
                captured.extend(chunk)
                expected_match = re.search(rb"(?m)^# bytes=(\d+)\r?$", captured[:2048])
                if expected_match:
                    expected = int(expected_match.group(1))
                    self.events.put(
                        (
                            "progress",
                            min(99, int(len(captured) * 100 / (expected + 512))),
                        )
                    )
                if b"===JARNSEN_DIAG_LOG_END===" in captured:
                    break
                await asyncio.sleep(0.01)
            else:
                raise RuntimeError("BLE-Transfer überschritt die maximale Blockzahl")

        begin = captured.find(b"===JARNSEN_DIAG_LOG_BEGIN===")
        end = captured.find(b"===JARNSEN_DIAG_LOG_END===")
        if begin < 0 or end < 0:
            raise RuntimeError("BLE-Exportmarker fehlen")
        payload = (
            bytes(captured[begin + len(b"===JARNSEN_DIAG_LOG_BEGIN===") : end])
            .lstrip(b"\r\n")
            .rstrip(b"\r\n")
        )
        self._finish_payload(payload, expected)

    async def _repair_pairing_async(self, ble_device: object, pin: str) -> None:
        address = getattr(ble_device, "address", str(ble_device))
        self.events.put(
            ("status_warning", f"Entferne alte Windows-Kopplung für {address} ...")
        )
        client = BleakClient(ble_device, timeout=60.0)
        try:
            await client.connect()
            await client.unpair()
        except Exception as exc:
            if "already unpaired" not in str(exc).lower():
                raise
        finally:
            if client.is_connected:
                await client.disconnect()
        await asyncio.sleep(1.0)
        self.events.put(
            ("status", "Neue PIN-authentifizierte Bluetooth-Kopplung wird aufgebaut")
        )
        async with BleakClient(ble_device, timeout=60.0) as client:
            await self._ensure_authenticated_pairing(client, pin, require_new=True)

    async def _ensure_authenticated_pairing(
        self, client: object, pin: str, require_new: bool = False
    ) -> None:
        if sys.platform != "win32":
            await client.pair()
            return
        if not pin or not re.fullmatch(r"\d{6}", pin):
            raise RuntimeError("Der BLE-PIN muss genau 6 Ziffern enthalten")
        try:
            from winrt.windows.devices.enumeration import (
                DeviceInformation,
                DevicePairingKinds,
                DevicePairingProtectionLevel,
                DevicePairingResultStatus,
            )
        except ImportError as exc:
            raise RuntimeError(
                "Windows-BLE-Kopplungsmodul fehlt in dieser App-Ausgabe"
            ) from exc

        backend = getattr(client, "_backend", None)
        requester = getattr(backend, "_requester", None)
        if requester is None:
            raise RuntimeError("Windows-BLE-Verbindung ist noch nicht bereit")
        info = await DeviceInformation.create_from_id_async(
            requester.device_information.id
        )
        if info.pairing.is_paired and not require_new:
            return
        if not info.pairing.can_pair and not info.pairing.is_paired:
            raise RuntimeError("Windows meldet, dass der Node nicht koppelbar ist")

        custom = info.pairing.custom
        kinds = (
            DevicePairingKinds.CONFIRM_ONLY
            | DevicePairingKinds.PROVIDE_PIN
            | DevicePairingKinds.CONFIRM_PIN_MATCH
        )

        def accept_pairing(_sender: object, args: object) -> None:
            if args.pairing_kind == DevicePairingKinds.PROVIDE_PIN:
                args.accept_with_pin(pin)
            else:
                args.accept()

        token = custom.add_pairing_requested(accept_pairing)
        try:
            result = await custom.pair_with_protection_level_async(
                kinds, DevicePairingProtectionLevel.ENCRYPTION_AND_AUTHENTICATION
            )
        finally:
            custom.remove_pairing_requested(token)
        if result.status not in (
            DevicePairingResultStatus.PAIRED,
            DevicePairingResultStatus.ALREADY_PAIRED,
        ):
            raise RuntimeError(f"Windows-Kopplung: {result.status.name}")

    def cancel(self) -> None:
        self.stop_event.set()
        self.status.configure(text="Abbruch angefordert ...")

    def _download_worker(self, port: str) -> None:
        ser: serial.Serial | None = None
        try:
            self.events.put(("status", f"Öffne {port} ohne DTR/RTS-Reset ..."))
            ser = serial.Serial()
            ser.port = port
            ser.baudrate = 115200
            ser.timeout = 0.10
            ser.write_timeout = 1.0
            ser.rtscts = False
            ser.dsrdtr = False
            ser.dtr = False
            ser.rts = False
            ser.open()
            self.events.put(
                ("status", f"{port} offen - jetzt Export am Gerät bestätigen")
            )

            scan = bytearray()
            captured = bytearray()
            end_marker = b""
            started = False
            expected = 0
            deadline = time.monotonic() + 300
            while not self.stop_event.is_set() and time.monotonic() < deadline:
                chunk = ser.read(4096)
                if chunk:
                    scan.extend(chunk)
                if not started:
                    found = None
                    for begin, end in PROTOCOLS:
                        pos = scan.find(begin)
                        if pos >= 0:
                            found = (pos, begin, end)
                            break
                    if not found:
                        # Recovery for native USB drivers that lose only the
                        # begin marker while the following header arrives.
                        pos = scan.find(b"# device=HELTEC_")
                        if pos >= 0:
                            found = (pos, b"", PROTOCOLS[0][1])
                    if not found:
                        if len(scan) > 1024:
                            del scan[:-1024]
                        continue
                    pos, begin, end_marker = found
                    after = bytes(scan[pos + len(begin) :]).lstrip(b"\r\n")
                    scan.clear()
                    scan.extend(after)
                    started = True
                    self.events.put(("status", "Transfer erkannt"))

                header = bytes(captured[-2048:]) + bytes(scan[:4096])
                match = re.search(rb"(?m)^# bytes=(\d+)\r?$", header)
                if match:
                    expected = int(match.group(1))
                end_pos = scan.find(end_marker)
                if end_pos >= 0:
                    captured.extend(scan[:end_pos].rstrip(b"\r\n"))
                    self._finish_payload(bytes(captured), expected)
                    return
                keep = max(1, len(end_marker) - 1)
                if len(scan) > keep:
                    take = len(scan) - keep
                    captured.extend(scan[:take])
                    del scan[:take]
                if expected:
                    self.events.put(
                        ("progress", min(99, int(len(captured) * 100 / expected)))
                    )

            if started:
                captured.extend(scan)
                partial = (
                    output_directory()
                    / f"Jarnsen_Node_Log_PARTIAL_{dt.datetime.now():%Y-%m-%d_%H%M%S}.txt"
                )
                partial.write_bytes(bytes(captured))
                raise RuntimeError(f"Transfer abgebrochen. Teil-Datei: {partial}")
            raise RuntimeError(
                "Kein Exportmarker empfangen. Export am Gerät erneut bestätigen."
            )
        except serial.SerialException as exc:
            raise_text = f"Port {port} konnte nicht geöffnet werden: {exc}\nAlle Serial-Monitore schließen oder Blockersuche verwenden."
            self.events.put(("error", raise_text))
        except Exception as exc:
            self.events.put(("error", str(exc)))
        finally:
            if ser and ser.is_open:
                ser.close()
            self.events.put(("done", None))

    def _finish_payload(self, payload: bytes, expected: int) -> None:
        device = header_value(payload, b"device")
        selected = self.expected_device
        if selected == "Tracker V1.1" and device != "HELTEC_TRACKER_V1.1":
            raise RuntimeError(f"Falsches Gerät: {device or 'unbekannt'}")
        if selected == "Heltec V3" and device != "HELTEC_V3_REPEATER":
            raise RuntimeError(f"Falsches Gerät: {device or 'unbekannt'}")
        sent_match = re.search(rb"(?m)^# payload_sent=(\d+)\r?$", payload)
        sent = int(sent_match.group(1)) if sent_match else 0
        if expected and sent and sent != expected:
            partial = (
                output_directory()
                / f"Jarnsen_Node_Log_PARTIAL_{dt.datetime.now():%Y-%m-%d_%H%M%S}.txt"
            )
            partial.write_bytes(payload)
            raise RuntimeError(
                f"Teiltransfer: {sent}/{expected} Bytes. Datei: {partial}"
            )
        crc_match = re.search(rb"(?m)^# crc32=([0-9a-fA-F]{8})\r?$", payload)
        bytes_match = re.search(rb"(?m)^# bytes=(\d+)\r?$", payload)
        if crc_match and bytes_match:
            payload_start = bytes_match.end()
            while payload_start < len(payload) and payload[payload_start] in b"\r\n":
                payload_start += 1
            log_bytes = payload[
                payload_start : payload_start + int(bytes_match.group(1))
            ]
            actual_crc = zlib.crc32(log_bytes) & 0xFFFFFFFF
            expected_crc = int(crc_match.group(1), 16)
            if actual_crc != expected_crc:
                raise RuntimeError(
                    f"CRC-Fehler: {actual_crc:08x} statt {expected_crc:08x}"
                )
        long_name = header_value(payload, b"long_name") or "Node"
        node_id = header_value(payload, b"node_id").lstrip("!") or "unknown"
        label = safe_filename(DEVICE_NAMES.get(device, device or "Node"))
        output = output_directory() / (
            f"{safe_filename(long_name)}_{safe_filename(node_id)}_{label}_"
            f"Diagnostic_Log_{dt.datetime.now():%Y-%m-%d_%H%M%S}.txt"
        )
        output.write_bytes(payload)
        comparison = update_history(payload)
        self.last_output = output
        self.events.put(("progress", 100))
        self.events.put(("dashboard", (payload, comparison)))
        self.events.put(
            (
                "result",
                f"GESPEICHERT: {output}\n\n{analyse_log(payload)}\n\n{comparison}",
            )
        )
        self.events.put(("status_success", "DONE - Verbindung geschlossen"))

    def _pump_events(self) -> None:
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "status":
                    self.status_level = "normal"
                    self.status.configure(text=str(value))
                    self._update_status_badge()
                elif kind == "status_success":
                    self.status_level = "success"
                    self.status.configure(text=str(value))
                    self._update_status_badge()
                elif kind == "status_warning":
                    self.status_level = "warning"
                    self.status.configure(text=str(value))
                    self._update_status_badge()
                elif kind == "progress":
                    self.progress["value"] = int(value)
                elif kind == "result":
                    self.set_result(str(value))
                elif kind == "dashboard":
                    self.last_payload, self.last_comparison = value
                    self.render_dashboard()
                    self.notebook.select(self.overview_tab)
                elif kind == "error":
                    self.status_level = "error"
                    self.status.configure(text="FEHLER")
                    self._update_status_badge()
                    self.set_result(str(value))
                    messagebox.showerror("Logdownload fehlgeschlagen", str(value))
                elif kind == "done":
                    self.start_button.configure(state="normal")
                    self.ble_download_button.configure(state="normal")
                    self.ble_pair_button.configure(state="normal")
                    self.cancel_button.configure(state="disabled")
                elif kind == "ble_devices":
                    self.ble_map = dict(value)
                    self.ble_device["values"] = list(self.ble_map)
                    if self.ble_map:
                        self.ble_device.current(0)
                        self.status.configure(
                            text=f"{len(self.ble_map)} Bluetooth-Gerät(e) gefunden"
                        )
                    else:
                        self.status.configure(text="Keine Bluetooth-Geräte gefunden")
                elif kind == "ble_scan_done":
                    self.ble_scan_button.configure(state="normal")
        except queue.Empty:
            pass
        self.after(100, self._pump_events)

    def open_folder(self) -> None:
        path = output_directory()
        explorer = shutil.which("explorer.exe")
        if not explorer:
            messagebox.showerror("Explorer", "Windows Explorer wurde nicht gefunden.")
            return
        subprocess.Popen([explorer, str(path)])

    def find_blocker(self) -> None:
        port = self.selected_port()
        if not port:
            return
        script = (
            "$p='" + port.replace("'", "''") + "';"
            "Get-CimInstance Win32_Process | Where-Object {$_.CommandLine -match [regex]::Escape($p)} | "
            "Select-Object ProcessId,Name,CommandLine | ConvertTo-Csv -NoTypeInformation"
        )
        try:
            powershell = shutil.which("powershell.exe")
            if not powershell:
                raise RuntimeError("Windows PowerShell wurde nicht gefunden.")
            result = subprocess.run(
                [powershell, "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                timeout=10,
            )
            text = result.stdout.strip()
            if not text:
                messagebox.showinfo(
                    "Blockersuche",
                    "Kein Prozess mit dem Port in der Befehlszeile gefunden.\nArduino IDE, VS Code oder Browser bitte manuell schließen.",
                )
            else:
                self.set_result("Mögliche blockierende Prozesse:\n" + text)
        except Exception as exc:
            messagebox.showerror("Blockersuche", str(exc))


def packaged_self_test() -> int:
    report = pathlib.Path.cwd() / "Jarnsen-Node-Service-Tool-self-test.txt"
    try:
        if not BLE_AVAILABLE:
            raise RuntimeError("bleak ist nicht verfügbar")
        if set(THEMES) != {"Modern", "Modern Pro", "Retro 90er", "Matrix"}:
            raise RuntimeError("Layouts sind unvollständig")
        if sys.platform == "win32":
            from winrt.windows.devices.enumeration import (
                DeviceInformation,
                DevicePairingKinds,
            )

            if not DeviceInformation or not DevicePairingKinds.PROVIDE_PIN:
                raise RuntimeError("Windows-PIN-Kopplung ist nicht verfügbar")
        report.write_text("OK: BLE, PIN-Kopplung und vier Layouts\n", encoding="utf-8")
        return 0
    except Exception as exc:
        report.write_text(f"FEHLER: {type(exc).__name__}: {exc}\n", encoding="utf-8")
        return 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(packaged_self_test())
    ServiceTool().mainloop()
