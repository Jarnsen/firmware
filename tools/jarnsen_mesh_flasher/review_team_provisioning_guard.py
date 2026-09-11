from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Callable

import yaml


_INSTALLED = False
_ROLE_INFO_CACHE: dict[str, str] = {}


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _key(port: str) -> str:
    return str(port or "").strip().upper()


def _guarded_probe_role_api(
    runtime_services: Any,
    provisioning: Any,
    base_probe: Callable[..., tuple[bool, Any | None]],
    base_raw: Callable[..., str],
    port: str,
    role_key: str,
) -> tuple[bool, Any | None]:
    """Verify Build-168+ capability through ROLE_INFO and recover one stale boot.

    ROLE_INFO is stronger evidence for role_api=1 than TOOL_INFO because it
    exercises the exact persistent-role service that is needed next. A freshly
    flashed native-USB ESP32 can still be emitting boot output when the profile
    stage starts; in that case perform exactly one controlled reboot, wait for a
    proven USB return, and retry. The safety contract stays strict: no role API
    means no profile write on Build 168+.
    """
    build_hint = int(provisioning._cached_build_hint(runtime_services, port) or 0)
    strict = build_hint >= 168 or str(role_key or "").strip().lower() == "drone_repeater"
    if not strict:
        return base_probe(runtime_services, port, role_key)

    def role_info() -> str:
        return base_raw(
            port,
            "JARNSEN_TOOL_ROLE_INFO",
            expected="===JARNSEN_ROLE===",
            timeout=3.0,
            attempts=1,
            services=runtime_services,
        )

    try:
        line = role_info()
        recovered = False
    except Exception as first_exc:
        _emit(
            f"PROVISION GUARD ROLE API WAIT port={port} build={build_hint or 'unknown'} "
            f"role={role_key} first={type(first_exc).__name__} action=single-reboot"
        )
        try:
            runtime_services.reboot_node(port)
            provisioning._adaptive_settle_auto_reboot(
                runtime_services,
                port,
                "role-api-readiness",
                wait_seconds=20,
                stage="Rollendienst vorbereiten",
                explicit_reboot=True,
            )
            line = role_info()
            recovered = True
        except Exception as retry_exc:
            raise runtime_services.FlasherError(
                "Die installierte Unified-Core-Firmware konnte den persistenten "
                "JARNSEN-Rollendienst (role_api=1) auch nach einem kontrollierten "
                "Neustart nicht bestätigen."
            ) from retry_exc

    data = provisioning._parse_role_info(line)
    if data.get("role_api") != "1":
        raise runtime_services.FlasherError(
            "Die aktuelle Firmware antwortet auf ROLE_INFO, meldet aber role_api=1 nicht. "
            "Der Profilvorgang wurde aus Sicherheitsgründen abgebrochen."
        )

    _ROLE_INFO_CACHE[_key(port)] = line
    _emit(
        f"PROVISION GUARD ROLE API READY port={port} build={build_hint or 'unknown'} "
        f"role={role_key} direct-role-info=1 reboot-recovery={int(recovered)} cached-next-read=1"
    )
    return True, None


def install(services: Any) -> None:
    """Final correctness and boot-readiness guard for Provisioning V2.

    Owner/short name are deliberately issued as CLI switches before --configure.
    Remove them only from the temporary YAML handed to --configure so Meshtastic
    does not call setOwner a second time inside the settings transaction.
    """
    global _INSTALLED
    if _INSTALLED or getattr(services, "_jarnsen_review_team_provisioning_guard", False):
        return
    _INSTALLED = True

    import profile_restore
    import review_team_provisioning_v2 as provisioning

    base_stream = profile_restore._stream_configure

    def stream_configure(
        runtime_services: Any,
        port: str,
        profile_path: Path,
        profile_data: dict[str, Any],
        **kwargs: Any,
    ):
        owner = str(profile_data.get("owner") or "").strip()
        owner_short = str(profile_data.get("owner_short") or "").strip()
        if not owner and not owner_short:
            return base_stream(runtime_services, port, profile_path, profile_data, **kwargs)

        configure_data = copy.deepcopy(profile_data)
        configure_data.pop("owner", None)
        configure_data.pop("owner_short", None)
        configure_data.pop("ownerShort", None)

        work_root = Path(runtime_services.PATHS.root) / "restore-work"
        work_root.mkdir(parents=True, exist_ok=True)
        stripped_path = work_root / f"{_key(port)}-configure-without-owner.yaml"
        stripped_path.write_text(
            yaml.safe_dump(configure_data, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        _emit(
            f"PROVISION V2 OWNER SPLIT port={port} long={int(bool(owner))} short={int(bool(owner_short))} "
            "cli-before-configure=1 yaml-owner-fields=0 duplicate-owner-write=0"
        )
        try:
            # Keep the original profile_data for progress accounting and for the
            # Provisioning-V2 stream to build --set-owner/--set-owner-short.
            return base_stream(runtime_services, port, stripped_path, profile_data, **kwargs)
        finally:
            try:
                stripped_path.unlink(missing_ok=True)
            except Exception:
                pass

    profile_restore._stream_configure = stream_configure

    # Build 168+ is strict, but TOOL_INFO is not the correct readiness gate.
    # Probe the actual role service instead. Reuse that exact ROLE_INFO reply in
    # _sync_firmware_role so the stronger check does not cost another serial pass.
    base_probe_role_api = provisioning._probe_role_api
    base_raw_command = provisioning._raw_command

    def raw_command_guard(
        port: str,
        command: str,
        *,
        expected: str,
        timeout: float,
        attempts: int = 2,
        services: Any | None = None,
    ) -> str:
        if str(command or "").strip().upper() == "JARNSEN_TOOL_ROLE_INFO":
            cached = _ROLE_INFO_CACHE.pop(_key(port), None)
            if cached is not None and expected in cached:
                _emit(f"PROVISION GUARD ROLE INFO REUSE port={port} source=capability-probe")
                return cached
        return base_raw_command(
            port,
            command,
            expected=expected,
            timeout=timeout,
            attempts=attempts,
            services=services,
        )

    def probe_role_api_guard(runtime_services: Any, port: str, role_key: str):
        return _guarded_probe_role_api(
            runtime_services,
            provisioning,
            base_probe_role_api,
            base_raw_command,
            port,
            role_key,
        )

    provisioning._raw_command = raw_command_guard
    provisioning._probe_role_api = probe_role_api_guard

    # The fast identity cache exists only to remove repeated final verification
    # probes. A real firmware flash is the hard invalidation boundary.
    base_flash_bundle = services.flash_bundle

    def flash_bundle(port: str, *args: Any, **kwargs: Any):
        key = _key(port)
        provisioning._FAST_IDENTITY_BY_PORT.pop(key, None)
        provisioning._EXPECTED_JARNSEN_ROLE_BY_PORT.pop(key, None)
        _ROLE_INFO_CACHE.pop(key, None)
        try:
            return base_flash_bundle(port, *args, **kwargs)
        finally:
            provisioning._FAST_IDENTITY_BY_PORT.pop(key, None)
            _ROLE_INFO_CACHE.pop(key, None)

    services.flash_bundle = flash_bundle
    services._jarnsen_review_team_provisioning_guard = True
    services._jarnsen_owner_single_write = True
    services._jarnsen_fast_identity_flash_invalidated = True
    services._jarnsen_role_api_boot_recovery = True
    services._jarnsen_role_info_capability_probe = True
    _emit(
        "REVIEW TEAM PROVISIONING GUARD installed owner-single-write=1 "
        "owner-before-configure=1 fast-identity-flash-invalidate=1 "
        "role-info-capability=1 role-api-single-reboot-recovery=1 role-info-reuse=1"
    )
