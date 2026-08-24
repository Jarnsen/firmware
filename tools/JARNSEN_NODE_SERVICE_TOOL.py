"""Portable Windows GUI for Tracker V1.1 and Heltec V3 diagnostic exports."""

# ruff: noqa: BLE001

from __future__ import annotations

import asyncio
import contextlib
import csv
import datetime as dt
import hashlib
import http.client
import itertools
import json
import math
import os
import pathlib
import queue
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import urllib.parse
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

try:
    from send2trash import send2trash

    RECYCLE_AVAILABLE = True
except ImportError:
    send2trash = None
    RECYCLE_AVAILABLE = False

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
JARNSEN_LIVE_CONTROL_UUID = "8d76a200-7b49-4f39-9f9a-9b934a19a003"
JARNSEN_LIVE_DATA_UUID = "8d76a200-7b49-4f39-9f9a-9b934a19a004"
GITHUB_REPOSITORY = "Jarnsen/firmware"
FIRMWARE_WORKFLOWS = {
    "HELTEC_TRACKER_V1.1": {
        "branch": "heltec-tracker-v11-vehicle-motion-wake",
        "workflow": "build-heltec-tracker-v11-vehicle-motion-wake.yml",
    },
    "HELTEC_V3_REPEATER": {
        "branch": "heltec-v3-repeater-light-sleep",
        "workflow": "build-heltec-v3-repeater-light-sleep.yml",
    },
}

THEMES = {
    "iOS": {
        "bg": "#F5F5F7",
        "panel": "#FFFFFF",
        "panel_alt": "#F2F2F7",
        "fg": "#1D1D1F",
        "muted": "#6E6E73",
        "accent": "#0071E3",
        "success": "#248A3D",
        "warning": "#C93400",
        "error": "#D70015",
        "font": "Segoe UI Variable",
        "mono": "Cascadia Mono",
        "columns": 2,
    },
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


def now_local() -> dt.datetime:
    return dt.datetime.now().astimezone()


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
        "timestamp": now_local().isoformat(timespec="seconds"),
        "node_id": header_value(payload, b"node_id"),
        "long_name": header_value(payload, b"long_name"),
        "short_name": header_value(payload, b"short_name"),
        "device": header_value(payload, b"device"),
        "firmware": header_value(payload, b"firmware"),
        "build": header_value(payload, b"build"),
        "battery_mv": voltage.group(1) if voltage else "",
        "battery_pct": percent.group(1) if percent else "",
        "capacity": battery_value("cap") or battery_value("capacity"),
        "confidence": battery_value("conf"),
        "tx": battery_value("tx"),
        "motion": str(len(re.findall(r"\| MOTION\s+\| confirmed", text))),
        "positions": str(len(re.findall(r"\| POSITION_TX\s+\|", text))),
    }


def normalize_node_id(value: str) -> str:
    raw = value.strip().lower().lstrip("!")
    return f"!{raw}" if raw else ""


def numeric_value(value: str) -> float | None:
    match = re.search(r"-?\d+(?:\.\d+)?", value or "")
    return float(match.group(0)) if match else None


def snapshot_metrics(payload: bytes) -> dict[str, object]:
    basic = log_metrics(payload)
    text = payload.decode("utf-8", "replace")
    battery_matches = list(re.finditer(r"\| BATTERY\s+\| ([^\r\n]+)", text))
    battery = battery_matches[-1].group(1) if battery_matches else ""
    tokens = dict(re.findall(r"(?:^|\s)([A-Za-z][A-Za-z0-9]*)=([^\s]+)", battery))

    def number(name: str) -> float | None:
        return numeric_value(tokens.get(name, ""))

    estimate = re.search(r"(?:^|\s)est=(.*?)(?:\s+ina=|\s+current=)", battery)
    remaining_secs = None
    if estimate and "learning" not in estimate.group(1).lower():
        value = estimate.group(1)
        days = (
            numeric_value(re.search(r"(\d+)d", value).group(1))
            if re.search(r"(\d+)d", value)
            else 0
        )
        hours = (
            numeric_value(re.search(r"(\d+)h", value).group(1))
            if re.search(r"(\d+)h", value)
            else 0
        )
        minutes = (
            numeric_value(re.search(r"(\d+)min", value).group(1))
            if re.search(r"(\d+)min", value)
            else 0
        )
        remaining_secs = (
            float(days or 0) * 86400
            + float(hours or 0) * 3600
            + float(minutes or 0) * 60
        )

    warning_count = int("incomplete sent=" in text)
    antenna_boots = re.findall(r"\| ANT_BOOT\s+\|[^\r\n]*txLock=(\d)", text)
    if antenna_boots and antenna_boots[-1] == "1":
        warning_count += 1
    basic.update(
        {
            "node_id": normalize_node_id(str(basic["node_id"])),
            "role": header_value(payload, b"role"),
            "remaining_secs": remaining_secs,
            "measured_secs": number("on") or number("measured"),
            "moving_secs": number("move"),
            "parked_secs": number("park"),
            "listen_secs": number("listen"),
            "service_secs": number("service"),
            "gps_secs": number("gps"),
            "ble_secs": number("ble"),
            "display_secs": number("disp"),
            "current_ma": number("current"),
            "consumed_mah": number("total") or number("used"),
            "warning_count": warning_count,
            "raw_size": len(payload),
        }
    )
    for key in (
        "battery_mv",
        "battery_pct",
        "capacity",
        "confidence",
        "tx",
        "motion",
        "positions",
    ):
        basic[key] = numeric_value(str(basic.get(key, "")))
    if basic["measured_secs"] is None:
        basic["measured_secs"] = sum(
            float(basic.get(key) or 0)
            for key in ("moving_secs", "parked_secs", "listen_secs", "service_secs")
        )
    return basic


class NodeRepository:
    """Rebuildable local catalog. Raw diagnostic logs remain the source of truth."""

    def __init__(self, directory: pathlib.Path | None = None) -> None:
        self.directory = directory or output_directory()
        self.database = self.directory / "Jarnsen_Node_Service.sqlite3"
        self._create_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _create_schema(self) -> None:
        with contextlib.closing(self._connect()) as connection, connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS nodes (
                    node_id TEXT PRIMARY KEY,
                    long_name TEXT NOT NULL DEFAULT '',
                    short_name TEXT NOT NULL DEFAULT '',
                    device TEXT NOT NULL DEFAULT '',
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    archived INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS node_names (
                    node_id TEXT NOT NULL REFERENCES nodes(node_id) ON DELETE CASCADE,
                    long_name TEXT NOT NULL,
                    short_name TEXT NOT NULL DEFAULT '',
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    PRIMARY KEY (node_id, long_name, short_name)
                );
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY,
                    node_id TEXT NOT NULL REFERENCES nodes(node_id) ON DELETE CASCADE,
                    path TEXT NOT NULL UNIQUE,
                    content_hash TEXT NOT NULL,
                    captured_at TEXT NOT NULL,
                    imported_at TEXT NOT NULL,
                    firmware TEXT NOT NULL DEFAULT '',
                    build TEXT NOT NULL DEFAULT '',
                    role TEXT NOT NULL DEFAULT '',
                    metrics_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS logs_node_time ON logs(node_id, captured_at);
                """)

    @staticmethod
    def _captured_at(path: pathlib.Path) -> str:
        match = re.search(r"(20\d{2}-\d{2}-\d{2})[_T](\d{2})(\d{2})(\d{2})", path.name)
        if match:
            return (
                f"{match.group(1)}T{match.group(2)}:{match.group(3)}:{match.group(4)}"
            )
        return (
            dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc)
            .astimezone()
            .isoformat(timespec="seconds")
        )

    def import_payload(self, payload: bytes, path: pathlib.Path) -> bool:
        metrics = snapshot_metrics(payload)
        node_id = str(metrics.get("node_id") or "")
        if not node_id or not str(metrics.get("device") or "").startswith("HELTEC_"):
            return False
        captured_at = self._captured_at(path)
        imported_at = now_local().isoformat(timespec="seconds")
        long_name = str(metrics.get("long_name") or node_id)
        short_name = str(metrics.get("short_name") or "")
        path_key = os.path.normcase(str(path.resolve()))
        digest = hashlib.sha256(payload).hexdigest()
        with contextlib.closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO nodes(node_id,long_name,short_name,device,first_seen,last_seen)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(node_id) DO UPDATE SET
                    long_name=excluded.long_name, short_name=excluded.short_name,
                    device=excluded.device, last_seen=MAX(nodes.last_seen,excluded.last_seen)
                """,
                (
                    node_id,
                    long_name,
                    short_name,
                    str(metrics["device"]),
                    captured_at,
                    captured_at,
                ),
            )
            connection.execute(
                """
                INSERT INTO node_names(node_id,long_name,short_name,first_seen,last_seen)
                VALUES(?,?,?,?,?)
                ON CONFLICT(node_id,long_name,short_name) DO UPDATE SET last_seen=MAX(last_seen,excluded.last_seen)
                """,
                (node_id, long_name, short_name, captured_at, captured_at),
            )
            connection.execute(
                """
                INSERT INTO logs(node_id,path,content_hash,captured_at,imported_at,firmware,build,role,metrics_json)
                VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(path) DO UPDATE SET
                    node_id=excluded.node_id, content_hash=excluded.content_hash,
                    captured_at=excluded.captured_at, imported_at=excluded.imported_at,
                    firmware=excluded.firmware, build=excluded.build, role=excluded.role,
                    metrics_json=excluded.metrics_json
                """,
                (
                    node_id,
                    path_key,
                    digest,
                    captured_at,
                    imported_at,
                    str(metrics.get("firmware") or ""),
                    str(metrics.get("build") or ""),
                    str(metrics.get("role") or ""),
                    json.dumps(metrics, ensure_ascii=False, separators=(",", ":")),
                ),
            )
        return True

    def scan_logs(self) -> tuple[int, int]:
        imported = skipped = 0
        for path in sorted(self.directory.glob("*.txt")):
            if "partial" in path.name.lower():
                skipped += 1
                continue
            try:
                payload = path.read_bytes()
                if self.import_payload(payload, path):
                    imported += 1
                else:
                    skipped += 1
            except (OSError, sqlite3.Error):
                skipped += 1
        return imported, skipped

    def list_nodes(self, include_archived: bool = False) -> list[sqlite3.Row]:
        query = (
            """
            SELECT n.*, COUNT(l.id) AS log_count,
                   MAX(l.firmware) FILTER (WHERE l.captured_at=(SELECT MAX(x.captured_at) FROM logs x WHERE x.node_id=n.node_id)) AS firmware
            FROM nodes n LEFT JOIN logs l ON l.node_id=n.node_id
            GROUP BY n.node_id ORDER BY n.long_name COLLATE NOCASE, n.node_id
            """
            if include_archived
            else """
            SELECT n.*, COUNT(l.id) AS log_count,
                   MAX(l.firmware) FILTER (WHERE l.captured_at=(SELECT MAX(x.captured_at) FROM logs x WHERE x.node_id=n.node_id)) AS firmware
            FROM nodes n LEFT JOIN logs l ON l.node_id=n.node_id
            WHERE n.archived=0
            GROUP BY n.node_id ORDER BY n.long_name COLLATE NOCASE, n.node_id
            """
        )
        with contextlib.closing(self._connect()) as connection, connection:
            return list(connection.execute(query))

    def logs_for_node(self, node_id: str) -> list[dict[str, object]]:
        with contextlib.closing(self._connect()) as connection, connection:
            rows = list(
                connection.execute(
                    "SELECT * FROM logs WHERE node_id=? ORDER BY captured_at",
                    (node_id,),
                )
            )
        result = []
        for row in rows:
            item = dict(row)
            item["metrics"] = json.loads(str(item.pop("metrics_json")))
            result.append(item)
        return result

    def latest_log(self, node_id: str) -> dict[str, object] | None:
        logs = self.logs_for_node(node_id)
        return logs[-1] if logs else None

    def set_archived(self, node_id: str, archived: bool) -> None:
        with contextlib.closing(self._connect()) as connection, connection:
            connection.execute(
                "UPDATE nodes SET archived=? WHERE node_id=?",
                (1 if archived else 0, node_id),
            )

    def delete_records(self, node_id: str) -> None:
        with contextlib.closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM nodes WHERE node_id=?", (node_id,))


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
        self.live_worker: threading.Thread | None = None
        self.last_output: pathlib.Path | None = None
        self.last_payload: bytes | None = None
        self.last_comparison = ""
        self.expected_device = "Automatisch"
        self.status_level = "normal"
        self.port_map: dict[str, str] = {}
        self.ble_map: dict[str, object] = {}
        self.repository = NodeRepository()
        self.firmware_cache_path = output_directory() / "Jarnsen_Firmware_Status.json"
        self.firmware_releases = self._load_firmware_cache()
        self.firmware_check_running = False
        self.selected_node_id = ""
        self.node_logs: list[dict[str, object]] = []
        self.show_archived_var = tk.BooleanVar(value=False)
        self.live_stop = threading.Event()
        self.live_commands: queue.Queue[str] = queue.Queue()
        self.live_connected = False
        self.live_snapshot: dict[str, object] = {}
        self.style = ttk.Style(self)
        self._build_ui()
        self.apply_theme()
        self.refresh_ports()
        self.repository.scan_logs()
        self.refresh_nodes()
        self.protocol("WM_DELETE_WINDOW", self.close_app)
        self.after(100, self._pump_events)
        self.after(800, self.refresh_firmware_status)

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
        self.theme.set("Modern")
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

        nodes = ttk.LabelFrame(controls, text="Nodes", padding=10)
        nodes.pack(fill="x", pady=(0, 10))
        self.node_tree = ttk.Treeview(
            nodes,
            columns=("name", "device", "id", "firmware"),
            show="headings",
            height=6,
            selectmode="browse",
        )
        self.node_tree.heading("name", text="Long Name")
        self.node_tree.heading("device", text="Typ")
        self.node_tree.heading("id", text="Node-ID")
        self.node_tree.heading("firmware", text="Software")
        self.node_tree.column("name", width=145, stretch=True)
        self.node_tree.column("device", width=65, stretch=False)
        self.node_tree.column("id", width=82, stretch=False)
        self.node_tree.column("firmware", width=75, stretch=False)
        self.node_tree.pack(fill="x")
        self.node_tree.bind("<<TreeviewSelect>>", self.on_node_selected)
        node_actions = ttk.Frame(nodes)
        node_actions.pack(fill="x", pady=(7, 0))
        ttk.Button(node_actions, text="Neu einlesen", command=self.rescan_logs).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(node_actions, text="Archivieren", command=self.archive_node).pack(
            side="left", fill="x", expand=True, padx=(5, 0)
        )
        ttk.Button(node_actions, text="Löschen …", command=self.delete_node).pack(
            side="left", fill="x", expand=True, padx=(5, 0)
        )
        self.github_button = ttk.Button(
            nodes,
            text="Firmwarestände über GitHub prüfen",
            command=self.refresh_firmware_status,
        )
        self.github_button.pack(fill="x", pady=(7, 0))
        ttk.Checkbutton(
            nodes,
            text="Archivierte Nodes anzeigen",
            variable=self.show_archived_var,
            command=self.refresh_nodes,
        ).pack(anchor="w", pady=(6, 0))

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
        ttk.Label(
            ble,
            text="Die sichere Kopplung und PIN-Eingabe erfolgen über Windows.",
            wraplength=320,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.ble_scan_button = ttk.Button(
            ble, text="Nodes suchen", command=self.scan_ble
        )
        self.ble_scan_button.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.ble_pair_button = ttk.Button(
            ble, text="Sicher koppeln", command=self.start_pairing
        )
        self.ble_pair_button.grid(
            row=2, column=1, sticky="ew", padx=(6, 0), pady=(8, 0)
        )
        self.ble_download_button = ttk.Button(
            ble,
            text="BLE-Log laden",
            command=self.start_ble_download,
            style="Primary.TButton",
        )
        ttk.Button(
            ble, text="Windows-Einstellungen", command=self.open_windows_bluetooth
        ).grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self.ble_download_button.grid(
            row=3, column=1, sticky="ew", padx=(6, 0), pady=(8, 0)
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
            "Bluetooth\n1. Node einmalig über Windows koppeln.\n"
            "2. 'Sicher koppeln' startet den Windows-PIN-Dialog.\n"
            "3. BLE-Log laden oder Live-Anzeige verbinden.\n"
            "Der Node zeigt dabei BT LOG DOWNLOAD.",
            justify="left",
            wraplength=330,
        )
        self.guide.pack(anchor="w")

        self.notebook = ttk.Notebook(workspace)
        self.notebook.pack(fill="both", expand=True)
        self.overview_tab = ttk.Frame(self.notebook, padding=10)
        self.history_tab = ttk.Frame(self.notebook, padding=10)
        self.trends_tab = ttk.Frame(self.notebook, padding=10)
        self.live_tab = ttk.Frame(self.notebook, padding=10)
        self.details_tab = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(self.overview_tab, text="Übersicht")
        self.notebook.add(self.history_tab, text="Log-Historie")
        self.notebook.add(self.trends_tab, text="Trends")
        self.notebook.add(self.live_tab, text="Live-Anzeige")
        self.notebook.add(self.details_tab, text="Details / Rohdaten")
        self.dashboard = ttk.Frame(self.overview_tab)
        self.dashboard.pack(fill="both", expand=True)
        self.result = tk.Text(
            self.details_tab, height=13, wrap="word", font=("Consolas", 9)
        )
        self.result.pack(fill="both", expand=True)
        self.result.insert("1.0", "Noch kein Log übertragen.")
        self.result.configure(state="disabled")

        history_actions = ttk.Frame(self.history_tab)
        history_actions.pack(fill="x", pady=(0, 8))
        self.history_title = ttk.Label(
            history_actions, text="Node auswählen", style="Section.TLabel"
        )
        self.history_title.pack(side="left")
        ttk.Button(
            history_actions, text="Log öffnen", command=self.open_selected_log
        ).pack(side="right")
        self.history_tree = ttk.Treeview(
            self.history_tab,
            columns=("time", "firmware", "build", "battery", "capacity", "warnings"),
            show="headings",
            selectmode="browse",
        )
        for column, label, width in (
            ("time", "Zeitpunkt", 150),
            ("firmware", "Firmware", 130),
            ("build", "Build", 90),
            ("battery", "Akku", 85),
            ("capacity", "Kapazität", 100),
            ("warnings", "Hinweise", 70),
        ):
            self.history_tree.heading(column, text=label)
            self.history_tree.column(
                column, width=width, stretch=column in ("time", "firmware")
            )
        self.history_tree.pack(fill="both", expand=True)
        self.history_tree.bind("<Double-1>", lambda _event: self.open_selected_log())

        trend_controls = ttk.Frame(self.trends_tab)
        trend_controls.pack(fill="x", pady=(0, 8))
        ttk.Label(trend_controls, text="Messwert").pack(side="left")
        self.trend_metric = ttk.Combobox(
            trend_controls,
            state="readonly",
            width=28,
            values=(
                "Batteriespannung",
                "Batteriestand",
                "Gelernte Kapazität",
                "Restlaufzeit",
                "Bewegungszeit",
                "Parkzeit",
                "Hörzeit (V3)",
                "Servicezeit (V3)",
                "GPS-Zeit",
                "BLE-Zeit",
                "Display-Zeit",
                "Position-TX",
            ),
        )
        self.trend_metric.set("Batteriespannung")
        self.trend_metric.pack(side="left", padx=(8, 0))
        self.trend_metric.bind(
            "<<ComboboxSelected>>", lambda _event: self.render_trend()
        )
        self.trend_summary = ttk.Label(
            trend_controls, text="Node auswählen", style="Subtitle.TLabel"
        )
        self.trend_summary.pack(side="right")
        self.trend_canvas = tk.Canvas(self.trends_tab, highlightthickness=0, height=440)
        self.trend_canvas.pack(fill="both", expand=True)
        self.trend_canvas.bind("<Configure>", lambda _event: self.render_trend())

        live_header = ttk.Frame(self.live_tab)
        live_header.pack(fill="x", pady=(0, 8))
        self.live_title = ttk.Label(
            live_header, text="Nicht verbunden", style="Section.TLabel"
        )
        self.live_title.pack(side="left")
        self.live_button = ttk.Button(
            live_header,
            text="Live verbinden",
            command=self.toggle_live,
            style="Primary.TButton",
        )
        self.live_button.pack(side="right")
        self.virtual_display = tk.Canvas(
            self.live_tab, height=270, highlightthickness=0
        )
        self.virtual_display.pack(fill="x")
        self.live_values = ttk.Label(
            self.live_tab,
            text="Service am Gerät öffnen und Bluetooth-Node auswählen.",
            justify="left",
        )
        self.live_values.pack(anchor="w", pady=(10, 8))
        remote = ttk.Frame(self.live_tab)
        remote.pack(fill="x")
        for label, command in (
            ("◀ Zurück", "BACK"),
            ("◀ Seite", "PREV"),
            ("▲", "UP"),
            ("OK", "SELECT"),
            ("▼", "DOWN"),
            ("Seite ▶", "NEXT"),
            ("Wecken", "WAKE"),
        ):
            ttk.Button(
                remote,
                text=label,
                command=lambda value=command: self.send_live_command(value),
            ).pack(side="left", fill="x", expand=True, padx=2)

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
            "Title.TLabel",
            background=bg,
            foreground=fg if name == "iOS" else accent,
            font=(font, 22 if name == "iOS" else 20, "bold"),
        )
        self.style.configure(
            "Subtitle.TLabel", background=bg, foreground=palette["muted"]
        )
        self.style.configure(
            "Status.TLabel", background=bg, foreground=fg, font=(font, 10, "bold")
        )
        self.style.configure(
            "Section.TLabel", background=bg, foreground=fg, font=(font, 13, "bold")
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
            "TButton",
            background=panel,
            foreground=accent if name == "iOS" else fg,
            bordercolor=palette["panel_alt"] if name == "iOS" else palette["muted"],
            relief="flat" if name == "iOS" else "raised",
            padding=(10, 7) if name == "iOS" else (6, 4),
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
        self.style.configure(
            "Treeview",
            background=panel,
            fieldbackground=panel,
            foreground=fg,
            rowheight=28 if name == "iOS" else 24,
            borderwidth=0 if name == "iOS" else 1,
        )
        self.style.configure(
            "Treeview.Heading",
            background=palette["panel_alt"],
            foreground=palette["muted"],
            font=(font, 9, "bold"),
            relief="flat" if name == "iOS" else "raised",
        )
        self.style.map(
            "Treeview",
            background=[("selected", accent)],
            foreground=[("selected", "#FFFFFF")],
        )
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
        if hasattr(self, "trend_canvas"):
            self.trend_canvas.configure(background=panel)
        if hasattr(self, "virtual_display"):
            self.virtual_display.configure(background=palette["panel_alt"])
        self.render_dashboard()
        self.render_trend()
        self.render_virtual_display()
        self._update_status_badge()

    def render_dashboard(self) -> None:
        if not hasattr(self, "dashboard"):
            return
        for child in self.dashboard.winfo_children():
            child.destroy()
        palette = THEMES.get(self.theme.get(), THEMES["Modern"])
        if self.last_payload:
            cards = diagnostic_snapshot(self.last_payload, self.last_comparison)
            firmware_card = self.firmware_card(
                header_value(self.last_payload, b"device"),
                header_value(self.last_payload, b"build"),
            )
            cards = {"softwarestand": firmware_card, **cards}
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
                        "BLE: sicher über den Windows-Systemdialog koppeln",
                        "CRC und Übertragungslänge werden automatisch geprüft",
                    ],
                    "level": "normal",
                },
            }
        columns = int(palette["columns"])
        for index, (key, card) in enumerate(cards.items()):
            row, column = divmod(index, columns)
            ios = self.theme.get() == "iOS"
            frame = tk.Frame(
                self.dashboard,
                background=palette["panel"],
                highlightthickness=(
                    0
                    if ios
                    else (2 if self.theme.get() in ("Retro 90er", "Matrix") else 1)
                ),
                highlightbackground=palette.get(str(card["level"]), palette["muted"]),
                bd=2 if self.theme.get() == "Retro 90er" else 0,
                relief="raised" if self.theme.get() == "Retro 90er" else "flat",
                padx=18 if ios else 14,
                pady=16 if ios else 12,
            )
            frame.grid(
                row=row,
                column=column,
                sticky="nsew",
                padx=7 if ios else 5,
                pady=7 if ios else 5,
            )
            label = key.replace("_", " ")
            label = label.title() if ios else label.upper()
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
                font=(palette["font"], 16 if ios else 14, "bold"),
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

    def refresh_nodes(self) -> None:
        if not hasattr(self, "node_tree"):
            return
        selected = self.selected_node_id
        for item in self.node_tree.get_children():
            self.node_tree.delete(item)
        for row in self.repository.list_nodes(self.show_archived_var.get()):
            node_id = str(row["node_id"])
            device = DEVICE_NAMES.get(str(row["device"]), str(row["device"]))
            device = (
                "Tracker"
                if "Tracker" in device
                else ("V3" if "V3" in device else device)
            )
            name = str(row["long_name"] or node_id)
            if row["archived"]:
                name = f"{name} (archiviert)"
            latest = self.repository.latest_log(node_id)
            build = str(latest["build"] or "") if latest else ""
            software = self.firmware_state(str(row["device"]), build)[0]
            self.node_tree.insert(
                "", "end", iid=node_id, values=(name, device, node_id, software)
            )
        if selected and self.node_tree.exists(selected):
            self.node_tree.selection_set(selected)
            self.node_tree.see(selected)
        elif self.node_tree.get_children():
            first = self.node_tree.get_children()[0]
            self.node_tree.selection_set(first)
            self.node_tree.focus(first)
            self.on_node_selected()

    def _load_firmware_cache(self) -> dict[str, object]:
        try:
            value = json.loads(self.firmware_cache_path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def refresh_firmware_status(self) -> None:
        if self.firmware_check_running:
            return
        self.firmware_check_running = True
        if hasattr(self, "github_button"):
            self.github_button.configure(state="disabled", text="GitHub wird geprüft …")
        threading.Thread(target=self._firmware_status_worker, daemon=True).start()

    def _firmware_status_worker(self) -> None:
        updated = dict(self.firmware_releases)
        failures = []
        for device, source in FIRMWARE_WORKFLOWS.items():
            query = urllib.parse.urlencode(
                {
                    "branch": source["branch"],
                    "status": "success",
                    "event": "push",
                    "per_page": 30,
                }
            )
            workflow = urllib.parse.quote(str(source["workflow"]), safe="._-")
            path = (
                f"/repos/{GITHUB_REPOSITORY}/actions/workflows/{workflow}/runs?{query}"
            )
            try:
                with contextlib.closing(
                    http.client.HTTPSConnection("api.github.com", timeout=12)
                ) as connection:
                    connection.request(
                        "GET",
                        path,
                        headers={
                            "Accept": "application/vnd.github+json",
                            "User-Agent": "Jarnsen-Node-Service-Tool",
                            "X-GitHub-Api-Version": "2022-11-28",
                        },
                    )
                    with contextlib.closing(connection.getresponse()) as response:
                        if response.status != 200:
                            raise RuntimeError(f"GitHub HTTP {response.status}")
                        payload = json.load(response)
                runs = [
                    {
                        "sha": str(run.get("head_sha") or "").lower(),
                        "time": str(run.get("updated_at") or ""),
                        "url": str(run.get("html_url") or ""),
                    }
                    for run in payload.get("workflow_runs", [])
                    if run.get("head_sha")
                ]
                if not runs:
                    raise RuntimeError("kein erfolgreicher Build gefunden")
                updated[device] = {
                    "runs": runs,
                    "checked_at": now_local().isoformat(timespec="seconds"),
                    "source": "GitHub",
                }
            except (
                OSError,
                ValueError,
                KeyError,
                RuntimeError,
                http.client.HTTPException,
            ) as exc:
                failures.append(f"{DEVICE_NAMES.get(device, device)}: {exc}")
        if updated:
            try:
                self.firmware_cache_path.write_text(
                    json.dumps(updated, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except OSError as exc:
                failures.append(f"Cache: {exc}")
        self.events.put(("firmware_status", (updated, failures)))

    def firmware_state(self, device: str, build: str) -> tuple[str, str, str]:
        release = self.firmware_releases.get(device)
        if not isinstance(release, dict):
            return ("nicht geprüft", "Kein GitHub-Stand verfügbar", "normal")
        runs = release.get("runs")
        if not isinstance(runs, list) or not runs:
            return ("nicht geprüft", "Kein erfolgreicher Build bekannt", "normal")
        valid_runs = [run for run in runs if isinstance(run, dict) and run.get("sha")]
        if not valid_runs:
            return ("nicht geprüft", "Kein erfolgreicher Build bekannt", "normal")
        local = build.strip().lower()
        latest = str(valid_runs[0]["sha"]).lower()
        checked = str(release.get("checked_at") or "")[:16].replace("T", " ")
        suffix = f" · geprüft {checked}" if checked else ""
        if local and latest.startswith(local):
            return (
                "aktuell",
                f"Build {local} entspricht dem letzten erfolgreichen GitHub-Build{suffix}",
                "success",
            )
        if local and any(
            str(run["sha"]).lower().startswith(local) for run in valid_runs[1:]
        ):
            return (
                "Update",
                f"Installiert {local}; verfügbar {latest[:8]}{suffix}",
                "warning",
            )
        if not local:
            return (
                "unbekannt",
                f"Im Log fehlt die Build-ID; GitHub {latest[:8]}{suffix}",
                "warning",
            )
        return (
            "abweichend",
            f"Build {local} ist keinem der letzten erfolgreichen Builds zugeordnet; GitHub {latest[:8]}{suffix}",
            "warning",
        )

    def firmware_card(self, device: str, build: str) -> dict[str, object]:
        state, detail, level = self.firmware_state(device, build)
        release = self.firmware_releases.get(device)
        runs = release.get("runs", []) if isinstance(release, dict) else []
        link = (
            str(runs[0].get("url") or "") if runs and isinstance(runs[0], dict) else ""
        )
        lines = [detail, "Vergleichsbasis: letzter erfolgreicher Firmware-Workflow"]
        if link:
            lines.append(link)
        return {
            "title": {
                "aktuell": "Firmware aktuell",
                "Update": "Update verfügbar",
                "abweichend": "Buildstand prüfen",
                "unbekannt": "Build-ID fehlt",
            }.get(state, "Noch nicht geprüft"),
            "lines": lines,
            "level": level,
        }

    def rescan_logs(self) -> None:
        imported, skipped = self.repository.scan_logs()
        self.refresh_nodes()
        self.status_level = "success"
        self.status.configure(
            text=f"{imported} Log(s) katalogisiert; {skipped} andere Datei(en) übersprungen"
        )
        self._update_status_badge()

    def on_node_selected(self, _event: object | None = None) -> None:
        selection = self.node_tree.selection()
        if not selection:
            return
        self.selected_node_id = str(selection[0])
        self.node_logs = self.repository.logs_for_node(self.selected_node_id)
        latest = self.node_logs[-1] if self.node_logs else None
        if latest:
            path = pathlib.Path(str(latest["path"]))
            try:
                payload = path.read_bytes()
                self.last_payload = payload
                self.last_output = path
                self.last_comparison = self.history_comparison(self.node_logs)
                self.set_result(
                    f"DATEI: {path}\n\n{analyse_log(payload)}\n\n{self.last_comparison}"
                )
            except OSError as exc:
                self.set_result(f"Logdatei nicht verfügbar: {exc}")
        self.refresh_history_view()
        self.render_dashboard()
        self.render_trend()

    @staticmethod
    def history_comparison(logs: list[dict[str, object]]) -> str:
        if len(logs) < 2:
            return "Historie: erster Messpunkt dieser Node"
        previous = logs[-2]["metrics"]
        current = logs[-1]["metrics"]
        changes = []
        for key, label in (
            ("firmware", "Firmware"),
            ("build", "Build"),
            ("battery_mv", "Akku mV"),
            ("battery_pct", "Akku %"),
            ("capacity", "Kapazität"),
            ("confidence", "Vertrauen"),
        ):
            old, new = previous.get(key), current.get(key)
            if old not in (None, "") and new not in (None, "") and old != new:
                changes.append(f"{label}: {old} → {new}")
        return "Vergleich zum vorherigen Download:\n" + (
            "\n".join(changes) if changes else "keine Änderung der Hauptwerte"
        )

    def refresh_history_view(self) -> None:
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)
        title = self.selected_node_id or "Node auswählen"
        if self.node_logs:
            metrics = self.node_logs[-1]["metrics"]
            title = f"{metrics.get('long_name') or title}  ·  {self.selected_node_id}  ·  {len(self.node_logs)} Log(s)"
        self.history_title.configure(text=title)
        for log in reversed(self.node_logs):
            metrics = log["metrics"]
            battery = "--"
            if metrics.get("battery_pct") is not None:
                battery = f"{float(metrics['battery_pct']):.0f} %"
            capacity = "--"
            if metrics.get("capacity") is not None:
                capacity = f"{float(metrics['capacity']):.0f} mAh"
            self.history_tree.insert(
                "",
                "end",
                iid=str(log["id"]),
                values=(
                    str(log["captured_at"]).replace("T", " "),
                    log["firmware"] or "--",
                    log["build"] or "--",
                    battery,
                    capacity,
                    int(metrics.get("warning_count") or 0),
                ),
            )

    def open_selected_log(self) -> None:
        selected = self.history_tree.selection()
        if not selected:
            messagebox.showinfo("Log-Historie", "Bitte zuerst einen Log auswählen.")
            return
        log_id = int(selected[0])
        log = next((item for item in self.node_logs if int(item["id"]) == log_id), None)
        if not log:
            return
        path = pathlib.Path(str(log["path"]))
        if not path.exists():
            messagebox.showerror("Log öffnen", "Die Logdatei ist nicht mehr vorhanden.")
            return
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            self.set_result(path.read_text(encoding="utf-8", errors="replace"))
            self.notebook.select(self.details_tab)

    def archive_node(self) -> None:
        if not self.selected_node_id:
            return
        rows = {str(row["node_id"]): row for row in self.repository.list_nodes(True)}
        row = rows.get(self.selected_node_id)
        if not row:
            return
        archived = not bool(row["archived"])
        self.repository.set_archived(self.selected_node_id, archived)
        self.status.configure(
            text=(
                "Node archiviert; Logs bleiben erhalten"
                if archived
                else "Node wiederhergestellt"
            )
        )
        self.selected_node_id = ""
        self.refresh_nodes()

    def delete_node(self) -> None:
        if not self.selected_node_id:
            return
        logs = self.repository.logs_for_node(self.selected_node_id)
        existing = [
            pathlib.Path(str(item["path"]))
            for item in logs
            if pathlib.Path(str(item["path"])).exists()
        ]
        size = sum(path.stat().st_size for path in existing)
        name = (
            str(logs[-1]["metrics"].get("long_name") or self.selected_node_id)
            if logs
            else self.selected_node_id
        )
        date_range = "--"
        if logs:
            date_range = f"{str(logs[0]['captured_at'])[:10]} bis {str(logs[-1]['captured_at'])[:10]}"
        question = (
            f"Node wirklich samt Logs entfernen?\n\n{name}\n{self.selected_node_id}\n"
            f"{len(existing)} Datei(en), {size / 1024:.1f} KiB\nZeitraum: {date_range}\n\n"
            "Die Dateien werden in den Windows-Papierkorb verschoben."
        )
        if not messagebox.askyesno("Node und Logs löschen", question, icon="warning"):
            return
        if not RECYCLE_AVAILABLE:
            messagebox.showerror(
                "Sicheres Löschen",
                "Die Papierkorb-Unterstützung fehlt in dieser App-Ausgabe.",
            )
            return
        try:
            for path in existing:
                send2trash(str(path))
            self.repository.delete_records(self.selected_node_id)
        except Exception as exc:
            messagebox.showerror(
                "Node löschen", f"Löschen nicht vollständig ausgeführt: {exc}"
            )
            return
        self.selected_node_id = ""
        self.node_logs = []
        self.last_payload = None
        self.refresh_nodes()
        self.render_dashboard()
        self.render_trend()
        self.status.configure(text="Node-Logs wurden in den Papierkorb verschoben")

    def render_trend(self) -> None:
        if not hasattr(self, "trend_canvas"):
            return
        canvas = self.trend_canvas
        canvas.delete("all")
        palette = THEMES.get(self.theme.get(), THEMES["Modern"])
        width = max(canvas.winfo_width(), 500)
        height = max(canvas.winfo_height(), 320)
        metric_map = {
            "Batteriespannung": ("battery_mv", "mV"),
            "Batteriestand": ("battery_pct", "%"),
            "Gelernte Kapazität": ("capacity", "mAh"),
            "Restlaufzeit": ("remaining_secs", "s"),
            "Bewegungszeit": ("moving_secs", "s"),
            "Parkzeit": ("parked_secs", "s"),
            "Hörzeit (V3)": ("listen_secs", "s"),
            "Servicezeit (V3)": ("service_secs", "s"),
            "GPS-Zeit": ("gps_secs", "s"),
            "BLE-Zeit": ("ble_secs", "s"),
            "Display-Zeit": ("display_secs", "s"),
            "Position-TX": ("tx", ""),
        }
        key, unit = metric_map.get(self.trend_metric.get(), ("battery_mv", "mV"))
        points = []
        for index, log in enumerate(self.node_logs):
            value = log["metrics"].get(key)
            if isinstance(value, (int, float)):
                points.append((index, float(value), str(log["captured_at"])))
        if not points:
            canvas.create_text(
                width / 2,
                height / 2,
                text="Für diesen Messwert liegen noch keine Daten vor.",
                fill=palette["muted"],
                font=(palette["font"], 12),
            )
            self.trend_summary.configure(text="Keine Trenddaten")
            return
        left, top, right, bottom = 62, 28, width - 24, height - 50
        values = [point[1] for point in points]
        minimum, maximum = min(values), max(values)
        if math.isclose(minimum, maximum):
            minimum -= max(abs(minimum) * 0.05, 1)
            maximum += max(abs(maximum) * 0.05, 1)
        canvas.create_rectangle(
            left, top, right, bottom, outline=palette["panel_alt"], width=1
        )
        for step in range(5):
            y = top + (bottom - top) * step / 4
            value = maximum - (maximum - minimum) * step / 4
            canvas.create_line(left, y, right, y, fill=palette["panel_alt"])
            canvas.create_text(
                left - 8,
                y,
                text=f"{value:.0f}",
                anchor="e",
                fill=palette["muted"],
                font=(palette["font"], 8),
            )
        coords = []
        coordinate_points = []
        for point_index, (_source_index, value, _stamp) in enumerate(points):
            x = (
                left
                if len(points) == 1
                else left + (right - left) * point_index / (len(points) - 1)
            )
            y = bottom - (value - minimum) * (bottom - top) / (maximum - minimum)
            coords.extend((x, y))
            coordinate_points.append((x, y, value))
        cumulative = key in {
            "moving_secs",
            "parked_secs",
            "listen_secs",
            "service_secs",
            "gps_secs",
            "ble_secs",
            "display_secs",
            "tx",
        }
        segment: list[float] = []
        previous_value: float | None = None
        for x, y, value in coordinate_points:
            if cumulative and previous_value is not None and value < previous_value:
                if len(segment) >= 4:
                    canvas.create_line(
                        *segment, fill=palette["accent"], width=3, smooth=True
                    )
                segment = []
            segment.extend((x, y))
            previous_value = value
        if len(segment) >= 4:
            canvas.create_line(*segment, fill=palette["accent"], width=3, smooth=True)
        for index in range(0, len(coords), 2):
            canvas.create_oval(
                coords[index] - 4,
                coords[index + 1] - 4,
                coords[index] + 4,
                coords[index + 1] + 4,
                fill=palette["accent"],
                outline=palette["panel"],
            )
        canvas.create_text(
            left,
            bottom + 22,
            text=points[0][2][:10],
            anchor="w",
            fill=palette["muted"],
            font=(palette["font"], 8),
        )
        canvas.create_text(
            right,
            bottom + 22,
            text=points[-1][2][:10],
            anchor="e",
            fill=palette["muted"],
            font=(palette["font"], 8),
        )
        if cumulative:
            delta = sum(
                current - previous if current >= previous else current
                for previous, current in itertools.pairwise(values)
            )
            change_label = "Zuwachs"
        else:
            delta = values[-1] - values[0]
            change_label = "Änderung"
        self.trend_summary.configure(
            text=f"{len(points)} Messpunkte · zuletzt {values[-1]:.0f} {unit} · {change_label} {delta:+.0f} {unit}"
        )

    def render_virtual_display(self) -> None:
        if not hasattr(self, "virtual_display"):
            return
        canvas = self.virtual_display
        canvas.delete("all")
        palette = THEMES.get(self.theme.get(), THEMES["Modern"])
        width = max(canvas.winfo_width(), 600)
        height = max(canvas.winfo_height(), 250)
        margin = 22
        canvas.create_rectangle(
            margin,
            margin,
            width - margin,
            height - margin,
            fill=palette["panel"],
            outline=palette["panel_alt"],
            width=2,
        )
        data = self.live_snapshot
        if not data:
            canvas.create_text(
                width / 2,
                height / 2 - 10,
                text="LIVE-DISPLAY",
                fill=palette["muted"],
                font=(palette["font"], 11, "bold"),
            )
            canvas.create_text(
                width / 2,
                height / 2 + 18,
                text="Noch nicht verbunden",
                fill=palette["fg"],
                font=(palette["font"], 18, "bold"),
            )
            return
        device = "Tracker V1.1" if data.get("d") == "trk" else "Heltec V3"
        page = str(data.get("p", "status")).replace("_", " ").title()
        battery = "--" if int(data.get("b", 255)) > 100 else f"{data.get('b')} %"
        canvas.create_text(
            margin + 22,
            margin + 20,
            text=device,
            anchor="w",
            fill=palette["muted"],
            font=(palette["font"], 10, "bold"),
        )
        canvas.create_text(
            width - margin - 22,
            margin + 20,
            text="SERVICE AKTIV" if data.get("s") else "SERVICE GESPERRT",
            anchor="e",
            fill=palette["success"] if data.get("s") else palette["warning"],
            font=(palette["font"], 10, "bold"),
        )
        canvas.create_text(
            margin + 22,
            margin + 62,
            text=page,
            anchor="w",
            fill=palette["fg"],
            font=(palette["font"], 25, "bold"),
        )
        canvas.create_text(
            width - margin - 22,
            margin + 62,
            text=battery,
            anchor="e",
            fill=palette["accent"],
            font=(palette["font"], 25, "bold"),
        )
        labels = [
            ("Spannung", f"{int(data.get('mv', 0)) / 1000:.3f} V"),
            ("Kapazität", f"{data.get('cp', 0)} mAh" if data.get("cp") else "Lernt"),
            ("Rest", self.format_live_duration(int(data.get("r", 0)))),
            ("On-Time", self.format_live_duration(int(data.get("on", 0)))),
        ]
        card_width = (width - 2 * margin - 56) / 4
        for index, (label, value) in enumerate(labels):
            x = margin + 22 + index * (card_width + 4)
            canvas.create_text(
                x,
                margin + 118,
                text=label,
                anchor="w",
                fill=palette["muted"],
                font=(palette["font"], 9),
            )
            canvas.create_text(
                x,
                margin + 145,
                text=value,
                anchor="w",
                fill=palette["fg"],
                font=(palette["font"], 13, "bold"),
            )

    @staticmethod
    def format_live_duration(seconds: int) -> str:
        if seconds <= 0:
            return "--"
        days, remainder = divmod(seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes = remainder // 60
        return (
            f"{days}d {hours}h"
            if days
            else (f"{hours}h {minutes}m" if hours else f"{minutes}m")
        )

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

    def start_pairing(self) -> None:
        if not BLE_AVAILABLE:
            messagebox.showerror(
                "Bluetooth nicht verfügbar",
                "Diese App-Ausgabe enthält kein Bluetooth-Modul.",
            )
            return
        ble_device = self.ble_map.get(self.ble_device.get())
        if not ble_device:
            messagebox.showinfo(
                "Bluetooth-Kopplung",
                "Bitte zuerst Nodes suchen und einen Node auswählen.",
            )
            return
        if self.worker and self.worker.is_alive():
            return
        self.ble_pair_button.configure(state="disabled")
        self.status_level = "warning"
        self.status.configure(
            text="Windows-Kopplung wird gestartet - PIN am Node ablesen"
        )
        self._update_status_badge()
        self.worker = threading.Thread(
            target=self._pair_worker, args=(ble_device,), daemon=True
        )
        self.worker.start()

    def _pair_worker(self, ble_device: object) -> None:
        try:
            asyncio.run(self._pair_async(ble_device))
            self.events.put(("paired", None))
        except Exception as exc:
            self.events.put(
                (
                    "pairing_required",
                    f"Die automatische Windows-Kopplung war nicht erfolgreich:\n\n{exc}\n\nAls Fallback werden die Windows-Bluetooth-Einstellungen geöffnet.",
                )
            )
        finally:
            self.events.put(("done", None))

    async def _pair_async(self, ble_device: object) -> None:
        self.events.put(
            ("status", "Windows-Systemdialog für sichere Kopplung wird vorbereitet ...")
        )
        async with BleakClient(ble_device, timeout=90.0, pair=True):
            self.events.put(("status", "Node sicher gekoppelt und erreichbar"))

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
        self.worker = threading.Thread(
            target=self._ble_download_worker,
            args=(ble_device,),
            daemon=True,
        )
        self.worker.start()

    def open_windows_bluetooth(self) -> None:
        if sys.platform != "win32":
            messagebox.showinfo(
                "Bluetooth-Kopplung",
                "Bitte den Node in den Bluetooth-Einstellungen des Betriebssystems koppeln.",
            )
            return
        try:
            explorer = shutil.which("explorer.exe")
            if not explorer:
                raise RuntimeError("Windows Explorer wurde nicht gefunden")
            subprocess.Popen([explorer, "ms-settings:bluetooth"])
            self.status_level = "warning"
            self.status.configure(
                text="Node jetzt in Windows koppeln; danach BLE-Log erneut laden"
            )
            self._update_status_badge()
        except Exception as exc:
            messagebox.showerror("Bluetooth-Einstellungen", str(exc))

    def _ble_download_worker(self, ble_device: object) -> None:
        try:
            asyncio.run(self._ble_download_async(ble_device))
        except Exception as exc:
            if self._is_authentication_error(exc):
                self.events.put(
                    (
                        "pairing_required",
                        (
                            "Der Node ist in Windows noch nicht korrekt gekoppelt.\n\n"
                            "Die Bluetooth-Einstellungen werden geöffnet. Dort den Node "
                            "auswählen und den am Node angezeigten PIN verwenden. Bei "
                            "einer alten Kopplung den Node zuerst aus Windows entfernen "
                            "und neu koppeln. Danach in der App erneut 'BLE-Log laden' wählen."
                        ),
                    )
                )
            else:
                self.events.put(("error", f"Bluetooth-Download fehlgeschlagen: {exc}"))
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

    async def _ble_download_async(self, ble_device: object) -> None:
        address = getattr(ble_device, "address", str(ble_device))
        self.events.put(("status", f"Verbinde verschlüsselt mit {address} ..."))
        async with BleakClient(ble_device, timeout=90.0, pair=True) as client:
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

    def toggle_live(self) -> None:
        if self.live_worker and self.live_worker.is_alive():
            self.live_stop.set()
            self.live_button.configure(text="Trenne …", state="disabled")
            return
        ble_device = self.ble_map.get(self.ble_device.get())
        if not ble_device:
            messagebox.showinfo(
                "Live-Anzeige",
                "Bitte links zuerst Bluetooth-Nodes suchen und einen Node auswählen.",
            )
            return
        if self.worker and self.worker.is_alive():
            messagebox.showinfo(
                "Live-Anzeige",
                "Bitte den laufenden Download oder Kopplungsvorgang zuerst beenden.",
            )
            return
        self.live_stop.clear()
        while not self.live_commands.empty():
            try:
                self.live_commands.get_nowait()
            except queue.Empty:
                break
        self.live_button.configure(text="Live trennen")
        self.live_title.configure(text="Verbindung wird aufgebaut …")
        self.live_worker = threading.Thread(
            target=self._live_worker, args=(ble_device,), daemon=True
        )
        self.live_worker.start()

    def _live_worker(self, ble_device: object) -> None:
        try:
            asyncio.run(self._live_async(ble_device))
        except Exception as exc:
            self.events.put(("live_error", str(exc)))
        finally:
            self.events.put(("live_disconnected", None))

    async def _live_async(self, ble_device: object) -> None:
        async with BleakClient(ble_device, timeout=90.0, pair=True) as client:
            await client.write_gatt_char(
                JARNSEN_LIVE_CONTROL_UUID, b"START", response=True
            )
            state = bytes(
                await client.read_gatt_char(JARNSEN_LIVE_CONTROL_UUID)
            ).decode("ascii", "replace")
            if state == "LOCKED":
                raise RuntimeError(
                    "Service am Gerät ist nicht geöffnet. Am Tracker/V3 zuerst das Servicefenster per Taste aktivieren."
                )
            if state != "READY":
                raise RuntimeError(
                    f"Live-Protokoll antwortet unerwartet: {state or '--'}"
                )
            self.events.put(("live_connected", None))
            while not self.live_stop.is_set():
                while True:
                    try:
                        command = self.live_commands.get_nowait()
                    except queue.Empty:
                        break
                    await client.write_gatt_char(
                        JARNSEN_LIVE_CONTROL_UUID,
                        command.encode("ascii"),
                        response=True,
                    )
                payload = bytes(await client.read_gatt_char(JARNSEN_LIVE_DATA_UUID))
                if payload:
                    self.events.put(("live_data", json.loads(payload.decode("utf-8"))))
                await asyncio.sleep(0.75)
            try:
                await client.write_gatt_char(
                    JARNSEN_LIVE_CONTROL_UUID, b"STOP", response=True
                )
            except Exception as exc:
                self.events.put(
                    ("status_warning", f"Live-Sitzung war bereits getrennt: {exc}")
                )

    def send_live_command(self, command: str) -> None:
        if not self.live_connected:
            self.status_level = "warning"
            self.status.configure(text="Live-Steuerung ist nicht verbunden")
            self._update_status_badge()
            return
        if command not in {"WAKE", "NEXT", "PREV", "UP", "DOWN", "SELECT", "BACK"}:
            return
        self.live_commands.put(command)

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
                    / f"Jarnsen_Node_Log_PARTIAL_{now_local():%Y-%m-%d_%H%M%S}.txt"
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
                / f"Jarnsen_Node_Log_PARTIAL_{now_local():%Y-%m-%d_%H%M%S}.txt"
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
            f"Diagnostic_Log_{now_local():%Y-%m-%d_%H%M%S}.txt"
        )
        output.write_bytes(payload)
        self.repository.import_payload(payload, output)
        comparison = update_history(payload)
        self.last_output = output
        self.events.put(("progress", 100))
        self.events.put(("dashboard", (payload, comparison)))
        self.events.put(
            ("nodes_refresh", normalize_node_id(header_value(payload, b"node_id")))
        )
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
                elif kind == "pairing_required":
                    self.status_level = "warning"
                    self.status.configure(text="Windows-Kopplung erforderlich")
                    self._update_status_badge()
                    self.set_result(str(value))
                    self.open_windows_bluetooth()
                    messagebox.showinfo("Bluetooth-Kopplung erforderlich", str(value))
                elif kind == "paired":
                    self.status_level = "success"
                    self.status.configure(
                        text="Sicher gekoppelt - Download und Live-Anzeige sind bereit"
                    )
                    self._update_status_badge()
                    messagebox.showinfo(
                        "Bluetooth-Kopplung",
                        "Der Node wurde über Windows sicher gekoppelt.",
                    )
                elif kind == "nodes_refresh":
                    self.selected_node_id = str(value)
                    self.refresh_nodes()
                    self.on_node_selected()
                elif kind == "firmware_status":
                    releases, failures = value
                    self.firmware_releases = dict(releases)
                    self.firmware_check_running = False
                    self.github_button.configure(
                        state="normal", text="Firmwarestände über GitHub prüfen"
                    )
                    self.refresh_nodes()
                    self.render_dashboard()
                    if failures:
                        self.status_level = "warning"
                        self.status.configure(
                            text="GitHub teilweise nicht erreichbar · Cache wird weiterverwendet"
                        )
                    else:
                        self.status_level = "success"
                        self.status.configure(
                            text="Firmwarestände mit erfolgreichen GitHub-Builds abgeglichen"
                        )
                    self._update_status_badge()
                elif kind == "live_connected":
                    self.live_connected = True
                    self.live_title.configure(
                        text="Live verbunden · sichere Service-Sitzung"
                    )
                    self.live_button.configure(text="Live trennen", state="normal")
                    self.status_level = "success"
                    self.status.configure(
                        text="LIVE - Status und sichere Navigation aktiv"
                    )
                    self._update_status_badge()
                elif kind == "live_data":
                    self.live_snapshot = dict(value)
                    self.render_virtual_display()
                    data = self.live_snapshot
                    if data.get("d") == "trk":
                        activity = (
                            f"Bewegt: {self.format_live_duration(int(data.get('mo', 0)))}   "
                            f"Park: {self.format_live_duration(int(data.get('pk', 0)))}   "
                            f"GPS: {self.format_live_duration(int(data.get('g', 0)))}"
                        )
                    else:
                        activity = (
                            f"Hören: {self.format_live_duration(int(data.get('li', 0)))}   "
                            f"Service: {self.format_live_duration(int(data.get('sv', 0)))}"
                        )
                    detail = (
                        f"Seite: {data.get('p', '--')}   Akku: {data.get('b', '--')} %   "
                        f"Kapazität: {data.get('cp', 0)} mAh   Restkapazität: {data.get('cl', 0)} mAh\n"
                        f"{activity}\n"
                        f"BLE: {self.format_live_duration(int(data.get('bl', 0)))}   "
                        f"Display: {self.format_live_duration(int(data.get('ds', 0)))}   "
                        f"Position-TX: {data.get('tx', 0)}"
                    )
                    self.live_values.configure(text=detail)
                elif kind == "live_error":
                    self.status_level = "warning"
                    self.status.configure(text="Live-Verbindung nicht verfügbar")
                    self._update_status_badge()
                    messagebox.showwarning("Live-Anzeige", str(value))
                elif kind == "live_disconnected":
                    self.live_connected = False
                    self.live_stop.clear()
                    self.live_title.configure(text="Nicht verbunden")
                    self.live_button.configure(text="Live verbinden", state="normal")
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

    def close_app(self) -> None:
        self.stop_event.set()
        self.live_stop.set()
        self.destroy()

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
                check=False,
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
        if not RECYCLE_AVAILABLE:
            raise RuntimeError("send2trash ist nicht verfügbar")
        if set(THEMES) != {
            "iOS",
            "Modern",
            "Modern Pro",
            "Retro 90er",
            "Matrix",
        }:
            raise RuntimeError("Layouts sind unvollständig")
        with tempfile.TemporaryDirectory() as temporary:
            directory = pathlib.Path(temporary)
            payload = (
                b"# device=HELTEC_TRACKER_V1.1\n# node_id=!1234abcd\n# long_name=Test Node\n"
                b"# short_name=TEST\n# firmware=2.8.0.test\n# build=deadbeef\n# role=TAK\n"
                b"0 | BATTERY | 4010mV 80% usb=0 charge=0 est=1d 02h 03min ina=OFF "
                b"current=0.0mA total=0.0mAh cap=12500mAh conf=80% move=10s park=20s gps=3s ble=4s disp=5s tx=6\n"
            )
            path = directory / "Test_Node_1234abcd_Tracker_2026-08-24_120000.txt"
            path.write_bytes(payload)
            repository = NodeRepository(directory)
            if not repository.import_payload(payload, path):
                raise RuntimeError("Testlog wurde nicht importiert")
            nodes = repository.list_nodes()
            if (
                len(nodes) != 1
                or nodes[0]["node_id"] != "!1234abcd"
                or nodes[0]["long_name"] != "Test Node"
            ):
                raise RuntimeError("Node-Zuordnung nach ID ist fehlerhaft")
        report.write_text(
            "OK: BLE, Papierkorb, Datenbank und fünf Layouts\n", encoding="utf-8"
        )
        return 0
    except Exception as exc:
        report.write_text(f"FEHLER: {type(exc).__name__}: {exc}\n", encoding="utf-8")
        return 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(packaged_self_test())
    ServiceTool().mainloop()
