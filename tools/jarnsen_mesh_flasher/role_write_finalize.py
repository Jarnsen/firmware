from __future__ import annotations

import time
from typing import Any

from profile_utils import summary_from_info_text

_INSTALLED = False
_PENDING_ROLE_BY_PORT: dict[str, str] = {}


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _key(port: str) -> str:
    return str(port or "").strip().upper()


def _norm(value: str) -> str:
    return str(value or "").strip().casefold()


def _decode(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _transient_disconnect_text(value: Any) -> bool:
    text = str(value or "").casefold()
    markers = (
        "connection timed out",
        "serial connection was interrupted",
        "device is rebooting",
        "device firmware is updating",
        "could not open port",
        "port not found",
        "port is not available",
        "clearcommerror",
        "semaphore timeout",
    )
    return any(marker in text for marker in markers)


def _read_role(services: Any, port: str) -> str:
    result = services.meshtastic(port, "--info", timeout=45, check=False)
    info = "\n".join(
        part for part in (_decode(result.stdout), _decode(result.stderr)) if part
    )
    return summary_from_info_text(info).role.strip()


def _set_role_explicit(services: Any, port: str, role: str) -> None:
    result = services.meshtastic(
        port,
        "--set",
        "device.role",
        role,
        timeout=60,
        check=False,
    )
    output = "\n".join(
        part for part in (_decode(result.stdout), _decode(result.stderr)) if part
    )
    returncode = int(getattr(result, "returncode", 0) or 0)
    _emit(
        f"ROLE FINALIZE SET port={port} role={role!r} exit={returncode} "
        f"output_chars={len(output)} transient={int(_transient_disconnect_text(output))}"
    )
    if returncode != 0 and not _transient_disconnect_text(output):
        raise services.FlasherError(
            "Rolle konnte nicht explizit geschrieben werden.\n\n"
            + (output[-1800:] if output else f"Exit {returncode}")
        )


def _run_reboot_with_disconnect_recovery(
    services: Any, base_reboot_node: Any, port: str
) -> None:
    try:
        base_reboot_node(port)
        return
    except Exception as exc:
        if not _transient_disconnect_text(exc):
            raise
        _emit(
            f"ROLE FINALIZE EXPECTED DISCONNECT port={port} "
            f"type={type(exc).__name__} message={str(exc)[:500]!r}"
        )

    # A role/power change can intentionally drop USB while Meshtastic CLI is
    # still waiting for its final acknowledgement. The write is not accepted as
    # successful here; we merely wait for the node and verify the result below.
    try:
        services.wait_for_serial(port, timeout=90)
    except Exception as wait_exc:
        raise services.FlasherError(
            f"{port} ist nach der Rollen-/Power-Änderung nicht wieder erreichbar."
        ) from wait_exc


def install(services: Any) -> None:
    """Guarantee that the role chosen in the write guard is the role left on the node.

    The staged profile restore normally writes role/power in its final transaction. Some
    Meshtastic/USB combinations drop the serial connection while that transaction is
    completing. That disconnect is recovered only when it matches a known reboot/update
    signature; afterwards the selected role is always read back and, if necessary,
    written explicitly once more.
    """
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    import write_choice_guard as choice_guard

    base_restore_profile = services.restore_profile
    base_reboot_node = services.reboot_node

    def restore_profile(port: str, profile=None) -> None:
        key = _key(port)
        selected_role = str(
            choice_guard._ROLE_OVERRIDE_BY_PORT.get(key, "") or ""
        ).strip()
        if selected_role:
            _PENDING_ROLE_BY_PORT[key] = selected_role
            _emit(
                f"ROLE FINALIZE CAPTURE port={port} selected={selected_role!r} "
                "source=write-choice"
            )
        try:
            return base_restore_profile(port, profile)
        except Exception:
            _PENDING_ROLE_BY_PORT.pop(key, None)
            raise

    def reboot_node(port: str) -> None:
        key = _key(port)
        selected_role = str(_PENDING_ROLE_BY_PORT.get(key, "") or "").strip()

        # First let the normal staged restore apply deferred role/power. A USB
        # disconnect at this point is expected on some Meshtastic builds and is
        # recovered by waiting for the same COM port to return.
        _run_reboot_with_disconnect_recovery(services, base_reboot_node, port)
        if not selected_role:
            return

        services.wait_for_serial(port, timeout=90)
        time.sleep(0.8)
        actual_role = _read_role(services, port)
        _emit(
            f"ROLE FINALIZE CHECK port={port} selected={selected_role!r} "
            f"actual={actual_role!r}"
        )
        if _norm(actual_role) == _norm(selected_role):
            _PENDING_ROLE_BY_PORT.pop(key, None)
            _emit(f"ROLE FINALIZE OK port={port} role={selected_role!r} retry=0")
            return

        _emit(
            f"ROLE FINALIZE RETRY port={port} selected={selected_role!r} "
            f"actual={actual_role!r} action=explicit-device.role"
        )
        _set_role_explicit(services, port, selected_role)

        # The explicit role write can itself reconnect USB. Give it a chance to
        # settle before forcing an additional reboot.
        time.sleep(1.2)
        try:
            services.wait_for_serial(port, timeout=90)
        except Exception:
            pass
        time.sleep(0.8)
        final_role = _read_role(services, port)

        if _norm(final_role) != _norm(selected_role):
            _emit(
                f"ROLE FINALIZE SECOND REBOOT port={port} selected={selected_role!r} "
                f"actual={final_role!r}"
            )
            _run_reboot_with_disconnect_recovery(services, base_reboot_node, port)
            services.wait_for_serial(port, timeout=90)
            time.sleep(0.8)
            final_role = _read_role(services, port)

        if _norm(final_role) != _norm(selected_role):
            raise services.FlasherError(
                "Rolle konnte nicht übernommen werden. "
                f"Gewählt {selected_role}, nach explizitem Schreiben gelesen "
                f"{final_role or 'unbekannt'}."
            )

        _PENDING_ROLE_BY_PORT.pop(key, None)
        _emit(f"ROLE FINALIZE OK port={port} role={selected_role!r} retry=1")

    services.restore_profile = restore_profile
    services.reboot_node = reboot_node
    services._jarnsen_role_write_finalize = True
    services._jarnsen_role_disconnect_recovery = True
    _emit(
        "ROLE FINALIZE installed selected-role=authoritative explicit-retry=1 "
        "final-readback=1 transient-disconnect-recovery=1"
    )
