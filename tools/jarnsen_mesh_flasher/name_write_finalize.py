from __future__ import annotations

import time
from typing import Any

from profile_utils import summary_from_info_text


_INSTALLED = False


def _emit(message: str) -> None:
    try:
        import diagnostics
        diagnostics._emit(message)
    except Exception:
        pass


def _resolve_live_port(services: Any, port: str) -> str:
    resolver = getattr(services, "resolve_live_port", None)
    if callable(resolver):
        try:
            live = str(resolver(port) or "").strip()
            if live:
                return live
        except Exception:
            pass
    return str(port)


def _wait_after_name_write(services: Any, port: str) -> str:
    waiter = getattr(services, "wait_for_serial", None)
    if callable(waiter):
        waiter(port, timeout=45)
    return _resolve_live_port(services, port)


def _write_names_atomic(services: Any, port: str, long_name: str, short_name: str) -> str:
    """Write Long/Short name in one Meshtastic session.

    Two separate CLI invocations are unsafe on ESP32 USB nodes because the first
    owner write can trigger a save/reboot window while the second process is
    already reconnecting.  The real Tracker V1.1 HIL reproduced exactly that
    failure: the flash succeeded but the old names survived.  Keep both owner
    fields in one command, then follow the physical USB device before readback.
    """
    live = _resolve_live_port(services, port)
    result = services.meshtastic(
        live,
        "--set-owner",
        str(long_name),
        "--set-owner-short",
        str(short_name),
        timeout=90,
        check=False,
    )
    returncode = int(getattr(result, "returncode", 0) or 0)
    if returncode != 0:
        details = "\n".join(
            part
            for part in (
                str(getattr(result, "stdout", "") or "").strip(),
                str(getattr(result, "stderr", "") or "").strip(),
            )
            if part
        )
        raise services.FlasherError(
            "Gerätenamen konnten nicht geschrieben werden"
            + (f": {details}" if details else f" (Exit {returncode})")
        )
    live = _wait_after_name_write(services, port)
    _emit(
        f"NAME FINALIZE WRITE port={port} live={live} atomic=1 "
        f"long={long_name!r} short={short_name!r}"
    )
    return live


def _read_names(services: Any, port: str, *, attempts: int = 4) -> tuple[str, str]:
    last_long = ""
    last_short = ""
    last_error = ""
    for attempt in range(1, attempts + 1):
        live = _resolve_live_port(services, port)
        try:
            result = services.meshtastic(live, "--info", timeout=30, check=False)
            text = "\n".join(
                part for part in (str(result.stdout or ""), str(result.stderr or "")) if part
            )
            summary = summary_from_info_text(text)
            last_long = str(summary.long_name or "").strip()
            last_short = str(summary.short_name or "").strip()
            _emit(
                f"NAME FINALIZE READ port={port} live={live} attempt={attempt}/{attempts} "
                f"long={last_long!r} short={last_short!r} chars={len(text)}"
            )
            if last_long or last_short:
                return last_long, last_short
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            _emit(
                f"NAME FINALIZE READ RETRY port={port} live={live} attempt={attempt}/{attempts} "
                f"error={last_error!r}"
            )
            try:
                waiter = getattr(services, "wait_for_serial", None)
                if callable(waiter):
                    waiter(port, timeout=20)
            except Exception:
                pass
        if attempt < attempts:
            time.sleep(1.25)
    if last_error:
        _emit(f"NAME FINALIZE READ END port={port} error={last_error!r}")
    return last_long, last_short


def install(services: Any) -> None:
    """Make Long/Short-name writing a verified all-board operation."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    def set_names(port: str, long_name: str, short_name: str) -> None:
        expected_long = str(long_name or "").strip()
        expected_short = str(short_name or "").strip()
        if not expected_long:
            raise services.FlasherError("Long Name fehlt.")
        if not (1 <= len(expected_short) <= 4):
            raise services.FlasherError("Short Name muss 1 bis 4 Zeichen lang sein.")

        _write_names_atomic(services, port, expected_long, expected_short)
        actual_long, actual_short = _read_names(services, port)
        if actual_long == expected_long and actual_short == expected_short:
            _emit(
                f"NAME FINALIZE OK port={port} long={actual_long!r} short={actual_short!r} "
                "retry-write=0 final-readback=1 atomic=1 reconnect-aware=1"
            )
            return

        _emit(
            f"NAME FINALIZE RETRY WRITE port={port} expected={expected_long!r}/{expected_short!r} "
            f"actual={actual_long!r}/{actual_short!r} atomic=1"
        )
        _write_names_atomic(services, port, expected_long, expected_short)
        time.sleep(0.8)
        actual_long, actual_short = _read_names(services, port)
        if actual_long != expected_long or actual_short != expected_short:
            raise services.FlasherError(
                "Namensprüfung fehlgeschlagen: "
                f"erwartet Long={expected_long!r}, Short={expected_short!r}; "
                f"gelesen Long={actual_long!r}, Short={actual_short!r}."
            )

        _emit(
            f"NAME FINALIZE OK port={port} long={actual_long!r} short={actual_short!r} "
            "retry-write=1 final-readback=1 atomic=1 reconnect-aware=1"
        )

    services.set_names = set_names
    services._jarnsen_name_write_finalize = True
    services._jarnsen_name_write_atomic = True
    _emit(
        "NAME WRITE FINALIZE installed all-boards=1 retry-write=1 final-readback=1 "
        "atomic-single-session=1 reconnect-aware=1"
    )
