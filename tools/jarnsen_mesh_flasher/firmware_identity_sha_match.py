from __future__ import annotations

import re
import threading
import time
from typing import Any


_INSTALLED = False
_SCAN_BY_PORT: dict[str, tuple[str | None, str]] = {}
_DEVICE_BY_PORT: dict[str, Any] = {}
_TRUSTED_BY_PORT: dict[str, Any] = {}
_CACHE: dict[tuple[str, str], tuple[float, Any | None]] = {}
_CACHE_LOCK = threading.Lock()


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _git_sha_from_version(version: str) -> str:
    """Extract Meshtastic's trailing source SHA from e.g. 2.8.0.20f3d4d."""
    value = str(version or "").strip()
    match = re.search(r"(?:^|[.\-+])([0-9a-fA-F]{7,40})$", value)
    return match.group(1).lower() if match else ""


def _artifact_version(name: str) -> str:
    match = re.search(
        r"-v([0-9]+\.[0-9]+\.[0-9]+(?:-(?:alpha|beta|rc)\.\d+)?)-Build-\d+$",
        str(name or ""),
        re.IGNORECASE,
    )
    return match.group(1) if match else ""


def install(services: Any) -> None:
    """Resolve JARNSEN builds from the source SHA already reported by Meshtastic.

    Current Unified-Core images can still expose Meshtastic's legacy
    firmwareEdition=VANILLA / firmwareVersion=2.x.y.<gitsha> metadata. The
    trailing SHA is nevertheless the exact GitHub workflow head used to build
    the JARNSEN image. Once that correlation succeeds the identity becomes
    monotonic for the connected port: later lower-confidence VANILLA scanner
    text must never overwrite a proven JARNSEN product/version/build.
    """

    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    import firmware_status_ui as firmware_status

    base_scan = services.scan_devices
    base_query = services.query_jarnsen_identity

    def _trusted_service_line(identity: Any) -> str:
        hardware = str(getattr(identity, "hardware", "") or "JARNSEN NODE").strip()
        sha = str(getattr(identity, "sha", "") or "").strip()
        build = getattr(identity, "build", None)
        return (
            "===JARNSEN_INFO=== "
            f"product=JARNSEN-MESH version=v{str(getattr(identity, 'version', '') or '').lstrip('vV')} "
            f"build={int(build) if build is not None else 0} hardware={hardware} sha={sha or 'unknown'}"
        )

    def _remember_trusted(port: str, identity: Any) -> Any:
        key_port = str(port or "").upper()
        if not key_port or identity is None or not bool(getattr(identity, "is_jarnsen", False)):
            return identity
        with _CACHE_LOCK:
            _TRUSTED_BY_PORT[key_port] = identity
            device = _DEVICE_BY_PORT.get(key_port)
        if device is not None:
            try:
                current = str(getattr(device, "model_text", "") or "")
                marker = _trusted_service_line(identity)
                lines = [line for line in current.splitlines() if "===JARNSEN_INFO===" not in line]
                enriched = "\n".join(lines + [marker]).strip()
                device.model_text = enriched
                with _CACHE_LOCK:
                    board_key = getattr(device, "board_key", None)
                    _SCAN_BY_PORT[key_port] = (board_key, enriched)
                _emit(
                    f"FIRMWARE IDENTITY TRUSTED port={key_port} product=JARNSEN-MESH "
                    f"version={getattr(identity, 'version', '')!r} build={getattr(identity, 'build', None)!r} "
                    "scanner-model-enriched=1"
                )
            except Exception as exc:
                _emit(
                    f"FIRMWARE IDENTITY TRUSTED ENRICH SKIP port={key_port} "
                    f"type={type(exc).__name__} message={str(exc)[:240]!r}"
                )
        return identity

    def cached_jarnsen_identity(port: str):
        key_port = str(port or "").upper()
        with _CACHE_LOCK:
            return _TRUSTED_BY_PORT.get(key_port)

    def scan_devices(*args: Any, **kwargs: Any):
        devices = base_scan(*args, **kwargs)
        for device in devices:
            try:
                port = str(getattr(device, "port", "") or "").upper()
                if not port:
                    continue
                board_key = getattr(device, "board_key", None)
                model_text = str(getattr(device, "model_text", "") or "")
                with _CACHE_LOCK:
                    _DEVICE_BY_PORT[port] = device
                    trusted = _TRUSTED_BY_PORT.get(port)
                if trusted is not None:
                    marker = _trusted_service_line(trusted)
                    if "===JARNSEN_INFO===" not in model_text:
                        model_text = (model_text.rstrip() + "\n" + marker).strip()
                        try:
                            device.model_text = model_text
                        except Exception:
                            pass
                _SCAN_BY_PORT[port] = (board_key, model_text)
                identity = firmware_status.parse_installed_firmware(model_text)
                sha = _git_sha_from_version(getattr(identity, "version", ""))
                if sha:
                    _emit(
                        f"FIRMWARE SHA SCAN port={port} board={board_key!r} "
                        f"reported={getattr(identity, 'version', '')!r} sha={sha}"
                    )
            except Exception:
                pass
        return devices

    def resolve_from_scan(port: str):
        key_port = str(port or "").upper()
        trusted = cached_jarnsen_identity(key_port)
        if trusted is not None:
            _emit(f"FIRMWARE SHA TRUSTED CACHE port={key_port} hit=1")
            return trusted

        board_key, model_text = _SCAN_BY_PORT.get(key_port, (None, ""))
        if board_key not in services.BOARD_PROFILES or not model_text:
            return None

        reported = firmware_status.parse_installed_firmware(model_text)
        if bool(getattr(reported, "is_jarnsen", False)):
            return _remember_trusted(key_port, reported)

        sha = _git_sha_from_version(str(getattr(reported, "version", "") or ""))
        if not sha:
            return None

        cache_key = (str(board_key), sha)
        now = time.monotonic()
        with _CACHE_LOCK:
            cached = _CACHE.get(cache_key)
            if cached and now - cached[0] < (300.0 if cached[1] is not None else 45.0):
                if cached[1] is not None:
                    return _remember_trusted(key_port, cached[1])
                return None

        profile = services.BOARD_PROFILES[board_key]
        wanted_prefix = str(profile["artifact_prefix"])
        client = services.GitHubFirmwareClient()
        runs = client._get_json(
            f"{client.api}/repos/{services.REPOSITORY}/actions/runs",
            branch=services.UNIFIED_BRANCH,
            status="success",
            per_page=50,
        ).get("workflow_runs", [])

        matched = None
        for run in runs:
            if str(run.get("head_branch") or "") != services.UNIFIED_BRANCH:
                continue
            if str(run.get("path") or "") != services.UNIFIED_WORKFLOW_PATH:
                continue
            head_sha = str(run.get("head_sha") or "").strip().lower()
            if not head_sha or not head_sha.startswith(sha):
                continue

            run_id = int(run.get("id") or 0)
            artifacts = client._get_json(
                f"{client.api}/repos/{services.REPOSITORY}/actions/runs/{run_id}/artifacts",
                per_page=100,
            ).get("artifacts", [])
            artifact = next(
                (
                    item
                    for item in artifacts
                    if not item.get("expired")
                    and str(item.get("name") or "").startswith(wanted_prefix)
                ),
                None,
            )
            if artifact is None:
                continue

            artifact_name = str(artifact.get("name") or "")
            version = _artifact_version(artifact_name)
            build = int(run.get("run_number") or 0)
            if not version or build <= 0:
                continue

            matched = firmware_status.FirmwareIdentity(
                product="JARNSEN-MESH",
                version=version,
                build=build,
                edition="JARNSEN-MESH",
                hardware=str(profile.get("label") or board_key),
                sha=head_sha,
            )
            _emit(
                f"FIRMWARE SHA MATCH port={key_port} board={board_key} sha={sha} "
                f"run={run_id} version={version!r} build={build}"
            )
            break

        with _CACHE_LOCK:
            _CACHE[cache_key] = (time.monotonic(), matched)
        if matched is None:
            _emit(
                f"FIRMWARE SHA NO-MATCH port={key_port} board={board_key} sha={sha} "
                "fallback=raw-identity"
            )
            return None
        return _remember_trusted(key_port, matched)

    def query_jarnsen_identity(port: str, timeout: float = 1.8):
        try:
            identity = resolve_from_scan(port)
            if identity is not None:
                return identity
        except Exception as exc:
            _emit(
                f"FIRMWARE SHA LOOKUP FAILED port={port} type={type(exc).__name__} "
                f"message={str(exc)[:400]!r} fallback=raw-identity"
            )
        result = base_query(port, timeout=timeout)
        if result is not None and bool(getattr(result, "is_jarnsen", False)):
            return _remember_trusted(port, result)
        trusted = cached_jarnsen_identity(port)
        if trusted is not None:
            _emit(f"FIRMWARE IDENTITY DOWNGRADE BLOCKED port={str(port or '').upper()} source=raw-fallback")
            return trusted
        return result

    services.scan_devices = scan_devices
    services.query_jarnsen_identity = query_jarnsen_identity
    firmware_status.query_jarnsen_identity = query_jarnsen_identity
    services.resolve_jarnsen_identity_from_scan = resolve_from_scan
    services.cached_jarnsen_identity = cached_jarnsen_identity
    services._jarnsen_firmware_identity_sha_match = True
    _emit(
        "FIRMWARE IDENTITY SHA MATCH installed scan-cache=1 github-run-correlation=1 "
        "exact-version-build=1 slow-second-info-avoided=1 monotonic-trusted-cache=1"
    )
