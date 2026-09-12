from __future__ import annotations

import time
from typing import Any, Iterable


_INSTALLED = False


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _key(port: str) -> str:
    return str(port or "").strip().upper()


def _resolve(services: Any, port: str) -> str:
    logical = str(port or "").strip()
    resolver = getattr(services, "resolve_live_port", None)
    if callable(resolver):
        try:
            live = str(resolver(logical) or "").strip()
            if live:
                return live
        except Exception:
            pass
    return logical


def _remember(services: Any, port: str) -> None:
    manager = getattr(services, "device_sessions", None)
    remember = getattr(manager, "remember", None)
    if callable(remember):
        try:
            fingerprint = remember(port)
            if fingerprint is not None:
                _emit(
                    "PORT RECONNECT REMEMBER "
                    f"logical={port} serial={getattr(fingerprint, 'serial_number', '')!r} "
                    f"vid={getattr(fingerprint, 'vid', None)!r} pid={getattr(fingerprint, 'pid', None)!r}"
                )
        except Exception as exc:
            _emit(
                f"PORT RECONNECT REMEMBER WARNING logical={port} "
                f"type={type(exc).__name__}:{exc}"
            )


def _transient(exc: BaseException) -> bool:
    text = str(exc or "").casefold()
    return any(
        token in text
        for token in (
            "timed out",
            "timeout",
            "connection timed out",
            "clearcommerror",
            "couldn't be opened",
            "could not open port",
            "file not found",
            "permissionerror",
            "serial port disconnected",
            "serial connection was interrupted",
            "das system kann die angegebene datei nicht finden",
            "das gerät erkennt den befehl nicht",
        )
    )


def _rewrite_port_args(services: Any, args: Iterable[str]) -> list[str]:
    values = [str(value) for value in args]
    for index, value in enumerate(values[:-1]):
        if value != "--port":
            continue
        logical = values[index + 1]
        live = _resolve(services, logical)
        if live and _key(live) != _key(logical):
            values[index + 1] = live
            _emit(f"PORT RECONNECT IO logical={logical} live={live}")
        break
    return values


def install(services: Any) -> None:
    """Keep one logical job alive while Windows may renumber its USB COM port.

    Per-port transaction/role/name state deliberately stays keyed by the original
    logical port. Only the final I/O boundary is redirected to the currently
    resolved physical COM port. This avoids splitting one flash into two jobs.
    """
    global _INSTALLED
    if _INSTALLED or getattr(services, "_jarnsen_port_reconnect_hardening", False):
        return
    _INSTALLED = True

    if not callable(getattr(services, "resolve_live_port", None)):
        raise RuntimeError("Port reconnect hardening requires device_core.resolve_live_port")
    if not callable(getattr(services, "wait_for_serial", None)):
        raise RuntimeError("Port reconnect hardening requires device_core.wait_for_serial")

    # Every helper-based Meshtastic/esptool call eventually crosses run_helper.
    # Rewrite only the actual CLI argument here so higher layers retain the
    # original logical port for transaction/name/role state.
    base_run_helper = services.run_helper

    def run_helper(
        tool: str,
        args: Iterable[str],
        *,
        timeout: int = 60,
        check: bool = True,
    ):
        return base_run_helper(
            tool,
            _rewrite_port_args(services, args),
            timeout=timeout,
            check=check,
        )

    services.run_helper = run_helper

    # Preserve the USB fingerprint before a destructive flash can make the
    # application COM disappear or return with a new number.
    base_flash_bundle = services.flash_bundle

    def flash_bundle(port: str, bundle: Any, log=None):
        _remember(services, port)
        return base_flash_bundle(port, bundle, log=log)

    services.flash_bundle = flash_bundle

    # A board can disappear during --info itself. Remember it first, then use a
    # bounded reconnect+retry path instead of treating the first transient USB
    # reset as a permanent board failure.
    base_verify_node = services.verify_node

    def verify_node(port: str, expected_board: str | None = None) -> str:
        _remember(services, port)
        last: BaseException | None = None
        for attempt in range(1, 4):
            try:
                return base_verify_node(port, expected_board=expected_board)
            except Exception as exc:
                last = exc
                if not _transient(exc) or attempt >= 3:
                    raise
                _emit(
                    f"PORT RECONNECT VERIFY RETRY logical={port} attempt={attempt}/3 "
                    f"type={type(exc).__name__}:{str(exc)[:300]}"
                )
                try:
                    services.wait_for_serial(port, timeout=25)
                except Exception as wait_exc:
                    _emit(
                        f"PORT RECONNECT VERIFY WAIT logical={port} attempt={attempt}/3 "
                        f"type={type(wait_exc).__name__}:{str(wait_exc)[:300]}"
                    )
                time.sleep(0.45)
        if last is not None:
            raise last
        raise services.FlasherError(f"{port}: Verifikation ohne Ergebnis beendet.")

    services.verify_node = verify_node

    # The exact JARNSEN identity probe uses raw serial underneath some runtime
    # layers. Resolve the live port at its public service boundary as well.
    base_identity = getattr(services, "query_jarnsen_identity", None)
    if callable(base_identity):
        def query_jarnsen_identity(port: str, *args: Any, **kwargs: Any):
            _remember(services, port)
            for attempt in range(1, 3):
                live = _resolve(services, port)
                value = base_identity(live, *args, **kwargs)
                if value is not None:
                    return value
                if attempt < 2:
                    try:
                        services.wait_for_serial(port, timeout=15)
                    except Exception:
                        pass
                    time.sleep(0.35)
            return None

        services.query_jarnsen_identity = query_jarnsen_identity

    # Profile V2 writes directly with Popen instead of services.run_helper.
    # Redirect just that physical command port; callbacks and transaction state
    # continue to use the logical job port outside this low-level call.
    try:
        import profile_restore

        base_stream_configure = profile_restore._stream_configure

        def stream_configure(
            runtime_services: Any,
            port: str,
            profile_path: Any,
            profile_data: Any,
            **kwargs: Any,
        ):
            live = _resolve(runtime_services, port)
            if _key(live) != _key(port):
                _emit(f"PORT RECONNECT PROFILE logical={port} live={live}")
            return base_stream_configure(
                runtime_services,
                live,
                profile_path,
                profile_data,
                **kwargs,
            )

        profile_restore._stream_configure = stream_configure
    except Exception as exc:
        raise RuntimeError(f"Profile reconnect hook failed: {exc}") from exc

    # Firmware role/radio services use direct pyserial. Redirect those opens at
    # the raw command boundary without changing the higher-level logical port.
    try:
        import radio_profile_node_sync

        base_raw_command = radio_profile_node_sync._raw_command

        def raw_command(
            port: str,
            command: str,
            *,
            expected: str,
            timeout: float = 10.0,
        ) -> str:
            live = _resolve(services, port)
            if _key(live) != _key(port):
                _emit(f"PORT RECONNECT RAW logical={port} live={live} command={command.split()[0]!r}")
            return base_raw_command(live, command, expected=expected, timeout=timeout)

        radio_profile_node_sync._raw_command = raw_command
    except Exception as exc:
        raise RuntimeError(f"Raw serial reconnect hook failed: {exc}") from exc

    services._jarnsen_port_reconnect_hardening = True
    services._jarnsen_logical_port_state = True
    _emit(
        "PORT RECONNECT HARDENING installed helper-alias=1 verify-retry=1 "
        "identity-alias=1 profile-alias=1 raw-alias=1 preflash-fingerprint=1"
    )
