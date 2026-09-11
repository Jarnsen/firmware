from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml


_INSTALLED = False


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _key(port: str) -> str:
    return str(port or "").strip().upper()


def install(services: Any) -> None:
    """Final correctness guard for Provisioning V2.

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

    # The fast identity cache exists only to remove repeated final verification
    # probes. A real firmware flash is the hard invalidation boundary.
    base_flash_bundle = services.flash_bundle

    def flash_bundle(port: str, *args: Any, **kwargs: Any):
        key = _key(port)
        provisioning._FAST_IDENTITY_BY_PORT.pop(key, None)
        provisioning._EXPECTED_JARNSEN_ROLE_BY_PORT.pop(key, None)
        try:
            return base_flash_bundle(port, *args, **kwargs)
        finally:
            provisioning._FAST_IDENTITY_BY_PORT.pop(key, None)

    services.flash_bundle = flash_bundle
    services._jarnsen_review_team_provisioning_guard = True
    services._jarnsen_owner_single_write = True
    services._jarnsen_fast_identity_flash_invalidated = True
    _emit(
        "REVIEW TEAM PROVISIONING GUARD installed owner-single-write=1 "
        "owner-before-configure=1 fast-identity-flash-invalidate=1"
    )
