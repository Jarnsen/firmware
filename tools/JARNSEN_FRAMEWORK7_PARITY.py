"""Framework7 parity bridge for every operator-facing stable Service Tool feature.

The v3 app deliberately keeps the complete v2.2.x Python service core as its
backend.  This module exposes the remaining operator workflows that were still
reachable only through the hidden Tk UI: serial monitor, full USB resync, serial
firmware/recovery, diagnostic bundle, config snapshots, app self-update and the
Jarnsen full-lock profile policy.

Automatic BLE/USB maintenance, database/history handling, profile verification,
OTA, maps and device policy continue to run in the same patched backend and are
reported in the parity matrix as inherited rather than reimplemented.
"""
from __future__ import annotations

import contextlib
import json
import pathlib
import threading
import urllib.parse
from typing import Any


STABLE_FEATURE_GROUPS = (
    ("Node-Verwaltung", "framework7", (
        "all-nodes-overview", "tile-first-node-dashboard", "node-search-filter-sort",
        "node-batch-actions", "per-node-edit-delete-menu", "managed-node-database",
        "same-name-history-alias-merge", "node-manager-multi-delete",
    )),
    ("BLE & Automatik", "inherited", (
        "automatic-ble-discovery-pairing", "windows-fixed-pin-custom-pairing",
        "persistent-ble-node-mapping", "ble-automatic-first-download",
        "ble-log-freshness-queue", "ble-auto-busy-retry", "30-second-idle-ble-scan",
        "ble-activity-trace", "per-node-sync-status", "resilient-auto-usb-retry",
        "sticky-auto-usb-session", "post-reset-auto-usb-log-grace",
    )),
    ("Profile & Provisioning", "framework7", (
        "tabbed-full-profile-editor", "descriptor-driven-profile-controls",
        "protobuf-upb-profile-editor-compat", "profile-setting-cards",
        "enum-bool-dropdowns", "profile-json-all-values-editor",
        "symmetric-read-write-profile-sections", "direct-admin-statusmessage-tak-write",
        "blank-target-name-preservation", "profile-source-name-prefill",
        "firmware-owned-position-verification", "firmware-owned-bluetooth-enabled-verification",
        "neighbor-info-policy-verification", "lora-standard-policy-verification",
        "profile-readback-verification", "usb-first-auto-profile-transport",
        "full-device-reset-profile-provisioning", "virgin-node-bootstrap-provisioning",
        "policy-last-usb-handoff", "one-jarnsen-pin-240180", "bluetooth-fixed-pin-240180",
    )),
    ("Jarnsen Schutz & Funk", "framework7", (
        "standard-jarnsen-a-jarnsen-b-rf-modes", "gated-authorized-frequency-a-b-ui",
        "authorized-hop-limit-up-to-20-gated", "authorized-duty-cycle-override-gated",
        "normal-meshtastic-limits-without-authorization", "service-admin-pin-policy",
        "15-minute-admin-unlock-policy", "persistent-full-lock-policy",
        "double-click-third-hold-3s-lock-gesture", "mesh-lock-alert-policy",
        "locked-full-unlocked-status-policy",
    )),
    ("Logs & Verlauf", "framework7", (
        "delta-log-generation-cursor-sync", "jarnsen-tool-usb-handshake",
        "explicit-node-usb-ack", "manual-full-log-resync", "managed-node-log-sync-state",
        "historical-position-map", "firmware-version-history-summary",
    )),
    ("Firmware & Recovery", "framework7", (
        "serial-latest-firmware-plus-otabt", "canonical-tracker-jarn-mesh-manifest",
        "direct-firmware-update-offer", "auto-usb-firmware-check-and-offer",
        "physical-usb-com-refind", "firmware-update-database-sync", "ble-ota",
        "serial-github-flash", "ble-authentication-guidance",
    )),
    ("Darstellung & Live", "improved", (
        "macos-ios-desktop-shell", "tabless-sidebar-navigation", "contextual-node-inspector",
        "adaptive-light-dark-shell", "macos-style-node-cards", "macos-style-action-sheets",
        "global-command-search", "contextual-bulk-action-bar", "customtkinter-liquid-surfaces",
        "true-rounded-node-cards", "rounded-inspector", "rounded-toolbar-and-sidebar",
        "pill-filter-controls", "softened-legacy-pages", "legacy-header-removal",
        "jarn-mesh-semantic-version-display",
    )),
)


def install_parity(LegacyBridge: type, ApiHandler: type) -> None:
    """Expose all remaining stable Service Tool workflows to Framework7."""

    def _usb_port(self: Any, requested: str = "", node_id: str = "") -> str:
        requested = str(requested or "").strip()
        targets = self._usb_targets() if hasattr(self, "_usb_targets") else []
        if requested:
            if any(str(item.get("device") or "") == requested for item in targets):
                return requested
            raise RuntimeError(f"USB/COM-Port {requested} ist nicht mehr verfügbar")
        if hasattr(self, "_current_usb_port"):
            with contextlib.suppress(Exception):
                port = str(self._current_usb_port(node_id) or "").strip()
                if port:
                    return port
        if len(targets) == 1:
            return str(targets[0].get("device") or "")
        if len(targets) > 1:
            raise RuntimeError("Mehrere USB/COM-Nodes erkannt – bitte den Ziel-Port auswählen")
        raise RuntimeError("Keine kompatible USB/COM-Node erkannt")

    def _set_selected_node(self: Any, node_id: str) -> str:
        normalized = str(node_id or "").strip()
        if not normalized:
            raise RuntimeError("Bitte eine Node auswählen")
        old = str(getattr(self.tool, "selected_node_id", "") or "")
        self.tool.selected_node_id = normalized
        return old

    def _service_collect(self: Any) -> dict[str, Any]:
        targets = self._usb_targets() if hasattr(self, "_usb_targets") else []
        serial_active = bool(
            hasattr(self.tool, "serial_monitor_active") and self.tool.serial_monitor_active()
        )
        serial_text = ""
        widget = getattr(self.tool, "serial_monitor_text", None)
        if widget is not None:
            with contextlib.suppress(Exception):
                serial_text = str(widget.get("1.0", "end-1c"))[-16000:]
        serial_status = ""
        status_widget = getattr(self.tool, "serial_monitor_status", None)
        if status_widget is not None:
            with contextlib.suppress(Exception):
                serial_status = str(status_widget.cget("text") or "")
        app_manifest = dict(getattr(self.tool, "app_update_manifest", {}) or {})
        profiles = self.tool.config_profile_store.get("profiles", [])
        security_profiles: list[dict[str, Any]] = []
        if isinstance(profiles, list):
            for slot, profile in enumerate(profiles):
                if not isinstance(profile, dict):
                    continue
                if hasattr(self.tool, "_ensure_jarnsen_policy_defaults_v2122"):
                    self.tool._ensure_jarnsen_policy_defaults_v2122(profile)
                security_profiles.append({
                    "slot": slot,
                    "name": str(profile.get("name") or f"Profil {slot + 1}"),
                    "pin": str(profile.get("jarnsen_pin") or "240180"),
                    "admin_minutes": int(profile.get("jarnsen_admin_unlock_minutes") or 15),
                    "full_lock_alert_mesh": bool(profile.get("jarnsen_full_lock_alert_mesh", True)),
                    "full_lock_gesture": str(profile.get("jarnsen_full_lock_gesture") or "DOUBLE_CLICK_THIRD_HOLD_3S"),
                    "lock_retries": int(profile.get("jarnsen_full_lock_alert_retries") or 3),
                })

        critical = {
            "serial_monitor": all(hasattr(self.tool, name) for name in (
                "start_serial_monitor", "stop_serial_monitor", "send_serial_monitor_command",
            )),
            "serial_flash": hasattr(self.tool, "_serial_update_worker"),
            "full_usb_resync": hasattr(self.tool, "start_full_usb_log_sync"),
            "diagnostic_bundle": hasattr(self.tool, "create_diagnostic_bundle"),
            "config_snapshot": hasattr(self.tool, "_auto_config_snapshot"),
            "app_self_update": all(hasattr(self.tool, name) for name in (
                "check_app_update", "_install_app_update_worker",
            )),
            "ble_ota": hasattr(self.tool, "batch_ota_v2133"),
            "profile_policy": hasattr(self.tool, "_ensure_jarnsen_policy_defaults_v2122"),
        }
        parity_groups = [
            {"group": group, "mode": mode, "features": list(features), "ok": True}
            for group, mode, features in STABLE_FEATURE_GROUPS
        ]
        return {
            "ok": all(critical.values()),
            "critical": critical,
            "usb": targets,
            "serial": {
                "active": serial_active,
                "status": serial_status or ("Monitor läuft" if serial_active else "Monitor gestoppt"),
                "bytes": int(getattr(self.tool, "serial_monitor_bytes", 0) or 0),
                "log_path": str(getattr(self.tool, "serial_monitor_log_path", "") or ""),
                "tail": serial_text,
            },
            "app_update": {
                "available": bool(getattr(self.tool, "app_update_available", False)),
                "remote_version": str(app_manifest.get("version") or ""),
                "manifest": app_manifest,
                "url_ready": bool(str(getattr(self.tool, "app_update_url", "") or "")),
            },
            "security_profiles": security_profiles,
            "parity": parity_groups,
            "stable_reference": "v2.2.1 operator features + v2.2.4 backend fixes",
            "backend_strategy": "same patched Python service core; Framework7 replaces only presentation",
        }

    def service_status(self: Any) -> dict[str, Any]:
        return self.call_ui(lambda: _service_collect(self), timeout=15.0)

    def _diagnostic_bundle(self: Any) -> dict[str, Any]:
        import JARNSEN_NODE_SERVICE_TOOL as legacy

        output = pathlib.Path(legacy.output_directory())
        before = set(output.glob("Jarnsen_Diagnosepaket_*.zip"))
        old_info = legacy.messagebox.showinfo
        old_error = legacy.messagebox.showerror
        captured_errors: list[str] = []
        legacy.messagebox.showinfo = lambda *_a, **_k: None
        legacy.messagebox.showerror = lambda _title, message, **_k: captured_errors.append(str(message))
        try:
            self.tool.create_diagnostic_bundle()
        finally:
            legacy.messagebox.showinfo = old_info
            legacy.messagebox.showerror = old_error
        if captured_errors:
            raise RuntimeError(captured_errors[-1])
        after = [path for path in output.glob("Jarnsen_Diagnosepaket_*.zip") if path not in before]
        if not after:
            after = list(output.glob("Jarnsen_Diagnosepaket_*.zip"))
        if not after:
            raise RuntimeError("Diagnosepaket konnte nicht erstellt werden")
        target = max(after, key=lambda path: path.stat().st_mtime)
        return {"message": "Diagnosepaket erstellt", "path": str(target)}

    def _config_snapshot(self: Any, node_id: str) -> dict[str, Any]:
        old = _set_selected_node(self, node_id)
        try:
            target = self.tool._auto_config_snapshot("manual-framework7")
        finally:
            self.tool.selected_node_id = old
        if not target:
            raise RuntimeError("Konfig-Snapshot konnte nicht erstellt werden")
        return {"message": "Konfig-Snapshot gespeichert", "path": str(target)}

    def _serial_monitor_start(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
        port = _usb_port(self, payload.get("port"), str(payload.get("node_id") or ""))
        if getattr(self.tool, "worker", None) and self.tool.worker.is_alive():
            raise RuntimeError("Ein Log-/Firmwarevorgang läuft bereits")
        if self.tool.serial_monitor_active():
            return {"message": "Serieller Monitor läuft bereits", "port": port}
        baud = int(payload.get("baud") or 115200)
        if baud not in {9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600}:
            raise RuntimeError("Nicht unterstützte Baudrate")
        self.tool._select_serial_port_in_ui(port)
        self.tool.serial_baud.set(str(baud))
        self.tool.start_serial_monitor()
        return {"message": f"Serieller Monitor {port} @ {baud} gestartet", "port": port, "baud": baud}

    def _serial_monitor_stop(self: Any) -> dict[str, Any]:
        if self.tool.serial_monitor_active():
            self.tool.stop_serial_monitor()
        return {"message": "Serieller Monitor wird beendet"}

    def _serial_monitor_send(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.tool.serial_monitor_active():
            raise RuntimeError("Serieller Monitor ist nicht verbunden")
        command = str(payload.get("text") or "")
        if not command:
            raise RuntimeError("Kein serieller Befehl angegeben")
        entry = self.tool.serial_command
        entry.delete(0, "end")
        entry.insert(0, command)
        if hasattr(self.tool, "serial_send_newline_var"):
            self.tool.serial_send_newline_var.set(bool(payload.get("newline", True)))
        self.tool.send_serial_monitor_command()
        return {"message": "Befehl gesendet"}

    def _serial_flash(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
        hardware = str(payload.get("hardware") or "").upper()
        if hardware not in {"TRACKER", "V3"}:
            raise RuntimeError("Hardware muss TRACKER oder V3 sein")
        port = _usb_port(self, payload.get("port"), str(payload.get("node_id") or ""))
        if getattr(self.tool, "worker", None) and self.tool.worker.is_alive():
            raise RuntimeError("Ein anderer Vorgang läuft bereits")
        if hasattr(self.tool, "serial_monitor_active") and self.tool.serial_monitor_active():
            raise RuntimeError("Seriellen Monitor vor dem Firmwareupdate stoppen")
        self.tool._select_serial_port_in_ui(port)
        with contextlib.suppress(Exception):
            self.tool.device.set("Tracker V1.1" if hardware == "TRACKER" else "Heltec V3")
        self.tool.stop_event.clear()
        self.tool.worker = threading.Thread(
            target=self.tool._serial_update_worker,
            args=(port, hardware),
            daemon=True,
            name=f"framework7-serial-flash-{hardware.lower()}",
        )
        self.tool.worker.start()
        return {"message": f"USB-Recovery/Firmwareupdate für {hardware} auf {port} gestartet", "port": port}

    def _full_resync(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
        port = _usb_port(self, payload.get("port"), str(payload.get("node_id") or ""))
        if getattr(self.tool, "worker", None) and self.tool.worker.is_alive():
            raise RuntimeError("Ein anderer Vorgang läuft bereits")
        if hasattr(self.tool, "serial_monitor_active") and self.tool.serial_monitor_active():
            raise RuntimeError("Seriellen Monitor vor der Log-Synchronisierung stoppen")
        self.tool._select_serial_port_in_ui(port)
        self.tool.start_full_usb_log_sync()
        return {"message": f"Vollständige USB-Log-Synchronisierung auf {port} gestartet", "port": port}

    def _ble_recovery(self: Any, node_id: str) -> dict[str, Any]:
        if not node_id:
            raise RuntimeError("Bitte eine Node für Bluetooth-Recovery auswählen")
        self._select_nodes([node_id])
        self.tool.batch_ota_v2133([node_id])
        return {"message": "Bluetooth-Recovery/OTA gestartet", "node_id": node_id}

    def _save_security_policy(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
        slot = int(payload.get("slot", -1))
        profiles = self.tool.config_profile_store.get("profiles", [])
        profile = profiles[slot] if isinstance(profiles, list) and 0 <= slot < len(profiles) else None
        if not isinstance(profile, dict):
            raise RuntimeError("Profil-Slot ist leer")
        self.tool._ensure_jarnsen_policy_defaults_v2122(profile)
        profile["jarnsen_pin"] = "240180"
        profile["jarnsen_admin_unlock_minutes"] = 15
        profile["jarnsen_full_lock_alert_mesh"] = bool(payload.get("full_lock_alert_mesh", True))
        profile["jarnsen_full_lock_gesture"] = "DOUBLE_CLICK_THIRD_HOLD_3S"
        profile["jarnsen_full_lock_alert_retries"] = 3
        import JARNSEN_NODE_SERVICE_TOOL as legacy
        profile["saved_at"] = legacy.now_local().isoformat(timespec="seconds")
        self.tool._save_config_profile_store()
        with contextlib.suppress(Exception):
            self.tool._refresh_config_profile_ui()
        return {"message": "Jarnsen Schutz-Policy im Profil gespeichert", "slot": slot}

    def service_action(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
        command = str(payload.get("command") or "").strip()

        def execute() -> dict[str, Any]:
            if command == "diagnostic_bundle":
                return _diagnostic_bundle(self)
            if command == "config_snapshot":
                return _config_snapshot(self, str(payload.get("node_id") or ""))
            if command == "serial_monitor_start":
                return _serial_monitor_start(self, payload)
            if command == "serial_monitor_stop":
                return _serial_monitor_stop(self)
            if command == "serial_monitor_send":
                return _serial_monitor_send(self, payload)
            if command == "serial_monitor_clear":
                self.tool.clear_serial_monitor()
                return {"message": "Serielle Anzeige gelöscht"}
            if command == "serial_monitor_marker":
                self.tool.add_serial_marker()
                return {"message": "Marker gesetzt"}
            if command == "serial_flash" or command == "recovery_usb":
                return _serial_flash(self, payload)
            if command == "full_log_resync":
                return _full_resync(self, payload)
            if command == "ble_recovery":
                return _ble_recovery(self, str(payload.get("node_id") or ""))
            if command == "app_update_check":
                self.tool.check_app_update(interactive=False)
                return {"message": "Tool-Updateprüfung gestartet"}
            if command == "app_update_install":
                if not bool(getattr(self.tool, "app_update_available", False)):
                    raise RuntimeError("Kein Tool-Update ist zur Installation vorgemerkt")
                if not str(getattr(self.tool, "app_update_url", "") or ""):
                    raise RuntimeError("Update-Datei ist noch nicht verfügbar")
                threading.Thread(
                    target=self.tool._install_app_update_worker,
                    daemon=True,
                    name="framework7-self-update",
                ).start()
                return {"message": "Tool-Update wird installiert; die App startet anschließend neu"}
            if command == "save_security_policy":
                return _save_security_policy(self, payload)
            if command == "usb_log":
                result = self.action({
                    "command": "usb_log",
                    "node_id": str(payload.get("node_id") or ""),
                    "node_ids": [str(payload.get("node_id") or "")] if str(payload.get("node_id") or "") else [],
                })
                return {"message": "USB-Logdownload gestartet", "detail": result}
            raise RuntimeError(f"Unbekannte Service-Aktion: {command}")

        # App update checker creates its own worker; everything else must touch Tk
        # widgets/state on the Tk thread before any legacy worker is started.
        return self.call_ui(execute, timeout=40.0)

    LegacyBridge.service_status = service_status
    LegacyBridge.service_action = service_action

    original_get = ApiHandler.do_GET
    original_post = ApiHandler.do_POST

    def do_GET(self: Any) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/service-status":
            if not self._authorized():
                self._send(403, {"ok": False, "error": "forbidden"})
                return
            try:
                self._send(200, self.bridge.service_status())
            except Exception as exc:  # noqa: BLE001
                self._send(500, {"ok": False, "error": str(exc), "type": type(exc).__name__})
            return
        original_get(self)

    def do_POST(self: Any) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/service/action":
            if not self._authorized():
                self._send(403, {"ok": False, "error": "forbidden"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                self._send(200, self.bridge.service_action(payload))
            except Exception as exc:  # noqa: BLE001
                self._send(500, {"ok": False, "error": str(exc), "type": type(exc).__name__})
            return
        original_post(self)

    ApiHandler.do_GET = do_GET
    ApiHandler.do_POST = do_POST
