"""Portable Windows GUI for Tracker V1.1 and Heltec V3 diagnostic exports."""

# ruff: noqa: BLE001

from __future__ import annotations

import asyncio
import contextlib
import csv
import datetime as dt
import hashlib
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
import urllib.error
import urllib.request
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
MESH_SERVICE_UUID = "6ba1b218-15a8-461f-9fa8-5dcae273eafd"
JARNSEN_DIAG_CONTROL_UUID = "8d76a200-7b49-4f39-9f9a-9b934a19a001"
JARNSEN_DIAG_DATA_UUID = "8d76a200-7b49-4f39-9f9a-9b934a19a002"
JARNSEN_LIVE_CONTROL_UUID = "8d76a200-7b49-4f39-9f9a-9b934a19a003"
JARNSEN_LIVE_DATA_UUID = "8d76a200-7b49-4f39-9f9a-9b934a19a004"
OTABT_SERVICE_UUID = "4fafc201-1fb5-459e-8fcc-c5c9c331914b"
OTABT_TX_UUID = "62ec0272-3ec5-11eb-b378-0242ac130003"
OTABT_WRITE_UUID = "62ec0272-3ec5-11eb-b378-0242ac130005"
OTABT_STALL_SECONDS = 180.0
GITHUB_REPOSITORY = "Jarnsen/firmware"
FIRMWARE_WORKFLOWS = {
    "HELTEC_TRACKER_V1.1",
    "HELTEC_V3_REPEATER",
}
OTABT_RELEASES = {
    "V3": {
        "tag": "jarnsen-v3-latest",
        "manifest": "heltec-v3-repeater-light-sleep.ota.json",
        "device": "HELTEC_V3_REPEATER",
    },
    "TRACKER": {
        "tag": "jarnsen-tracker-latest",
        "manifest": "heltec-tracker-v11-vehicle-motion-wake.ota.json",
        "device": "HELTEC_TRACKER_V1.1",
    },
}
OTABT_HARDWARE_CODES = {
    43: "V3",
    48: "TRACKER",
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


def parse_track_points(payload: bytes | None) -> list[dict[str, object]]:
    """Read the movement-filtered TRACK_POINT breadcrumbs from a diagnostic log."""
    if not payload:
        return []
    text = payload.decode("utf-8", "replace")
    points: list[dict[str, object]] = []
    seen: set[tuple[int, int, int]] = set()
    for match in re.finditer(
        r"(?m)^[^|\r\n]+\|\s*TRACK_POINT\s*\|\s*(?P<detail>[^\r\n]+)$",
        text,
    ):
        detail = match.group("detail")
        lat_match = re.search(r"(?:^|\s)lat=(-?\d+(?:\.\d+)?)", detail)
        lon_match = re.search(r"(?:^|\s)lon=(-?\d+(?:\.\d+)?)", detail)
        epoch_match = re.search(r"(?:^|\s)epoch=(\d+)", detail)
        source_match = re.search(r"(?:^|\s)source=([A-Za-z0-9_-]+)", detail)
        accuracy_match = re.search(r"(?:^|\s)acc=(\d+)mm", detail)
        mgrs_match = re.search(r"(?:^|\s)mgrs=(.*?)\s+source=", detail)
        if not (lat_match and lon_match and epoch_match):
            continue
        latitude = float(lat_match.group(1))
        longitude = float(lon_match.group(1))
        epoch = int(epoch_match.group(1))
        if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
            continue
        key = (round(latitude * 10_000_000), round(longitude * 10_000_000), epoch)
        if key in seen:
            continue
        seen.add(key)
        points.append(
            {
                "latitude": latitude,
                "longitude": longitude,
                "epoch": epoch,
                "mgrs": mgrs_match.group(1).strip() if mgrs_match else "---",
                "source": source_match.group(1) if source_match else "unknown",
                "accuracy_mm": int(accuracy_match.group(1)) if accuracy_match else 0,
            }
        )
    return points


def geographic_distance_m(
    latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float
) -> float:
    lat_a = math.radians(latitude_a)
    lat_b = math.radians(latitude_b)
    delta_lat = lat_b - lat_a
    delta_lon = math.radians(longitude_b - longitude_a)
    x = delta_lon * math.cos((lat_a + lat_b) / 2.0)
    return math.hypot(delta_lat, x) * 6_371_000.0


def safe_filename(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._-")
    return value[:48] or "Node"


def current_battery_line(text: str) -> str:
    live = list(re.finditer(r"(?m)^LIVE \| BATTERY\s+\| ([^\r\n]+)", text))
    if live:
        return live[-1].group(1)
    historical = list(re.finditer(r"\| BATTERY\s+\| ([^\r\n]+)", text))
    return historical[-1].group(1) if historical else ""


def log_metrics(payload: bytes) -> dict[str, str]:
    text = payload.decode("utf-8", "replace")
    battery = current_battery_line(text)

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
        "confidence": battery_value("conf") or battery_value("confidence"),
        "tx": battery_value("tx"),
        "motion": str(len(re.findall(r"\| MOTION\s+\| confirmed", text))),
        "positions": str(
            len(
                re.findall(
                    r"\| (?:POSITION_TX|POSITION_AUTO|POSITION_MAN)\s+\|", text
                )
            )
        ),
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
    battery = current_battery_line(text)
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
    is_v3 = device == "HELTEC_V3_REPEATER"
    motion = len(re.findall(r"\| MOTION\s+\| confirmed", text))
    if is_v3:
        automatic_positions = len(re.findall(r"\| POSITION_AUTO\s+\|", text))
        manual_positions = len(re.findall(r"\| POSITION_MAN\s+\|", text))
        positions = automatic_positions + manual_positions
        fresh = automatic_positions
    else:
        automatic_positions = 0
        manual_positions = 0
        positions = len(re.findall(r"\| POSITION_TX\s+\|", text))
        fresh = len(re.findall(r"\| POSITION_TX\s+\|.*fresh=1", text))
    boots = len(re.findall(r"\| BOOT\s+\|", text))
    battery = current_battery_line(text) or "keine Batteriedaten"
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
    battery = current_battery_line(text)
    latest_battery = bool(battery)
    tokens = dict(re.findall(r"(?:^|\s)([A-Za-z][A-Za-z0-9]*)=([^\s]+)", battery))
    voltage = re.search(r"(?:^|\s)(\d+)mV(?:\s|$)", battery)
    percent = re.search(r"(?:^|\s)(\d+)%", battery)
    device = header_value(payload, b"device")
    is_v3 = device == "HELTEC_V3_REPEATER"
    motion = len(re.findall(r"\| MOTION\s+\| confirmed", text))
    if is_v3:
        automatic_positions = len(re.findall(r"\| POSITION_AUTO\s+\|", text))
        manual_positions = len(re.findall(r"\| POSITION_MAN\s+\|", text))
        positions = automatic_positions + manual_positions
        fresh = automatic_positions
    else:
        automatic_positions = 0
        manual_positions = 0
        positions = len(re.findall(r"\| POSITION_TX\s+\|", text))
        fresh = len(re.findall(r"\| POSITION_TX\s+\|.*fresh=1", text))
    boots = len(re.findall(r"\| BOOT\s+\|", text))
    ina = (
        "ACTIVE"
        if "ina=ACTIVE" in text or "INA226: ACTIVE" in text
        else (
            "OFF"
            if "ina=OFF" in text or "INA226: OFF" in text or "INA226 --" in text
            else "--"
        )
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

    def first_token(*names: str, fallback: str = "--") -> str:
        for name in names:
            if name in tokens:
                return tokens[name]
        return fallback

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
                f"Kapazität  {('nicht verfügbar (INA226)' if is_v3 and ina == 'OFF' else first_token('cap', 'capacity'))}",
                f"Prognose  {token('est')}",
                f"Vertrauen  {('nicht verfügbar' if is_v3 and ina == 'OFF' else first_token('conf', 'confidence'))}",
            ],
            "level": (
                "warning" if percent and int(percent.group(1)) <= 20 else "success"
            ),
        },
        "power": {
            "title": f"INA226 {ina}",
            "lines": [
                f"Strom  {token('current')}",
                f"Verbrauch  {first_token('total', 'used')}",
                f"USB / Laden  {token('usb')} / {token('charge')}",
            ],
            "level": "success" if ina == "ACTIVE" else "warning",
        },
        "runtime": {
            "title": "Laufzeiten",
            "lines": (
                [
                    f"Funk hören / Service  {token('listen')} / {token('service')}",
                    f"BLE / Display  {token('ble')} / {token('disp')}",
                    f"Messzeit  {first_token('on', 'measured')}",
                    f"Position-TX  {token('tx')}",
                ]
                if is_v3
                else [
                    f"Bewegt / Park  {token('move')} / {token('park')}",
                    f"GPS / BLE  {token('gps')} / {token('ble')}",
                    f"Display / TX  {token('disp')} / {token('tx')}",
                    f"Light / Deep  {token('lightSleep')} / {token('deepSleep')}",
                ]
            ),
            "level": "normal",
        },
        "events": {
            "title": (
                f"{first_token('auto', fallback=str(automatic_positions))} automatisch / "
                f"{first_token('manual', fallback=str(manual_positions))} manuell"
                if is_v3
                else f"{positions} Positionen"
            ),
            "lines": (
                [
                    f"Automatisch  {first_token('auto', fallback=str(automatic_positions))}",
                    f"Manuell  {first_token('manual', fallback=str(manual_positions))}",
                    f"TX-Zähler  {token('tx')}",
                ]
                if is_v3
                else [
                    f"Frisch  {fresh}",
                    f"Motion  {motion}",
                    f"TX-Zähler  {token('tx')}",
                ]
            ),
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
        self.geometry("1240x860")
        self.minsize(1000, 720)
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
        self.live_image: tk.PhotoImage | None = None
        self.style = ttk.Style(self)
        self.track_points: list[dict[str, object]] = []
        self.track_view: tuple[float, float, float, float, float] | None = None
        self._build_ui()
        self.apply_theme()
        self.refresh_ports()
        self.repository.scan_logs()
        self.refresh_nodes()
        self.protocol("WM_DELETE_WINDOW", self.close_app)
        self.after_idle(self._maximize_window)
        self.after(100, self._pump_events)
        self.after(800, self.refresh_firmware_status)

    def _maximize_window(self) -> None:
        try:
            if sys.platform == "win32":
                self.state("zoomed")
            else:
                self.attributes("-zoomed", True)
        except tk.TclError:
            self.geometry(f"{self.winfo_screenwidth()}x{self.winfo_screenheight()}+0+0")

    def _build_ui(self) -> None:
        self.root = ttk.Frame(self, padding=10)
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
        ).pack(anchor="w", pady=(0, 6))

        status_bar = ttk.Frame(self.root)
        status_bar.pack(fill="x", pady=(0, 8))
        self.status_badge = tk.Label(status_bar, text=" BEREIT ", padx=7, pady=2)
        self.status_badge.pack(side="left", padx=(0, 8))
        self.status = ttk.Label(status_bar, text="Bereit", style="Status.TLabel")
        self.status.pack(side="left", fill="x", expand=True)
        ttk.Label(status_bar, text="Download").pack(side="left", padx=(8, 6))
        self.progress = ttk.Progressbar(status_bar, maximum=100, length=340)
        self.progress.pack(side="left")
        self.progress_percent = ttk.Label(
            status_bar, text="0 %", width=5, anchor="e", style="Status.TLabel"
        )
        self.progress_percent.pack(side="left", padx=(6, 8))
        self.progress_text = ttk.Label(status_bar, text="Bereit", width=30)
        self.progress_text.pack(side="left")

        body = ttk.Panedwindow(self.root, orient="horizontal")
        body.pack(fill="both", expand=True)
        controls = ttk.Frame(body, padding=(0, 0, 12, 0), width=365)
        body.add(controls, weight=0)
        workspace = ttk.Frame(body)
        body.add(workspace, weight=1)

        nodes = ttk.LabelFrame(controls, text="Nodes", padding=6)
        nodes.pack(fill="x", pady=(0, 6))
        self.node_tree = ttk.Treeview(
            nodes,
            columns=("name", "device", "id", "firmware"),
            show="headings",
            height=4,
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
        node_actions.pack(fill="x", pady=(4, 0))
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
        self.github_button.pack(fill="x", pady=(4, 0))
        ttk.Checkbutton(
            nodes,
            text="Archivierte Nodes anzeigen",
            variable=self.show_archived_var,
            command=self.refresh_nodes,
        ).pack(anchor="w", pady=(3, 0))

        setup = ttk.LabelFrame(controls, text="USB / seriell", padding=6)
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

        ble = ttk.LabelFrame(controls, text="Bluetooth Low Energy", padding=6)
        ble.pack(fill="x", pady=(6, 0))
        self.ble_device = tk.Listbox(
            ble,
            height=3,
            selectmode="extended",
            exportselection=False,
            activestyle="dotbox",
        )
        self.ble_device.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.ble_count_label = ttk.Label(
            ble,
            text="Noch nicht gesucht",
            style="Subtitle.TLabel",
        )
        self.ble_count_label.grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(5, 0)
        )
        ttk.Label(
            ble,
            text="Mehrere Nodes mit Strg/Umschalt markieren. Downloads laufen nacheinander.",
            wraplength=320,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(5, 0))
        self.ble_scan_button = ttk.Button(
            ble, text="Nodes suchen", command=self.scan_ble
        )
        self.ble_scan_button.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self.ble_pair_button = ttk.Button(
            ble, text="In Windows koppeln", command=self.start_pairing
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
        ttk.Button(
            ble, text="Windows-Einstellungen", command=self.open_windows_bluetooth
        ).grid(row=4, column=0, sticky="ew", pady=(8, 0))
        self.ble_download_button.grid(
            row=4, column=1, sticky="ew", padx=(6, 0), pady=(8, 0)
        )
        self.ble_update_button = ttk.Button(
            ble,
            text="Firmware über Bluetooth aktualisieren",
            command=self.start_ble_update,
            style="Primary.TButton",
        )
        self.ble_update_button.grid(
            row=5, column=0, columnspan=2, sticky="ew", pady=(8, 0)
        )
        ble.columnconfigure(1, weight=1)
        if not BLE_AVAILABLE:
            self.ble_scan_button.configure(state="disabled")
            self.ble_pair_button.configure(state="disabled")
            self.ble_download_button.configure(state="disabled")
            self.ble_update_button.configure(state="disabled")

        actions = ttk.Frame(controls)
        actions.pack(fill="x", pady=6)
        self.cancel_button = ttk.Button(
            actions, text="Abbrechen", command=self.cancel, state="disabled"
        )
        self.cancel_button.pack(side="left", fill="x", expand=True)
        ttk.Button(actions, text="Logordner öffnen", command=self.open_folder).pack(
            side="left", fill="x", expand=True, padx=(6, 0)
        )

        guide = ttk.LabelFrame(controls, text="Kurzablauf", padding=6)
        guide.pack(fill="x")
        self.guide = ttk.Label(
            guide,
            text="USB: Port öffnen → Export am Gerät starten.\n"
            "BLE: suchen → Node(s) markieren → Log laden. Live: genau eine Node.",
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
        self.track_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.insert(3, self.track_tab, text="Positionskarte")
        overview_body = ttk.Frame(self.overview_tab)
        overview_body.pack(fill="both", expand=True)
        self.dashboard_canvas = tk.Canvas(overview_body, highlightthickness=0)
        self.dashboard_canvas.pack(fill="both", expand=True)
        self.dashboard = ttk.Frame(self.dashboard_canvas)
        self.dashboard_window = self.dashboard_canvas.create_window(
            (0, 0), window=self.dashboard, anchor="nw"
        )
        self.dashboard.bind(
            "<Configure>",
            lambda _event: self.dashboard_canvas.configure(
                scrollregion=self.dashboard_canvas.bbox("all")
            ),
        )
        self.dashboard_canvas.bind("<Configure>", self._resize_dashboard)
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

        track_header = ttk.Frame(self.track_tab)
        track_header.pack(fill="x", pady=(0, 8))
        self.track_summary = ttk.Label(
            track_header,
            text="Node oder Log auswählen",
            style="Section.TLabel",
        )
        self.track_summary.pack(side="left")
        ttk.Button(
            track_header, text="Alle Punkte", command=self.fit_track_map
        ).pack(side="right")
        ttk.Button(
            track_header, text="−", width=3, command=lambda: self.zoom_track_map(1.4)
        ).pack(side="right", padx=(5, 0))
        ttk.Button(
            track_header, text="+", width=3, command=lambda: self.zoom_track_map(0.7)
        ).pack(side="right", padx=(5, 0))
        self.track_canvas = tk.Canvas(
            self.track_tab, highlightthickness=1, height=500
        )
        self.track_canvas.pack(fill="both", expand=True)
        self.track_canvas.bind(
            "<Configure>", lambda _event: self.render_track_map()
        )
        self.track_canvas.bind("<Button-1>", self.select_track_point)
        self.track_canvas.bind(
            "<MouseWheel>",
            lambda event: self.zoom_track_map(0.82 if event.delta > 0 else 1.22),
        )
        self.track_info = ttk.Label(
            self.track_tab,
            text="Grün: Start · Rot: letzter Punkt · Klick zeigt MGRS und Zeit",
            justify="left",
        )
        self.track_info.pack(anchor="w", pady=(8, 0))

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
            self.live_tab, height=390, highlightthickness=0
        )
        self.virtual_display.pack(fill="both", expand=True)
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

        self.render_dashboard()
        self.render_track_map()

    def _resize_dashboard(self, event: tk.Event) -> None:
        self.dashboard_canvas.itemconfigure(self.dashboard_window, width=event.width)
        self.after_idle(self.render_dashboard)

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
        if hasattr(self, "ble_device"):
            self.ble_device.configure(
                background=panel,
                foreground=fg,
                selectbackground=accent,
                selectforeground="#FFFFFF" if name != "Matrix" else "#001A05",
                highlightbackground=palette["muted"],
                highlightcolor=accent,
            )
        if hasattr(self, "trend_canvas"):
            self.trend_canvas.configure(background=panel)
        if hasattr(self, "track_canvas"):
            self.track_canvas.configure(
                background=palette["panel_alt"],
                highlightbackground=palette["muted"],
            )
        if hasattr(self, "dashboard_canvas"):
            self.dashboard_canvas.configure(background=bg)
        if hasattr(self, "virtual_display"):
            self.virtual_display.configure(background=palette["panel_alt"])
        self.render_dashboard()
        self.render_trend()
        self.render_track_map()
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
        available_width = max(
            (
                self.dashboard_canvas.winfo_width()
                if hasattr(self, "dashboard_canvas")
                else self.dashboard.winfo_width()
            ),
            420,
        )
        columns = 3 if available_width >= 1050 else (2 if available_width >= 700 else 1)
        card_wrap = max(250, int(available_width / columns) - 70)
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
                padx=12 if ios else 9,
                pady=10 if ios else 7,
            )
            frame.grid(
                row=row,
                column=column,
                sticky="nsew",
                padx=5 if ios else 4,
                pady=5 if ios else 4,
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
                font=(palette["font"], 14 if ios else 13, "bold"),
                wraplength=card_wrap,
                justify="left",
            ).pack(anchor="w", pady=(2, 5))
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
                    wraplength=card_wrap,
                    justify="left",
                ).pack(anchor="w", pady=1)
        for column in range(columns):
            self.dashboard.columnconfigure(column, weight=1, uniform="cards")
        for row in range((len(cards) + columns - 1) // columns):
            self.dashboard.rowconfigure(row, weight=0)

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

    def set_transfer_progress(
        self, value: int | None, text: str, indeterminate: bool = False
    ) -> None:
        self.progress.stop()
        self.progress.configure(
            mode="indeterminate" if indeterminate else "determinate"
        )
        if indeterminate:
            self.progress.start(12)
            self.progress_percent.configure(text="…")
        else:
            percent = max(0, min(100, int(value or 0)))
            self.progress["value"] = percent
            self.progress_percent.configure(text=f"{percent} %")
        self.progress_text.configure(text=text)

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
        for device in FIRMWARE_WORKFLOWS:
            try:
                if device == "HELTEC_TRACKER_V1.1":
                    # Both endpoints are fixed HTTPS literals; no user-controlled
                    # scheme or host can reach urlopen.
                    response = urllib.request.urlopen(  # nosec B310  # nosemgrep
                        "https://api.github.com/repos/Jarnsen/firmware/actions/workflows/build-heltec-tracker-v11-vehicle-motion-wake.yml/runs?branch=heltec-tracker-v11-vehicle-motion-wake&status=success&event=push&per_page=30",
                        timeout=12,
                    )
                else:
                    response = urllib.request.urlopen(  # nosec B310  # nosemgrep
                        "https://api.github.com/repos/Jarnsen/firmware/actions/workflows/build-heltec-v3-repeater-light-sleep.yml/runs?branch=heltec-v3-repeater-light-sleep&status=success&event=push&per_page=30",
                        timeout=12,
                    )
                with contextlib.closing(response):
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
                urllib.error.URLError,
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
        self.last_payload = None
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
        self.update_track_points()

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
        self.track_points = []
        self.track_view = None
        self.refresh_nodes()
        self.render_dashboard()
        self.render_trend()
        self.render_track_map()
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

    def update_track_points(self) -> None:
        self.track_points = parse_track_points(self.last_payload)
        self.track_view = None
        if self.track_points:
            self.fit_track_map()
            self.show_track_point(len(self.track_points) - 1)
        else:
            self.render_track_map()
            if hasattr(self, "track_info"):
                self.track_info.configure(
                    text=(
                        "Noch keine >25-m-Positionspunkte in diesem Log. "
                        "Sie erscheinen nach dem nächsten Firmwarelauf und Logdownload."
                    )
                )

    def fit_track_map(self) -> None:
        if not hasattr(self, "track_canvas"):
            return
        if not self.track_points:
            self.track_view = None
            self.render_track_map()
            return
        width = max(self.track_canvas.winfo_width(), 600)
        height = max(self.track_canvas.winfo_height(), 360)
        mean_latitude = sum(
            float(point["latitude"]) for point in self.track_points
        ) / len(self.track_points)
        cosine = max(0.15, math.cos(math.radians(mean_latitude)))
        projected = [
            (float(point["longitude"]) * cosine, float(point["latitude"]))
            for point in self.track_points
        ]
        x_values = [point[0] for point in projected]
        y_values = [point[1] for point in projected]
        span_x = max((max(x_values) - min(x_values)) * 1.20, 0.0005 * cosine)
        span_y = max((max(y_values) - min(y_values)) * 1.20, 0.0005)
        plot_aspect = max(1.0, (width - 100) / max(height - 90, 1))
        if span_x / span_y < plot_aspect:
            span_x = span_y * plot_aspect
        else:
            span_y = span_x / plot_aspect
        self.track_view = (
            (min(x_values) + max(x_values)) / 2.0,
            (min(y_values) + max(y_values)) / 2.0,
            span_x,
            span_y,
            cosine,
        )
        self.render_track_map()

    def zoom_track_map(self, factor: float) -> None:
        if not self.track_view:
            self.fit_track_map()
            return
        center_x, center_y, span_x, span_y, cosine = self.track_view
        factor = max(0.25, min(4.0, factor))
        self.track_view = (
            center_x,
            center_y,
            max(span_x * factor, 0.00001),
            max(span_y * factor, 0.00001),
            cosine,
        )
        self.render_track_map()

    def track_screen_points(self) -> list[tuple[float, float]]:
        if not self.track_view:
            return []
        width = max(self.track_canvas.winfo_width(), 600)
        height = max(self.track_canvas.winfo_height(), 360)
        left, top, right, bottom = 50.0, 35.0, width - 35.0, height - 45.0
        center_x, center_y, span_x, span_y, cosine = self.track_view
        minimum_x = center_x - span_x / 2.0
        minimum_y = center_y - span_y / 2.0
        return [
            (
                left
                + (float(point["longitude"]) * cosine - minimum_x)
                / span_x
                * (right - left),
                bottom
                - (float(point["latitude"]) - minimum_y)
                / span_y
                * (bottom - top),
            )
            for point in self.track_points
        ]

    def render_track_map(self) -> None:
        if not hasattr(self, "track_canvas"):
            return
        canvas = self.track_canvas
        canvas.delete("all")
        palette = THEMES.get(self.theme.get(), THEMES["Modern"])
        width = max(canvas.winfo_width(), 600)
        height = max(canvas.winfo_height(), 360)
        left, top, right, bottom = 50.0, 35.0, width - 35.0, height - 45.0
        canvas.create_rectangle(
            left,
            top,
            right,
            bottom,
            outline=palette["muted"],
            fill=palette["panel_alt"],
        )
        for step in range(1, 5):
            x = left + (right - left) * step / 5.0
            y = top + (bottom - top) * step / 5.0
            canvas.create_line(x, top, x, bottom, fill=palette["panel"])
            canvas.create_line(left, y, right, y, fill=palette["panel"])
        canvas.create_text(
            right - 8,
            top + 8,
            text="N ↑  Offline-Karte",
            anchor="ne",
            fill=palette["muted"],
            font=(palette["font"], 9, "bold"),
        )
        if not self.track_points:
            canvas.create_text(
                width / 2,
                height / 2,
                text="Noch keine gespeicherten Positionspunkte",
                fill=palette["muted"],
                font=(palette["font"], 12),
            )
            self.track_summary.configure(text="Keine Positionsdaten")
            return
        if not self.track_view:
            self.fit_track_map()
            return
        screen_points = self.track_screen_points()
        route_coordinates = [coordinate for point in screen_points for coordinate in point]
        if len(route_coordinates) >= 4:
            canvas.create_line(
                *route_coordinates,
                fill=palette["accent"],
                width=3,
                smooth=False,
            )
        for index, (x, y) in enumerate(screen_points):
            endpoint = index in (0, len(screen_points) - 1)
            radius = 7 if endpoint else 4
            color = (
                palette["success"]
                if index == 0
                else (palette["error"] if index == len(screen_points) - 1 else palette["accent"])
            )
            canvas.create_oval(
                x - radius,
                y - radius,
                x + radius,
                y + radius,
                fill=color,
                outline=palette["panel"],
                width=2 if endpoint else 1,
            )
        distance = sum(
            geographic_distance_m(
                float(previous["latitude"]),
                float(previous["longitude"]),
                float(current["latitude"]),
                float(current["longitude"]),
            )
            for previous, current in itertools.pairwise(self.track_points)
        )
        distance_text = f"{distance / 1000.0:.2f} km" if distance >= 1000 else f"{distance:.0f} m"
        self.track_summary.configure(
            text=f"{len(self.track_points)} Punkte · Wegstrecke {distance_text} · >25-m-Filter"
        )

    def select_track_point(self, event: tk.Event) -> None:
        screen_points = self.track_screen_points()
        if not screen_points:
            return
        index = min(
            range(len(screen_points)),
            key=lambda item: (screen_points[item][0] - event.x) ** 2
            + (screen_points[item][1] - event.y) ** 2,
        )
        self.show_track_point(index)

    def show_track_point(self, index: int) -> None:
        if not (0 <= index < len(self.track_points)):
            return
        point = self.track_points[index]
        epoch = int(point.get("epoch") or 0)
        timestamp = (
            dt.datetime.fromtimestamp(epoch, tz=dt.timezone.utc)
            .astimezone()
            .strftime("%d.%m.%Y %H:%M:%S %Z")
            if epoch
            else "Zeit unbekannt"
        )
        source = {"phone": "Telefon", "gps": "GNSS"}.get(
            str(point.get("source")), str(point.get("source") or "unbekannt")
        )
        accuracy_mm = int(point.get("accuracy_mm") or 0)
        accuracy = f" · Genauigkeit ±{accuracy_mm / 1000.0:.1f} m" if accuracy_mm else ""
        self.track_info.configure(
            text=(
                f"Punkt {index + 1}/{len(self.track_points)} · {point.get('mgrs') or 'MGRS unbekannt'} · "
                f"{timestamp} · {source}{accuracy}\n"
                f"{float(point['latitude']):.7f}, {float(point['longitude']):.7f}"
            )
        )

    def render_virtual_display(self) -> None:
        if not hasattr(self, "virtual_display"):
            return
        canvas = self.virtual_display
        canvas.delete("all")
        palette = THEMES.get(self.theme.get(), THEMES["Modern"])
        width = max(canvas.winfo_width(), 600)
        height = max(canvas.winfo_height(), 360)
        margin = 16
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
        frame = data.get("frame")
        frame_width = int(data.get("width", 0))
        frame_height = int(data.get("height", 0))
        if not isinstance(frame, bytes) or frame_width <= 0 or frame_height <= 0:
            canvas.create_text(
                width / 2,
                height / 2,
                text="Ungültiger Display-Frame",
                fill=palette["error"],
                font=(palette["font"], 14, "bold"),
            )
            return
        image = tk.PhotoImage(width=frame_width, height=frame_height)
        foreground = palette["fg"]
        background = palette["panel"]
        rows = []
        for y in range(frame_height):
            row = []
            page_offset = (y // 8) * frame_width
            bit = 1 << (y & 7)
            for x in range(frame_width):
                row.append(foreground if frame[page_offset + x] & bit else background)
            rows.append("{" + " ".join(row) + "}")
        image.put(" ".join(rows))
        footer_height = 36
        scale = max(
            1,
            min(
                int((width - 2 * margin - 32) / frame_width),
                int((height - 2 * margin - footer_height - 24) / frame_height),
            ),
        )
        self.live_image = image.zoom(scale, scale)
        display_height = height - 2 * margin - footer_height
        canvas.create_image(
            width / 2,
            margin + display_height / 2,
            image=self.live_image,
        )
        canvas.create_text(
            width - margin - 12,
            height - margin - 8,
            text=(
                f"Frame {data.get('sequence', 0)} · {frame_width}×{frame_height} · {scale}× · "
                f"OLED {'AN' if data.get('screen_on') else 'AUS / virtuell'}"
            ),
            anchor="se",
            fill=palette["muted"],
            font=(palette["font"], 8),
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
        self.set_transfer_progress(None, "Warte auf Export", True)
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
            devices = asyncio.run(BleakScanner.discover(timeout=8.0, return_adv=True))
            found = {}
            for device, advertisement in devices.values():
                name = device.name or "Unbenanntes BLE-Gerät"
                service_uuids = {
                    value.lower() for value in (advertisement.service_uuids or [])
                }
                if MESH_SERVICE_UUID in service_uuids:
                    found[f"{name} - {device.address}"] = device
                elif OTABT_SERVICE_UUID in service_uuids:
                    found[f"[OTA] {name} - {device.address}"] = device
            self.events.put(("ble_devices", (found, len(devices))))
        except Exception as exc:
            self.events.put(("error", f"Bluetooth-Suche fehlgeschlagen: {exc}"))
        finally:
            self.events.put(("ble_scan_done", None))

    def start_pairing(self) -> None:
        self.open_windows_bluetooth()

    def selected_ble_devices(self) -> list[tuple[str, object]]:
        selected = []
        labels = list(self.ble_map)
        for index in self.ble_device.curselection():
            if 0 <= index < len(labels):
                label = labels[index]
                selected.append((label, self.ble_map[label]))
        return selected

    def start_ble_download(self) -> None:
        if not BLE_AVAILABLE:
            messagebox.showerror(
                "Bluetooth nicht verfügbar",
                "Diese App-Ausgabe enthält kein Bluetooth-Modul. USB bleibt nutzbar.",
            )
            return
        ble_devices = self.selected_ble_devices()
        if not ble_devices:
            messagebox.showerror(
                "Kein Bluetooth-Gerät",
                "Bitte zuerst Bluetooth-Nodes suchen und mindestens einen Node markieren.",
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
        self.set_transfer_progress(None, "Verbinden", True)
        self.set_result(
            f"{len(ble_devices)} Node(s) markiert. Download-Warteschlange wird gestartet ..."
        )
        self.worker = threading.Thread(
            target=self._ble_download_worker,
            args=(ble_devices,),
            daemon=True,
        )
        self.worker.start()

    def start_ble_update(self) -> None:
        if not BLE_AVAILABLE:
            messagebox.showerror(
                "Bluetooth nicht verfügbar",
                "Diese App-Ausgabe enthält kein Bluetooth-Modul.",
            )
            return
        ble_devices = self.selected_ble_devices()
        if not ble_devices:
            messagebox.showerror(
                "Kein Bluetooth-Gerät",
                "Bitte zuerst Bluetooth-Nodes suchen und mindestens einen Node markieren.",
            )
            return
        if self.worker and self.worker.is_alive():
            return
        recovery_device_code = ""
        ota_loader_entries = [
            label for label, _device in ble_devices if label.startswith("[OTA]")
        ]
        if ota_loader_entries:
            if len(ble_devices) != 1:
                messagebox.showerror(
                    "OTA-Wiederaufnahme",
                    "Einen bereits wartenden OTA-Loader bitte einzeln aktualisieren.",
                )
                return
            answer = messagebox.askyesnocancel(
                "OTA-Gerätetyp bestätigen",
                "Der OTA-Loader meldet keinen eindeutigen Gerätetyp.\n\n"
                "Ist das wartende Gerät ein Heltec V3?\n\n"
                "Ja = Heltec V3\nNein = Tracker V1.1\nAbbrechen = nichts ändern",
            )
            if answer is None:
                return
            recovery_device_code = "V3" if answer else "TRACKER"
        if not messagebox.askyesno(
            "Bluetooth-Firmwareupdate",
            f"{len(ble_devices)} Node(s) nacheinander aktualisieren?\n\n"
            "Die passende Firmware wird direkt von GitHub geladen und geprüft. "
            "Einstellungen und Logs bleiben erhalten. Für den Updatevorgang wird "
            "USB-Strom oder mindestens 25 % Akku empfohlen.",
        ):
            return
        self.stop_event.clear()
        self.start_button.configure(state="disabled")
        self.ble_download_button.configure(state="disabled")
        self.ble_update_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.progress["value"] = 0
        self.set_transfer_progress(None, "OTA-Warteschlange vorbereiten", True)
        self.set_result(
            f"{len(ble_devices)} Node(s) markiert. Sichere OTA-Prüfung wird gestartet ..."
        )
        self.worker = threading.Thread(
            target=self._ble_update_worker,
            args=(ble_devices, recovery_device_code),
            daemon=True,
        )
        self.worker.start()

    @staticmethod
    def _download_otabt_bundle(device_code: str) -> tuple[bytes, dict[str, object]]:
        release_config = OTABT_RELEASES.get(device_code)
        if not release_config:
            raise RuntimeError(f"Unbekannter Gerätetyp {device_code}")
        tag = str(release_config["tag"])
        release_url = (
            f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/tags/{tag}"
        )
        request = urllib.request.Request(
            release_url, headers={"User-Agent": "Jarnsen-Node-Service-Tool"}
        )
        with contextlib.closing(
            urllib.request.urlopen(request, timeout=30)  # nosec B310  # nosemgrep
        ) as response:
            release = json.load(response)
        assets = {
            str(asset.get("name") or ""): str(asset.get("browser_download_url") or "")
            for asset in release.get("assets", [])
            if isinstance(asset, dict)
        }
        manifest_name = str(release_config["manifest"])
        manifest_url = assets.get(manifest_name, "")
        if not manifest_url:
            raise RuntimeError(f"GitHub-Manifest {manifest_name} fehlt")
        manifest_request = urllib.request.Request(
            manifest_url, headers={"User-Agent": "Jarnsen-Node-Service-Tool"}
        )
        with contextlib.closing(
            urllib.request.urlopen(  # nosec B310  # nosemgrep
                manifest_request, timeout=30
            )
        ) as response:
            manifest = json.load(response)
        if not isinstance(manifest, dict) or int(manifest.get("schema", 0)) != 1:
            raise RuntimeError("GitHub-OTA-Manifest ist ungültig")
        if str(manifest.get("device") or "") != str(release_config["device"]):
            raise RuntimeError("Firmwaretyp im Manifest passt nicht zum Node")
        firmware_name = str(manifest.get("firmware_asset") or "")
        firmware_url = assets.get(firmware_name, "")
        expected_hash = str(manifest.get("firmware_sha256") or "").lower()
        expected_size = int(manifest.get("firmware_size") or 0)
        if not firmware_name.endswith(".update.bin") or not re.fullmatch(
            r"[0-9a-f]{64}", expected_hash
        ):
            raise RuntimeError("Firmwareangaben im Manifest sind ungültig")
        if not firmware_url:
            raise RuntimeError(f"GitHub-Firmware {firmware_name} fehlt")
        firmware_request = urllib.request.Request(
            firmware_url, headers={"User-Agent": "Jarnsen-Node-Service-Tool"}
        )
        with contextlib.closing(
            urllib.request.urlopen(  # nosec B310  # nosemgrep
                firmware_request, timeout=90
            )
        ) as response:
            firmware = response.read(0x330000 + 1)
        if not firmware or len(firmware) > 0x330000 or firmware[0] != 0xE9:
            raise RuntimeError("Firmware ist kein gültiges ESP32-S3-Updateabbild")
        if len(firmware) != expected_size:
            raise RuntimeError("Firmwaregröße stimmt nicht mit GitHub-Manifest überein")
        if hashlib.sha256(firmware).hexdigest() != expected_hash:
            raise RuntimeError("SHA-256-Prüfung der GitHub-Firmware fehlgeschlagen")
        return firmware, manifest

    async def _read_otabt_status(self, client: object) -> tuple[str, str]:
        await client.write_gatt_char(
            JARNSEN_DIAG_CONTROL_UUID, b"OTASTATUS", response=True
        )
        response = bytes(await client.read_gatt_char(JARNSEN_DIAG_CONTROL_UUID)).decode(
            "ascii", "replace"
        )
        parts = response.split(":")
        device_code = parts[1] if len(parts) > 1 else ""
        build = parts[2].lower() if len(parts) > 2 else ""
        if response.startswith("NO_LOADER:"):
            raise RuntimeError(
                "otaBTupdate-Bootloader fehlt; bitte einmalig per USB installieren"
            )
        if response.startswith("NO_BT_OTA:"):
            raise RuntimeError(
                "Installierter OTA-Bootloader unterstützt Bluetooth nicht"
            )
        if response.startswith("LOW_POWER:"):
            raise RuntimeError("Akkustand unter 25 %; bitte USB-Strom anschließen")
        if not response.startswith("OTA_OK:") or device_code not in OTABT_RELEASES:
            raise RuntimeError(
                "Die laufende Firmware kann otaBTupdate noch nicht starten. "
                "Einmalig den aktuellen USB-Bootstrap mit Hauptfirmware und "
                f"otaBTupdate installieren ({response or '--'})"
            )
        return device_code, build

    async def _hold_otabt_client(self, client: object) -> None:
        await client.write_gatt_char(
            JARNSEN_DIAG_CONTROL_UUID, b"HOLDOTA", response=True
        )
        response = bytes(await client.read_gatt_char(JARNSEN_DIAG_CONTROL_UUID)).decode(
            "ascii", "replace"
        )
        if response != "OTA_HELD":
            raise RuntimeError(
                f"OTA-Warteschlange wurde nicht reserviert ({response or '--'})"
            )

    @staticmethod
    def _ble_identity_suffix(device: object) -> str:
        name = str(getattr(device, "name", "") or "")
        match = re.search(r"([0-9a-fA-F]{4})$", name)
        return match.group(1).lower() if match else ""

    async def _find_ble_service(
        self,
        address: str,
        service_uuid: str,
        description: str,
        name_suffix: str = "",
    ) -> object:
        deadline = time.monotonic() + OTABT_STALL_SECONDS
        while time.monotonic() < deadline:
            if self.stop_event.is_set():
                raise RuntimeError("Update abgebrochen")
            devices = await BleakScanner.discover(timeout=5.0, return_adv=True)
            candidates = []
            for device, advertisement in devices.values():
                advertised = {
                    str(value).lower() for value in (advertisement.service_uuids or [])
                }
                if service_uuid.lower() not in advertised:
                    continue
                candidates.append(device)
                if str(device.address).lower() == address.lower():
                    return device
                if name_suffix and self._ble_identity_suffix(device) == name_suffix:
                    return device
            if len(candidates) == 1:
                return candidates[0]
        raise RuntimeError(
            f"{description} meldet sich seit {int(OTABT_STALL_SECONDS)} Sekunden nicht"
        )

    async def _verify_updated_firmware(
        self, device_code: str, source_sha: str, preferred_address: str = ""
    ) -> str:
        """Find the rebooted node by device type/build, not its changing address."""
        deadline = time.monotonic() + OTABT_STALL_SECONDS
        last_error = ""
        while time.monotonic() < deadline:
            if self.stop_event.is_set():
                raise RuntimeError("Update abgebrochen")
            devices = await BleakScanner.discover(timeout=5.0, return_adv=True)
            candidates = []
            for device, advertisement in devices.values():
                advertised = {
                    str(value).lower() for value in (advertisement.service_uuids or [])
                }
                if MESH_SERVICE_UUID.lower() in advertised:
                    candidates.append(device)
            candidates.sort(
                key=lambda item: str(getattr(item, "address", "")).lower()
                != preferred_address.lower()
            )
            for candidate in candidates:
                try:
                    async with BleakClient(
                        candidate,
                        timeout=30.0,
                        pair=False,
                        winrt={"use_cached_services": False},
                    ) as verify_client:
                        verified_code, verified_build = await self._read_otabt_status(
                            verify_client
                        )
                    if verified_code == device_code and source_sha.startswith(
                        verified_build
                    ):
                        return verified_build
                except Exception as exc:
                    last_error = str(exc)
            await asyncio.sleep(1.0)
        detail = f" ({last_error})" if last_error else ""
        raise RuntimeError(
            "aktualisierte Firmware meldet sich nicht mit dem erwarteten Build"
            + detail
        )

    async def _identify_otabt_loader(
        self, client: object, fallback_device_code: str = ""
    ) -> str:
        responses: asyncio.Queue[str] = asyncio.Queue()
        response_buffer = bytearray()

        def notification_handler(_sender: object, data: bytearray) -> None:
            response_buffer.extend(data)
            while b"\n" in response_buffer:
                raw, _, remainder = response_buffer.partition(b"\n")
                response_buffer[:] = remainder
                responses.put_nowait(raw.decode("ascii", "replace").strip())

        await client.start_notify(OTABT_TX_UUID, notification_handler)
        try:
            await client.write_gatt_char(OTABT_WRITE_UUID, b"VERSION\n", response=True)
            response = await asyncio.wait_for(responses.get(), timeout=15.0)
        finally:
            with contextlib.suppress(Exception):
                await client.stop_notify(OTABT_TX_UUID)
        parts = response.split()
        if len(parts) < 2 or parts[0] != "OK":
            raise RuntimeError(f"Ungültige otaBTupdate-Antwort: {response or '--'}")
        try:
            hardware_code = int(parts[1])
        except ValueError as exc:
            raise RuntimeError(
                f"otaBTupdate meldet ungültigen Gerätetyp: {response}"
            ) from exc
        device_code = OTABT_HARDWARE_CODES.get(hardware_code)
        if not device_code and fallback_device_code in OTABT_RELEASES:
            return fallback_device_code
        if not device_code:
            raise RuntimeError(
                f"otaBTupdate-Gerätetyp {hardware_code} wird nicht unterstützt"
            )
        return device_code

    async def _upload_otabt_firmware(
        self,
        ota_device: object,
        firmware: bytes,
        firmware_hash: str,
        index: int,
        total: int,
    ) -> None:
        notifications: asyncio.Queue[str] = asyncio.Queue()
        notification_buffer = bytearray()

        def notification_handler(_sender: object, data: bytearray) -> None:
            notification_buffer.extend(data)
            while b"\n" in notification_buffer:
                raw, _, remainder = notification_buffer.partition(b"\n")
                notification_buffer[:] = remainder
                notifications.put_nowait(raw.decode("ascii", "replace").strip())

        async def next_response(timeout: float = OTABT_STALL_SECONDS) -> str:
            try:
                response = await asyncio.wait_for(
                    notifications.get(), timeout=timeout
                )
            except asyncio.TimeoutError as exc:
                raise RuntimeError(
                    f"kein OTA-Fortschritt seit {int(OTABT_STALL_SECONDS)} Sekunden"
                ) from exc
            if response.startswith("ERR"):
                raise RuntimeError(f"otaBTupdate meldet: {response}")
            return response

        async with BleakClient(
            ota_device,
            timeout=90.0,
            pair=False,
            winrt={"use_cached_services": False},
        ) as client:
            await client.start_notify(OTABT_TX_UUID, notification_handler)
            await asyncio.sleep(0.75)
            await client.write_gatt_char(OTABT_WRITE_UUID, b"VERSION\n", response=True)
            version = await next_response()
            if not version.startswith("OK "):
                raise RuntimeError(f"Ungültige otaBTupdate-Antwort: {version}")
            command = f"OTA {len(firmware)} {firmware_hash}\n".encode("ascii")
            await client.write_gatt_char(OTABT_WRITE_UUID, command, response=True)
            if await next_response() != "ERASING":
                raise RuntimeError("otaBTupdate hat den Löschvorgang nicht bestätigt")
            if await next_response() != "OK":
                raise RuntimeError("otaBTupdate ist nicht empfangsbereit")

            characteristic = client.services.get_characteristic(OTABT_WRITE_UUID)
            max_chunk = int(
                getattr(characteristic, "max_write_without_response_size", 244) or 244
            )
            chunk_size = max(20, min(128, max_chunk))
            sent = 0
            while sent < len(firmware):
                if self.stop_event.is_set():
                    raise RuntimeError("Update abgebrochen")
                if not client.is_connected:
                    raise RuntimeError("Bluetooth-Verbindung während OTA getrennt")
                chunk = firmware[sent : sent + chunk_size]
                await client.write_gatt_char(OTABT_WRITE_UUID, chunk, response=True)
                sent += len(chunk)
                expected = "OK" if sent == len(firmware) else "ACK"
                response = await next_response(30.0)
                if response != expected:
                    raise RuntimeError(
                        f"Unerwartete otaBTupdate-Antwort: {response or '--'}"
                    )
                overall = int(((index - 1) + sent / len(firmware)) * 100 / total)
                self.events.put(("progress", overall))
                self.events.put(
                    (
                        "progress_detail",
                        (
                            overall,
                            f"Node {index}/{total} · {sent * 100 // len(firmware)} % übertragen",
                            False,
                        ),
                    )
                )
            with contextlib.suppress(Exception):
                await client.stop_notify(OTABT_TX_UUID)

    async def _ble_update_fleet_async(
        self,
        ble_devices: list[tuple[str, object]],
        recovery_device_code: str = "",
    ) -> tuple[int, list[str]]:
        reservations: list[dict[str, object]] = []
        failures: list[str] = []
        bundles: dict[str, tuple[bytes, dict[str, object]]] = {}
        total = len(ble_devices)
        completed = 0
        try:
            for index, (label, ble_device) in enumerate(ble_devices, start=1):
                if self.stop_event.is_set():
                    break
                self.events.put(
                    (
                        "status",
                        f"Prüfe und reserviere Node {index}/{total}: {label}",
                    )
                )
                client = BleakClient(
                    ble_device,
                    timeout=90.0,
                    pair=False,
                    winrt={"use_cached_services": False},
                )
                try:
                    await client.connect()
                    if client.services.get_service(OTABT_SERVICE_UUID):
                        device_code = await self._identify_otabt_loader(
                            client, recovery_device_code
                        )
                        await client.disconnect()
                        reservations.append(
                            {
                                "index": index,
                                "label": label,
                                "device": ble_device,
                                "client": None,
                                "device_code": device_code,
                                "installed_build": "",
                                "loader_ready": True,
                            }
                        )
                        continue
                    device_code, installed_build = await self._read_otabt_status(client)
                    await self._hold_otabt_client(client)
                    reservations.append(
                        {
                            "index": index,
                            "label": label,
                            "device": ble_device,
                            "client": client,
                            "device_code": device_code,
                            "installed_build": installed_build,
                            "loader_ready": False,
                        }
                    )
                except Exception as exc:
                    failures.append(f"{label}: {exc}")
                    with contextlib.suppress(Exception):
                        await client.disconnect()

            for device_code in {str(entry["device_code"]) for entry in reservations}:
                self.events.put(
                    (
                        "status",
                        f"Lade geprüfte {device_code}-Firmware direkt von GitHub ...",
                    )
                )
                bundles[device_code] = await asyncio.to_thread(
                    self._download_otabt_bundle, device_code
                )

            for entry in reservations:
                if self.stop_event.is_set():
                    break
                index = int(entry["index"])
                label = str(entry["label"])
                client = entry["client"]
                device_code = str(entry["device_code"])
                firmware, manifest = bundles[device_code]
                source_sha = str(manifest.get("source_sha") or "").lower()
                installed_build = str(entry["installed_build"])
                if installed_build and source_sha.startswith(installed_build):
                    completed += 1
                    self.events.put(
                        (
                            "status_success",
                            f"Node {index}/{total} ist bereits aktuell ({installed_build})",
                        )
                    )
                    await client.write_gatt_char(
                        JARNSEN_DIAG_CONTROL_UUID, b"RELEASE", response=True
                    )
                    await client.disconnect()
                    entry["client"] = None
                    self.events.put(("progress", int(index * 100 / total)))
                    continue
                firmware_hash = str(manifest["firmware_sha256"])
                address = str(getattr(entry["device"], "address", ""))
                name_suffix = self._ble_identity_suffix(entry["device"])
                self.events.put(
                    (
                        "status",
                        f"Node {index}/{total}: starte sicheren otaBTupdate-Modus ...",
                    )
                )
                try:
                    if entry.get("loader_ready"):
                        ota_device = entry["device"]
                        self.events.put(
                            (
                                "progress_detail",
                                (
                                    None,
                                    f"Node {index}/{total} · wartendes OTA fortsetzen",
                                    True,
                                ),
                            )
                        )
                    else:
                        await client.write_gatt_char(
                            JARNSEN_DIAG_CONTROL_UUID,
                            f"OTABT {firmware_hash}".encode("ascii"),
                            response=True,
                        )
                        response = bytes(
                            await client.read_gatt_char(JARNSEN_DIAG_CONTROL_UUID)
                        ).decode("ascii", "replace")
                        if response != "OTA_READY":
                            raise RuntimeError(
                                f"Node startet otaBTupdate nicht ({response or '--'})"
                            )
                        # Keep the encrypted reservation alive until the scheduled
                        # reboot, even if this node waited longer than 15 minutes.
                        await asyncio.sleep(4.0)
                        with contextlib.suppress(Exception):
                            await client.disconnect()
                        entry["client"] = None
                        self.events.put(
                            (
                                "progress_detail",
                                (
                                    None,
                                    f"Node {index}/{total} · OTA-Bootloader startet",
                                    True,
                                ),
                            )
                        )
                        ota_device = await self._find_ble_service(
                            address,
                            OTABT_SERVICE_UUID,
                            "otaBTupdate-Bootloader",
                            name_suffix,
                        )
                    await self._upload_otabt_firmware(
                        ota_device,
                        firmware,
                        firmware_hash,
                        index,
                        total,
                    )
                    self.events.put(
                        (
                            "progress_detail",
                            (
                                None,
                                f"Node {index}/{total} · Neustart und Kontrolle",
                                True,
                            ),
                        )
                    )
                    verified_build = await self._verify_updated_firmware(
                        device_code, source_sha, address
                    )
                    completed += 1
                    self.events.put(
                        (
                            "status_success",
                            f"Node {index}/{total} erfolgreich aktualisiert · Build {verified_build}",
                        )
                    )
                except Exception as exc:
                    failures.append(f"{label}: {exc}")
        finally:
            for entry in reservations:
                client = entry.get("client")
                if not client:
                    continue
                with contextlib.suppress(Exception):
                    if client.is_connected:
                        await client.write_gatt_char(
                            JARNSEN_DIAG_CONTROL_UUID, b"RELEASE", response=True
                        )
                        await client.disconnect()
        return completed, failures

    def _ble_update_worker(
        self,
        ble_devices: list[tuple[str, object]],
        recovery_device_code: str = "",
    ) -> None:
        try:
            completed, failures = asyncio.run(
                self._ble_update_fleet_async(ble_devices, recovery_device_code)
            )
            self.events.put(
                ("ota_queue_result", (completed, len(ble_devices), failures))
            )
        except Exception as exc:
            self.events.put(("ota_error", str(exc)))
        finally:
            self.events.put(("done", None))

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

    def _ble_download_worker(self, ble_devices: list[tuple[str, object]]) -> None:
        failures = []
        completed = 0
        held: list[tuple[int, str, object]] = []
        total = len(ble_devices)
        try:
            if total > 1:
                for index, (label, ble_device) in enumerate(ble_devices, start=1):
                    if self.stop_event.is_set():
                        break
                    self.events.put(
                        (
                            "status",
                            f"Reserviere Node {index}/{total}: Bluetooth-Pfad bleibt für die Warteschlange offen ...",
                        )
                    )
                    self.events.put(
                        (
                            "progress_detail",
                            (
                                None,
                                f"Reserviere Node {index}/{total} · {len(held)} offen",
                                True,
                            ),
                        )
                    )
                    try:
                        asyncio.run(self._set_ble_queue_hold_async(ble_device, True))
                        held.append((index, label, ble_device))
                    except Exception as exc:
                        failures.append(
                            f"{label}: Warteschlangen-Reservierung fehlgeschlagen: {exc}"
                        )
                queue_entries = list(held)
            else:
                queue_entries = [(1, ble_devices[0][0], ble_devices[0][1])]

            if total > 1 and held and not self.stop_event.is_set():
                self.events.put(
                    (
                        "status",
                        f"{len(held)}/{total} Node(s) reserviert · Downloads starten nacheinander",
                    )
                )

            for entry in queue_entries:
                index, label, ble_device = entry
                queue_hold_active = entry in held
                if self.stop_event.is_set():
                    break
                try:
                    asyncio.run(
                        self._ble_download_async(
                            ble_device,
                            index,
                            total,
                            label,
                            release_queue_hold=queue_hold_active,
                        )
                    )
                    completed += 1
                    if queue_hold_active:
                        held.remove(entry)
                except Exception as exc:
                    failures.append(f"{label}: {exc}")
                    if queue_hold_active:
                        try:
                            asyncio.run(
                                self._set_ble_queue_hold_async(ble_device, False)
                            )
                            held.remove(entry)
                        except Exception:
                            # Retry all still-held nodes once in the common cleanup.
                            pass
        except Exception as exc:
            failures.append(f"Warteschlange: {exc}")
        finally:
            for _index, label, ble_device in list(held):
                try:
                    asyncio.run(self._set_ble_queue_hold_async(ble_device, False))
                except Exception as exc:
                    failures.append(
                        f"{label}: Bluetooth-Freigabe nicht bestätigt ({exc}); "
                        "die harte Sicherheitszeit schließt den Pfad automatisch"
                    )

            if self.stop_event.is_set():
                self.events.put(
                    (
                        "status_warning",
                        f"Download abgebrochen · {completed}/{len(ble_devices)} abgeschlossen",
                    )
                )
                if failures:
                    self.events.put(
                        (
                            "result",
                            "Warteschlange abgebrochen.\n\n" + "\n".join(failures),
                        )
                    )
            elif failures:
                self.events.put(
                    ("queue_result", (completed, len(ble_devices), failures))
                )
            else:
                self.events.put(
                    (
                        "status_success",
                        f"DONE · {completed}/{len(ble_devices)} Node-Logs gespeichert",
                    )
                )
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

    async def _write_ble_queue_hold(self, client: object, active: bool) -> None:
        command = b"HOLD" if active else b"RELEASE"
        expected = "HELD" if active else "IDLE"
        await client.write_gatt_char(JARNSEN_DIAG_CONTROL_UUID, command, response=True)
        state = bytes(await client.read_gatt_char(JARNSEN_DIAG_CONTROL_UUID)).decode(
            "ascii", "replace"
        )
        if active and state == "LOCKED":
            raise RuntimeError(
                "Servicefenster am Node ist nicht geöffnet oder bereits abgelaufen"
            )
        if state != expected:
            action = "HOLD" if active else "RELEASE"
            raise RuntimeError(
                f"Firmware bestätigt {action} nicht ({state or '--'}); "
                "bitte zuerst die aktuelle kombinierte Firmware installieren"
            )

    async def _set_ble_queue_hold_async(self, ble_device: object, active: bool) -> None:
        async with BleakClient(
            ble_device,
            timeout=90.0,
            pair=False,
            winrt={"use_cached_services": False},
        ) as client:
            await self._write_ble_queue_hold(client, active)

    async def _ble_download_async(
        self,
        ble_device: object,
        index: int,
        total: int,
        label: str,
        release_queue_hold: bool = False,
    ) -> None:
        address = getattr(ble_device, "address", str(ble_device))
        prefix = f"Node {index}/{total}"
        self.events.put(
            ("status", f"{prefix}: Verbinde verschlüsselt mit {address} ...")
        )
        self.events.put(("progress_detail", (None, f"{prefix} · Verbinden", True)))
        async with BleakClient(
            ble_device,
            timeout=90.0,
            pair=False,
            winrt={"use_cached_services": False},
        ) as client:
            await client.write_gatt_char(
                JARNSEN_DIAG_CONTROL_UUID, b"START", response=True
            )
            self.events.put(
                ("progress_detail", (None, f"{prefix} · Authentifizieren", True))
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
                    bytes_start = expected_match.end()
                    while (
                        bytes_start < len(captured) and captured[bytes_start] in b"\r\n"
                    ):
                        bytes_start += 1
                    transferred = min(expected, max(0, len(captured) - bytes_start))
                    self.events.put(
                        (
                            "progress_detail",
                            (
                                min(
                                    99,
                                    int(
                                        (
                                            (index - 1)
                                            + (
                                                transferred / expected
                                                if expected
                                                else 0.99
                                            )
                                        )
                                        * 100
                                        / total
                                    ),
                                ),
                                (
                                    f"{prefix} · {transferred:,}/{expected:,} Bytes"
                                ).replace(",", "."),
                                False,
                            ),
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
            if release_queue_hold:
                await self._write_ble_queue_hold(client, False)
                self.events.put(
                    (
                        "status",
                        f"{prefix}: Log vollständig · Bluetooth-Reservierung freigegeben",
                    )
                )
        self._finish_payload(
            payload,
            expected,
            completion_progress=int(index * 100 / total),
            completion_label=f"{prefix} abgeschlossen",
            completion_status=None,
        )

    def toggle_live(self) -> None:
        if self.live_worker and self.live_worker.is_alive():
            self.live_stop.set()
            self.live_button.configure(text="Trenne …", state="disabled")
            return
        selected = self.selected_ble_devices()
        if not selected:
            messagebox.showinfo(
                "Live-Anzeige",
                "Bitte links zuerst Bluetooth-Nodes suchen und einen Node auswählen.",
            )
            return
        if len(selected) != 1:
            messagebox.showinfo(
                "Live-Anzeige",
                "Für die Live-Anzeige bitte genau einen Bluetooth-Node markieren.",
            )
            return
        _label, ble_device = selected[0]
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
            message = str(exc)
            lowered = message.lower()
            if self._is_authentication_error(exc):
                self.events.put(
                    (
                        "pairing_required",
                        (
                            "Für die Live-Anzeige muss der Node zuerst direkt in Windows gekoppelt werden. "
                            "Die Bluetooth-Einstellungen werden jetzt geöffnet."
                        ),
                    )
                )
                return
            if "characteristic" in lowered and "not found" in lowered:
                message = (
                    "Der Live-BLE-Dienst fehlt in der vom Node gemeldeten Service-Liste. "
                    "Bitte zuerst die neueste kombinierte Firmware für diesen Node flashen. "
                    "Ist sie bereits installiert, den Node einmal aus den Windows-"
                    "Bluetooth-Geräten entfernen, neu koppeln und Live erneut starten."
                )
            self.events.put(("live_error", message))
        finally:
            self.events.put(("live_disconnected", None))

    async def _live_async(self, ble_device: object) -> None:
        async with BleakClient(
            ble_device,
            timeout=90.0,
            pair=False,
            winrt={"use_cached_services": False},
        ) as client:
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
                    await asyncio.sleep(0.12)
                frame = await self._read_live_frame(client)
                self.events.put(("live_data", frame))
                await asyncio.sleep(0.35)
            try:
                await client.write_gatt_char(
                    JARNSEN_LIVE_CONTROL_UUID, b"STOP", response=True
                )
            except Exception as exc:
                self.events.put(
                    ("status_warning", f"Live-Sitzung war bereits getrennt: {exc}")
                )

    async def _read_live_frame(self, client: BleakClient) -> dict[str, object]:
        await client.write_gatt_char(JARNSEN_LIVE_CONTROL_UUID, b"FRAME", response=True)
        await asyncio.sleep(0.10)
        assembled = bytearray()
        width = height = sequence = total = 0
        screen_on = False
        for _ in range(32):
            packet = bytes(await client.read_gatt_char(JARNSEN_LIVE_DATA_UUID))
            if len(packet) < 12 or packet[:2] != b"JF" or packet[2] != 1:
                raise RuntimeError("Live-Frame-Protokoll ist ungültig")
            screen_on = bool(packet[3] & 1)
            width, height = packet[4], packet[5]
            sequence = int.from_bytes(packet[6:8], "little")
            offset = int.from_bytes(packet[8:10], "little")
            total = int.from_bytes(packet[10:12], "little")
            if total <= 0 or total > 2048 or offset != len(assembled):
                raise RuntimeError("Live-Frame enthält ungültige Längenangaben")
            assembled.extend(packet[12:])
            if len(assembled) >= total:
                break
        if len(assembled) != total or total != width * ((height + 7) // 8):
            raise RuntimeError("Live-Frame wurde unvollständig übertragen")
        return {
            "frame": bytes(assembled),
            "width": width,
            "height": height,
            "sequence": sequence,
            "screen_on": screen_on,
        }

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
            self.events.put(("progress_detail", (None, "Port öffnen", True)))
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
            self.events.put(("progress_detail", (None, "Warte auf Export", True)))

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
                    self.events.put(
                        ("progress_detail", (None, "Log vorbereiten", True))
                    )

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
                    progress_bytes = bytes(captured) + bytes(scan)
                    bytes_header = re.search(
                        rb"(?m)^# bytes=(\d+)\r?$", progress_bytes[:4096]
                    )
                    data_start = (
                        bytes_header.end() if bytes_header else len(progress_bytes)
                    )
                    while (
                        data_start < len(progress_bytes)
                        and progress_bytes[data_start] in b"\r\n"
                    ):
                        data_start += 1
                    transferred = min(
                        expected, max(0, len(progress_bytes) - data_start)
                    )
                    self.events.put(
                        (
                            "progress_detail",
                            (
                                min(99, int(transferred * 100 / expected)),
                                f"Übertragen {transferred:,}/{expected:,} Bytes".replace(
                                    ",", "."
                                ),
                                False,
                            ),
                        )
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

    def _finish_payload(
        self,
        payload: bytes,
        expected: int,
        completion_progress: int = 100,
        completion_label: str = "Abgeschlossen",
        completion_status: str | None = "DONE - Verbindung geschlossen",
    ) -> None:
        verify_progress = max(0, completion_progress - 1)
        self.events.put(
            ("progress_detail", (verify_progress, "Prüfen und speichern", False))
        )
        device = header_value(payload, b"device")
        selected = self.expected_device
        if selected == "Tracker V1.1" and device != "HELTEC_TRACKER_V1.1":
            raise RuntimeError(f"Falsches Gerät: {device or 'unbekannt'}")
        if selected == "Heltec V3" and device != "HELTEC_V3_REPEATER":
            raise RuntimeError(f"Falsches Gerät: {device or 'unbekannt'}")
        sent_match = re.search(rb"(?m)^# payload_sent=(\d+)\r?$", payload)
        sent = int(sent_match.group(1)) if sent_match else 0
        if expected and sent and sent < expected:
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
            payload_bytes = int(bytes_match.group(1))
            # The CRC covers only the diagnostic log files, not metadata lines.
            # Locate those bytes backwards from the protocol footer.  This also
            # accepts V3 builds which place a LIVE snapshot after ``# bytes``.
            footer_matches = list(
                re.finditer(rb"(?m)\r?\n# payload_sent=\d+\r?$", payload)
            )
            if not footer_matches or footer_matches[-1].start() < payload_bytes:
                raise RuntimeError("BLE-Export enthält keinen vollständigen Nutzdatenblock")
            payload_end = footer_matches[-1].start()
            log_bytes = payload[payload_end - payload_bytes : payload_end]
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
        self.events.put(("progress", completion_progress))
        self.events.put(
            ("progress_detail", (completion_progress, completion_label, False))
        )
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
        if completion_status:
            self.events.put(("status_success", completion_status))

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
                    percent = max(0, min(100, int(value)))
                    self.progress["value"] = percent
                    self.progress_percent.configure(text=f"{percent} %")
                elif kind == "progress_detail":
                    progress_value, label, indeterminate = value
                    self.set_transfer_progress(
                        progress_value, str(label), bool(indeterminate)
                    )
                elif kind == "result":
                    self.set_result(str(value))
                elif kind == "dashboard":
                    self.last_payload, self.last_comparison = value
                    self.render_dashboard()
                    self.update_track_points()
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
                elif kind == "queue_result":
                    completed, total, failures = value
                    summary = (
                        f"{completed}/{total} Node-Logs gespeichert.\n\n"
                        + "Fehlgeschlagen:\n"
                        + "\n".join(str(item) for item in failures)
                    )
                    self.status_level = "warning"
                    self.status.configure(
                        text=f"Download beendet · {completed}/{total} erfolgreich"
                    )
                    self._update_status_badge()
                    self.set_result(summary)
                    messagebox.showwarning("Mehrfachdownload", summary)
                elif kind == "ota_queue_result":
                    completed, total, failures = value
                    if failures:
                        summary = (
                            f"{completed}/{total} Node(s) aktualisiert oder bereits aktuell.\n\n"
                            "Nicht abgeschlossen:\n"
                            + "\n".join(str(item) for item in failures)
                        )
                        self.status_level = "warning"
                        self.status.configure(
                            text=f"Bluetooth-Firmwareupdate beendet · {completed}/{total} erfolgreich"
                        )
                        self.set_result(summary)
                        messagebox.showwarning("Gruppenupdate", summary)
                    else:
                        summary = (
                            f"Alle {total} Node(s) wurden aktualisiert oder waren bereits aktuell.\n"
                            "Firmwarestand und Neustart wurden über Bluetooth kontrolliert."
                        )
                        self.status_level = "success"
                        self.status.configure(
                            text="Bluetooth-Firmwareupdate abgeschlossen"
                        )
                        self.set_result(summary)
                        messagebox.showinfo("Gruppenupdate", summary)
                    self._update_status_badge()
                elif kind == "ota_error":
                    self.status_level = "error"
                    self.status.configure(
                        text="Bluetooth-Firmwareupdate fehlgeschlagen"
                    )
                    self._update_status_badge()
                    self.set_result(str(value))
                    messagebox.showerror("Bluetooth-Firmwareupdate", str(value))
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
                            text=(
                                "Offline - GitHub wird beim nächsten Start erneut geprüft · Cache aktiv"
                                if len(failures) == len(FIRMWARE_WORKFLOWS)
                                else "GitHub teilweise nicht erreichbar · Cache wird weiterverwendet"
                            )
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
                    self.live_values.configure(
                        text=(
                            "Pixelgenaue Spiegelung des Geräte-Framebuffers · "
                            f"Frame {value.get('sequence', 0)} · "
                            f"OLED {'eingeschaltet' if value.get('screen_on') else 'ausgeschaltet, virtuelle Bedienung aktiv'}"
                        )
                    )
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
                    if self.progress.cget("mode") == "indeterminate":
                        self.progress.stop()
                    self.start_button.configure(state="normal")
                    self.ble_download_button.configure(state="normal")
                    self.ble_update_button.configure(state="normal")
                    self.ble_pair_button.configure(state="normal")
                    self.cancel_button.configure(state="disabled")
                elif kind == "ble_devices":
                    compatible, total = value
                    self.ble_map = dict(compatible)
                    self.ble_device.delete(0, "end")
                    for label in self.ble_map:
                        self.ble_device.insert("end", label)
                    if self.ble_map:
                        self.ble_device.selection_set(0)
                        self.ble_count_label.configure(
                            text=(
                                f"{len(self.ble_map)} verfügbare Node(s) · "
                                f"{total} Bluetooth-Gerät(e) insgesamt"
                            )
                        )
                        self.status.configure(
                            text=(
                                f"{len(self.ble_map)} kompatible Node(s) gefunden "
                                f"({total} BLE-Geräte insgesamt)"
                            )
                        )
                    else:
                        self.ble_count_label.configure(
                            text=f"0 verfügbare Nodes · {total} Bluetooth-Gerät(e) insgesamt"
                        )
                        self.status.configure(
                            text=f"Keine kompatible Node gefunden ({total} BLE-Geräte insgesamt)"
                        )
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
                b"2026-08-26T12:00:00Z | TRACK_POINT    | lat=51.1234567 lon=7.1234567 "
                b"epoch=1787745600 mgrs=32U LB 1234 5678 source=gps acc=2500mm\n"
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
            track_points = parse_track_points(payload)
            if (
                len(track_points) != 1
                or track_points[0]["mgrs"] != "32U LB 1234 5678"
                or track_points[0]["source"] != "gps"
            ):
                raise RuntimeError("Positionsverlauf wird nicht korrekt gelesen")
        report.write_text(
            "OK: BLE, Papierkorb, Datenbank, Positionskarte und fünf Layouts\n",
            encoding="utf-8",
        )
        return 0
    except Exception as exc:
        report.write_text(f"FEHLER: {type(exc).__name__}: {exc}\n", encoding="utf-8")
        return 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        raise SystemExit(packaged_self_test())
    ServiceTool().mainloop()
