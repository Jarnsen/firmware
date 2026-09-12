from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

_MANIFEST_SUFFIX = "-package-manifest.json"
_SUMS_SUFFIX = "-SHA256SUMS.txt"
_SIZE_LIMITS = {
    "manifest": (80, 1024 * 1024),
    "checksums": (64, 1024 * 1024),
    "update": (128 * 1024, 8 * 1024 * 1024),
    "factory": (256 * 1024, 32 * 1024 * 1024),
    "meshtastic-webflasher": (256 * 1024, 32 * 1024 * 1024),
    "uf2": (64 * 1024, 16 * 1024 * 1024),
}


class _LegacyReleaseRequired(RuntimeError):
    """No package manifest exists, so the pre-Unified resolver may be used."""


class _ReleaseLookupUnavailable(RuntimeError):
    """GitHub Releases could not be queried; the existing Actions path may retry."""


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _plain_version(value: Any) -> str:
    return str(value or "").strip().removeprefix("v")


def _release_key(
    release: dict[str, Any], base_version: str
) -> tuple[int, int, int, int]:
    """Order alpha < beta < rc < stable without pinning a particular release."""
    version = _plain_version(release.get("tag_name") or release.get("name"))
    match = re.fullmatch(
        rf"{re.escape(base_version)}(?:-(alpha|beta|rc)(?:[.-]?(\d+))?)?",
        version,
        re.IGNORECASE,
    )
    if not match:
        return (-1, -1, -1, -1)
    channel = (match.group(1) or "stable").lower()
    rank = {"alpha": 0, "beta": 1, "rc": 2, "stable": 3}[channel]
    sequence = int(match.group(2) or 0)
    build_match = re.search(
        r"(?i)\bBuild\s*[-#]?\s*(\d+)", str(release.get("name") or "")
    )
    build = int(build_match.group(1)) if build_match else 0
    release_id = int(release.get("id") or 0)
    return (rank, sequence, build, release_id)


def _asset_digest(asset: dict[str, Any]) -> str | None:
    digest = str(asset.get("digest") or "").strip().lower()
    match = re.fullmatch(r"sha256:([0-9a-f]{64})", digest)
    return match.group(1) if match else None


def _asset_by_name(
    services: Any, assets: list[dict[str, Any]], name: str
) -> dict[str, Any]:
    matches = [
        item for item in assets if str(item.get("name") or "").lower() == name.lower()
    ]
    if len(matches) != 1:
        raise services.FlasherError(
            f"Release-Datei {name} ist nicht eindeutig vorhanden ({len(matches)} Treffer)."
        )
    return matches[0]


def _variant_asset_name(prefix: str, variant: str) -> str:
    suffixes = {
        "update": "-update.bin",
        "factory": "-factory.bin",
        "meshtastic-webflasher": "-meshtastic-webflasher.bin",
        "webflasher": "-webflasher.bin",
        "uf2": "-firmware.uf2",
    }
    return prefix + suffixes[variant]


def _validate_manifest(
    services: Any,
    manifest: dict[str, Any],
    *,
    board_key: str,
    release_version: str,
) -> tuple[int, tuple[str, ...], str]:
    if (
        manifest.get("schema") != 1
        or str(manifest.get("product") or "") != "JARNSEN-MESH"
    ):
        raise services.FlasherError(
            "Release enthält kein gültiges Unified-Core-Manifest (Schema/Produkt)."
        )
    profile = services.BOARD_PROFILES[board_key]
    actual_env = str(manifest.get("platformio_environment") or "").strip()
    expected_env = str(profile.get("pio_env") or "").strip()
    if actual_env != expected_env:
        raise services.FlasherError(
            f"Firmware gehört zu {actual_env or 'unbekannt'}, angeschlossen ist {expected_env}."
        )
    manifest_version = _plain_version(manifest.get("version"))
    if manifest_version != release_version or not manifest_version.startswith(
        services.JARNSEN_BASE_VERSION
    ):
        raise services.FlasherError(
            f"Manifest-Version {manifest_version or 'unbekannt'} passt nicht zum Release {release_version}."
        )
    try:
        build = int(manifest.get("build"))
    except (TypeError, ValueError) as exc:
        raise services.FlasherError(
            "Unified-Core-Manifest enthält keine gültige Buildnummer."
        ) from exc
    if build <= 0:
        raise services.FlasherError(
            "Unified-Core-Manifest enthält keine gültige Buildnummer."
        )
    raw_variants = manifest.get("variants")
    if not isinstance(raw_variants, list):
        raise services.FlasherError(
            "Unified-Core-Manifest enthält keine Variantenliste."
        )
    variants = tuple(str(item or "").strip().lower() for item in raw_variants)
    allowed = {"update", "factory", "meshtastic-webflasher", "webflasher", "uf2"}
    if (
        not variants
        or len(set(variants)) != len(variants)
        or any(item not in allowed for item in variants)
    ):
        raise services.FlasherError(
            "Unified-Core-Manifest enthält ungültige Firmwarevarianten."
        )
    kind = str(profile.get("artifact_kind") or "esp32").lower()
    required = {"uf2"} if kind == "uf2" else {"update", "factory"}
    if not required.issubset(variants):
        missing = ", ".join(sorted(required.difference(variants)))
        raise services.FlasherError(
            f"Manifest enthält die benötigte Firmwarevariante nicht: {missing}."
        )
    if kind == "uf2" and set(variants) != {"uf2"}:
        raise services.FlasherError("Wio-Manifest mischt UF2 mit ESP32-Firmwaretypen.")
    source_sha = str(manifest.get("source_sha") or "").strip().lower()
    if source_sha and not re.fullmatch(r"[0-9a-f]{7,40}", source_sha):
        raise services.FlasherError(
            "Unified-Core-Manifest enthält eine ungültige Quell-SHA."
        )
    return build, variants, source_sha


def _validate_declared_asset(services: Any, asset: dict[str, Any], role: str) -> None:
    try:
        size = int(asset.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    low, high = _SIZE_LIMITS[role]
    if size < low or size > high:
        raise services.FlasherError(
            f"Firmwaregröße für {asset.get('name') or role} ist unzulässig ({size} Bytes)."
        )
    if str(asset.get("state") or "uploaded") != "uploaded":
        raise services.FlasherError(
            f"GitHub-Asset {asset.get('name') or role} ist nicht vollständig hochgeladen."
        )


def _download_asset(
    client: Any, services: Any, asset: dict[str, Any], destination: Path, role: str
) -> Path:
    _validate_declared_asset(services, asset, role)
    expected_size = int(asset["size"])
    expected_sha = _asset_digest(asset)
    if destination.exists():
        if destination.stat().st_size == expected_size and (
            expected_sha is None or services._sha256(destination) == expected_sha
        ):
            return destination
        destination.unlink(missing_ok=True)

    partial = destination.with_suffix(destination.suffix + ".part")
    last_error: Exception | None = None
    for attempt in range(1, 4):
        response = None
        try:
            partial.unlink(missing_ok=True)
            response = client._request(
                "GET",
                str(asset.get("url") or ""),
                headers={"Accept": "application/octet-stream"},
                stream=True,
            )
            with partial.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        handle.write(chunk)
            actual_size = partial.stat().st_size if partial.exists() else 0
            if actual_size != expected_size:
                raise services.FlasherError(
                    f"Downloadgröße stimmt nicht: {asset['name']} ({actual_size}/{expected_size} Bytes)."
                )
            actual_sha = services._sha256(partial)
            if expected_sha and actual_sha != expected_sha:
                raise services.FlasherError(
                    f"SHA-256-Prüfung fehlgeschlagen: {asset['name']}"
                )
            partial.replace(destination)
            return destination
        except Exception as exc:
            last_error = exc
            partial.unlink(missing_ok=True)
            if attempt < 3:
                time.sleep(float(attempt))
        finally:
            if response is not None:
                response.close()
    raise services.FlasherError(
        f"GitHub-Release-Download nach drei Versuchen fehlgeschlagen: {asset.get('name')}: {last_error}"
    ) from last_error


def _release_bundle(
    client: Any, services: Any, release: dict[str, Any], board_key: str
):
    profile = services.BOARD_PROFILES[board_key]
    release_version = _plain_version(release.get("tag_name"))
    assets = list(release.get("assets") or [])
    wanted_prefix = str(profile.get("artifact_prefix") or "")
    manifests = [
        item
        for item in assets
        if str(item.get("name") or "").startswith(wanted_prefix)
        and str(item.get("name") or "").lower().endswith(_MANIFEST_SUFFIX)
    ]
    if len(manifests) != 1:
        raise _LegacyReleaseRequired(
            f"Keine passende Firmware für {profile['label']} im Release {release_version} gefunden."
        )
    manifest_asset = manifests[0]
    prefix = str(manifest_asset["name"])[: -len(_MANIFEST_SUFFIX)]
    release_id = int(release.get("id") or 0)
    cache_root = (
        services.PATHS.firmware / f"release-{release_id}-{board_key}-{prefix[-48:]}"
    )
    marker = cache_root / ".complete"
    cache_root.mkdir(parents=True, exist_ok=True)
    try:
        manifest_path = _download_asset(
            client,
            services,
            manifest_asset,
            cache_root / str(manifest_asset["name"]),
            "manifest",
        )
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise services.FlasherError(
                "Release enthält kein lesbares Unified-Core-Manifest."
            ) from exc
        if not isinstance(manifest, dict):
            raise services.FlasherError(
                "Release enthält kein gültiges Unified-Core-Manifest."
            )
        build, variants, source_sha = _validate_manifest(
            services, manifest, board_key=board_key, release_version=release_version
        )

        sums_asset = _asset_by_name(services, assets, prefix + _SUMS_SUFFIX)
        sums_path = _download_asset(
            client,
            services,
            sums_asset,
            cache_root / str(sums_asset["name"]),
            "checksums",
        )
        sums = services._read_checksum_manifest(sums_path)
        if not sums:
            raise services.FlasherError("SHA256SUMS ist leer oder unlesbar.")

        paths: dict[str, Path] = {}
        for variant in variants:
            role = "meshtastic-webflasher" if variant == "webflasher" else variant
            name = _variant_asset_name(prefix, variant)
            asset = _asset_by_name(services, assets, name)
            path = _download_asset(client, services, asset, cache_root / name, role)
            wanted = sums.get(name)
            actual = services._sha256(path)
            if not wanted or actual != wanted.lower():
                raise services.FlasherError(f"SHA-256-Prüfung fehlgeschlagen: {name}")
            api_digest = _asset_digest(asset)
            if api_digest and api_digest != wanted.lower():
                raise services.FlasherError(
                    f"GitHub- und Paket-Prüfsumme widersprechen sich: {name}"
                )
            paths[variant] = path

        kind = str(profile.get("artifact_kind") or "esp32").lower()
        if kind == "uf2":
            factory = update = web = paths["uf2"]
        else:
            factory = paths["factory"]
            update = paths["update"]
            web = paths.get("meshtastic-webflasher") or paths.get("webflasher")
        bundle = services.FirmwareBundle(
            board_key=board_key,
            run_id=0,
            run_number=build,
            artifact_id=int(manifest_asset.get("id") or 0),
            artifact_name=prefix,
            root=cache_root,
            factory=factory,
            update=update,
            webflasher=web,
            checksums=sums_path,
            version=release_version,
        )
        bundle.source_kind = "github-release"
        bundle.release_id = release_id
        bundle.release_tag = str(release.get("tag_name") or "")
        bundle.release_url = str(release.get("html_url") or "")
        bundle.source_sha = source_sha
        bundle.manifest = manifest
        bundle.manifest_path = manifest_path
        bundle.available_variants = variants
        bundle.normal_update = update
        bundle.firmware_type = "Update" if kind != "uf2" else "UF2"
        if kind == "uf2":
            bundle.flash_strategy = "uf2"
        else:
            try:
                bundle.flash_targets = services.esp32_update_targets(bundle)
                bundle.flash_strategy = "partition_update"
            except Exception as exc:
                raise services.FlasherError(
                    f"Flashlayout konnte nicht sicher bestimmt werden: {exc}"
                ) from exc
        marker.write_text(
            json.dumps(
                {
                    "release_id": release_id,
                    "release_tag": bundle.release_tag,
                    "board_key": board_key,
                    "build": build,
                    "source_sha": source_sha,
                    "variants": variants,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        _emit(
            f"UNIFIED RELEASE READY tag={bundle.release_tag!r} build={build} board={board_key!r} "
            f"env={profile.get('pio_env')!r} normal_update={update.name!r} "
            f"factory={factory.name!r} web={getattr(web, 'name', None)!r} sha256=1"
        )
        return bundle
    except Exception:
        marker.unlink(missing_ok=True)
        raise


def _resolve_from_releases(client: Any, services: Any, board_key: str):
    try:
        response = client._get_json(
            f"{client.api}/repos/{services.REPOSITORY}/releases", per_page=50
        )
    except Exception as exc:
        raise _ReleaseLookupUnavailable(str(exc)) from exc
    releases = response if isinstance(response, list) else []
    candidates = [
        item
        for item in releases
        if isinstance(item, dict)
        and not item.get("draft")
        and _release_key(item, services.JARNSEN_BASE_VERSION)[0] >= 0
    ]
    candidates.sort(
        key=lambda item: _release_key(item, services.JARNSEN_BASE_VERSION), reverse=True
    )
    diagnostics: list[str] = []
    for release in candidates:
        try:
            return _release_bundle(client, services, release, board_key)
        except _LegacyReleaseRequired as exc:
            diagnostics.append(f"{release.get('tag_name')}: {exc}")
    detail = "\n".join(diagnostics[:6])
    raise _LegacyReleaseRequired(
        f"Kein gültiger Unified-Core-GitHub-Release für {services.BOARD_PROFILES[board_key]['label']} gefunden."
        + (f"\n\n{detail}" if detail else "")
    )


def install(services: Any) -> None:
    client_type = services.GitHubFirmwareClient
    if getattr(client_type, "_jarnsen_unified_release_resolver", False):
        return
    legacy_resolve = client_type.resolve_latest

    def resolve_latest(self: Any, board_key: str):
        if board_key not in services.BOARD_PROFILES:
            raise services.FlasherError(f"Nicht unterstütztes Board: {board_key}")
        local = getattr(services, "_jarnsen_local_firmware_bundle", None)
        if local is not None and getattr(local, "board_key", None) == board_key:
            return local
        try:
            return _resolve_from_releases(self, services, board_key)
        except (_LegacyReleaseRequired, _ReleaseLookupUnavailable) as release_error:
            _emit(
                f"UNIFIED RELEASE FALLBACK board={board_key!r} reason={type(release_error).__name__}:{release_error} "
                "legacy=actions/ota"
            )
            try:
                return legacy_resolve(self, board_key)
            except Exception as legacy_error:
                raise services.FlasherError(
                    f"GitHub-Release und Legacy-Erkennung sind fehlgeschlagen.\n\n"
                    f"Release: {release_error}\nLegacy (*.ota.json/Actions): {legacy_error}"
                ) from release_error

    client_type.resolve_latest = resolve_latest
    client_type._jarnsen_unified_release_resolver = True
    services.resolve_unified_release = lambda client, board_key: _resolve_from_releases(
        client, services, board_key
    )
    services.validate_unified_manifest = (
        lambda manifest, board_key, version: _validate_manifest(
            services,
            manifest,
            board_key=board_key,
            release_version=_plain_version(version),
        )
    )
    _emit(
        "UNIFIED RELEASE RESOLVER installed release-first=1 package-manifest=1 board-gate=1 "
        "size=1 sha256=1 type-separation=1 legacy-actions-ota=1"
    )
