from __future__ import annotations

import hashlib
import json
import platform
import re
import sys
import threading
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from tkinter import messagebox
from typing import Any, Callable

FLASH_MODES = {
    "provision": {
        "label": "Erstflash + Funktionsprofil",
        "keeps": "Sicherheitsbackup, soweit das angeschlossene Gerät lesbar ist",
        "changes": "Firmware, gewähltes Funktionsprofil und Gerätenamen",
    },
    "update": {
        "label": "Firmware-Update",
        "keeps": "Profil, Namen, Kanäle, NVS und Diagnose-Logs",
        "changes": "nur die Anwendungs-Firmware",
    },
    "repair": {
        "label": "Reparatur",
        "keeps": "gesichertes Profil und die im Flasher gewählten Namen",
        "changes": "Bootloader, Partitionen und Firmware",
    },
    "factory": {
        "label": "Werkseinstellung",
        "keeps": "nur das vorher angelegte Sicherheitsbackup",
        "changes": "den vollständigen Flash; Einstellungen und Namen werden gelöscht",
    },
}


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


@dataclass(frozen=True)
class PreflightItem:
    key: str
    state: str
    text: str


@dataclass
class PreflightReport:
    port: str
    board_key: str
    mode: str
    items: list[PreflightItem] = field(default_factory=list)
    installed_version: str = ""
    installed_build: int | None = None
    target_version: str = ""
    target_build: int | None = None
    recovery_mode: str = ""

    @property
    def ready(self) -> bool:
        return not any(item.state == "error" for item in self.items)

    def add(self, key: str, state: str, text: str) -> None:
        self.items.append(PreflightItem(key, state, text))

    def format(self) -> str:
        symbols = {"ok": "✓", "warning": "!", "error": "✗"}
        lines = [
            f"Modus: {FLASH_MODES[self.mode]['label']}",
            f"Port: {self.port}",
            "",
        ]
        lines.extend(
            f"{symbols.get(item.state, '•')} {item.text}" for item in self.items
        )
        lines.extend(
            (
                "",
                f"Geändert wird: {FLASH_MODES[self.mode]['changes']}",
                f"Erhalten bleibt: {FLASH_MODES[self.mode]['keeps']}",
                "",
                "ERGEBNIS: " + ("BEREIT" if self.ready else "GESPERRT"),
            )
        )
        return "\n".join(lines)


class HashCache:
    """Persistent SHA256 cache keyed by immutable file metadata."""

    def __init__(self, root: Path) -> None:
        self.path = Path(root) / "firmware-hash-cache.json"
        self._lock = threading.RLock()
        self._values: dict[str, dict[str, Any]] = {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._values = raw
        except Exception:
            self._values = {}

    def digest(self, path: Path) -> str:
        source = Path(path)
        stat = source.stat()
        key = str(source.resolve()).casefold()
        with self._lock:
            cached = self._values.get(key, {})
            if (
                cached.get("size") == stat.st_size
                and cached.get("mtime_ns") == stat.st_mtime_ns
                and re.fullmatch(r"[0-9a-f]{64}", str(cached.get("sha256") or ""))
            ):
                _emit(f"HASH CACHE HIT file={source.name!r} bytes={stat.st_size}")
                return str(cached["sha256"])

        digest = hashlib.sha256()
        with source.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        value = digest.hexdigest().lower()
        with self._lock:
            self._values[key] = {
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "sha256": value,
            }
            self._save()
        _emit(f"HASH CACHE MISS file={source.name!r} bytes={stat.st_size}")
        return value

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(self._values, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temp.replace(self.path)


def is_retryable_flash_error(exc: BaseException) -> bool:
    text = str(exc).casefold()
    return any(
        token in text
        for token in (
            "timeout",
            "timed out",
            "serial exception",
            "write timeout",
            "read timeout",
            "could not open port",
            "device couldn't be opened",
            "clearcommerror",
            "semaphore",
            "invalid head of packet",
            "packet content transfer stopped",
        )
    )


def baud_candidates(selected: Any) -> tuple[str, ...]:
    allowed = ("921600", "460800", "230400", "115200")
    value = str(selected or "921600")
    try:
        start = allowed.index(value)
    except ValueError:
        start = 0
    return allowed[start:]


def _identity_for(services: Any, port: str) -> Any:
    cached = getattr(services, "cached_jarnsen_identity", None)
    if callable(cached):
        try:
            value = cached(port)
            if value is not None:
                return value
        except Exception:
            pass
    query = getattr(services, "query_jarnsen_identity", None)
    if callable(query):
        try:
            return query(port)
        except Exception:
            pass
    return None


def _version_key(
    version: str, build: int | None
) -> tuple[int, int, int, int, int, int]:
    match = re.fullmatch(
        r"(\d+)\.(\d+)\.(\d+)(?:-(alpha|beta|rc)\.(\d+))?",
        str(version or "").strip().lstrip("vV"),
        re.IGNORECASE,
    )
    if not match:
        return (-1, -1, -1, -1, -1, int(build or 0))
    channel = (match.group(4) or "final").lower()
    return (
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3)),
        {"alpha": 0, "beta": 1, "rc": 2, "final": 3}.get(channel, -1),
        int(match.group(5) or 0),
        int(build or 0),
    )


def run_preflight(
    services: Any,
    port: str,
    board_key: str,
    bundle: Any,
    mode: str,
    *,
    probe_device: bool = True,
) -> PreflightReport:
    if mode not in FLASH_MODES:
        raise services.FlasherError(f"Unbekannter Flashmodus: {mode}")
    report = PreflightReport(str(port), str(board_key), mode)

    if board_key not in services.BOARD_PROFILES:
        report.add("board", "error", f"Board {board_key!r} wird nicht unterstützt")
        return report
    board_label = str(services.BOARD_PROFILES[board_key]["label"])
    report.add("board", "ok", f"Zielboard: {board_label}")

    if mode != "factory" and getattr(
        services, "_jarnsen_functional_profiles_installed", False
    ):
        try:
            from functional_profiles import active_profile as active_functional_profile
            from functional_profiles import firmware_compatibility_for_board

            functional = active_functional_profile(services)
            if functional is None:
                if mode in {"provision", "repair"}:
                    report.add(
                        "functional-profile",
                        "error",
                        "Erstflash/Reparatur: Bitte zuerst oben ein Funktionsprofil auswählen - "
                        "TAK, TAK TRACKER, TAK REPEATER oder DRONE REPEATER.",
                    )
                else:
                    report.add(
                        "functional-profile",
                        "warning",
                        "Kein Funktionsprofil ausgewählt; das reine Firmware-Update verändert keine Konfiguration.",
                    )
            else:
                allowed, message = firmware_compatibility_for_board(
                    functional, board_key, services
                )
                report.add(
                    "functional-profile",
                    "ok" if allowed else "error",
                    f"Funktionsprofil {functional.label}: {message}",
                )
        except Exception as exc:
            report.add(
                "functional-profile",
                "warning",
                f"Funktionsprofil konnte nicht geprüft werden: {exc}",
            )

    bundle_board = str(getattr(bundle, "board_key", "") or "")
    if bundle_board != board_key:
        report.add(
            "bundle-board", "error", "Firmwarepaket gehört zu einem anderen Board"
        )
    else:
        report.add("bundle-board", "ok", "Firmwarepaket passt zum Zielboard")

    try:
        details = services.validate_firmware_bundle(bundle, board_key)
        files = ", ".join(details.get("files") or [])
        report.add(
            "artifact", "ok", f"SHA256, Imageformat und Dateien geprüft: {files}"
        )
    except Exception as exc:
        report.add("artifact", "error", f"Firmwarepaket ungültig: {exc}")

    report.target_version = str(getattr(bundle, "version", "") or "")
    try:
        report.target_build = int(getattr(bundle, "run_number", 0) or 0) or None
    except Exception:
        report.target_build = None

    identity = _identity_for(services, port) if probe_device else None
    if identity is not None:
        report.installed_version = str(getattr(identity, "version", "") or "")
        report.installed_build = getattr(identity, "build", None)
        hardware = str(getattr(identity, "hardware", "") or "")
        detected = (
            services.detect_board_from_text(f"hardware: {hardware}\nJARNSEN-MESH")
            if hardware
            else None
        )
        if not detected and probe_device:
            try:
                recovery = services.recovery_probe(port, board_key)
                report.recovery_mode = str(recovery.get("mode") or "")
                detected = str(recovery.get("detected_board") or "") or None
            except Exception:
                detected = None
        if detected and detected != board_key:
            report.add(
                "device-board",
                "error",
                f"Angeschlossen ist {services.BOARD_PROFILES[detected]['label']}, nicht {board_label}",
            )
        elif detected == board_key:
            report.add(
                "device-board", "ok", "USB-Gerät und gewähltes Board stimmen überein"
            )
        else:
            report.add(
                "device-board",
                "warning",
                "Boardkennung fehlt in der Firmwareantwort; manuelle Boardauswahl wird verwendet",
            )
        installed = report.installed_version or "unbekannt"
        build = (
            f" · Build {report.installed_build}"
            if report.installed_build is not None
            else ""
        )
        target_build = (
            f" · Build {report.target_build}" if report.target_build is not None else ""
        )
        report.add(
            "versions",
            "ok",
            f"Installiert: {installed}{build} → Ziel: {report.target_version}{target_build}",
        )
        if bool(getattr(identity, "is_jarnsen", False)):
            current_key = _version_key(report.installed_version, report.installed_build)
            target_key = _version_key(report.target_version, report.target_build)
            if current_key[0] >= 0 and target_key[0] >= 0:
                if current_key > target_key:
                    report.add(
                        "version-order",
                        "error" if mode == "update" else "warning",
                        "Zielfirmware ist älter als die installierte JARNSEN-MESH Firmware",
                    )
                elif current_key == target_key:
                    report.add(
                        "version-order",
                        "warning",
                        "Diese Firmware ist bereits installiert; erneutes Schreiben ist optional",
                    )
                else:
                    report.add(
                        "version-order",
                        "ok",
                        "Zielfirmware ist neuer als die installierte Version",
                    )
    elif probe_device:
        try:
            recovery = services.recovery_probe(port, board_key)
            report.recovery_mode = str(recovery.get("mode") or "")
            if recovery.get("ready"):
                report.add(
                    "recovery",
                    "warning",
                    str(recovery.get("guidance") or "Bootloader bereit"),
                )
            else:
                report.add(
                    "recovery",
                    "error",
                    str(recovery.get("guidance") or "Gerät antwortet nicht"),
                )
        except Exception as exc:
            report.add("device", "error", f"Gerät konnte nicht geprüft werden: {exc}")
    else:
        report.add(
            "device", "warning", "Hardwareprüfung in diesem Testlauf übersprungen"
        )

    kind = str(
        services.BOARD_PROFILES[board_key].get("artifact_kind") or "esp32"
    ).lower()
    if mode == "update" and kind != "uf2":
        try:
            targets = list(
                getattr(bundle, "flash_targets", [])
                or services.esp32_update_targets(bundle)
            )
            if not targets:
                raise ValueError("keine App-Partition")
            labels = ", ".join(
                f"{label}@0x{offset:x}" for label, offset, _size in targets
            )
            report.add("targets", "ok", f"Dynamische Updateziele: {labels}")
        except Exception as exc:
            report.add(
                "targets", "error", f"Update-Partitionen nicht sicher bestimmbar: {exc}"
            )
    elif kind == "uf2":
        report.add("transport", "ok", "UF2-Bootloader-Übertragung wird verwendet")
    else:
        report.add("transport", "ok", "Vollständiger ESP-Factory-Flash wird verwendet")

    _emit(
        f"ADVANCED PREFLIGHT port={port!r} board={board_key!r} mode={mode!r} "
        f"ready={int(report.ready)} checks={len(report.items)} recovery={report.recovery_mode!r}"
    )
    return report


_SECRET_LINE = re.compile(
    r"(?i)(psk|password|passwd|token|secret|private[_ -]?key|channel[_ -]?key)"
)
_BEARER = re.compile(r"(?i)Bearer\s+[A-Za-z0-9._~+/=-]+")


def redact_support_text(value: Any) -> str:
    home = str(Path.home())
    safe: list[str] = []
    for raw in str(value or "").splitlines():
        line = raw.replace(home, "<HOME>") if home else raw
        line = _BEARER.sub("Bearer <redacted>", line)
        if _SECRET_LINE.search(line):
            if ":" in line:
                line = line.split(":", 1)[0] + ": <redacted>"
            elif "=" in line:
                line = line.split("=", 1)[0] + "=<redacted>"
            else:
                line = "<redacted sensitive line>"
        safe.append(line)
    return "\n".join(safe)


def friendly_error(exc: BaseException) -> tuple[str, tuple[str, ...]]:
    raw = str(exc) or type(exc).__name__
    lower = raw.casefold()
    if "usb_log_unsupported" in lower:
        return "Der USB-Node-Log ist erst mit JARNSEN-MESH-Firmware verfügbar.", (
            "Zuerst das Firmware-Update erfolgreich abschließen.",
            "Danach das Board neu erkennen lassen und den Node-Log erneut starten.",
        )
    if "supreme_port_missing" in lower:
        return "Der gewählte Supreme-COM-Port ist nicht mehr vorhanden.", (
            "Keinen V3 zusätzlich anschließen; nur den T-Beam Supreme verbunden lassen.",
            "BOOT gedrückt halten, USB einstecken und nach 2-3 Sekunden BOOT loslassen.",
            "Danach ‚Neu suchen‘ anklicken und nur einen tatsächlich angezeigten USB-COM-Port wählen.",
            "Falls das Board nicht eindeutig erkannt wird, T-Beam Supreme manuell auswählen.",
        )
    if "supreme_bootloader_sync" in lower:
        return "Der T-Beam Supreme benötigt den manuellen Downloadmodus.", (
            "Antenne angeschlossen lassen und das USB-Kabel abziehen.",
            "BOOT gedrückt halten, USB wieder einstecken und nach 2-3 Sekunden BOOT loslassen.",
            "Danach denselben Firmware-Update-Vorgang erneut starten; ‚Neu suchen‘ ist nicht erforderlich.",
        )
    if "board" in lower or ("gerät" in lower and "erkannt" in lower):
        return "Board oder Zielgerät konnte nicht sicher bestätigt werden.", (
            "Boardauswahl und angeschlossenen COM-Port prüfen.",
            "Nur das gewünschte Zielgerät angeschlossen lassen.",
        )
    if "sha256" in lower or "image-header" in lower or "firmwarepaket" in lower:
        return "Das Firmwarepaket ist unvollständig oder beschädigt.", (
            "Firmware erneut über ‚Neueste prüfen‘ laden.",
            "Bei einer PC-Datei das richtige Boardpaket auswählen.",
        )
    if (
        "bootloader_sync" in lower
        or "no serial data received" in lower
        or "failed to connect to espressif device" in lower
    ):
        return "Der ESP32 konnte nicht in den Flash-/Bootloader-Modus wechseln.", (
            "Nur dieses eine Board angeschlossen lassen und den Vorgang erneut starten.",
            "Falls der automatische USB-Reset erneut scheitert: BOOT gedrückt halten, RESET kurz drücken, dann BOOT loslassen.",
            "Eine niedrigere Baudrate hilft bei fehlender Bootloader-Antwort nicht.",
        )
    if is_retryable_flash_error(exc):
        return "Die USB-Verbindung wurde während des Vorgangs unterbrochen.", (
            "USB-Kabel und Port prüfen; möglichst keinen Hub verwenden.",
            "Gerät erneut verbinden und Recovery/Vorgang wiederholen.",
            "Der Flasher versucht automatisch niedrigere Baudraten.",
        )
    if "github" in lower or "http" in lower or "download" in lower:
        return "Firmware konnte nicht zuverlässig von GitHub geladen werden.", (
            "Internetverbindung prüfen und erneut versuchen.",
            "Ein begonnener Download wird automatisch fortgesetzt.",
        )
    return raw, (
        "Diagnose-ZIP für die genaue Ursache öffnen.",
        "Vorgang nach Prüfung von USB-Port und Board erneut starten.",
    )


def create_diagnostic_package(
    services: Any,
    *,
    app: Any | None = None,
    error: BaseException | None = None,
) -> Path:
    root = Path(services.PATHS.logs) / "SUPPORT"
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = root / f"JARNSEN-MESH-FLASHER-Diagnose-{stamp}.zip"

    selected_port = ""
    selected_board = ""
    if app is not None:
        try:
            # Error handling often runs on a worker. Do not read Tk variables
            # from that thread; plain Python device records are safe.
            devices = list(getattr(app, "devices", []) or [])
            if len(devices) == 1:
                selected_port = str(getattr(devices[0], "port", "") or "")
                selected_board = str(getattr(devices[0], "board_key", "") or "")
        except Exception:
            pass
    device_rows = []
    if app is not None:
        for device in list(getattr(app, "devices", []) or []):
            device_rows.append(
                {
                    "port": str(getattr(device, "port", "") or ""),
                    "description": str(getattr(device, "description", "") or ""),
                    "board_key": str(getattr(device, "board_key", "") or ""),
                }
            )
    bundle = getattr(app, "bundle", None) if app is not None else None
    bundle_row: dict[str, Any] = {}
    if bundle is not None:
        bundle_row = {
            "artifact": str(getattr(bundle, "artifact_name", "") or ""),
            "version": str(getattr(bundle, "version", "") or ""),
            "build": getattr(bundle, "run_number", None),
            "board_key": str(getattr(bundle, "board_key", "") or ""),
            "files": [
                {
                    "name": Path(value).name,
                    "bytes": Path(value).stat().st_size if Path(value).exists() else -1,
                }
                for value in {
                    str(getattr(bundle, "factory", "") or ""),
                    str(getattr(bundle, "update", "") or ""),
                    str(getattr(bundle, "webflasher", "") or ""),
                }
                if value
            ],
        }
    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "frozen": bool(getattr(sys, "frozen", False)),
        "selected_port": selected_port,
        "selected_board": selected_board,
        "error_type": type(error).__name__ if error else "",
        "error": redact_support_text(error) if error else "",
        "flash_baud": str(getattr(services, "_jarnsen_flash_baud", "")),
        "boards": sorted(services.BOARD_PROFILES),
        "devices": device_rows,
        "firmware": bundle_row,
    }
    log_text = ""
    if app is not None:
        try:
            path = Path(app.log_path)
            if path.exists():
                log_text = path.read_text(encoding="utf-8", errors="replace")[-250000:]
        except Exception:
            pass
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "summary.json", json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
        )
        archive.writestr("flasher-redacted.log", redact_support_text(log_text))
        archive.writestr(
            "README.txt",
            "Dieses Paket enthält keine Profile oder Firmwaredateien. "
            "Kennwörter, Tokens, PSKs und private Schlüssel werden geschwärzt.\n",
        )
    _emit(f"SUPPORT PACKAGE READY path={str(target)!r} bytes={target.stat().st_size}")
    return target


def start_factory_reset(app: Any, services: Any) -> None:
    if getattr(app, "busy", False):
        return
    device = app._selected_device()
    board_key = app._selected_board_key()
    if device is None or board_key not in services.BOARD_PROFILES:
        messagebox.showwarning(
            "Zielgerät fehlt",
            "Bitte zuerst COM-Port und Board eindeutig auswählen.",
            parent=app,
        )
        return
    label = str(services.BOARD_PROFILES[board_key]["label"])
    if not messagebox.askyesno(
        "Werkseinstellung - Daten werden gelöscht",
        f"Port: {device.port}\nBoard: {label}\n\n"
        "Ein Sicherheitsbackup wird angelegt. Danach werden Einstellungen, Namen, "
        "Kanäle und lokale Daten gelöscht.\n\nWerkseinstellung wirklich starten?",
        parent=app,
    ):
        return

    app._set_busy(True)

    def worker() -> None:
        try:
            app._set_progress(0.04, "Werkseinstellung · Firmware laden")
            bundle = getattr(app, "bundle", None)
            if bundle is None or getattr(bundle, "board_key", None) != board_key:
                bundle = services.GitHubFirmwareClient().resolve_latest(board_key)
                app.bundle = bundle
            report = run_preflight(services, device.port, board_key, bundle, "factory")
            for line in report.format().splitlines():
                if line:
                    app._append_log(f"PREFLIGHT · {line}")
            if not report.ready:
                raise services.FlasherError(report.format())

            app._set_progress(0.18, "Werkseinstellung · Sicherheitsbackup")
            backup = services.backup_flash(device.port, board_key)
            kind = str(
                services.BOARD_PROFILES[board_key].get("artifact_kind") or "esp32"
            ).lower()
            if kind == "uf2":
                app._set_progress(0.36, "Werkseinstellung · Konfiguration löschen")
                services.meshtastic(device.port, "--factory-reset", timeout=90)
                services.wait_for_serial(device.port, timeout=90)
            live_port = services.resolve_live_port(device.port)
            app._set_progress(0.42, "Werkseinstellung · Factory-Firmware schreiben")
            services.flash_bundle(live_port, bundle, log=app._append_log)
            app._set_progress(0.92, "Werkseinstellung · Auf USB warten")
            services.wait_for_serial(live_port, timeout=120)
            live_port = services.resolve_live_port(live_port)
            services.verify_node(live_port, expected_board=board_key)
            app._set_progress(1.0, "Werkseinstellung abgeschlossen")
            app.after(
                0,
                messagebox.showinfo,
                "Werkseinstellung abgeschlossen",
                f"{label} wurde vollständig neu installiert.\n\nBackup: {Path(backup).name}\n"
                "Einstellungen und Namen wurden nicht wiederhergestellt.",
            )
        except Exception as exc:
            app._show_error(exc)
        finally:
            app._set_busy(False)

    threading.Thread(target=worker, name="jarnsen-factory-reset", daemon=True).start()


def start_preflight_check(app: Any, services: Any) -> None:
    if getattr(app, "busy", False):
        return
    device = app._selected_device()
    board_key = app._selected_board_key()
    if device is None or board_key not in services.BOARD_PROFILES:
        messagebox.showwarning(
            "Vorabcheck",
            "Bitte zuerst COM-Port und Board eindeutig auswählen.",
            parent=app,
        )
        return
    selected = (
        str(getattr(app, "operation_mode", None).get())
        if hasattr(app, "operation_mode")
        else "Firmware-Update"
    )
    mode = {
        "Erstflash": "provision",
        "Firmware-Update": "update",
        "Reparatur": "repair",
        "Werkseinstellung": "factory",
    }.get(selected, "update")
    app._set_busy(True)

    def worker() -> None:
        try:
            app._set_progress(0.08, "Vorabcheck · Firmwarepaket prüfen")
            bundle = getattr(app, "bundle", None)
            if bundle is None or getattr(bundle, "board_key", None) != board_key:
                bundle = services.GitHubFirmwareClient().resolve_latest(board_key)
                app.bundle = bundle
                app.after(0, app.firmware_var.set, bundle.display_name)
            app._set_progress(0.45, "Vorabcheck · USB-Gerät und Partitionen prüfen")
            report = run_preflight(services, device.port, board_key, bundle, mode)
            for line in report.format().splitlines():
                if line:
                    app._append_log(f"PREFLIGHT · {line}")
            state = "Bereit" if report.ready else "Gesperrt"
            app._set_progress(1.0 if report.ready else 0.0, f"Vorabcheck · {state}")
            show = messagebox.showinfo if report.ready else messagebox.showerror
            app.after(0, show, "Vorabcheck", report.format())
        except Exception as exc:
            app._show_error(exc)
        finally:
            app._set_busy(False)

    threading.Thread(target=worker, name="jarnsen-preflight", daemon=True).start()


def _provisioning_profile_ready(app: Any, services: Any) -> bool:
    """Require a selected profile before the destructive first-flash workflow."""
    board_key = (
        app._selected_board_key() if hasattr(app, "_selected_board_key") else None
    )
    try:
        from functional_profiles import active_profile as active_functional_profile
        from functional_profiles import firmware_compatibility_for_board

        functional = active_functional_profile(services)
    except Exception as exc:
        messagebox.showerror(
            "Erstflash",
            f"Funktionsprofil konnte nicht gelesen werden.\n\n{exc}",
            parent=app,
        )
        return False
    if functional is None:
        messagebox.showwarning(
            "Funktionsprofil auswählen",
            "Beim Erstflash bitte zuerst auswählen, als was dieses Board arbeiten soll: "
            "TAK, TAK TRACKER, TAK REPEATER oder DRONE REPEATER.",
            parent=app,
        )
        return False
    allowed, reason = firmware_compatibility_for_board(functional, board_key, services)
    if not allowed:
        messagebox.showerror("Erstflash nicht möglich", reason, parent=app)
        return False
    return True


def start_flash_mode(app: Any, services: Any, mode: str) -> None:
    if mode == "provision":
        if _provisioning_profile_ready(app, services):
            app.start_flash(flash_mode="provision")
        return
    if mode == "update":
        import native_actions

        native_actions.start_firmware_only(app, services)
    elif mode == "repair":
        app.start_flash()
    elif mode == "factory":
        start_factory_reset(app, services)
    else:
        raise services.FlasherError(f"Unbekannter Flashmodus: {mode}")


def install(services: Any) -> None:
    if getattr(services, "_jarnsen_advanced_flasher_v1", False):
        return

    hash_cache = HashCache(Path(services.PATHS.root))
    services._sha256 = hash_cache.digest
    services.firmware_hash_cache = hash_cache
    services.run_flash_preflight = (
        lambda port, board_key, bundle, mode="update", probe_device=True: run_preflight(
            services, port, board_key, bundle, mode, probe_device=probe_device
        )
    )
    services.create_diagnostic_package = (
        lambda app=None, error=None: create_diagnostic_package(
            services, app=app, error=error
        )
    )
    services.flash_baud_candidates = baud_candidates
    services.is_retryable_flash_error = is_retryable_flash_error

    client_type = services.GitHubFirmwareClient
    base_get_json = client_type._get_json

    def retrying_get_json(self: Any, url: str, **params: Any) -> dict:
        last_error: BaseException | None = None
        for attempt in range(1, 4):
            try:
                return base_get_json(self, url, **params)
            except Exception as exc:
                last_error = exc
                text = str(exc).casefold()
                transient = any(
                    token in text
                    for token in (
                        "http 429",
                        "http 500",
                        "http 502",
                        "http 503",
                        "http 504",
                        "timeout",
                        "connection",
                        "temporarily unavailable",
                    )
                )
                if attempt >= 3 or not transient:
                    raise
                _emit(f"GITHUB JSON RETRY attempt={attempt}/3 url={url!r} error={exc}")
                time.sleep(float(attempt))
        if last_error is not None:
            raise last_error

    client_type._get_json = retrying_get_json

    base_flash_bundle: Callable[..., Any] = services.flash_bundle

    def resilient_flash_bundle(port: str, bundle: Any, log=None):
        profile = services.BOARD_PROFILES.get(getattr(bundle, "board_key", ""), {})
        if str(profile.get("artifact_kind") or "esp32").lower() == "uf2":
            return base_flash_bundle(port, bundle, log=log)
        selected = str(getattr(services, "_jarnsen_flash_baud", "921600"))
        candidates = baud_candidates(selected)
        last_error: BaseException | None = None
        for index, baud in enumerate(candidates, start=1):
            services._jarnsen_flash_baud = baud
            try:
                if log and index > 1:
                    log(
                        f"RECOVERY · Flash erneut mit {baud} Baud ({index}/{len(candidates)})"
                    )
                return base_flash_bundle(port, bundle, log=log)
            except Exception as exc:
                last_error = exc
                if index >= len(candidates) or not is_retryable_flash_error(exc):
                    raise
                if log:
                    log(
                        f"RECOVERY · USB-Fehler bei {baud} Baud · nächster sicherer Versuch"
                    )
                time.sleep(1.0)
        if last_error is not None:
            raise last_error

    resilient_flash_bundle._jarnsen_resilient_flash = True
    services.flash_bundle = resilient_flash_bundle
    services._jarnsen_advanced_flasher_v1 = True
    _emit(
        "ADVANCED FLASHER installed modes=provision,update,repair,factory preflight=1 "
        "hash-cache=1 download-resume=1 flash-baud-fallback=1 support-zip=1"
    )
