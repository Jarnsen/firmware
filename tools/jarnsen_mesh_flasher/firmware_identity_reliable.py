from __future__ import annotations

import re
import time
from dataclasses import replace
from typing import Any


_INSTALLED = False


def _emit(message: str) -> None:
    try:
        import diagnostics
        diagnostics._emit(message)
    except Exception:
        pass


def _decode(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _hardware_hint_from_info(text: str) -> str:
    """Extract Meshtastic's PIO environment without another hardware probe."""
    source = str(text or "")
    patterns = (
        r'"pioEnv"\s*:\s*"([^"\r\n]+)"',
        r"\bpioEnv\s*[:=]\s*['\"]?([A-Za-z0-9_.-]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, source, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return ""


def install(services: Any) -> None:
    """Make installed-firmware detection use multiple serialized sources.

    The old dashboard relied on one short raw JARNSEN_TOOL_INFO probe. If that
    happened during reboot, sleep or another serial operation, the UI fell back
    to stale scanner text and could temporarily label a JARNSEN node as VANILLA.
    This wrapper retries the exact local identity first and then performs a fresh
    Meshtastic --info read before giving up.
    """
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    import firmware_status_ui as firmware_status

    base_service_query = services.query_jarnsen_identity
    base_module_query = firmware_status.query_jarnsen_identity

    def query_jarnsen_identity(port: str, timeout: float = 1.8):
        attempts = (max(2.4, float(timeout)), max(3.2, float(timeout)))
        last_identity = None

        for index, attempt_timeout in enumerate(attempts, start=1):
            try:
                identity = base_service_query(port, timeout=attempt_timeout)
                if identity is not None:
                    last_identity = identity
                    if bool(getattr(identity, "is_jarnsen", False)):
                        version = str(getattr(identity, "version", "") or "").strip()
                        build = getattr(identity, "build", None)
                        _emit(
                            f"FIRMWARE IDENTITY RELIABLE raw-ok port={port} attempt={index} "
                            f"version={version!r} build={build!r}"
                        )
                        if version or build is not None:
                            return identity
            except Exception as exc:
                _emit(
                    f"FIRMWARE IDENTITY RELIABLE raw-failed port={port} attempt={index} "
                    f"type={type(exc).__name__} message={str(exc)[:400]!r}"
                )
            if index < len(attempts):
                time.sleep(0.18)

        fresh_text = ""
        try:
            result = services.meshtastic(
                port,
                "--info",
                timeout=28,
                check=False,
            )
            fresh_text = "\n".join(
                part for part in (_decode(result.stdout), _decode(result.stderr)) if part
            )
        except Exception as exc:
            fresh_text = "\n".join(
                part
                for part in (
                    _decode(getattr(exc, "stdout", "")),
                    _decode(getattr(exc, "stderr", "")),
                    _decode(getattr(exc, "output", "")),
                )
                if part
            )
            _emit(
                f"FIRMWARE IDENTITY RELIABLE info-exception port={port} "
                f"type={type(exc).__name__} chars={len(fresh_text)}"
            )

        if fresh_text:
            parsed = firmware_status.parse_installed_firmware(fresh_text)
            hardware_hint = _hardware_hint_from_info(fresh_text)
            if hardware_hint and not str(getattr(parsed, "hardware", "") or "").strip():
                try:
                    parsed = replace(parsed, hardware=hardware_hint)
                    _emit(
                        f"FIRMWARE IDENTITY RELIABLE info-hardware port={port} "
                        f"pio_env={hardware_hint!r} source=same-info"
                    )
                except (TypeError, ValueError):
                    pass
            if bool(getattr(parsed, "is_jarnsen", False)) or str(getattr(parsed, "version", "") or "").strip():
                _emit(
                    f"FIRMWARE IDENTITY RELIABLE info-ok port={port} "
                    f"product={getattr(parsed, 'product', '')!r} edition={getattr(parsed, 'edition', '')!r} "
                    f"version={getattr(parsed, 'version', '')!r} build={getattr(parsed, 'build', None)!r} "
                    f"hardware={getattr(parsed, 'hardware', '')!r}"
                )
                return parsed

        if last_identity is not None:
            _emit(f"FIRMWARE IDENTITY RELIABLE partial-identity port={port}")
            return last_identity

        # Last compatibility attempt uses the original module probe directly.
        # This is kept separate from the service wrapper in case another runtime
        # layer replaced only services.query_jarnsen_identity.
        try:
            identity = base_module_query(port, timeout=max(2.4, float(timeout)))
            if identity is not None:
                _emit(f"FIRMWARE IDENTITY RELIABLE compatibility-ok port={port}")
                return identity
        except Exception as exc:
            _emit(
                f"FIRMWARE IDENTITY RELIABLE compatibility-failed port={port} "
                f"type={type(exc).__name__} message={str(exc)[:400]!r}"
            )

        _emit(f"FIRMWARE IDENTITY RELIABLE no-identity port={port}")
        return None

    query_jarnsen_identity._jarnsen_reliable = True  # type: ignore[attr-defined]
    services.query_jarnsen_identity = query_jarnsen_identity
    firmware_status.query_jarnsen_identity = query_jarnsen_identity
    services._jarnsen_firmware_identity_reliable = True
    services._jarnsen_info_hardware_reuse = True
    _emit(
        "FIRMWARE IDENTITY RELIABLE installed raw-retries=2 fresh-info=1 "
        "module-and-service-hook=1 same-info-hardware=1"
    )
