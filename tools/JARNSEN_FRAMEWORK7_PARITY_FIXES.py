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
        worker = getattr(tool, "serial_monitor_worker", None)
        checker = getattr(worker, "is_alive", None)
        if not callable(checker):
            return False
        try:
            return bool(checker())
        except Exception:
            return False

    def _ensure_headless_serial_monitor_compat(tool: Any) -> None:
        """Normalize serial state that legacy Tk initialization used to create.

        The declaration-only Tk shim intentionally returns no-op callables for
        unknown widget methods. A missing legacy instance attribute can therefore
        surface as a function in the headless service object unless the adapter
        initializes it explicitly. Keep the monitor-active probe live and ensure
        the power-sample store is a real mutable list for both status reporting and
        subsequent serial-monitor sampling.
        """
        monitor = getattr(tool, "serial_monitor_active", None)
        if callable(monitor):
            try:
                monitor()
            except AttributeError as exc:
                if "is_alive" not in str(exc):
                    raise
                tool.serial_monitor_active = lambda: _serial_monitor_active_from_worker(tool)

        samples = getattr(tool, "serial_power_samples", None)
        if samples is None or callable(samples):
            tool.serial_power_samples = []
            return
        try:
            list(samples)
        except TypeError:
            tool.serial_power_samples = []

    def service_status(self: Any) -> dict[str, Any]:
        _ensure_headless_serial_monitor_compat(self.tool)
        data = original_status(self)

        def collect() -> dict[str, Any]:
            import JARNSEN_NODE_SERVICE_TOOL as legacy

            samples = []
            raw_samples = getattr(self.tool, "serial_power_samples", [])
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
            }

        extra = self.call_ui(collect, timeout=10.0)
        serial = data.setdefault("serial", {})
        serial["power_samples"] = extra["power_samples"]
        data["output_directory"] = extra["output_directory"]
        critical = data.setdefault("critical", {})
        critical.update({
            "serial_filter_search_pause": True,
            "serial_power_view": isinstance(getattr(self.tool, "serial_power_samples", None), list),
            "serial_session_export": hasattr(self.tool, "serial_monitor_log_path"),
            "ui_zoom": True,
        })
        data["ok"] = all(bool(value) for value in critical.values())
        return data

    def service_action(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
        command = str(payload.get("command") or "").strip()
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
                if getattr(self.tool, "worker", None) and self.tool.worker.is_alive():
                    raise RuntimeError("Ein anderer Log-/Firmwarevorgang läuft bereits")
                _ensure_headless_serial_monitor_compat(self.tool)
                if hasattr(self.tool, "serial_monitor_active") and self.tool.serial_monitor_active():
                    raise RuntimeError("Seriellen Monitor vor dem USB-Logdownload stoppen")
                self.tool._select_serial_port_in_ui(port)
                starter = getattr(self.tool, "_start_auto_usb_download", None)
                if starter is None:
                    raise RuntimeError("USB-Logdownload ist in diesem Backend nicht verfügbar")
                starter(port)
                return {"message": f"USB-Logdownload auf {port} gestartet", "port": port}

            source = getattr(self.tool, "serial_monitor_log_path", None)
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
