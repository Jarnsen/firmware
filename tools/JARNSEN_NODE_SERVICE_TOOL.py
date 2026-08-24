#!/usr/bin/env python3
"""Portable Windows GUI for Tracker V1.1 and Heltec V3 diagnostic exports."""

from __future__ import annotations

import datetime as dt
import csv
import pathlib
import queue
import re
import subprocess
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import serial
from serial.tools import list_ports


PROTOCOLS = (
    (b"===JARNSEN_DIAG_LOG_BEGIN===", b"===JARNSEN_DIAG_LOG_END==="),
    (b"===TRACKER_LOG_BEGIN===", b"===TRACKER_LOG_END==="),
)
DEVICE_NAMES = {
    "HELTEC_TRACKER_V1.1": "Tracker V1.1",
    "HELTEC_V3_REPEATER": "Heltec V3",
}


def output_directory() -> pathlib.Path:
    downloads = pathlib.Path.home() / "Downloads"
    target = (downloads if downloads.exists() else pathlib.Path.home()) / "Meshtastic-Logs"
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
            same_node = [row for row in rows if current["node_id"] and row.get("node_id") == current["node_id"]]
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
        ("firmware", "Firmware"), ("build", "Build"), ("battery_mv", "Akku mV"),
        ("battery_pct", "Akku %"), ("capacity", "Kapazität"), ("confidence", "Vertrauen"),
        ("tx", "TX"), ("motion", "Motion"), ("positions", "Positionen"),
    ):
        old, new = previous.get(key, ""), current.get(key, "")
        if old and new and old != new:
            changes.append(f"{label}: {old} -> {new}")
    return "Vergleich zum letzten Log:\n" + ("\n".join(changes) if changes else "keine Änderung der erfassten Werte")


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
    ina = "ACTIVE" if "ina=ACTIVE" in text or "INA226: ACTIVE" in text else (
        "OFF" if "ina=OFF" in text else "nicht ermittelt"
    )
    warnings = []
    if "incomplete sent=" in text:
        warnings.append("unvollständiger früherer Export")
    if "ANT_LOCK       | NVS read failed" in text:
        warnings.append("Antennen-TX-Sperre wegen fehlendem NVS-Wert")
    return (
        f"Gerät: {DEVICE_NAMES.get(device, device)}\n"
        f"Node: {long_name} ({short_name})  ID: {node_id}\n"
        f"Firmware: {firmware}  Build: {build}  Rolle: {role}\n"
        f"Boot-Einträge: {boots}  Motion: {motion}  Positionen: {positions} ({fresh} frisch)\n"
        f"INA226: {ina}\nLetzte Batteriezeile: {battery}\n"
        f"Hinweise: {', '.join(warnings) if warnings else 'keine offensichtlichen Exportwarnungen'}"
    )


class ServiceTool(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Jarnsen Node Service Tool")
        self.geometry("760x590")
        self.minsize(700, 540)
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.last_output: pathlib.Path | None = None
        self.port_map: dict[str, str] = {}
        self.style = ttk.Style(self)
        self._build_ui()
        self.apply_theme()
        self.refresh_ports()
        self.after(100, self._pump_events)

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)
        title_row = ttk.Frame(root)
        title_row.pack(fill="x")
        self.title_label = ttk.Label(title_row, text="Jarnsen Node Service Tool", style="Title.TLabel")
        self.title_label.pack(side="left")
        ttk.Label(title_row, text="Layout").pack(side="right", padx=(8, 4))
        self.theme = ttk.Combobox(title_row, state="readonly", values=("Modern", "Retro 90er"), width=12)
        self.theme.current(0)
        self.theme.pack(side="right")
        self.theme.bind("<<ComboboxSelected>>", lambda _event: self.apply_theme())
        ttk.Label(root, text="Diagnoselog für Tracker V1.1 und Heltec V3").pack(anchor="w", pady=(0, 12))

        setup = ttk.LabelFrame(root, text="Verbindung", padding=10)
        setup.pack(fill="x")
        ttk.Label(setup, text="Gerät").grid(row=0, column=0, sticky="w")
        self.device = ttk.Combobox(setup, state="readonly", values=("Automatisch", "Tracker V1.1", "Heltec V3"), width=20)
        self.device.current(0)
        self.device.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        ttk.Label(setup, text="COM-Port").grid(row=0, column=1, sticky="w")
        self.port = ttk.Combobox(setup, state="readonly", width=44)
        self.port.grid(row=1, column=1, sticky="ew", padx=(0, 8))
        ttk.Button(setup, text="Aktualisieren", command=self.refresh_ports).grid(row=1, column=2)
        setup.columnconfigure(1, weight=1)

        actions = ttk.Frame(root)
        actions.pack(fill="x", pady=10)
        self.start_button = ttk.Button(actions, text="Port öffnen und warten", command=self.start_download)
        self.start_button.pack(side="left")
        self.cancel_button = ttk.Button(actions, text="Abbrechen", command=self.cancel, state="disabled")
        self.cancel_button.pack(side="left", padx=6)
        ttk.Button(actions, text="Blockierendes Programm suchen", command=self.find_blocker).pack(side="left", padx=6)
        ttk.Button(actions, text="Logordner öffnen", command=self.open_folder).pack(side="right")

        guide = ttk.LabelFrame(root, text="Ablauf am Gerät", padding=10)
        guide.pack(fill="x")
        self.guide = ttk.Label(
            guide,
            text="1. Port öffnen.  2. Am Gerät: Service -> Diagnostic Log -> Export via USB.\n"
                 "3. HOLD: EXPORT NOW lang bestätigen. Der Port wird nach DONE geschlossen.",
            justify="left",
        )
        self.guide.pack(anchor="w")

        self.status = ttk.Label(root, text="Bereit", font=("Segoe UI", 10, "bold"))
        self.status.pack(anchor="w", pady=(12, 3))
        self.progress = ttk.Progressbar(root, maximum=100)
        self.progress.pack(fill="x")

        ttk.Label(root, text="Ergebnis / Kurzanalyse").pack(anchor="w", pady=(12, 3))
        self.result = tk.Text(root, height=13, wrap="word", font=("Consolas", 9))
        self.result.pack(fill="both", expand=True)
        self.result.insert("1.0", "Noch kein Log übertragen.")
        self.result.configure(state="disabled")

    def apply_theme(self) -> None:
        retro = hasattr(self, "theme") and self.theme.get() == "Retro 90er"
        try:
            self.style.theme_use("clam" if retro else ("vista" if "vista" in self.style.theme_names() else "clam"))
        except tk.TclError:
            self.style.theme_use("clam")
        if retro:
            bg, panel, fg, accent = "#070B0A", "#101A14", "#56FF77", "#20D95B"
            self.configure(background=bg)
            self.style.configure(".", background=bg, foreground=fg, fieldbackground=panel, font=("Consolas", 9))
            self.style.configure("TFrame", background=bg)
            self.style.configure("TLabelframe", background=bg, foreground=accent, bordercolor=accent, relief="solid")
            self.style.configure("TLabelframe.Label", background=bg, foreground=accent, font=("Consolas", 10, "bold"))
            self.style.configure("TLabel", background=bg, foreground=fg)
            self.style.configure("Title.TLabel", background=bg, foreground=accent, font=("Consolas", 18, "bold"))
            self.style.configure("TButton", background=panel, foreground=fg, bordercolor=accent, focusthickness=1, focuscolor=accent)
            self.style.map("TButton", background=[("active", "#163822")], foreground=[("active", "#A0FFB0")])
            self.style.configure("TCombobox", fieldbackground=panel, background=panel, foreground=fg, arrowcolor=accent)
            self.style.configure("Horizontal.TProgressbar", troughcolor=panel, background=accent, bordercolor=accent)
            self.result.configure(background="#020503", foreground=fg, insertbackground=fg, selectbackground="#174D29", font=("Consolas", 9))
        else:
            bg, fg, accent = "#F4F7FB", "#16202A", "#1457A0"
            self.configure(background=bg)
            self.style.configure(".", font=("Segoe UI", 9))
            self.style.configure("TFrame", background=bg)
            self.style.configure("TLabel", background=bg, foreground=fg)
            self.style.configure("Title.TLabel", background=bg, foreground=accent, font=("Segoe UI", 18, "bold"))
            self.style.configure("TLabelframe", background=bg, foreground=fg)
            self.style.configure("TLabelframe.Label", background=bg, foreground=accent, font=("Segoe UI", 10, "bold"))
            self.style.configure("Horizontal.TProgressbar", background=accent)
            self.result.configure(background="white", foreground=fg, insertbackground=fg, selectbackground="#B9D6F5", font=("Consolas", 9))

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
        self.start_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.progress["value"] = 0
        self.set_result("Warte auf Exportmarker ...")
        self.worker = threading.Thread(target=self._download_worker, args=(port,), daemon=True)
        self.worker.start()

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
            self.events.put(("status", f"{port} offen - jetzt Export am Gerät bestätigen"))

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
                        if len(scan) > 1024:
                            del scan[:-1024]
                        continue
                    pos, begin, end_marker = found
                    after = bytes(scan[pos + len(begin):]).lstrip(b"\r\n")
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
                    self.events.put(("progress", min(99, int(len(captured) * 100 / expected))))

            if started:
                captured.extend(scan)
                partial = output_directory() / f"Jarnsen_Node_Log_PARTIAL_{dt.datetime.now():%Y-%m-%d_%H%M%S}.txt"
                partial.write_bytes(bytes(captured))
                raise RuntimeError(f"Transfer abgebrochen. Teil-Datei: {partial}")
            raise RuntimeError("Kein Exportmarker empfangen. Export am Gerät erneut bestätigen.")
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
        selected = self.device.get()
        if selected == "Tracker V1.1" and device != "HELTEC_TRACKER_V1.1":
            raise RuntimeError(f"Falsches Gerät: {device or 'unbekannt'}")
        if selected == "Heltec V3" and device != "HELTEC_V3_REPEATER":
            raise RuntimeError(f"Falsches Gerät: {device or 'unbekannt'}")
        sent_match = re.search(rb"(?m)^# payload_sent=(\d+)\r?$", payload)
        sent = int(sent_match.group(1)) if sent_match else 0
        if expected and sent and sent < expected:
            partial = output_directory() / f"Jarnsen_Node_Log_PARTIAL_{dt.datetime.now():%Y-%m-%d_%H%M%S}.txt"
            partial.write_bytes(payload)
            raise RuntimeError(f"Teiltransfer: {sent}/{expected} Bytes. Datei: {partial}")
        node_name = header_value(payload, b"long_name") or header_value(payload, b"short_name") or "Node"
        node_id = header_value(payload, b"node_id").lstrip("!") or "unknown"
        label = safe_filename(DEVICE_NAMES.get(device, device or "Node"))
        output = output_directory() / (
            f"{safe_filename(node_name)}_{safe_filename(node_id)}_{label}_"
            f"Diagnostic_Log_{dt.datetime.now():%Y-%m-%d_%H%M%S}.txt"
        )
        output.write_bytes(payload)
        comparison = update_history(payload)
        self.last_output = output
        self.events.put(("progress", 100))
        self.events.put(("result", f"GESPEICHERT: {output}\n\n{analyse_log(payload)}\n\n{comparison}"))
        self.events.put(("status", "DONE - Port geschlossen"))

    def _pump_events(self) -> None:
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "status":
                    self.status.configure(text=str(value))
                elif kind == "progress":
                    self.progress["value"] = int(value)
                elif kind == "result":
                    self.set_result(str(value))
                elif kind == "error":
                    self.status.configure(text="FEHLER")
                    self.set_result(str(value))
                    messagebox.showerror("Logdownload fehlgeschlagen", str(value))
                elif kind == "done":
                    self.start_button.configure(state="normal")
                    self.cancel_button.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self._pump_events)

    def open_folder(self) -> None:
        path = output_directory()
        subprocess.Popen(["explorer", str(path)])

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
            result = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True, timeout=10)
            text = result.stdout.strip()
            if not text:
                messagebox.showinfo("Blockersuche", "Kein Prozess mit dem Port in der Befehlszeile gefunden.\nArduino IDE, VS Code oder Browser bitte manuell schließen.")
            else:
                self.set_result("Mögliche blockierende Prozesse:\n" + text)
        except Exception as exc:
            messagebox.showerror("Blockersuche", str(exc))


if __name__ == "__main__":
    ServiceTool().mainloop()
