"""Safety contracts for Framework7 serial flash/recovery actions."""
from __future__ import annotations

import hashlib
import json
import re
import threading
import urllib.parse
from typing import Any, Callable

import JARNSEN_FRAMEWORK7_SERIES as series
from JARNSEN_FRAMEWORK7_SERIES_HARDENING import (
    OTA_LOADER_OFFSET,
    OTA_LOADER_SHA256,
    _detect_usb_hardware,
    _validate_manifest_contract,
)

MAX_SERVICE_REQUEST = 2 * 1024 * 1024


def _target_port(bridge: Any, payload: dict[str, Any]) -> str:
    requested = str(payload.get("port") or "").strip()
    targets = bridge._usb_targets() if hasattr(bridge, "_usb_targets") else []
    if requested:
        if any(str(item.get("device") or "") == requested for item in targets):
            return requested
        raise RuntimeError(f"USB/COM-Port {requested} ist nicht mehr verfügbar")
    node_id = str(payload.get("node_id") or "")
    if hasattr(bridge, "_current_usb_port"):
        try:
            resolved = str(bridge._current_usb_port(node_id) or "").strip()
            if resolved:
                return resolved
        except Exception:
            pass
    if len(targets) == 1:
        return str(targets[0].get("device") or "")
    if len(targets) > 1:
        raise RuntimeError("Mehrere USB/COM-Nodes erkannt – bitte den Ziel-Port auswählen")
    raise RuntimeError("Keine kompatible USB/COM-Node erkannt")


def _validate_bundle(bundle: Any, code: str) -> tuple[bytes, bytes, dict[str, Any]]:
    if not isinstance(bundle, tuple) or len(bundle) != 3:
        raise RuntimeError("Serielles Firmwarebundle ist unvollständig")
    firmware, loader, manifest = bundle
    manifest = dict(manifest)
    _validate_manifest_contract(manifest, code)
    series._validate_image(
        bytes(firmware),
        int(manifest.get("firmware_size") or 0),
        str(manifest.get("firmware_sha256") or ""),
    )
    if hashlib.sha256(bytes(loader)).hexdigest() != OTA_LOADER_SHA256:
        raise RuntimeError("otaBTupdate entspricht nicht dem geprüften Loader")
    if str(manifest.get("ota_partition_offset") or OTA_LOADER_OFFSET).lower() != OTA_LOADER_OFFSET.lower():
        raise RuntimeError("OTA-Loader-Offset im Manifest ist nicht 0x340000")
    return bytes(firmware), bytes(loader), manifest


def _install_one_shot_bundle(
    tool: Any, code: str, bundle: tuple[bytes, bytes, dict[str, Any]]
) -> Callable[[], None]:
    previous = getattr(tool, "_download_serial_bundle", None)
    if not callable(previous):
        raise RuntimeError("Serieller Firmware-Bundle-Loader fehlt")
    token = object()
    tool._framework7_generic_flash_cache_token = token

    def restore() -> None:
        if tool.__dict__.get("_framework7_generic_flash_cache_token") is token:
            tool._framework7_generic_flash_cache_token = None
        if getattr(tool, "_download_serial_bundle", None) is cached:
            tool._download_serial_bundle = previous

    def cached(requested_code: str):
        requested_code = str(requested_code or "").upper()
        if (
            requested_code == code
            and tool.__dict__.get("_framework7_generic_flash_cache_token") is token
        ):
            restore()
            return bundle
        return previous(requested_code)

    tool._download_serial_bundle = cached
    return restore


def _restore_bundle_after_worker(tool: Any, restore: Callable[[], None]) -> None:
    """Remove the one-shot loader after success, early failure or cancellation."""
    worker = tool.__dict__.get("worker")
    checker = getattr(worker, "is_alive", None)
    if not callable(checker):
        restore()
        return
    try:
        active = bool(checker())
    except Exception:
        active = False
    if not active:
        restore()
        return

    def wait_and_restore() -> None:
        try:
            joiner = getattr(worker, "join", None)
            if callable(joiner):
                joiner()
        finally:
            restore()

    threading.Thread(
        target=wait_and_restore,
        daemon=True,
        name="framework7-serial-bundle-cleanup",
    ).start()


def install_flash_hardening(LegacyBridge: type, ApiHandler: type) -> None:
    if bool(getattr(LegacyBridge, "_framework7_flash_hardening_installed", False)):
        return
    if not hasattr(LegacyBridge, "service_action"):
        raise RuntimeError("Parity service_action muss vor Flash-Hardening installiert sein")

    previous_action = LegacyBridge.service_action

    def service_action(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise RuntimeError("Service-Aktion muss ein JSON-Objekt sein")
        command = str(payload.get("command") or "").strip()
        if command not in {"serial_flash", "recovery_usb"}:
            return previous_action(self, payload)

        hardware = str(payload.get("hardware") or "").upper()
        if hardware not in series.DEVICES:
            raise RuntimeError("Hardware muss TRACKER oder V3 sein")
        if getattr(self.tool, "worker", None) is not None and self.tool.worker.is_alive():
            raise RuntimeError("Ein anderer Vorgang läuft bereits")
        if hasattr(self.tool, "serial_monitor_active") and self.tool.serial_monitor_active():
            raise RuntimeError("Seriellen Monitor vor dem Firmwareupdate stoppen")

        def identify() -> str:
            port = _target_port(self, payload)
            detected = _detect_usb_hardware(self.tool, port)
            if detected not in series.DEVICES:
                raise RuntimeError(
                    "Hardware konnte für Recovery nicht sicher von der USB-Node erkannt werden. "
                    "Virgin-Nodes bitte über 'Serie / Nodes einrichten' mit eindeutigem Grundprofil initialisieren."
                )
            if detected != hardware:
                raise RuntimeError(
                    f"Recovery abgebrochen: erkannt {series.DEVICES[detected]['label']}, "
                    f"ausgewählt {series.DEVICES[hardware]['label']}"
                )
            return port

        port = self.call_ui(identify, timeout=45.0)
        loader = getattr(self.tool, "_download_serial_bundle", None)
        if not callable(loader):
            raise RuntimeError("Serieller Firmware-Bundle-Loader fehlt")
        bundle = _validate_bundle(loader(hardware), hardware)
        restore = _install_one_shot_bundle(self.tool, hardware, bundle)
        guarded = dict(payload)
        guarded["port"] = port
        try:
            result = previous_action(self, guarded)
        except Exception:
            restore()
            raise
        _restore_bundle_after_worker(self.tool, restore)
        if isinstance(result, dict):
            result["hardware_verified"] = hardware
            result["preflight_bundle"] = True
        return result

    LegacyBridge.service_action = service_action

    previous_status = LegacyBridge.service_status

    def service_status(self: Any) -> dict[str, Any]:
        data = previous_status(self)
        critical = data.setdefault("critical", {})
        critical["serial_flash_hardware_guard"] = True
        critical["serial_flash_preflight_bundle"] = True
        data["ok"] = all(bool(value) for value in critical.values())
        return data

    LegacyBridge.service_status = service_status

    previous_post = ApiHandler.do_POST

    def do_POST(self: Any) -> None:  # noqa: N802
        if urllib.parse.urlparse(self.path).path != "/api/service/action":
            return previous_post(self)
        if not self._authorized():
            self._send(403, {"ok": False, "error": "forbidden"})
            return
        try:
            raw_length = str(self.headers.get("Content-Length", "") or "").strip()
            if not re.fullmatch(r"\d+", raw_length):
                self._send(400, {"ok": False, "error": "Ungültige Content-Length"})
                return
            length = int(raw_length)
            if length <= 0 or length > MAX_SERVICE_REQUEST:
                self._send(
                    413 if length > MAX_SERVICE_REQUEST else 400,
                    {"ok": False, "error": "Service-Anforderung ist leer oder zu groß"},
                )
                return
            raw = self.rfile.read(length)
            if len(raw) != length:
                self._send(400, {"ok": False, "error": "Service-Anforderung ist unvollständig"})
                return
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                self._send(400, {"ok": False, "error": "Service-Aktion muss ein JSON-Objekt sein"})
                return
            self._send(200, self.bridge.service_action(payload))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            self._send(400, {"ok": False, "error": f"Ungültige Service-Anforderung: {exc}"})
        except RuntimeError as exc:
            self._send(409, {"ok": False, "error": str(exc), "type": type(exc).__name__})
        except Exception as exc:  # noqa: BLE001
            self._send(500, {"ok": False, "error": str(exc), "type": type(exc).__name__})

    ApiHandler.do_POST = do_POST
    LegacyBridge._framework7_flash_hardening_installed = True
