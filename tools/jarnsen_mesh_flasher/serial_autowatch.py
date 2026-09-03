from __future__ import annotations

from typing import Any

import customtkinter as ctk


def _emit(message: str) -> None:
    try:
        import diagnostics
        diagnostics._emit(message)
    except Exception:
        pass


def install(services: Any) -> None:
    """Refresh the device list automatically when wired COM ports change."""
    original_init = ctk.CTk.__init__

    def root_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        self._jarnsen_wired_signature = None
        self._jarnsen_hotplug_pending = False

        def signature() -> tuple[str, ...]:
            try:
                items = list(services.list_ports.comports())
            except Exception as exc:
                _emit(f"SERIAL HOTPLUG ENUM ERROR type={type(exc).__name__} message={exc}")
                return ()

            ports: list[str] = []
            bluetooth_test = getattr(services, "is_bluetooth_serial", None)
            for item in items:
                port = str(getattr(item, "device", "") or "").upper()
                if not port:
                    continue
                try:
                    if callable(bluetooth_test) and bluetooth_test(item):
                        continue
                except Exception:
                    pass
                ports.append(port)
            return tuple(sorted(set(ports)))

        def tick() -> None:
            try:
                current = signature()
                previous = getattr(self, "_jarnsen_wired_signature", None)
                if previous is None:
                    self._jarnsen_wired_signature = current
                    _emit(f"SERIAL HOTPLUG BASELINE wired={list(current)}")
                elif current != previous:
                    self._jarnsen_wired_signature = current
                    self._jarnsen_hotplug_pending = True
                    _emit(f"SERIAL HOTPLUG CHANGE before={list(previous)} after={list(current)}")

                if getattr(self, "_jarnsen_hotplug_pending", False):
                    busy = bool(getattr(self, "busy", False))
                    refresh = getattr(self, "refresh_devices", None)
                    if not busy and callable(refresh):
                        self._jarnsen_hotplug_pending = False
                        _emit("SERIAL HOTPLUG REFRESH trigger=automatic")
                        refresh()

                self.after(800, tick)
            except Exception as exc:
                _emit(f"SERIAL HOTPLUG TICK ERROR type={type(exc).__name__} message={exc}")
                try:
                    self.after(1500, tick)
                except Exception:
                    pass

        try:
            self.after(1200, tick)
        except Exception:
            pass

    ctk.CTk.__init__ = root_init  # type: ignore[assignment]
    _emit("SERIAL HOTPLUG installed interval=800ms automatic-refresh=1")
