from __future__ import annotations

import os
from typing import Any

DEFAULT_REFERENCE_VERSION = "2.0.0-alpha.29"
DEFAULT_REFERENCE_BUILD = 181


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


def resolve_reference_bundle(services: Any, board_key: str):
    """Resolve the exact firmware release approved for physical HIL."""
    if board_key not in services.BOARD_PROFILES:
        raise services.FlasherError(f"Nicht unterstütztes HIL-Board: {board_key}")

    version = _reference_version()
    build = _reference_build()
    tag = f"v{version}"
    client = services.GitHubFirmwareClient()
    try:
        release = client._get_json(
            f"{client.api}/repos/{services.REPOSITORY}/releases/tags/{tag}"
        )
    except Exception as exc:
        raise services.FlasherError(
            f"HIL-Referenzrelease {tag} (Build {build}) konnte nicht geladen werden: {exc}"
        ) from exc
    if not isinstance(release, dict):
        raise services.FlasherError(
            f"HIL-Referenzrelease {tag} liefert keine gültigen Release-Metadaten."
        )

    import unified_release_resolver as resolver

    bundle = resolver._release_bundle(client, services, release, board_key)
    actual_version = str(getattr(bundle, "version", "") or "").strip().removeprefix("v")
    actual_build = int(getattr(bundle, "run_number", 0) or 0)
    if actual_version != version or actual_build != build:
        raise services.FlasherError(
            "HIL-Referenz stimmt nicht mit dem aufgelösten Paket überein: "
            f"erwartet={version}/Build {build}, ist={actual_version}/Build {actual_build}."
        )
    return bundle
