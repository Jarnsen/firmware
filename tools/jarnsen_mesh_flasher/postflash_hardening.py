from __future__ import annotations

import time
from typing import Any, Callable

_INSTALLED = False
_V3_POSTFLASH_READY_TIMEOUT = 60
_V3_FIRMWARE_ONLY_READY_TIMEOUT = 45
_V3_POSTFLASH_BOOT_GRACE = 6.0
_V3_POSTFLASH_PROBE_INTERVAL = 1.8


def _postflash_timeout_seconds(
    expected_board: str | None,
    timeout: int,
    require_jarnsen: bool,
    expected_build: int | None,
    *,
    extended_v3_grace: bool = True,
) -> int:
    """Give current Heltec V3 builds enough time to finish a reboot/migration cycle."""
    requested = max(1, int(timeout))
    board = str(expected_board or "").strip().lower()
    build = int(expected_build or 0)
    if extended_v3_grace and board == "repeater" and require_jarnsen and build >= 168:
        # The image is already hash-verified at this point. A V3 that has not
        # brought its application service up within one minute needs recovery,
        # not twelve minutes of serial probing.
        return min(requested, _V3_POSTFLASH_READY_TIMEOUT)
    return requested


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
    """Prove the post-flash JARNSEN service with one non-resetting serial probe."""
    build_hint = int(expected_build or 0)
    if build_hint < 168:
        return None

    import radio_profile_legacy_fallback as legacy
    import review_team_provisioning_v2 as provisioning

    guard_factory = getattr(services, "jarnsen_serial_guard", None)
    guard = guard_factory(port) if callable(guard_factory) else None

    def probe() -> str:
        return legacy._safe_raw_command_once(
            port,
            "JARNSEN_TOOL_INFO",
            expected="===JARNSEN_INFO===",
            timeout=1.5,
        )

    if guard is None:
        line = probe()
    else:
        with guard:
            line = probe()

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

    try:
        provisioning._FAST_IDENTITY_BY_PORT[str(port or "").strip().upper()] = identity
    except Exception:
        pass
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
    extended_v3_grace: bool = True,
    require_meshtastic: bool = True,
) -> tuple[str, str, Any]:
    """Wait for the application without repeatedly resetting a booting V3."""
    requested_timeout = max(1, int(timeout))
    ready_timeout = _postflash_timeout_seconds(
        expected_board,
        requested_timeout,
        require_jarnsen,
        expected_build,
        extended_v3_grace=extended_v3_grace,
    )
    board = str(expected_board or "").strip().lower()
    current_v3 = (
        board == "repeater" and require_jarnsen and int(expected_build or 0) >= 168
    )
    started = time.monotonic()

    def notify(detail: str) -> None:
        callback = getattr(services, "_jarnsen_flash_progress_callback", None)
        if callable(callback):
            try:
                callback(
                    1.0,
                    "V3 Startprüfung" if current_v3 else "Node Startprüfung",
                    detail,
                )
            except Exception:
                pass
        ui_log = getattr(services, "_jarnsen_ui_log_callback", None)
        if callable(ui_log):
            try:
                ui_log(
                    ("V3 STARTPRÜFUNG · " if current_v3 else "NODE STARTPRÜFUNG · ")
                    + detail
                )
            except Exception:
                pass

    if current_v3:
        _emit(
            "POSTFLASH V3 SAFE WAIT "
            f"logical={port!r} requested={requested_timeout}s effective={ready_timeout}s "
            f"boot-grace={_V3_POSTFLASH_BOOT_GRACE:.1f}s probe-interval={_V3_POSTFLASH_PROBE_INTERVAL:.1f}s "
            "single-shot=1 dtr=0 rts=0 flash-retry-after-reset=0"
        )
        notify(
            f"Flash verifiziert · {_V3_POSTFLASH_BOOT_GRACE:.0f}s Boot-Ruhephase · "
            "keine Reset-Leitungen"
        )

    deadline = started + ready_timeout
    last_error = ""
    last_live = str(port or "").strip()
    probe_attempt = 0

    # CP210x stays visible while the ESP32-S3 is still in early boot. Do not
    # touch the serial port immediately after esptool's hard reset.
    grace_until = min(
        deadline, started + (_V3_POSTFLASH_BOOT_GRACE if current_v3 else 0.0)
    )
    while time.monotonic() < grace_until:
        checker = getattr(services, "raise_if_cancelled", None)
        if callable(checker):
            checker()
        time.sleep(min(0.25, max(0.01, grace_until - time.monotonic())))

    while time.monotonic() < deadline:
        checker = getattr(services, "raise_if_cancelled", None)
        if callable(checker):
            checker()

        resolver = getattr(services, "resolve_live_port", None)
        try:
            live = str(resolver(port) if callable(resolver) else port).strip() or str(
                port
            )
        except Exception:
            live = str(port)
        last_live = live
        probe_attempt += 1
        if current_v3:
            elapsed = int(time.monotonic() - started)
            notify(f"JARNSEN-Dienst prüfen · Versuch {probe_attempt} · {elapsed}s")

        identity: Any = None
        raw_service_ready = False
        try:
            if require_jarnsen:
                build_hint = int(expected_build or 0)
                if build_hint >= 168:
                    identity = _raw_jarnsen_service_identity(
                        services,
                        live,
                        expected_version=expected_version,
                        expected_build=build_hint,
                    )
                    raw_service_ready = identity is not None
                else:
                    identity = services.query_jarnsen_identity(live)

                if not _is_jarnsen(identity):
                    raise RuntimeError("JARNSEN-Firmwareidentität noch nicht bereit")
                if expected_version is not None:
                    actual_version = str(getattr(identity, "version", "") or "")
                    if actual_version != str(expected_version):
                        raise RuntimeError(
                            f"Firmwareversion noch nicht Zielstand: {actual_version!r} != "
                            f"{str(expected_version)!r}"
                        )
                if expected_build is not None:
                    actual_build = int(getattr(identity, "build", 0) or 0)
                    if actual_build != int(expected_build):
                        raise RuntimeError(
                            f"Firmware-Build noch nicht Zielstand: {actual_build!r} != "
                            f"{int(expected_build)!r}"
                        )

            if require_meshtastic:
                info = services.verify_node(live, expected_board=expected_board)
            else:
                info = ""
                hardware = str(getattr(identity, "hardware", "") or "")
                detected = (
                    services.detect_board_from_text(
                        f"hardware: {hardware}\nJARNSEN-MESH"
                    )
                    if hardware
                    else None
                )
                if expected_board and detected and detected != expected_board:
                    raise services.FlasherError(
                        "Post-Flash-Rawdienst meldet ein anderes Board."
                    )
                if expected_board and detected is None:
                    raise RuntimeError(
                        "JARNSEN-Rawdienst antwortet, aber die Boardkennung fehlt noch"
                    )

            _emit(
                "POSTFLASH READY "
                f"logical={port!r} live={live!r} board={expected_board or ''!r} "
                f"jarnsen={int(_is_jarnsen(identity))} raw-service={int(raw_service_ready)} "
                f"meshtastic-required={int(require_meshtastic)} attempts={probe_attempt}"
            )
            if current_v3:
                notify(f"JARNSEN-Dienst bereit · {time.monotonic()-started:.1f}s")
            return live, info, identity
        except Exception as exc:
            cancelled_type = getattr(services, "OperationCancelled", ())
            if cancelled_type and isinstance(exc, cancelled_type):
                raise
            last_error = f"{type(exc).__name__}: {exc}"
            _emit(
                "POSTFLASH WAIT "
                f"logical={port!r} live={live!r} board={expected_board or ''!r} "
                f"attempt={probe_attempt} error={last_error[:500]!r}"
            )

            lower = last_error.casefold()
            port_missing = any(
                token in lower
                for token in (
                    "could not open port",
                    "couldn't be opened",
                    "file not found",
                    "angegebene datei nicht finden",
                    "clearcommerror",
                    "permissionerror",
                )
            )
            if port_missing:
                waiter = getattr(services, "wait_for_device_reconnect", None)
                remaining = max(0.0, deadline - time.monotonic())
                if callable(waiter) and remaining >= 2.0:
                    wait_for = min(12, max(2, int(remaining)))
                    if current_v3:
                        notify(f"USB-Neuanmeldung abwarten · max. {wait_for}s")
                    try:
                        live = str(
                            waiter(
                                port,
                                timeout=wait_for,
                                expected_board=expected_board,
                            )
                            or ""
                        ).strip()
                        if live:
                            last_live = live
                            _emit(
                                f"POSTFLASH RECONNECT logical={port!r} live={live!r} "
                                f"attempt={probe_attempt}"
                            )
                    except Exception as wait_exc:
                        last_error = f"{type(wait_exc).__name__}: {wait_exc}"
                else:
                    waiter_serial = getattr(services, "wait_for_serial", None)
                    if callable(waiter_serial) and remaining >= 2.0:
                        try:
                            waiter_serial(port, timeout=min(8, max(2, int(remaining))))
                        except Exception:
                            pass

            sleep_for = _V3_POSTFLASH_PROBE_INTERVAL if current_v3 else 0.6
            if time.monotonic() < deadline:
                time.sleep(min(sleep_for, max(0.05, deadline - time.monotonic())))

    _emit(
        "POSTFLASH NOT READY "
        f"logical={port!r} live={last_live!r} board={expected_board or ''!r} "
        f"attempts={probe_attempt} last={last_error[:700]!r} flash-retry-after-reset=0"
    )
    if board == "repeater":
        raise services.FlasherError(
            f"POSTFLASH_APPLICATION_NOT_READY: {last_live}: Die V3-Firmware wurde "
            "geschrieben und per Flash-Hash verifiziert, aber der JARNSEN-Dienst "
            f"antwortete innerhalb von {ready_timeout}s nicht stabil. USER/BOOT nicht "
            "halten; RESET einmal kurz drücken, 3–5 Sekunden warten und dann INFO LESEN. "
            "Ein automatisches erneutes Flashen wird absichtlich nicht gestartet."
        )
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
                    require_meshtastic=board != "repeater",
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
                timeout=(
                    _V3_FIRMWARE_ONLY_READY_TIMEOUT
                    if str(board_key).strip().lower() == "repeater"
                    else 90
                ),
                require_jarnsen=True,
                expected_version=version,
                expected_build=build,
                extended_v3_grace=False,
                require_meshtastic=False,
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
        "application-ready-gate=1 raw-service-ready-gate=1 physical-reconnect=1 "
        "v3-postflash-max=60s v3-boot-grace=6s v3-single-shot=1 dtr-rts-safe=1 "
        "v3-firmware-only-max=45s firmware-only-raw-proof=1"
    )
