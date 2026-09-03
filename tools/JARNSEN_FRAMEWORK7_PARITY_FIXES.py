"""Final headless adapters for Framework7 stable-tool parity.

Avoid nested Tk dispatch for USB log actions and expose the useful parts of the
old enhanced serial monitor (power samples and explicit session-log export) to
the visible Framework7 service workspace.
"""
from __future__ import annotations

import contextlib
import pathlib
import shutil
from typing import Any


def install_parity_fixes(LegacyBridge: type) -> None:
    original_status = LegacyBridge.service_status
    original_action = LegacyBridge.service_action

    def _serial_monitor_active_from_worker(tool: Any) -> bool:
        """Read headless serial-monitor state without legacy Tk/thread assumptions."""
        worker = tool.__dict__.get("serial_monitor_worker")
        checker = getattr(worker, "is_alive", None)
        if not callable(checker):
            return False
        try:
            return bool(checker())
        except Exception:
            return False

    def _ensure_headless_serial_monitor_compat(tool: Any) -> None:
        """Normalize serial state that legacy Tk initialization used to create.

        Framework7 deliberately never constructs the legacy Tk serial-monitor
        controls.  Do not probe the inherited ``serial_monitor_active`` method in
        headless mode: depending on which stable-tool patch supplied that method,
        it can dereference a Tk variable that the declaration-only Tk shim exposes
        as a function stub.  That is the source of
        ``'function' object has no attribute 'get'`` when opening Service &
        Recovery.  The worker thread is the authoritative state in Framework7,
        so bind the instance method directly to that state.
        """
        if tool.__dict__.get("_headless_scheduler") is not None:
            tool.serial_monitor_active = lambda: _serial_monitor_active_from_worker(tool)
        else:
            monitor = getattr(tool, "serial_monitor_active", None)
            if callable(monitor):
                try:
                    monitor()
                except (AttributeError, TypeError):
                    tool.serial_monitor_active = lambda: _serial_monitor_active_from_worker(tool)

        samples = tool.__dict__.get("serial_power_samples")
        if samples is None or callable(samples):
            tool.serial_power_samples = []
            return
        try:
            list(samples)
        except TypeError:
            tool.serial_power_samples = []

    def _ensure_framework7_serial_log(tool: Any, *, reset: bool = False) -> pathlib.Path:
        """Guarantee a real session log even when legacy Tk side effects are absent."""
        import JARNSEN_NODE_SERVICE_TOOL as legacy

        current = tool.__dict__.get("_framework7_serial_log_path")
        path = pathlib.Path(str(current)) if current else None
        if reset or path is None:
            output = pathlib.Path(legacy.output_directory())
            output.mkdir(parents=True, exist_ok=True)
            path = output / f"Serial_Monitor_{legacy.now_local():%Y-%m-%d_%H%M%S}.log"
            path.touch(exist_ok=True)
            tool._framework7_serial_log_path = str(path)
            tool._framework7_serial_log_snapshot = ""
            tool.serial_monitor_log_path = str(path)
        elif not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        return path

    def _mirror_serial_tail_to_log(tool: Any) -> None:
        """Persist the exact headless monitor text incrementally without duplicates."""
        path_text = str(tool.__dict__.get("_framework7_serial_log_path") or "").strip()
        if not path_text:
            return
        path = pathlib.Path(path_text)
        monitor = tool.__dict__.get("serial_monitor_text")
        getter = getattr(monitor, "get", None)
        if not callable(getter):
            return
        try:
            current = str(getter("1.0", "end") or "")
        except TypeError:
            current = str(getter() or "")
        previous = str(tool.__dict__.get("_framework7_serial_log_snapshot") or "")
        if current == previous:
            return
        if current.startswith(previous):
            delta = current[len(previous):]
        else:
            # Display was cleared/rotated. Keep the session log continuous.
            delta = "\n--- Anzeige neu aufgebaut ---\n" + current
        if delta:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", newline="") as handle:
                handle.write(delta)
        tool._framework7_serial_log_snapshot = current
        tool.serial_monitor_log_path = str(path)

    def service_status(self: Any) -> dict[str, Any]:
        _ensure_headless_serial_monitor_compat(self.tool)
        with contextlib.suppress(Exception):
            _mirror_serial_tail_to_log(self.tool)
        data = original_status(self)

        def collect() -> dict[str, Any]:
            import JARNSEN_NODE_SERVICE_TOOL as legacy

            samples = []
            raw_samples = self.tool.__dict__.get("serial_power_samples", [])
            try:
                sample_items = list(raw_samples or [])
            except TypeError:
                sample_items = []
            for item in sample_items[-240:]:
                try:
                    stamp, voltage, current, power = item
                    samples.append({
                        "time": float(stamp),
                        "voltage_v": float(voltage) if voltage is not None else None,
                        "current_ma": float(current) if current is not None else None,
                        "power_mw": float(power) if power is not None else None,
                    })
                except Exception:
                    continue
            return {
                "power_samples": samples,
                "output_directory": str(pathlib.Path(legacy.output_directory())),
                "framework7_log_path": str(self.tool.__dict__.get("_framework7_serial_log_path") or ""),
            }

        extra = self.call_ui(collect, timeout=10.0)
        serial = data.setdefault("serial", {})
        serial["power_samples"] = extra["power_samples"]
        if extra["framework7_log_path"]:
            serial["log_path"] = extra["framework7_log_path"]
            serial["logging"] = True
        data["output_directory"] = extra["output_directory"]
        critical = data.setdefault("critical", {})
        critical.update({
            "serial_filter_search_pause": True,
            "serial_power_view": isinstance(self.tool.__dict__.get("serial_power_samples"), list),
            "serial_session_export": True,
            "serial_session_autolog": True,
            "ui_zoom": True,
        })
        data["ok"] = all(bool(value) for value in critical.values())
        return data

    def service_action(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
        command = str(payload.get("command") or "").strip()

        if command == "serial_monitor_start":
            def prepare_log() -> None:
                _ensure_headless_serial_monitor_compat(self.tool)
                _ensure_framework7_serial_log(self.tool, reset=True)

            self.call_ui(prepare_log, timeout=10.0)
            try:
                result = original_action(self, payload)
            except Exception:
                # Keep the empty log as useful evidence that startup itself failed.
                raise
            path = str(self.tool.__dict__.get("_framework7_serial_log_path") or "")
            if isinstance(result, dict):
                result.setdefault("log_path", path)
                result.setdefault("message", f"Serieller Monitor gestartet · Log: {path}")
            return result

        if command not in {"usb_log", "serial_monitor_export"}:
            return original_action(self, payload)

        def execute() -> dict[str, Any]:
            if command == "usb_log":
                node_id = str(payload.get("node_id") or "").strip()
                requested = str(payload.get("port") or "").strip()
                targets = self._usb_targets() if hasattr(self, "_usb_targets") else []
                port = ""
                if requested:
                    if not any(str(item.get("device") or "") == requested for item in targets):
                        raise RuntimeError(f"USB/COM-Port {requested} ist nicht mehr verfügbar")
                    port = requested
                elif hasattr(self, "_current_usb_port"):
                    with contextlib.suppress(Exception):
                        port = str(self._current_usb_port(node_id) or "").strip()
                if not port and len(targets) == 1:
                    port = str(targets[0].get("device") or "")
                if not port:
                    if len(targets) > 1:
                        raise RuntimeError("Mehrere USB/COM-Nodes erkannt – bitte den Ziel-Port auswählen")
                    raise RuntimeError("Keine kompatible USB/COM-Node erkannt")
                worker = self.tool.__dict__.get("worker")
                checker = getattr(worker, "is_alive", None)
                if callable(checker) and checker():
                    raise RuntimeError("Ein anderer Log-/Firmwarevorgang läuft bereits")
                _ensure_headless_serial_monitor_compat(self.tool)
                if self.tool.serial_monitor_active():
                    raise RuntimeError("Seriellen Monitor vor dem USB-Logdownload stoppen")
                self.tool._select_serial_port_in_ui(port)
                starter = getattr(self.tool, "_start_auto_usb_download", None)
                if starter is None:
                    raise RuntimeError("USB-Logdownload ist in diesem Backend nicht verfügbar")
                starter(port)
                return {"message": f"USB-Logdownload auf {port} gestartet", "port": port}

            with contextlib.suppress(Exception):
                _mirror_serial_tail_to_log(self.tool)
            source = self.tool.__dict__.get("_framework7_serial_log_path") or self.tool.__dict__.get("serial_monitor_log_path")
            source_path = pathlib.Path(str(source or ""))
            if not source_path.exists():
                raise RuntimeError("Noch kein serielles Sitzungslog vorhanden")
            import JARNSEN_NODE_SERVICE_TOOL as legacy
            output = pathlib.Path(legacy.output_directory())
            output.mkdir(parents=True, exist_ok=True)
            target = output / f"Serial_Monitor_Export_{legacy.now_local():%Y-%m-%d_%H%M%S}.log"
            shutil.copy2(source_path, target)
            return {"message": "Serielles Sitzungslog exportiert", "path": str(target)}

        return self.call_ui(execute, timeout=30.0)

    LegacyBridge.service_status = service_status
    LegacyBridge.service_action = service_action

    # Install the serial fleet/new-node workflow after the stable parity wrappers
    # so its service-status capability becomes part of the final health verdict.
    import JARNSEN_FRAMEWORK7_SERVICE_TOOL as base
    from JARNSEN_FRAMEWORK7_SERIES import install_series

    install_series(LegacyBridge, base.ApiHandler)
