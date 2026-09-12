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


def _read_names(services: Any, port: str, *, attempts: int = 4) -> tuple[str, str]:
    last_long = ""
    last_short = ""
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            result = services.meshtastic(port, "--info", timeout=30, check=False)
            text = "\n".join(
                part for part in (str(result.stdout or ""), str(result.stderr or "")) if part
            )
            summary = summary_from_info_text(text)
            last_long = str(summary.long_name or "").strip()
            last_short = str(summary.short_name or "").strip()
            _emit(
                f"NAME FINALIZE READ port={port} attempt={attempt}/{attempts} "
                f"long={last_long!r} short={last_short!r} chars={len(text)}"
            )
            if last_long or last_short:
                return last_long, last_short
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            _emit(
                f"NAME FINALIZE READ RETRY port={port} attempt={attempt}/{attempts} "
                f"error={last_error!r}"
            )
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

    base_set_names = services.set_names

    def set_names(port: str, long_name: str, short_name: str) -> None:
        expected_long = str(long_name or "").strip()
        expected_short = str(short_name or "").strip()
        base_set_names(port, expected_long, expected_short)

        actual_long, actual_short = _read_names(services, port)
        if actual_long == expected_long and actual_short == expected_short:
            _emit(
                f"NAME FINALIZE OK port={port} long={actual_long!r} short={actual_short!r} "
                "retry-write=0 final-readback=1"
            )
            return

        _emit(
            f"NAME FINALIZE RETRY WRITE port={port} expected={expected_long!r}/{expected_short!r} "
            f"actual={actual_long!r}/{actual_short!r}"
        )
        base_set_names(port, expected_long, expected_short)
        time.sleep(1.0)
        actual_long, actual_short = _read_names(services, port)
        if actual_long != expected_long or actual_short != expected_short:
            raise services.FlasherError(
                "Namensprüfung fehlgeschlagen: "
                f"erwartet Long={expected_long!r}, Short={expected_short!r}; "
                f"gelesen Long={actual_long!r}, Short={actual_short!r}."
            )

        _emit(
            f"NAME FINALIZE OK port={port} long={actual_long!r} short={actual_short!r} "
            "retry-write=1 final-readback=1"
        )

    services.set_names = set_names
    services._jarnsen_name_write_finalize = True
    _emit("NAME WRITE FINALIZE installed all-boards=1 retry-write=1 final-readback=1")
