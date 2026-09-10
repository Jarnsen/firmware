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


def install(services: Any) -> None:
    """Late review-team hardening for profile-only and firmware identity UX.

    This layer intentionally sits last. It does not change firmware contents; it
    only stabilizes the Flasher's interpretation and serial workflow.
    """
    global _INSTALLED
    if _INSTALLED or getattr(services, "_jarnsen_review_team_hardening", False):
        return
    _INSTALLED = True

    import firmware_identity_sha_match as identity_cache
    import firmware_status_ui as status
    import profile_runtime_stability_v2 as profile_v2

    # A proven JARNSEN identity must remain monotonic while the same node remains
    # connected. Four seconds was shorter than one normal UI/scan cycle and could
    # visibly downgrade Build 167 back to VANILLA metadata. The scanner already
    # invalidates trusted identities on disconnect and flash operations.
    identity_cache._TRUSTED_TTL = max(float(getattr(identity_cache, "_TRUSTED_TTL", 0.0)), 300.0)

    base_query = services.query_jarnsen_identity
    base_display = status._installed_display

    def query_jarnsen_identity(port: str, timeout: float = 1.8):
        identity = base_query(port, timeout=timeout)
        if identity is not None and not bool(getattr(identity, "is_jarnsen", False)):
            _VERIFIED_RAW_IDENTITIES.add(_identity_key(identity))
            _emit(
                f"REVIEW IDENTITY RAW VERIFIED port={_key(port)} "
                f"edition={getattr(identity, 'edition', '')!r} version={getattr(identity, 'version', '')!r}"
            )
        return identity

    def installed_display(identity: Any) -> str:
        # During the asynchronous SHA/release check, do not present low-confidence
        # legacy VANILLA metadata as a final fact. If correlation really fails,
        # query_jarnsen_identity marks that raw identity as verified and the normal
        # VANILLA display is then allowed.
        if (
            _looks_like_unverified_git_build(identity)
            and _identity_key(identity) not in _VERIFIED_RAW_IDENTITIES
        ):
            return "Firmware wird verifiziert …"
        return base_display(identity)

    services.query_jarnsen_identity = query_jarnsen_identity
    status.query_jarnsen_identity = query_jarnsen_identity
    status._installed_display = installed_display

    # Reuse the role/name preflight result for the immediately following board
    # check. Older code depended only on one exact worker-thread name. Keep that
    # fast path, but also accept an authoritative active profile_only transaction.
    # Never reuse while the choice reader itself is collecting a fresh snapshot.
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
                    record_kind = str(getattr(record, "kind", "") or "") if record is not None else ""
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
                    _emit(f"REVIEW PROFILE PREFLIGHT EXPIRED port={port} age={age:.2f}s")
        return base_meshtastic(port, *args, **kwargs)

    services.meshtastic = meshtastic

    # Startup invariants: source/frozen GUI smoke imports the same runtime stack,
    # so a missing prerequisite or accidental layer-order regression fails CI.
    if float(identity_cache._TRUSTED_TTL) < 300.0:
        raise RuntimeError("Review identity cache hardening is not active")
    if not getattr(services, "_jarnsen_profile_export_completion_fix", False):
        raise RuntimeError("Profile export completion watcher is not active")
    if not _should_reuse_preflight("jarnsen-profile-only", ""):
        raise RuntimeError("Profile preflight thread fallback self-check failed")
    if not _should_reuse_preflight("worker", "profile_only"):
        raise RuntimeError("Profile preflight transaction fallback self-check failed")

    probe = status.FirmwareIdentity(product="VANILLA", edition="VANILLA", version="2.8.0.ff63f24")
    if installed_display(probe) != "Firmware wird verifiziert …":
        raise RuntimeError("Provisional firmware identity display self-check failed")

    services._jarnsen_review_team_hardening = True
    services._jarnsen_identity_monotonic_300s = True
    services._jarnsen_profile_preflight_reuse_contextual = True
    services._jarnsen_provisional_identity_display = True
    _emit(
        "REVIEW TEAM HARDENING installed identity-ttl=300s provisional-vanilla=1 "
        "verified-raw-fallback=1 preflight-reuse-thread=1 preflight-reuse-transaction=1 "
        "export-watcher-required=1"
    )
