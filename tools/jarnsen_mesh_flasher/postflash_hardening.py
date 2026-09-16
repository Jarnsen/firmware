from __future__ import annotations

import time
from typing import Any, Callable

_INSTALLED = False


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _board_key(bundle: Any) -> str:
    return str(getattr(bundle, "board_key", "") or "").strip().lower()


def _is_jarnsen(identity: Any) -> bool:
    return bool(identity is not None and getattr(identity, "is_jarnsen", False))


def _raw_jarnsen_service_identity(
    services: Any,
    port: str,
    *,
    expected_version: str | None = None,
    expected_build: int | None = None,
) -> Any | None:
    """Require the persistent JARNSEN raw service on role-api builds.

    ``query_jarnsen_identity`` intentionally has a Meshtastic ``--info``
    fallback so the UI can still identify a node while the raw USB service is
    temporarily unavailable.  That fallback is useful for display, but it is
    not strong enough as a post-flash readiness gate before ROLE_SET/radio
    commands.  Build 168+ advertises the persistent role service and must prove
    it by answering JARNSEN_TOOL_INFO directly.
    """
    build_hint = int(expected_build or 0)
    if build_hint < 168:
        return None

    import review_team_provisioning_v2 as provisioning

    line = provisioning._raw_command(
        port,
        "JARNSEN_TOOL_INFO",
        expected="===JARNSEN_INFO===",
        timeout=4.0,
        attempts=1,
        services=services,
    )
    if "role_api=1" not in str(line):
        raise RuntimeError("JARNSEN-Raw-Dienst meldet role_api=1 noch nicht")

    identity = provisioning._parse_tool_identity(line)
    if not _is_jarnsen(identity):
        raise RuntimeError(
            "JARNSEN-Raw-Dienst lieferte keine gültige Firmwareidentität"
        )

    if expected_version is not None:
        actual_version = str(getattr(identity, "version", "") or "")
        if actual_version != str(expected_version):
            raise RuntimeError(
                f"Raw-Dienst meldet noch falsche Firmwareversion: {actual_version!r} != "
                f"{str(expected_version)!r}"
            )
    actual_build = int(getattr(identity, "build", 0) or 0)
    if actual_build != build_hint:
        raise RuntimeError(
            f"Raw-Dienst meldet noch falschen Firmware-Build: {actual_build!r} != {build_hint!r}"
        )
    return identity


def wait_for_node_ready(
    services: Any,
    port: str,
    *,
    expected_board: str | None = None,
    timeout: int = 90,
    require_jarnsen: bool = True,
    expected_version: str | None = None,
    expected_build: int | None = None,
) -> tuple[str, str, Any]:
    """Wait for the application, not merely for a visible COM port.

    Native USB and CP210x ports can become visible several seconds before the
    freshly flashed application and the JARNSEN USB service are ready.  The
    caller therefore gets success only after the same logical/physical device
    answers at application level and, on current role-api builds, the exact raw
    JARNSEN service is ready too.
    """
    deadline = time.monotonic() + max(1, int(timeout))
    last_error = ""
    last_live = str(port or "").strip()

    while time.monotonic() < deadline:
        resolver = getattr(services, "resolve_live_port", None)
        try:
            live = str(resolver(port) if callable(resolver) else port).strip() or str(
                port
            )
        except Exception:
            live = str(port)
        last_live = live

        identity: Any = None
        raw_service_ready = False
        try:
            if require_jarnsen:
                identity = services.query_jarnsen_identity(live)
                if not _is_jarnsen(identity):
                    last_error = "JARNSEN-Firmwareidentität noch nicht bereit"
                    time.sleep(1.5)
                    continue
                if expected_version is not None:
                    actual_version = str(getattr(identity, "version", "") or "")
                    if actual_version != str(expected_version):
                        last_error = (
                            f"Firmwareversion noch nicht Zielstand: {actual_version!r} != "
                            f"{str(expected_version)!r}"
                        )
                        time.sleep(1.5)
                        continue
                if expected_build is not None:
                    actual_build = int(getattr(identity, "build", 0) or 0)
                    if actual_build != int(expected_build):
                        last_error = (
                            f"Firmware-Build noch nicht Zielstand: {actual_build!r} != "
                            f"{int(expected_build)!r}"
                        )
                        time.sleep(1.5)
                        continue

                build_hint = int(expected_build or getattr(identity, "build", 0) or 0)
                if build_hint >= 168:
                    raw_identity = _raw_jarnsen_service_identity(
                        services,
                        live,
                        expected_version=expected_version,
                        expected_build=build_hint,
                    )
                    if raw_identity is not None:
                        identity = raw_identity
                        raw_service_ready = True

            info = services.verify_node(live, expected_board=expected_board)
            _emit(
                "POSTFLASH READY "
                f"logical={port!r} live={live!r} board={expected_board or ''!r} "
                f"jarnsen={int(_is_jarnsen(identity))} raw-service={int(raw_service_ready)}"
            )
            return live, info, identity
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            _emit(
                "POSTFLASH WAIT "
                f"logical={port!r} live={live!r} board={expected_board or ''!r} "
                f"error={last_error[:500]!r}"
            )
            time.sleep(1.5)

    _emit(
        "POSTFLASH NOT READY "
        f"logical={port!r} live={last_live!r} board={expected_board or ''!r} "
        f"last={last_error[:700]!r} flash-retry-after-reset=0"
    )
    # Keep the user-facing exception intentionally free of low-level transient
    # USB keywords such as "timeout" or "serial exception". advanced_flasher's
    # baud fallback uses those tokens to decide whether the entire image should
    # be written again. At this point the image has already been hash-verified;
    # only application readiness failed, so an automatic reflash is unsafe and
    # unnecessary. Full details stay in diagnostics above.
    raise services.FlasherError(
        f"POSTFLASH_APPLICATION_NOT_READY: {last_live}: Das verifizierte Image bleibt "
        "installiert, aber die Anwendung bzw. der JARNSEN-Dienst wurde nicht rechtzeitig "
        "bereit. Automatisches erneutes Flashen ist gesperrt; Diagnose/Recovery ist erforderlich."
    )


def _supreme_connection_args(
    base: Callable[..., list[str]],
    board_key: str,
    *,
    before: str = "usb-reset",
    after: str = "watchdog-reset",
) -> list[str]:
    """Keep verified writes separate from the disconnecting watchdog reset."""
    if (
        str(board_key or "").strip().lower() == "tbeam_supreme"
        and after == "watchdog-reset"
    ):
        after = "no-reset"
    return base(board_key, before=before, after=after)


def finish_supreme_application_start(
    services: Any,
    logical_port: str,
    *,
    log: Callable[[str], None] | None = None,
    timeout: int = 90,
    expected_version: str | None = None,
    expected_build: int | None = None,
) -> str:
    """Reset a verified Supreme image without turning port loss into flash failure.

    esptool can verify the image hash and then lose the native USB COM handle
    while performing ``watchdog-reset``.  That serial exception is expected on
    Windows and must never cause the already verified image to be written again.
    Reset is therefore a separate, non-flash phase; success is decided by the
    same physical USB device returning and the application answering.
    """
    from flash_runtime import _stream_esptool

    resolver = getattr(services, "resolve_live_port", None)
    flash_port = str(
        resolver(logical_port) if callable(resolver) else logical_port
    ).strip()
    if not flash_port:
        flash_port = str(logical_port)

    if log:
        log(
            "NODE START · Flash/Hash bereits verifiziert · separater ESP32-S3 "
            "Watchdog-Reset"
        )

    try:
        result = _stream_esptool(
            services,
            flash_port,
            [
                "--chip",
                "esp32s3",
                "--before",
                "no-reset",
                "--after",
                "watchdog-reset",
                "read-flash-status",
            ],
            timeout=30,
            stage="Node starten",
            phase_start=0.98,
            phase_end=0.99,
            log=log,
            check=False,
        )
        _emit(
            "SUPREME POSTFLASH RESET "
            f"port={flash_port!r} exit={int(getattr(result, 'returncode', 1))} "
            "flash-retry=0"
        )
    except Exception as exc:
        # Losing the native USB handle during watchdog reset is expected.  The
        # physical reconnect + application readiness checks below are the only
        # success criteria here.
        _emit(
            "SUPREME POSTFLASH RESET PORT-LOSS "
            f"port={flash_port!r} type={type(exc).__name__} "
            f"message={str(exc)[:500]!r} flash-retry=0"
        )

    waiter = getattr(services, "wait_for_device_reconnect", None)
    if callable(waiter):
        live = str(
            waiter(
                logical_port,
                timeout=min(max(timeout, 20), 60),
                expected_board="tbeam_supreme",
            )
        ).strip()
    else:
        live = str(logical_port)

    ready_live, _info, _identity = wait_for_node_ready(
        services,
        logical_port,
        expected_board="tbeam_supreme",
        timeout=timeout,
        require_jarnsen=True,
        expected_version=expected_version,
        expected_build=expected_build,
    )
    if log:
        log(f"NODE START · Supreme-Anwendung bereit · Port={ready_live}")
    return ready_live or live


def install(services: Any) -> None:
    global _INSTALLED
    if _INSTALLED or getattr(services, "_jarnsen_postflash_hardening", False):
        return

    import unified_service_v2

    base_connection_args = unified_service_v2.esp32_connection_args

    def connection_args(
        board_key: str,
        *,
        before: str = "usb-reset",
        after: str = "watchdog-reset",
    ) -> list[str]:
        return _supreme_connection_args(
            base_connection_args,
            board_key,
            before=before,
            after=after,
        )

    unified_service_v2.esp32_connection_args = connection_args

    base_flash_bundle = services.flash_bundle

    def flash_bundle(
        port: str, bundle: Any, log: Callable[[str], None] | None = None
    ) -> None:
        base_flash_bundle(port, bundle, log=log)
        board = _board_key(bundle)
        version = str(getattr(bundle, "version", "") or "") or None
        build = int(getattr(bundle, "run_number", 0) or 0) or None
        if board == "tbeam_supreme":
            finish_supreme_application_start(
                services,
                port,
                log=log,
                timeout=120,
                expected_version=version,
                expected_build=build,
            )
        else:
            profile = services.BOARD_PROFILES.get(board, {})
            if str(profile.get("artifact_kind") or "esp32").lower() == "esp32":
                wait_for_node_ready(
                    services,
                    port,
                    expected_board=board or None,
                    timeout=90,
                    require_jarnsen=True,
                    expected_version=version,
                    expected_build=build,
                )

    services.flash_bundle = flash_bundle

    base_firmware_only = unified_service_v2.flash_firmware_only_bundle

    def firmware_only_bundle(
        runtime_services: Any,
        port: str,
        board_key: str,
        bundle: Any,
        log: Callable[[str], None] | None,
    ) -> None:
        def relay(message: str) -> None:
            text = str(message)
            if (
                board_key == "tbeam_supreme"
                and "Watchdog-Reset durch esptool ausgelöst" in text
            ):
                text = "FLASH VERIFIZIERT · separater Supreme-Reset folgt"
            if log:
                log(text)

        base_firmware_only(runtime_services, port, board_key, bundle, relay)
        version = str(getattr(bundle, "version", "") or "") or None
        build = int(getattr(bundle, "run_number", 0) or 0) or None
        if str(board_key).strip().lower() == "tbeam_supreme":
            finish_supreme_application_start(
                runtime_services,
                port,
                log=log,
                timeout=120,
                expected_version=version,
                expected_build=build,
            )
        else:
            wait_for_node_ready(
                runtime_services,
                port,
                expected_board=board_key,
                timeout=90,
                require_jarnsen=True,
                expected_version=version,
                expected_build=build,
            )

    unified_service_v2.flash_firmware_only_bundle = firmware_only_bundle
    services.wait_for_node_ready = lambda port, **kwargs: wait_for_node_ready(
        services, port, **kwargs
    )
    services.finish_supreme_application_start = (
        lambda port, **kwargs: finish_supreme_application_start(
            services, port, **kwargs
        )
    )
    services._jarnsen_postflash_hardening = True
    _INSTALLED = True
    _emit(
        "POSTFLASH HARDENING installed hash-before-reset=1 flash-retry-after-reset=0 "
        "application-ready-gate=1 raw-service-ready-gate=1 physical-reconnect=1"
    )
