from __future__ import annotations

import re
import threading
import time
from typing import Any


_INSTALLED = False
_VERIFIED_RAW_IDENTITIES: set[tuple[str, str, str, str]] = set()


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _key(port: str) -> str:
    return str(port or "").strip().upper()


def _identity_key(identity: Any) -> tuple[str, str, str, str]:
    return (
        str(getattr(identity, "product", "") or "").strip().casefold(),
        str(getattr(identity, "edition", "") or "").strip().casefold(),
        str(getattr(identity, "version", "") or "").strip().casefold(),
        str(getattr(identity, "hardware", "") or "").strip().casefold(),
    )


def _looks_like_unverified_git_build(identity: Any) -> bool:
    if identity is None or bool(getattr(identity, "is_jarnsen", False)):
        return False
    product = str(getattr(identity, "product", "") or "").strip().casefold()
    edition = str(getattr(identity, "edition", "") or "").strip().casefold()
    version = str(getattr(identity, "version", "") or "").strip()
    raw_kind = f"{product} {edition}"
    if "vanilla" not in raw_kind and "meshtastic" not in raw_kind:
        return False
    return bool(re.search(r"(?:^|[.\-+])[0-9a-fA-F]{7,40}$", version))


def _should_reuse_preflight(thread_name: str, record_kind: str) -> bool:
    name = str(thread_name or "").strip().casefold()
    kind = str(record_kind or "").strip().casefold()
    return kind == "profile_only" or name.startswith("jarnsen-profile-only")


def _selected_port(app: Any) -> str:
    try:
        device = app._selected_device()
    except Exception:
        device = None
    return _key(getattr(device, "port", "")) if device is not None else ""


def install(services: Any) -> None:
    """Harden profile-only serial use and keep firmware identity UI coherent."""
    global _INSTALLED
    if _INSTALLED or getattr(services, "_jarnsen_review_team_hardening", False):
        return
    _INSTALLED = True

    import firmware_identity_sha_match as identity_cache
    import firmware_status_ui as status
    import profile_runtime_stability_v2 as profile_v2
    import radio_profile_node_sync as node_sync
    import radio_profiles
    import reference_dashboard

    # A proven JARNSEN identity must remain monotonic while the same node remains
    # connected. Four seconds was shorter than one normal UI/scan cycle.
    identity_cache._TRUSTED_TTL = max(
        float(getattr(identity_cache, "_TRUSTED_TTL", 0.0)), 300.0
    )

    base_query = services.query_jarnsen_identity
    base_display = status._installed_display

    def query_jarnsen_identity(port: str, timeout: float = 1.8):
        identity = base_query(port, timeout=timeout)
        if identity is not None and not bool(getattr(identity, "is_jarnsen", False)):
            _VERIFIED_RAW_IDENTITIES.add(_identity_key(identity))
            _emit(
                f"REVIEW IDENTITY RAW VERIFIED port={_key(port)} "
                f"edition={getattr(identity, 'edition', '')!r} "
                f"version={getattr(identity, 'version', '')!r}"
            )
        return identity

    def installed_display(identity: Any) -> str:
        # Do not advertise low-confidence raw VANILLA metadata while its embedded
        # Git SHA is still being correlated against JARNSEN releases.
        if (
            _looks_like_unverified_git_build(identity)
            and _identity_key(identity) not in _VERIFIED_RAW_IDENTITIES
        ):
            return "Firmware wird verifiziert ..."
        return base_display(identity)

    services.query_jarnsen_identity = query_jarnsen_identity
    status.query_jarnsen_identity = query_jarnsen_identity
    status._installed_display = installed_display

    # reference_dashboard imports these symbols directly. Rebinding only the
    # source module leaves stale function objects in the dashboard and produces
    # the exact field symptom: log says Build 167 while the banner says VANILLA.
    reference_dashboard.query_jarnsen_identity = query_jarnsen_identity
    reference_dashboard._installed_display = installed_display

    # Keep a verified per-port banner from being downgraded by the synchronous
    # fallback parse at the beginning of the next asynchronous refresh.
    base_build_dashboard = reference_dashboard._build_dashboard

    def build_dashboard(app: Any, runtime_services: Any) -> None:
        base_build_dashboard(app, runtime_services)
        variable = getattr(app, "installed_firmware_var", None)
        if variable is None or getattr(app, "_jarnsen_identity_banner_guard", False):
            return

        verified_by_port: dict[str, str] = {}
        reentry = {"active": False}

        def keep_verified_banner(*_args: Any) -> None:
            if reentry["active"]:
                return
            port = _selected_port(app)
            if not port:
                return
            try:
                value = str(variable.get() or "")
            except Exception:
                return

            upper = value.upper()
            if "JARNSEN-MESH" in upper and "BUILD" in upper:
                verified_by_port[port] = value
                return

            trusted = verified_by_port.get(port)
            if trusted and (
                "VANILLA" in upper or "FIRMWARE WIRD VERIFIZIERT" in upper
            ):
                reentry["active"] = True
                try:
                    variable.set(trusted)
                finally:
                    reentry["active"] = False
                _emit(
                    f"REVIEW IDENTITY BANNER HOLD port={port} action=keep-verified "
                    "fallback-overwrite=blocked"
                )

        try:
            variable.trace_add("write", keep_verified_banner)
            app._jarnsen_identity_banner_guard = True
            app._jarnsen_identity_banner_verified_by_port = verified_by_port
        except Exception as exc:
            _emit(
                "REVIEW IDENTITY BANNER GUARD WARNING "
                f"type={type(exc).__name__} message={str(exc)[:240]!r}"
            )

    reference_dashboard._build_dashboard = build_dashboard

    # Reuse the role/name preflight result for the immediately following board
    # check. Accept both the historical worker name and an active profile-only
    # transaction; never reuse while the choice reader itself is taking a snapshot.
    base_meshtastic = services.meshtastic

    def meshtastic(port: str, *args: str, **kwargs: Any):
        is_info = tuple(str(value) for value in args) == ("--info",)
        if is_info and not bool(getattr(profile_v2._CHOICE_READ, "active", False)):
            key = _key(port)
            cached = profile_v2._PREFLIGHT_INFO.get(key)
            if cached is not None:
                age = time.monotonic() - float(cached[0])
                if age <= 45.0:
                    record = profile_v2._record(services, port)
                    record_kind = (
                        str(getattr(record, "kind", "") or "")
                        if record is not None
                        else ""
                    )
                    thread_name = threading.current_thread().name
                    if _should_reuse_preflight(thread_name, record_kind):
                        profile_v2._PREFLIGHT_INFO.pop(key, None)
                        _emit(
                            f"REVIEW PROFILE PREFLIGHT REUSE port={port} age={age:.2f}s "
                            f"thread={thread_name!r} record={record_kind!r} second-info=0"
                        )
                        return cached[1]
                else:
                    profile_v2._PREFLIGHT_INFO.pop(key, None)
                    _emit(
                        f"REVIEW PROFILE PREFLIGHT EXPIRED port={port} age={age:.2f}s"
                    )
        return base_meshtastic(port, *args, **kwargs)

    services.meshtastic = meshtastic

    # The normal profile-only write already exported the complete current node
    # configuration successfully. Do not immediately seize the same COM port with
    # optional JARNSEN_TOOL_RADIO_INFO probes. The Flasher's persisted selected
    # radio profile is authoritative for the requested operation. J1/J2 selection
    # is still applied later by the existing slot-selection path when required.
    base_read_active_profile = node_sync._read_active_profile

    def read_active_profile(port: str, runtime_services: Any) -> str:
        record = profile_v2._record(runtime_services, port)
        kind = str(getattr(record, "kind", "") or "") if record is not None else ""
        if kind != "profile_only":
            return base_read_active_profile(port, runtime_services)

        selected = radio_profiles.PROFILE_STANDARD
        try:
            settings = dict(runtime_services.load_radio_profile_settings())
            candidate = str(settings.get("selected") or "").strip().lower()
            if candidate in radio_profiles.PROFILE_KEYS:
                selected = candidate
        except Exception as exc:
            _emit(
                f"REVIEW PROFILE RADIO SETTINGS FALLBACK port={port} "
                f"type={type(exc).__name__} selected=standard"
            )

        _emit(
            f"REVIEW PROFILE RADIO PREFLIGHT port={port} selected={selected} "
            "source=flasher-settings raw-radio-info=0 serial-reopen=0"
        )
        return selected

    node_sync._read_active_profile = read_active_profile

    # Startup invariants make wrong install order or stale direct imports a hard
    # CI/source-smoke failure instead of another field-only regression.
    if float(identity_cache._TRUSTED_TTL) < 300.0:
        raise RuntimeError("Review identity cache hardening is not active")
    if not getattr(services, "_jarnsen_profile_export_completion_fix", False):
        raise RuntimeError("Profile export completion watcher is not active")
    if reference_dashboard.query_jarnsen_identity is not query_jarnsen_identity:
        raise RuntimeError("Dashboard identity query was not rebound")
    if reference_dashboard._installed_display is not installed_display:
        raise RuntimeError("Dashboard identity display was not rebound")
    if not _should_reuse_preflight("jarnsen-profile-only", ""):
        raise RuntimeError("Profile preflight thread fallback self-check failed")
    if not _should_reuse_preflight("worker", "profile_only"):
        raise RuntimeError("Profile preflight transaction fallback self-check failed")

    probe = status.FirmwareIdentity(
        product="VANILLA", edition="VANILLA", version="2.8.0.ff63f24"
    )
    if installed_display(probe) != "Firmware wird verifiziert ...":
        raise RuntimeError("Provisional firmware identity display self-check failed")

    services._jarnsen_review_team_hardening = True
    services._jarnsen_identity_monotonic_300s = True
    services._jarnsen_profile_preflight_reuse_contextual = True
    services._jarnsen_provisional_identity_display = True
    services._jarnsen_dashboard_identity_rebound = True
    services._jarnsen_profile_radio_raw_preflight_skipped = True
    _emit(
        "REVIEW TEAM HARDENING installed identity-ttl=300s provisional-vanilla=1 "
        "dashboard-direct-bindings=updated banner-monotonic-per-port=1 "
        "preflight-reuse-contextual=1 profile-radio-info-raw=0 "
        "export-watcher-required=1"
    )
