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
import pathlib
import re
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
                # Windows packages only expose the physical serial targets here.
                name = device.upper()
                if not name.startswith("COM"):
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

            # Opening a serial log/firmware session can make the port scanner
            # briefly return no candidates even though the cable is still attached.
            previous = [
                dict(item)
                for item in self.__dict__.get("_framework7_usb_cache", [])
                if isinstance(item, dict)
            ]
            worker_busy = False
            worker = getattr(self.tool, "worker", None)
            if worker is not None:
                with contextlib.suppress(Exception):
                    worker_busy = bool(worker.is_alive())
            if result:
                self.__dict__["_framework7_usb_empty_passes"] = 0
            elif previous:
                empty_passes = int(self.__dict__.get("_framework7_usb_empty_passes") or 0) + 1
                self.__dict__["_framework7_usb_empty_passes"] = empty_passes
                if worker_busy or empty_passes < 2:
                    result = previous

            self.__dict__["_framework7_usb_cache"] = [dict(item) for item in result]
            self.__dict__["_framework7_usb_cache_at"] = time.monotonic()
        finally:
            self.__dict__["_framework7_usb_scan_running"] = False

    def _run_usb_refresh_worker(self: Any) -> None:
        try:
            _framework7_usb_refresh_worker(self)
        finally:
            self.__dict__["_framework7_usb_scan_running"] = False

    def _start_usb_refresh(self: Any) -> None:
        if bool(self.__dict__.get("_framework7_usb_scan_running", False)):
            return
        self.__dict__["_framework7_usb_scan_running"] = True
        threading.Thread(
            target=_run_usb_refresh_worker,
            args=(self,),
            name="framework7-usb-discovery",
            daemon=True,
        ).start()

    def bridge_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        _guard_callable_mappings(self.tool)
        self.__dict__.setdefault("_framework7_usb_cache", [])
        self.__dict__.setdefault("_framework7_usb_cache_at", 0.0)
        self.__dict__.setdefault("_framework7_usb_empty_passes", 0)
        self.__dict__.setdefault("_framework7_usb_identity_conflict", None)

        # Framework7 owns USB attach prompting. The old background auto-log must
        # never race the popup or silently open the port behind it.
        auto_var = getattr(self.tool, "auto_usb_log_var", None)
        if auto_var is not None:
            with contextlib.suppress(Exception):
                auto_var.set(False)
        old_poll = getattr(self.tool, "_poll_auto_usb_log", None)
        if callable(old_poll) and not hasattr(self.tool, "_framework7_legacy_auto_usb_poll"):
            self.tool._framework7_legacy_auto_usb_poll = old_poll
            self.tool._poll_auto_usb_log = lambda: None

        _install_usb_payload_observer(self)
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
        # Never enumerate COM ports on an API request thread; the last complete
        # snapshot stays available while one background refresh is running.
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

    @staticmethod
    def _payload_header(payload: bytes, name: str) -> str:
        match = re.search(
            rb"(?m)^# " + re.escape(name.encode("ascii")) + rb"=([^\r\n]+)",
            bytes(payload or b""),
        )
        return match.group(1).decode("utf-8", "replace").strip() if match else ""

    @staticmethod
    def _normalize_node_id(value: str) -> str:
        raw = str(value or "").strip().lower().lstrip("!")
        return f"!{raw}" if raw else ""

    def _target_for_port(self: Any, port: str = "") -> dict[str, Any] | None:
        targets = self._usb_targets()
        requested = str(port or "").strip().lower()
        if requested:
            matches = [item for item in targets if str(item.get("device") or "").strip().lower() == requested]
            if len(matches) == 1:
                return dict(matches[0])
        return dict(targets[0]) if len(targets) == 1 else None

    def _set_cached_usb_mapping(self: Any, target: dict[str, Any], node_id: str) -> None:
        port = str(target.get("device") or "").strip().lower()
        identity = str(target.get("identity") or "").strip().lower()
        cached = self.__dict__.get("_framework7_usb_cache", [])
        if not isinstance(cached, list):
            return
        for item in cached:
            if not isinstance(item, dict):
                continue
            item_port = str(item.get("device") or "").strip().lower()
            item_identity = str(item.get("identity") or "").strip().lower()
            if (identity and item_identity == identity) or (port and item_port == port):
                item["mapped_node_id"] = node_id

    def _remember_usb_mapping(
        self: Any,
        target: dict[str, Any],
        node_id: str,
        long_name: str,
        short_name: str,
        device: str,
    ) -> None:
        repository = self.tool.repository
        node_id = _normalize_node_id(node_id)
        identity = str(target.get("identity") or "").strip().lower()
        port = str(target.get("device") or "").strip()
        if not node_id:
            return

        # One physical USB identity must resolve to one current node. Historical
        # entries may stay parallel, but they no longer claim the attached port.
        if identity and hasattr(repository, "_connect"):
            with contextlib.suppress(Exception):
                with contextlib.closing(repository._connect()) as connection, connection:
                    connection.execute(
                        "UPDATE managed_nodes SET usb_identity='',last_port='' WHERE usb_identity=? AND node_id<>?",
                        (identity, node_id),
                    )

        updater = getattr(repository, "upsert_managed_node", None)
        if callable(updater):
            updater(
                node_id=node_id,
                long_name=long_name or node_id,
                short_name=short_name,
                hardware=device,
                usb_identity=identity,
                last_port=port,
                status="USB verbunden",
            )
        _set_cached_usb_mapping(self, target, node_id)
        self.tool.selected_node_id = node_id

    def _observe_usb_payload(self: Any, payload: bytes) -> None:
        node_id = _normalize_node_id(_payload_header(payload, "node_id"))
        long_name = _payload_header(payload, "long_name").strip()
        short_name = _payload_header(payload, "short_name").strip()
        device = _payload_header(payload, "device").strip()
        if not node_id or not long_name or not short_name:
            return

        port = ""
        port_control = getattr(self.tool, "port", None)
        if port_control is not None:
            with contextlib.suppress(Exception):
                port = str(port_control.get() or "").strip()
        target = _target_for_port(self, port)
        if not target:
            return

        repository = self.tool.repository
        identity = str(target.get("identity") or "").strip().lower()
        existing_id = ""
        if identity and hasattr(repository, "managed_node_by_usb"):
            with contextlib.suppress(Exception):
                existing = repository.managed_node_by_usb(identity)
                if existing:
                    existing_id = _normalize_node_id(str(dict(existing).get("node_id") or ""))

        # Once this exact USB identity is explicitly bound to the current node,
        # a previous "parallel behalten" decision must not be asked again.
        if existing_id == node_id:
            _remember_usb_mapping(self, target, node_id, long_name, short_name, device)
            self.__dict__["_framework7_usb_identity_conflict"] = None
            return

        matches: list[dict[str, Any]] = []
        finder = getattr(repository, "same_name_nodes_v2131", None)
        if callable(finder):
            with contextlib.suppress(Exception):
                matches = [dict(item) for item in finder(long_name, short_name, node_id)]
        matches = [item for item in matches if _normalize_node_id(str(item.get("node_id") or "")) != node_id]

        if matches:
            old_ids = sorted(_normalize_node_id(str(item.get("node_id") or "")) for item in matches)
            key = f"{identity or str(target.get('device') or '').lower()}|{node_id}|{'|'.join(old_ids)}"
            self.__dict__["_framework7_usb_identity_conflict"] = {
                "key": key,
                "port": str(target.get("device") or ""),
                "identity": identity,
                "new_node_id": node_id,
                "long_name": long_name,
                "short_name": short_name,
                "device": device,
                "matches": [
                    {
                        "node_id": _normalize_node_id(str(item.get("node_id") or "")),
                        "long_name": str(item.get("long_name") or long_name),
                        "short_name": str(item.get("short_name") or short_name),
                        "log_count": int(item.get("log_count") or 0),
                        "last_seen": str(item.get("last_seen") or ""),
                    }
                    for item in matches
                ],
            }
            return

        _remember_usb_mapping(self, target, node_id, long_name, short_name, device)
        self.__dict__["_framework7_usb_identity_conflict"] = None

    def _install_usb_payload_observer(self: Any) -> None:
        if bool(getattr(self.tool, "_framework7_usb_payload_observer", False)):
            return
        finish = getattr(self.tool, "_finish_payload", None)
        if not callable(finish):
            return

        def finish_with_identity(payload: bytes, *args: Any, **kwargs: Any) -> Any:
            value = finish(payload, *args, **kwargs)
            try:
                _observe_usb_payload(self, bytes(payload or b""))
            except Exception as exc:
                self.activity.append(f"USB identity mapping: {type(exc).__name__}: {exc}")
                del self.activity[:-200]
            return value

        self.tool._finish_payload = finish_with_identity
        self.tool._framework7_usb_payload_observer = True

    def _delete_old_node_data(self: Any, node_ids: list[str]) -> tuple[int, int]:
        repository = self.tool.repository
        try:
            import JARNSEN_NODE_SERVICE_TOOL as legacy
        except Exception as exc:
            raise RuntimeError(f"Papierkorb-Unterstützung nicht verfügbar: {exc}") from exc
        recycle = getattr(legacy, "send2trash", None)
        if not callable(recycle):
            raise RuntimeError("Alte Logdateien können ohne Papierkorb-Unterstützung nicht sicher gelöscht werden")

        deleted_files = 0
        deleted_nodes = 0
        for node_id in node_ids:
            logs = repository.logs_for_node(node_id)
            for log in logs:
                path = pathlib.Path(str(log.get("path") or ""))
                if path.is_file():
                    recycle(str(path))
                    deleted_files += 1
            repository.delete_records(node_id)
            deleted_nodes += 1
        return deleted_nodes, deleted_files

    def _resolve_usb_identity(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
        conflict = self.__dict__.get("_framework7_usb_identity_conflict")
        if not isinstance(conflict, dict):
            raise RuntimeError("Es liegt kein offener Node-ID-Konflikt vor")
        key = str(payload.get("conflict_key") or "")
        if key and key != str(conflict.get("key") or ""):
            raise RuntimeError("Der Node-ID-Konflikt hat sich inzwischen geändert")

        decision = str(payload.get("decision") or "").strip().lower()
        if decision not in {"merge", "replace", "parallel"}:
            raise RuntimeError("Ungültige Entscheidung zur Node-Zuordnung")

        new_node_id = _normalize_node_id(str(conflict.get("new_node_id") or ""))
        old_node_ids = [
            _normalize_node_id(str(item.get("node_id") or ""))
            for item in conflict.get("matches") or []
            if isinstance(item, dict)
        ]
        old_node_ids = [item for item in dict.fromkeys(old_node_ids) if item and item != new_node_id]
        repository = self.tool.repository
        merged_logs = 0
        deleted_nodes = 0
        deleted_files = 0

        if decision == "merge":
            merger = getattr(repository, "merge_node_history_v2131", None)
            if not callable(merger):
                raise RuntimeError("Historien-Zusammenführung ist in diesem Backend nicht verfügbar")
            for old_id in old_node_ids:
                merged_logs += int(merger(old_id, new_node_id) or 0)
            message = f"{len(old_node_ids)} alte Node-Einträge und {merged_logs} Log(s) zusammengeführt"
        elif decision == "replace":
            deleted_nodes, deleted_files = _delete_old_node_data(self, old_node_ids)
            message = f"{deleted_nodes} alte Node-Einträge ersetzt; {deleted_files} Logdatei(en) in den Papierkorb verschoben"
        else:
            message = "Alte und aktuelle Node werden getrennt weitergeführt"

        target = _target_for_port(self, str(conflict.get("port") or "")) or {
            "device": str(conflict.get("port") or ""),
            "identity": str(conflict.get("identity") or ""),
        }
        _remember_usb_mapping(
            self,
            target,
            new_node_id,
            str(conflict.get("long_name") or ""),
            str(conflict.get("short_name") or ""),
            str(conflict.get("device") or ""),
        )
        self.__dict__["_framework7_usb_identity_conflict"] = None
        self.activity.append(f"USB-Zuordnung {decision}: {new_node_id} · {message}")
        del self.activity[:-200]
        return {
            "resolved": True,
            "decision": decision,
            "node_id": new_node_id,
            "message": message,
            "merged_logs": merged_logs,
            "deleted_nodes": deleted_nodes,
            "deleted_files": deleted_files,
        }

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
        conflict = self.__dict__.get("_framework7_usb_identity_conflict")
        data["connections"] = {
            "usb": targets,
            "usb_count": len(targets),
            "unique_usb": targets[0] if len(targets) == 1 else None,
            "usb_target_policy": "exact-identity-then-name-shortname",
            "transport_priority": "USB -> BLE",
            "usb_identity_conflict": dict(conflict) if isinstance(conflict, dict) else None,
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

        if command == "resolve_usb_identity":
            value = self.call_ui(lambda: _resolve_usb_identity(self, payload), timeout=45.0)
            return {"ok": True, "result": value}

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
