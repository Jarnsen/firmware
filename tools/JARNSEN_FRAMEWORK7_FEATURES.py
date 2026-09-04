"""Deep Framework7 feature bridge for Jarnsen Node Service Tool v3.

Keeps the mature Python/Tk service core hidden and exposes the remaining workflows
as local JSON endpoints for the Framework7 desktop UI.  Nothing is reachable
outside 127.0.0.1 and the parent launcher still requires its per-start token.
"""
from __future__ import annotations

import asyncio
import base64
import contextlib
import datetime as dt
import json
import pathlib
import re
import threading
import time
import urllib.parse
from typing import Any


def _profile_at(tool: Any, slot: int) -> dict[str, Any]:
    profiles = tool.config_profile_store.get("profiles", [])
    profile = profiles[slot] if isinstance(profiles, list) and 0 <= slot < len(profiles) else None
    if not isinstance(profile, dict):
        raise RuntimeError(f"Grundprofil {slot + 1} ist leer")
    return profile


def _safe_profile_summary(tool: Any, profile: dict[str, Any], slot: int) -> dict[str, Any]:
    categories = (
        "Gerät & Mesh",
        "LoRa & Funk",
        "Kanäle & PSK",
        "Position & GPS",
        "Bluetooth",
        "Module",
        "Strom & Display",
        "Erweitert / Alle Werte",
    )
    category_rows = []
    for category in categories:
        try:
            items = tool._profile_category_items(profile, category)
        except Exception:
            items = []
        category_rows.append(
            {
                "name": category,
                "items": [{"kind": str(kind), "name": str(name)} for kind, name in items],
            }
        )
    return {
        "slot": slot,
        "name": str(profile.get("name") or f"Profil {slot + 1}"),
        "saved_at": str(profile.get("saved_at") or ""),
        "source_hw": str(profile.get("source_hw") or ""),
        "source_firmware": str(profile.get("source_firmware") or ""),
        "source_long_name": str(profile.get("source_long_name") or profile.get("long_name") or ""),
        "source_short_name": str(profile.get("source_short_name") or profile.get("short_name") or ""),
        "psk_included": bool(profile.get("psk_included")),
        "config_count": len(profile.get("config", {})) if isinstance(profile.get("config"), dict) else 0,
        "module_count": len(profile.get("module_config", {})) if isinstance(profile.get("module_config"), dict) else 0,
        "channel_count": len(profile.get("channels", [])) if isinstance(profile.get("channels"), list) else 0,
        "categories": category_rows,
    }


def _normalize_pin(value: object) -> str:
    pin = str(value or "240180").strip()
    if not re.fullmatch(r"\d{6}", pin):
        raise RuntimeError("Der Bluetooth-PIN muss genau aus 6 Ziffern bestehen")
    return pin


def _profile_slot_count(tool: Any) -> int:
    profiles = tool.config_profile_store.get("profiles", [])
    return max(4, len(profiles) if isinstance(profiles, list) else 0)


def install(LegacyBridge: type, ApiHandler: type) -> None:
    """Attach Framework7-native deep features to the existing launcher classes."""

    def profiles(self: Any) -> dict[str, Any]:
        def collect() -> dict[str, Any]:
            profiles_data = self.tool.config_profile_store.get("profiles", [])
            result: list[dict[str, Any]] = []
            for slot in range(_profile_slot_count(self.tool)):
                profile = profiles_data[slot] if isinstance(profiles_data, list) and slot < len(profiles_data) else None
                if isinstance(profile, dict):
                    result.append(_safe_profile_summary(self.tool, profile, slot))
                else:
                    result.append({"slot": slot, "empty": True, "name": f"Profil {slot + 1}", "categories": []})
            return {
                "profiles": result,
                "rules": {
                    "position_mesh": True,
                    "neighbor_info_default": True,
                    "preserve_identity_keys": True,
                    "blank_names_preserve_target": True,
                    "default_pin": "240180",
                },
            }

        return self.call_ui(collect, timeout=15.0)

    def profile_section(self: Any, slot: int, kind: str, name: str) -> dict[str, Any]:
        def collect() -> dict[str, Any]:
            from google.protobuf import json_format

            profile = _profile_at(self.tool, slot)
            message = self.tool._profile_message(profile, kind, name)
            data = json_format.MessageToDict(message, preserving_proto_field_name=True)
            notes: list[str] = []
            if kind == "config" and name == "position":
                notes.append("Position ins Mesh bleibt durch die Jarnsen-Regeln aktiviert.")
            if kind == "module" and name == "neighbor_info":
                notes.append("Neighbor Info bleibt standardmäßig aktiviert und wird über LoRa übertragen.")
            if kind == "config" and name == "security":
                notes.append("Geräteidentitäts-Schlüssel werden beim Übertragen nicht von einem Profil auf eine andere Node kopiert.")
            if kind == "channel":
                notes.append("PSK wird nur übertragen, wenn „PSK anwenden“ ausdrücklich aktiviert ist.")
            return {
                "slot": slot,
                "kind": kind,
                "name": name,
                "title": self.tool._profile_section_title(kind, name),
                "data": data,
                "notes": notes,
            }

        return self.call_ui(collect, timeout=15.0)

    def save_profile_section(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
        slot = int(payload.get("slot", -1))
        kind = str(payload.get("kind") or "")
        name = str(payload.get("name") or "")
        raw = payload.get("data")
        if not isinstance(raw, dict):
            raise RuntimeError("Profilabschnitt enthält keine gültigen JSON-Daten")

        def save() -> dict[str, Any]:
            from google.protobuf import json_format

            profile = _profile_at(self.tool, slot)
            current = self.tool._profile_message(profile, kind, name)
            updated = type(current)()
            json_format.ParseDict(raw, updated, ignore_unknown_fields=False)
            if kind == "config" and name == "position":
                if hasattr(updated, "position_broadcast_secs") and int(updated.position_broadcast_secs) <= 0:
                    updated.position_broadcast_secs = max(
                        1, int(getattr(current, "position_broadcast_secs", 900) or 900)
                    )
                if hasattr(updated, "position_broadcast_smart_enabled"):
                    updated.position_broadcast_smart_enabled = True
            if kind == "module" and name == "neighbor_info":
                if hasattr(updated, "enabled"):
                    updated.enabled = True
                if hasattr(updated, "transmit_over_lora"):
                    updated.transmit_over_lora = True
                if hasattr(updated, "update_interval") and int(updated.update_interval) < 14400:
                    updated.update_interval = 14400
            self.tool._save_profile_message(profile, kind, name, updated)
            return {"ok": True, "saved_at": str(profile.get("saved_at") or "")}

        return self.call_ui(save, timeout=20.0)

    def _current_usb_port(self: Any, node_id: str) -> str:
        management = None
        if hasattr(self.tool.repository, "management_for_node"):
            management = self.tool.repository.management_for_node(node_id)
        management = dict(management) if management else {}
        expected_identity = str(management.get("usb_identity") or "").lower()
        last_port = str(management.get("last_port") or "")
        candidates = []
        with contextlib.suppress(Exception):
            candidates = list(self.tool._auto_usb_log_candidates())
        for item in candidates:
            with contextlib.suppress(Exception):
                key = str(self.tool._serial_identity_key(item) or "").lower()
                if expected_identity and key == expected_identity:
                    return str(item.get("device") or "")
        for item in candidates:
            if str(item.get("device") or "") == last_port:
                return last_port
        return ""

    def _select_profile_target(self: Any, node_id: str, preferred: str = "Automatisch") -> tuple[str, str]:
        node_id = str(node_id or "").strip()
        preferred_norm = str(preferred or "Automatisch").strip().lower()
        usb_port = self._current_usb_port(node_id) if node_id else ""
        entries: list[tuple[str, Any]] = []
        if node_id and hasattr(self.tool, "_ble_entries_for_nodes_v2133"):
            entries, _missing = self.tool._ble_entries_for_nodes_v2133([node_id])

        if preferred_norm in {"automatisch", "auto", "usb"} and usb_port:
            self.tool._select_serial_port_in_ui(usb_port)
            self.tool.config_profile_transport_var.set("USB")
            return "USB", usb_port
        if preferred_norm == "usb":
            raise RuntimeError("Diese Node ist aktuell nicht eindeutig über USB/COM erreichbar")
        if preferred_norm in {"automatisch", "auto", "bluetooth", "ble"} and len(entries) == 1:
            self.tool._select_ble_entries_v2133(entries)
            self.tool.config_profile_transport_var.set("Bluetooth")
            return "Bluetooth", entries[0][0]
        if preferred_norm in {"bluetooth", "ble"}:
            raise RuntimeError("Diese Node ist aktuell nicht eindeutig über Bluetooth erreichbar")
        raise RuntimeError("Keine eindeutige USB- oder Bluetooth-Verbindung zur Node gefunden")

    def profile_action(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
        command = str(payload.get("command") or "")
        slot = int(payload.get("slot", -1))
        node_id = str(payload.get("node_id") or "").strip()
        preferred = str(payload.get("transport") or "Automatisch")

        def execute() -> dict[str, Any]:
            profiles_list = self.tool.config_profile_store.get("profiles", [])
            if command == "rename":
                profile = _profile_at(self.tool, slot)
                name = str(payload.get("name") or "").strip() or f"Profil {slot + 1}"
                profile["name"] = name
                profile["saved_at"] = dt.datetime.now().astimezone().isoformat(timespec="seconds")
                self.tool._save_config_profile_store()
                self.tool._refresh_config_profile_ui()
                return {"ok": True, "message": f"Profil heißt jetzt {name}"}
            if command == "delete_profile":
                if not isinstance(profiles_list, list) or slot < 0 or slot >= len(profiles_list):
                    raise RuntimeError("Profil-Slot existiert nicht")
                profiles_list[slot] = None
                self.tool._save_config_profile_store()
                self.tool._refresh_config_profile_ui()
                return {"ok": True, "message": f"Profil {slot + 1} gelöscht"}

            profile = _profile_at(self.tool, slot)
            if command == "capture":
                self._select_profile_target(node_id, preferred)
                self.tool.start_config_profile_capture(slot)
                return {"ok": True, "message": f"Profil {slot + 1} wird von der Node eingelesen"}

            long_name = str(payload.get("long_name") or "").strip()
            short_name = str(payload.get("short_name") or "").strip()
            if len(short_name) > 4:
                raise RuntimeError("Der Short Name darf maximal 4 Zeichen lang sein")
            pin = _normalize_pin(payload.get("pin"))
            self.tool.config_target_long_var.set(long_name)
            self.tool.config_target_short_var.set(short_name)
            if hasattr(self.tool, "config_bt_pin_var"):
                self.tool.config_bt_pin_var.set(pin)
            if hasattr(self.tool, "config_apply_bt_pin_var"):
                self.tool.config_apply_bt_pin_var.set(bool(payload.get("apply_pin", True)))
            if hasattr(self.tool, "config_apply_psk_var"):
                self.tool.config_apply_psk_var.set(bool(payload.get("apply_psk", False)))

            transport, target = self._select_profile_target(node_id, preferred)
            if command == "apply":
                self.tool.start_config_profile_apply(slot)
                return {
                    "ok": True,
                    "message": f"{profile.get('name') or f'Profil {slot + 1}'} wird über {transport} übertragen",
                    "target": target,
                }
            if command == "provision":
                if transport != "USB":
                    raise RuntimeError("Werkreset + Neuaufsetzen ist aus Sicherheitsgründen nur über USB erlaubt")
                if self.tool.worker and self.tool.worker.is_alive():
                    raise RuntimeError("Ein anderer Vorgang läuft noch")
                self.tool._provision_active = True
                self.tool._provision_context = None
                self.tool._set_config_profile_buttons_state("disabled")
                self.tool.stop_event.clear()
                self.tool.worker = threading.Thread(
                    target=self.tool._config_profile_provision_worker,
                    args=(slot, profile, target),
                    daemon=True,
                )
                self.tool.worker.start()
                return {
                    "ok": True,
                    "message": f"Werkreset, Firmware und {profile.get('name') or f'Profil {slot + 1}'} wurden gestartet",
                    "target": target,
                }
            raise RuntimeError(f"Unbekannte Profilaktion: {command}")

        return self.call_ui(execute, timeout=30.0)

    def positions(self: Any, node_id: str) -> dict[str, Any]:
        import JARNSEN_NODE_SERVICE_TOOL as legacy

        canonical = node_id
        if hasattr(self.tool.repository, "canonical_node_id_v2131"):
            with contextlib.suppress(Exception):
                canonical = self.tool.repository.canonical_node_id_v2131(node_id)
        logs = self.tool.repository.logs_for_node(canonical)
        points: list[dict[str, Any]] = []
        seen: set[tuple[int, int, int]] = set()
        for log in logs:
            path = pathlib.Path(str(log.get("path") or ""))
            if not path.exists():
                continue
            try:
                raw_points = legacy.parse_track_points(path.read_bytes())
            except OSError:
                continue
            for point in raw_points:
                key = (
                    round(float(point.get("latitude") or 0.0) * 10_000_000),
                    round(float(point.get("longitude") or 0.0) * 10_000_000),
                    int(point.get("epoch") or 0),
                )
                if key in seen:
                    continue
                seen.add(key)
                item = dict(point)
                item["log_captured_at"] = str(log.get("captured_at") or "")
                points.append(item)
        points.sort(key=lambda item: (int(item.get("epoch") or 0), str(item.get("log_captured_at") or "")))
        distance = 0.0
        for previous, current in zip(points, points[1:]):
            distance += legacy.geographic_distance_m(
                float(previous["latitude"]),
                float(previous["longitude"]),
                float(current["latitude"]),
                float(current["longitude"]),
            )
        bounds = None
        if points:
            latitudes = [float(item["latitude"]) for item in points]
            longitudes = [float(item["longitude"]) for item in points]
            bounds = {
                "south": min(latitudes),
                "north": max(latitudes),
                "west": min(longitudes),
                "east": max(longitudes),
            }
        return {
            "node_id": canonical,
            "points": points,
            "count": len(points),
            "distance_m": distance,
            "bounds": bounds,
            "logs_scanned": len(logs),
        }

    def live_state(self: Any, node_id: str) -> dict[str, Any]:
        def collect() -> dict[str, Any]:
            snapshot = dict(getattr(self.tool, "live_snapshot", {}) or {})
            frame = snapshot.get("frame")
            if isinstance(frame, (bytes, bytearray)):
                snapshot["frame_b64"] = base64.b64encode(bytes(frame)).decode("ascii")
                snapshot.pop("frame", None)
            return {
                "node_id": str(getattr(self.tool, "_framework7_live_node", "") or node_id),
                "connected": bool(getattr(self.tool, "live_connected", False)),
                "running": bool(getattr(self.tool, "live_worker", None) and self.tool.live_worker.is_alive()),
                "snapshot": snapshot,
            }

        return self.call_ui(collect, timeout=10.0)

    def live_action(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
        command = str(payload.get("command") or "")
        node_id = str(payload.get("node_id") or "").strip()

        if command == "start":
            def prepare() -> tuple[str, Any]:
                entries, missing = self.tool._ble_entries_for_nodes_v2133([node_id])
                if missing or len(entries) != 1:
                    raise RuntimeError("Die Node ist aktuell nicht eindeutig über BLE erreichbar")
                if self.tool.worker and self.tool.worker.is_alive():
                    raise RuntimeError("Ein anderer Download-/Firmwarevorgang läuft noch")
                if self.tool.live_worker and self.tool.live_worker.is_alive():
                    if str(getattr(self.tool, "_framework7_live_node", "")) == node_id:
                        return entries[0]
                    self.tool.live_stop.set()
                    raise RuntimeError("Eine andere Live-Sitzung wird gerade beendet. Bitte erneut starten.")
                self.tool._select_ble_entries_v2133(entries)
                self.tool._framework7_live_node = node_id
                return entries[0]

            label, device = self.call_ui(prepare, timeout=10.0)

            def pair_and_start() -> None:
                try:
                    if hasattr(self.tool, "_ensure_ble_pairing_v2133"):
                        asyncio.run(self.tool._ensure_ble_pairing_v2133(device, label))
                    self.tk_host.after(0, self.tool.toggle_live)
                except Exception as exc:  # noqa: BLE001
                    events = getattr(self.tool, "mac_activity_events_v220", None)
                    if isinstance(events, list):
                        events.append(f"Live {label}: {exc}")

            threading.Thread(target=pair_and_start, daemon=True, name="framework7-live-start").start()
            return {"ok": True, "message": f"Live-Verbindung zu {label} wird aufgebaut"}

        def execute() -> dict[str, Any]:
            if command == "stop":
                if self.tool.live_worker and self.tool.live_worker.is_alive():
                    self.tool.toggle_live()
                return {"ok": True, "message": "Live-Verbindung wird beendet"}
            if command == "command":
                control = str(payload.get("control") or "").upper()
                if control not in {"WAKE", "NEXT", "PREV", "UP", "DOWN", "SELECT", "BACK"}:
                    raise RuntimeError("Ungültiger Live-Befehl")
                self.tool.send_live_command(control)
                return {"ok": True, "message": control}
            raise RuntimeError(f"Unbekannte Live-Aktion: {command}")

        return self.call_ui(execute, timeout=10.0)

    def delete_nodes_without_legacy_dialog(self: Any, node_ids: list[str]) -> dict[str, Any]:
        def execute() -> dict[str, Any]:
            import JARNSEN_NODE_SERVICE_TOOL as legacy

            ids: list[str] = []
            for value in node_ids:
                normalized = legacy.normalize_node_id(str(value or ""))
                if normalized and normalized not in ids:
                    ids.append(normalized)
            if not ids:
                return {"ok": True, "deleted": 0, "logs": 0}
            paths: list[pathlib.Path] = []
            for node_id in ids:
                for item in self.tool.repository.logs_for_node(node_id):
                    path = pathlib.Path(str(item.get("path") or ""))
                    if path.exists() and path not in paths:
                        paths.append(path)
            if paths and (not legacy.RECYCLE_AVAILABLE or legacy.send2trash is None):
                raise RuntimeError("Papierkorb-Unterstützung fehlt; es wurde nichts gelöscht")
            for path in paths:
                legacy.send2trash(str(path))
            for node_id in ids:
                self.tool.repository.delete_records(node_id)
            with contextlib.suppress(Exception):
                self.tool.repository.scan_logs()
            with contextlib.suppress(Exception):
                self.tool.refresh_nodes()
            with contextlib.suppress(Exception):
                self.tool.refresh_all_nodes_overview()
            return {"ok": True, "deleted": len(ids), "logs": len(paths)}

        return self.call_ui(execute, timeout=30.0)

    # Attach bridge methods.
    LegacyBridge.profiles = profiles
    LegacyBridge.profile_section = profile_section
    LegacyBridge.save_profile_section = save_profile_section
    LegacyBridge.profile_action = profile_action
    LegacyBridge.positions = positions
    LegacyBridge.live_state = live_state
    LegacyBridge.live_action = live_action
    LegacyBridge.delete_nodes_without_legacy_dialog = delete_nodes_without_legacy_dialog

    original_action = LegacyBridge.action

    def action_with_framework7(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
        if str(payload.get("command") or "") == "delete":
            ids = [str(item) for item in payload.get("node_ids") or [] if str(item).strip()]
            return self.delete_nodes_without_legacy_dialog(ids)
        return original_action(self, payload)

    LegacyBridge.action = action_with_framework7

    original_get = ApiHandler.do_GET
    original_post = ApiHandler.do_POST

    def do_GET(self: Any) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path in {"/api/profiles"} or path.startswith("/api/profile/") or path.startswith("/api/live/") or (path.startswith("/api/node/") and path.endswith("/positions")):
            if not self._authorized():
                self._send(403, {"ok": False, "error": "forbidden"})
                return
            try:
                if path == "/api/profiles":
                    self._send(200, self.bridge.profiles())
                    return
                if path.startswith("/api/profile/"):
                    parts = [urllib.parse.unquote(part) for part in path.split("/") if part]
                    if len(parts) != 5:
                        raise RuntimeError("Ungültiger Profilpfad")
                    self._send(200, self.bridge.profile_section(int(parts[2]), parts[3], parts[4]))
                    return
                if path.startswith("/api/node/") and path.endswith("/positions"):
                    node_id = urllib.parse.unquote(path[len("/api/node/") : -len("/positions")]).strip("/")
                    self._send(200, self.bridge.positions(node_id))
                    return
                if path.startswith("/api/live/"):
                    node_id = urllib.parse.unquote(path[len("/api/live/") :]).strip("/")
                    self._send(200, self.bridge.live_state(node_id))
                    return
            except Exception as exc:  # noqa: BLE001
                self._send(500, {"ok": False, "error": str(exc), "type": type(exc).__name__})
                return
        original_get(self)

    def do_POST(self: Any) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        if path in {"/api/profile/action", "/api/profile/section", "/api/live/action"}:
            if not self._authorized():
                self._send(403, {"ok": False, "error": "forbidden"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                if path == "/api/profile/action":
                    self._send(200, self.bridge.profile_action(payload))
                elif path == "/api/profile/section":
                    self._send(200, self.bridge.save_profile_section(payload))
                else:
                    self._send(200, self.bridge.live_action(payload))
            except Exception as exc:  # noqa: BLE001
                self._send(500, {"ok": False, "error": str(exc), "type": type(exc).__name__})
            return
        original_post(self)

    ApiHandler.do_GET = do_GET
    ApiHandler.do_POST = do_POST
