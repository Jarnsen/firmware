from __future__ import annotations

import os
from typing import Any

DEFAULT_REFERENCE_VERSION = "2.0.0-alpha.31"
DEFAULT_REFERENCE_BUILD = 185
DEFAULT_REFERENCE_SHA = "6c2cb31dea29981efc3e19460ed23d5e7b5d227d"


def _reference_version() -> str:
    return (
        os.environ.get("JARNSEN_HIL_REFERENCE_VERSION", DEFAULT_REFERENCE_VERSION)
        .strip()
        .removeprefix("v")
    )


def _reference_build() -> int:
    raw = os.environ.get(
        "JARNSEN_HIL_REFERENCE_BUILD", str(DEFAULT_REFERENCE_BUILD)
    ).strip()
    try:
        build = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"Ungültiger HIL-Referenz-Build: {raw!r}") from exc
    if build <= 0:
        raise RuntimeError(f"Ungültiger HIL-Referenz-Build: {build}")
    return build


def _reference_sha() -> str:
    value = (
        os.environ.get("JARNSEN_HIL_REFERENCE_SHA", DEFAULT_REFERENCE_SHA)
        .strip()
        .lower()
    )
    if len(value) != 40 or any(ch not in "0123456789abcdef" for ch in value):
        raise RuntimeError(f"Ungültiger HIL-Referenz-SHA: {value!r}")
    return value


def resolve_reference_bundle(services: Any, board_key: str):
    """Resolve the exact firmware release approved for physical HIL."""
    if board_key not in services.BOARD_PROFILES:
        raise services.FlasherError(f"Nicht unterstütztes HIL-Board: {board_key}")

    version = _reference_version()
    build = _reference_build()
    source_sha = _reference_sha()
    tag = f"v{version}"
    client = services.GitHubFirmwareClient()
    try:
        release = client._get_json(
            f"{client.api}/repos/{services.REPOSITORY}/releases/tags/{tag}"
        )
    except Exception as exc:
        raise services.FlasherError(
            f"HIL-Referenzrelease {tag} (Build {build}, SHA {source_sha}) "
            f"konnte nicht geladen werden: {exc}"
        ) from exc
    if not isinstance(release, dict):
        raise services.FlasherError(
            f"HIL-Referenzrelease {tag} liefert keine gültigen Release-Metadaten."
        )

    actual_sha = str(release.get("target_commitish") or "").strip().lower()
    if actual_sha != source_sha:
        raise services.FlasherError(
            "HIL-Referenzrelease zeigt auf den falschen Quellstand: "
            f"erwartet={source_sha}, ist={actual_sha or '<leer>'}."
        )

    import unified_release_resolver as resolver

    bundle = resolver._release_bundle(client, services, release, board_key)
    actual_version = str(getattr(bundle, "version", "") or "").strip().removeprefix("v")
    actual_build = int(getattr(bundle, "run_number", 0) or 0)
    if actual_version != version or actual_build != build:
        raise services.FlasherError(
            "HIL-Referenz stimmt nicht mit dem aufgelösten Paket überein: "
            f"erwartet={version}/Build {build}/SHA {source_sha}, "
            f"ist={actual_version}/Build {actual_build}/SHA {actual_sha}."
        )
    return bundle
