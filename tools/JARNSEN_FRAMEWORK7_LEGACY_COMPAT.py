"""Restore stable Service Tool USB-first behavior in the Framework7 bridge.

The legacy desktop tool treats a physically attached, unique Meshtastic COM port
as a valid target even before that device has a managed-node database entry. The
Framework7 bridge originally required a selected managed node, which made profile
capture/apply/provision appear disabled for new or serial-only nodes.

Keep the old safety rule: an exact stored USB identity wins. A unique physical
USB target is a safe fallback. When multiple USB targets are present and none can
be mapped exactly, never guess.
"""
from __future__ import annotations

import contextlib
import threading
import time
from typing import Any


class _CallableGetAdapter:
    """Keep legacy callables callable while providing mapping-style ``get`` safely."""

    def __init__(self, function: Any) -> None:
        self._function = function

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self._function(*args, **kwargs)

    def get(self, key: Any, default: Any = None) -> Any:
        try:
            value = self._function()
        except TypeError:
            try:
                value = self._function(key)
            except Exception:
                return default
            if isinstance(value, dict):
                return value.get(key, default)
            return default if value is None else value
        except Exception:
            return default
        if isinstance(value, dict):
            return value.get(key, default)
        with contextlib.suppress(Exception):
            return dict(value).get(key, default)
        return default


def _guard_callable_mappings(tool: Any) -> None:
    """Normalize compatibility state that older patches sometimes expose as methods."""

    for name in ("node_sync_state_v2132", "config_profile_store"):
        value = getattr(tool, name, None)
        if callable(value) and not hasattr(value, "get"):
            setattr(tool, name, _CallableGetAdapter(value))


def install_legacy_compat(LegacyBridge: type) -> None:
    # install_fixes() and the v3.1 entry point both call this layer. It must be
    # idempotent or state/action wrappers and USB scans get installed twice.
    if getattr(LegacyBridge, "_jarnsen_legacy_compat_usb_first", False):
        return
    LegacyBridge._jarnsen_legacy_compat_usb_first = True

    # Some bridge generations implemented _current_usb_port() as a local helper
    # but never attached it to LegacyBridge. Headless startup must not depend on
    # that presentation-era installation accident. Reuse it when available and
    # otherwise fall through to the physical USB discovery below.
    original_init = LegacyBridge.__init__
    original_current_usb_port = getattr(LegacyBridge, "_current_usb_port", None)
    original_profile_action = LegacyBridge.profile_action
    original_state = LegacyBridge.state
    original_action = LegacyBridge.action

    def _framework7_usb_refresh_worker(self: Any) -> None:
        # Keep this stable shape: the build-time full diagnostics patch
        # instruments this exact legacy candidate block.
        candidates: list[Any] = []
        with contextlib.suppress(Exception):
            candidates = list(self.tool._auto_usb_log_candidates())

        try:
            result: list[dict[str, Any]] = []
            seen: set[str] = set()
            for item in candidates:
                if not isinstance(item, dict):
                    continue
                device = str(item.get("device") or "").strip()
                if not device or device.lower() in seen:
                    continue
                seen.add(device.lower())
                identity = ""
                identity_reader = getattr(self.tool, "_serial_identity_key", None)
                if callable(identity_reader):
                    with contextlib.suppress(Exception):
                        identity = str(identity_reader(item) or "").strip().lower()
                mapped_node_id = ""
                if identity and hasattr(self.tool.repository, "managed_node_by_usb"):
                    with contextlib.suppress(Exception):
                        managed = self.tool.repository.managed_node_by_usb(identity)
                        if managed:
                            mapped_node_id = str(dict(managed).get("node_id") or "")
                result.append(
                    {
                        "device": device,
                        "description": str(item.get("description") or ""),
                        "manufacturer": str(item.get("manufacturer") or ""),
                        "serial_number": str(item.get("serial_number") or ""),
                        "identity": identity,
                        "mapped_node_id": mapped_node_id,
                    }
                )
            self.__dict__["_framework7_usb_cache"] = [dict(item) for item in result]
            self.__dict__["_framework7_usb_cache_at"] = time.monotonic()
        finally:
            self.__dict__["_framework7_usb_scan_running"] = False

    def _start_usb_refresh(self: Any) -> None:
        if bool(self.__dict__.get("_framework7_usb_scan_running", False)):
            return
        self.__dict__["_framework7_usb_scan_running"] = True
        threading.Thread(
            target=_framework7_usb_refresh_worker,
            args=(self,),
            name="framework7-usb-discovery",
            daemon=True,
        ).start()

    def bridge_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        _guard_callable_mappings(self.tool)
        self.__dict__.setdefault("_framework7_usb_cache", [])
        self.__dict__.setdefault("_framework7_usb_cache_at", 0.0)
        _start_usb_refresh(self)

    def _usb_targets(self: Any) -> list[dict[str, Any]]:
        cached = self.__dict__.get("_framework7_usb_cache")
        if not isinstance(cached, list):
            cached = []
        last = float(self.__dict__.get("_framework7_usb_cache_at") or 0.0)
        age = time.monotonic() - last if last else 9999.0
        if age >= 1.0:
            _start_usb_refresh(self)
        # Critical invariant: API request threads NEVER enumerate COM ports.
        # The last complete snapshot stays available while one background refresh is running.
        result = [dict(item) for item in cached if isinstance(item, dict)]
        return result

    def _current_usb_port(self: Any, node_id: str = "") -> str:
        node_id = str(node_id or "").strip()
        if node_id and callable(original_current_usb_port):
            with contextlib.suppress(Exception):
                exact = str(original_current_usb_port(self, node_id) or "").strip()
                if exact:
                    return exact

        targets = self._usb_targets()
        if node_id:
            normalized = node_id.lower()
            mapped = [
                item
                for item in targets
                if str(item.get("mapped_node_id") or "").strip().lower() == normalized
            ]
            if len(mapped) == 1:
                return str(mapped[0]["device"])
        if len(targets) == 1:
            return str(targets[0]["device"])
        return ""

    def _select_profile_target(
        self: Any, node_id: str, preferred: str = "Automatisch"
    ) -> tuple[str, str]:
        node_id = str(node_id or "").strip()
        preferred_norm = str(preferred or "Automatisch").strip().lower()
        usb_port = self._current_usb_port(node_id)

        entries: list[tuple[str, Any]] = []
        if node_id and hasattr(self.tool, "_ble_entries_for_nodes_v2133"):
            with contextlib.suppress(Exception):
                entries, _missing = self.tool._ble_entries_for_nodes_v2133([node_id])

        # USB is intentionally checked before BLE for Automatisch. A physically
        # attached serial node is always the preferred service transport.
        if preferred_norm in {"automatisch", "auto", "usb"} and usb_port:
            self.tool._select_serial_port_in_ui(usb_port)
            self.tool.config_profile_transport_var.set("USB")
            return "USB", usb_port

        if preferred_norm == "usb":
            targets = self._usb_targets()
            if len(targets) > 1:
                raise RuntimeError(
                    "Mehrere USB/COM-Nodes sind angeschlossen. Bitte nur die Ziel-Node angeschlossen lassen "
                    "oder zuerst eine bereits eindeutig zugeordnete Node auswählen."
                )
            raise RuntimeError("Keine kompatible Node ist aktuell über USB/COM erreichbar")

        if preferred_norm in {"automatisch", "auto", "bluetooth", "ble"} and len(entries) == 1:
            self.tool._select_ble_entries_v2133(entries)
            self.tool.config_profile_transport_var.set("Bluetooth")
            return "Bluetooth", entries[0][0]

        if preferred_norm in {"bluetooth", "ble"}:
            if not node_id:
                raise RuntimeError("Für Bluetooth bitte zuerst eine bekannte Node auswählen")
            raise RuntimeError("Diese Node ist aktuell nicht eindeutig über Bluetooth erreichbar")

        targets = self._usb_targets()
        if len(targets) > 1:
            raise RuntimeError(
                "Mehrere USB/COM-Nodes erkannt; automatische Zielwahl ist deshalb absichtlich gesperrt"
            )
        raise RuntimeError("Keine eindeutige USB- oder Bluetooth-Verbindung zur Node gefunden")

    def profile_action(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
        command = str(payload.get("command") or "")
        node_id = str(payload.get("node_id") or "").strip()
        if command != "capture" or node_id:
            return original_profile_action(self, payload)

        slot = int(payload.get("slot", -1))
        preferred = str(payload.get("transport") or "Automatisch")
        if slot < 0:
            raise RuntimeError("Ungültiger Profil-Slot")

        def execute() -> dict[str, Any]:
            transport, target = self._select_profile_target("", preferred)
            if transport != "USB":
                raise RuntimeError("Eine neue/unbekannte Node kann ohne Auswahl nur über USB eingelesen werden")
            self.tool.start_config_profile_capture(slot)
            return {
                "ok": True,
                "message": f"Profil {slot + 1} wird über {target} von der seriellen Node eingelesen",
                "target": target,
                "transport": transport,
            }

        return self.call_ui(execute, timeout=30.0)

    def state(self: Any) -> dict[str, Any]:
        _guard_callable_mappings(self.tool)
        data = original_state(self)
        targets = self._usb_targets()
        data["connections"] = {
            "usb": targets,
            "usb_count": len(targets),
            "unique_usb": targets[0] if len(targets) == 1 else None,
            "usb_target_policy": "exact-identity-then-unique-physical",
            "transport_priority": "USB -> BLE",
        }
        summary = data.get("summary")
        if isinstance(summary, dict):
            summary["usb"] = len(targets)

        by_node = {
            str(item.get("mapped_node_id") or "").strip().lower(): item
            for item in targets
            if str(item.get("mapped_node_id") or "").strip()
        }
        for node in data.get("nodes", []):
            if not isinstance(node, dict):
                continue
            usb = by_node.get(str(node.get("node_id") or "").strip().lower())
            node["usb_reachable"] = bool(usb)
            node["usb"] = usb
            node["transport"] = "USB" if usb else ("BLE" if node.get("ble_reachable") else "Offline")
        return data

    def _start_usb_log(self: Any, node_id: str) -> dict[str, Any]:
        port = self._current_usb_port(node_id)
        if not port:
            targets = self._usb_targets()
            if len(targets) > 1:
                raise RuntimeError("Mehrere USB-Nodes erkannt; USB-Logziel ist nicht eindeutig")
            raise RuntimeError("Keine kompatible USB/COM-Node erkannt")
        if getattr(self.tool, "worker", None) and self.tool.worker.is_alive():
            raise RuntimeError("Ein anderer Vorgang läuft noch")
        self.tool._select_serial_port_in_ui(port)
        starter = getattr(self.tool, "_start_auto_usb_download", None)
        if not callable(starter):
            raise RuntimeError("USB-Logdownload ist in diesem Backend nicht verfügbar")
        starter(port)
        return {"started": True, "transport": "USB", "target": port, "node_id": node_id}

    def action(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
        command = str(payload.get("command") or "")
        node_ids = [str(item) for item in payload.get("node_ids") or [] if str(item).strip()]
        node_id = str(payload.get("node_id") or "").strip() or (node_ids[0] if len(node_ids) == 1 else "")

        # A normal one-node Log action is also USB-first. If that exact node is
        # not connected over USB, preserve the mature BLE batch fallback.
        if command == "download_log" and len(node_ids) <= 1 and node_id:
            if self._current_usb_port(node_id):
                value = self.call_ui(lambda: _start_usb_log(self, node_id), timeout=30.0)
                return {"ok": True, "result": value}
            return original_action(self, payload)

        if command != "usb_log":
            return original_action(self, payload)

        # Keep a named execute() block for build-time USB diagnostics to wrap.
        def execute() -> dict[str, Any]:
            return _start_usb_log(self, node_id)

        value = self.call_ui(execute, timeout=30.0)
        return {"ok": True, "result": value}

    LegacyBridge.__init__ = bridge_init
    LegacyBridge._framework7_usb_refresh_worker = _framework7_usb_refresh_worker
    LegacyBridge._usb_targets = _usb_targets
    LegacyBridge._current_usb_port = _current_usb_port
    LegacyBridge._select_profile_target = _select_profile_target
    LegacyBridge.profile_action = profile_action
    LegacyBridge.state = state
    LegacyBridge.action = action
