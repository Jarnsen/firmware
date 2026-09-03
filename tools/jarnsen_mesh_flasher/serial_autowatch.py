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
    """Refresh on wired hotplug only after Windows has a stable device view."""
    original_init = ctk.CTk.__init__

    def root_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        self._jarnsen_wired_signature = None
        self._jarnsen_hotplug_candidate = None
        self._jarnsen_hotplug_candidate_count = 0
        self._jarnsen_hotplug_pending = False

        def signature() -> tuple[str, ...]:
            try:
                items = list(services.list_ports.comports())
            except Exception as exc:
                _emit(f"SERIAL HOTPLUG ENUM ERROR type={type(exc).__name__} message={exc}")
                return ()

            values: list[str] = []
            bluetooth_test = getattr(services, "is_bluetooth_serial", None)
            fingerprint = getattr(services, "serial_device_fingerprint", None)
            for item in items:
                port = str(getattr(item, "device", "") or "").upper()
                if not port:
                    continue
                try:
                    if callable(bluetooth_test) and bluetooth_test(item):
                        continue
                except Exception:
                    pass
                fp = ""
                try:
                    if callable(fingerprint):
                        fp = str(fingerprint(item) or "")
                except Exception:
                    fp = ""
                values.append(f"{port}|{fp}")
            return tuple(sorted(set(values)))

        def ports_from_signature(value: tuple[str, ...]) -> list[str]:
            return sorted(item.split("|", 1)[0] for item in value)

        def candidate_stable(current: tuple[str, ...], required: int) -> bool:
            candidate = getattr(self, "_jarnsen_hotplug_candidate", None)
            if candidate == current:
                self._jarnsen_hotplug_candidate_count += 1
            else:
                self._jarnsen_hotplug_candidate = current
                self._jarnsen_hotplug_candidate_count = 1
            count = int(getattr(self, "_jarnsen_hotplug_candidate_count", 0))
            _emit(
                f"SERIAL HOTPLUG DEBOUNCE count={count}/{required} "
                f"candidate={ports_from_signature(current)}"
            )
            if count >= required:
                self._jarnsen_hotplug_candidate = None
                self._jarnsen_hotplug_candidate_count = 0
                return True
            return False

        def accept_change(previous: tuple[str, ...], current: tuple[str, ...]) -> bool:
            previous_set = set(previous)
            current_set = set(current)
            added = current_set - previous_set
            removed = previous_set - current_set

            # New ports and COM-number replacements must be visible in two
            # consecutive polls before a scan begins.  This avoids probing the
            # short-lived first COM number during USB CDC re-enumeration.
            if added:
                _emit(
                    f"SERIAL HOTPLUG ADD/REPLACE pending added={ports_from_signature(tuple(sorted(added)))} "
                    f"removed={ports_from_signature(tuple(sorted(removed)))}"
                )
                return candidate_stable(current, 2)

            # Removal gets a longer grace window because JARNSEN-MESH can
            # temporarily drop USB while booting, waking or changing mode.
            if removed:
                _emit(
                    f"SERIAL HOTPLUG REMOVE pending removed={ports_from_signature(tuple(sorted(removed)))}"
                )
                return candidate_stable(current, 6)

            return False

        def tick() -> None:
            try:
                current = signature()
                previous = getattr(self, "_jarnsen_wired_signature", None)
                if previous is None:
                    self._jarnsen_wired_signature = current
                    _emit(f"SERIAL HOTPLUG BASELINE wired={ports_from_signature(current)}")
                elif current == previous:
                    self._jarnsen_hotplug_candidate = None
                    self._jarnsen_hotplug_candidate_count = 0
                elif accept_change(previous, current):
                    self._jarnsen_wired_signature = current
                    self._jarnsen_hotplug_pending = True
                    _emit(
                        f"SERIAL HOTPLUG CHANGE accepted before={ports_from_signature(previous)} "
                        f"after={ports_from_signature(current)}"
                    )

                if getattr(self, "_jarnsen_hotplug_pending", False):
                    busy = bool(getattr(self, "busy", False))
                    refresh = getattr(self, "refresh_devices", None)
                    if not busy and callable(refresh):
                        self._jarnsen_hotplug_pending = False
                        _emit("SERIAL HOTPLUG REFRESH trigger=automatic stable=1")
                        refresh()

                self.after(700, tick)
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
    _emit(
        "SERIAL HOTPLUG installed interval=700ms addition-debounce=2 "
        "removal-debounce=6 fingerprint-signature=1"
    )
