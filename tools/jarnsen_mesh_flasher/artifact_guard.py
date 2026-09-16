from __future__ import annotations

import re
import struct
from pathlib import Path
from typing import Any, Callable

_INSTALLED = False


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _norm(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", str(value or "").upper()).strip("_")


def _unique_paths(values: list[Any], suffix: str) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()
    for value in values:
        if value is None or not str(value).strip():
            continue
        try:
            path = Path(value)
            resolved = path.resolve()
        except Exception:
            continue
        if path.suffix.lower() != suffix.lower() or resolved in seen:
            continue
        seen.add(resolved)
        found.append(path)
    return found


def _flash_files(services: Any, bundle: Any) -> tuple[str, list[Path]]:
    board_key = str(getattr(bundle, "board_key", "") or "")
    profile = services.BOARD_PROFILES.get(board_key, {})
    kind = str(profile.get("artifact_kind") or "esp32").strip().lower()
    values = [
        getattr(bundle, "factory", None),
        getattr(bundle, "update", None),
        getattr(bundle, "webflasher", None),
    ]
    if kind == "uf2":
        files = _unique_paths(values, ".uf2")
        if not files:
            root = Path(getattr(bundle, "root", "") or ".")
            if root.exists():
                files = sorted(path for path in root.rglob("*.uf2") if path.is_file())
        if len(files) != 1:
            raise services.FlasherError(
                f"Firmware-Sicherheitsprüfung: genau eine UF2-Datei erwartet, gefunden {len(files)}."
            )
        return kind, files

    files = _unique_paths(values, ".bin")
    strategy = str(
        profile.get("flash_strategy")
        or getattr(bundle, "flash_strategy", "")
        or "dual_slot"
    ).lower()
    minimum = 2 if strategy == "factory_only" else 2
    if len(files) < minimum:
        raise services.FlasherError(
            "Firmware-Sicherheitsprüfung: Factory-/Update-BIN fehlt oder ist nicht eindeutig."
        )
    return kind, files


def _validate_local_board_evidence(services: Any, bundle: Any, board_key: str) -> None:
    source = str(getattr(bundle, "local_source", "") or "").strip()
    if not source:
        return
    profile = services.BOARD_PROFILES[board_key]
    root = Path(getattr(bundle, "root", "") or ".")
    names = [
        str(getattr(bundle, "artifact_name", "") or ""),
        Path(source).name,
    ]
    if root.exists():
        names.extend(path.name for path in root.rglob("*") if path.is_file())
    evidence = _norm(" ".join(names))

    tokens = [
        profile.get("pio_env"),
        profile.get("label"),
        profile.get("artifact_prefix"),
    ]
    tokens.extend(profile.get("match") or ())
    normalized = [_norm(token) for token in tokens if len(_norm(token)) >= 4]
    if not any(token in evidence for token in normalized):
        raise services.FlasherError(
            "Lokales Firmwarepaket enthält keine eindeutige Board-Kennung. "
            f"Ausgewählt: {profile['label']}. Aus Sicherheitsgründen wird nicht geflasht."
        )


def _validate_checksums(services: Any, bundle: Any, files: list[Path]) -> None:
    checksum_value = getattr(bundle, "checksums", None)
    if checksum_value is None or not str(checksum_value).strip():
        raise services.FlasherError("Firmware-Sicherheitsprüfung: SHA256SUMS fehlt.")
    checksums = Path(checksum_value)
    if not checksums.exists() or checksums.stat().st_size < 20:
        raise services.FlasherError(
            f"Firmware-Sicherheitsprüfung: ungültige Prüfsummendatei {checksums}."
        )
    manifest = services._read_checksum_manifest(checksums)
    if not manifest:
        raise services.FlasherError(
            "Firmware-Sicherheitsprüfung: SHA256SUMS ist leer oder unlesbar."
        )
    for path in files:
        if not path.exists() or path.stat().st_size <= 0:
            raise services.FlasherError(
                f"Firmware-Datei fehlt oder ist leer: {path.name}"
            )
        wanted = manifest.get(path.name)
        if not wanted:
            raise services.FlasherError(f"SHA256SUMS enthält {path.name} nicht.")
        actual = services._sha256(path)
        if actual.lower() != str(wanted).lower():
            raise services.FlasherError(
                f"SHA256-Prüfung fehlgeschlagen: {path.name}\nErwartet: {wanted}\nIst: {actual}"
            )


def _validate_magic(services: Any, kind: str, files: list[Path]) -> None:
    if kind == "uf2":
        head = files[0].read_bytes()[:8]
        if len(head) < 8:
            raise services.FlasherError(f"UF2-Datei ist zu klein: {files[0].name}")
        magic0, magic1 = struct.unpack("<II", head)
        if magic0 != 0x0A324655 or magic1 != 0x9E5D5157:
            raise services.FlasherError(f"UF2-Header ist ungültig: {files[0].name}")
        return

    for path in files:
        lower = path.name.lower()
        offsets = (0,) if lower.endswith("-update.bin") else (0, 0x1000, 0x10000)
        valid = False
        with path.open("rb") as handle:
            for offset in offsets:
                handle.seek(offset)
                if handle.read(1) == b"\xe9":
                    valid = True
                    break
        if not valid:
            expected = ", ".join(hex(offset) for offset in offsets)
            raise services.FlasherError(
                f"ESP32-Image-Header ist ungültig: {path.name} (geprüft bei {expected})"
            )


def validate_bundle(
    services: Any, bundle: Any, expected_board: str | None = None
) -> dict[str, Any]:
    board_key = str(getattr(bundle, "board_key", "") or "").strip()
    if board_key not in services.BOARD_PROFILES:
        raise services.FlasherError(
            f"Firmware-Sicherheitsprüfung: unbekanntes Board {board_key!r}."
        )
    if expected_board and board_key != expected_board:
        raise services.FlasherError(
            "Firmware-Sicherheitsprüfung: falsches Boardpaket. "
            f"Erwartet {services.BOARD_PROFILES[expected_board]['label']}, "
            f"Paket ist {services.BOARD_PROFILES[board_key]['label']}."
        )

    version = str(getattr(bundle, "version", "") or "").strip()
    if not version.startswith(str(services.JARNSEN_BASE_VERSION)):
        raise services.FlasherError(
            f"Firmware-Sicherheitsprüfung: Version {version or 'unbekannt'} gehört nicht zur "
            f"JARNSEN-MESH {services.JARNSEN_BASE_VERSION} Linie."
        )

    artifact_name = str(getattr(bundle, "artifact_name", "") or "").strip()
    if not getattr(bundle, "local_source", None):
        prefix = str(services.BOARD_PROFILES[board_key].get("artifact_prefix") or "")
        if prefix and not artifact_name.startswith(prefix):
            raise services.FlasherError(
                f"Firmware-Sicherheitsprüfung: Artifact {artifact_name!r} passt nicht zu {prefix!r}."
            )

    manifest = getattr(bundle, "manifest", None)
    if manifest is not None:
        expected_env = str(services.BOARD_PROFILES[board_key].get("pio_env") or "")
        actual_env = (
            str(manifest.get("platformio_environment") or "")
            if isinstance(manifest, dict)
            else ""
        )
        if actual_env != expected_env:
            raise services.FlasherError(
                f"Firmware-Sicherheitsprüfung: Manifest gehört zu {actual_env or 'unbekannt'}, "
                f"angeschlossen ist {expected_env}."
            )
        normal = Path(getattr(bundle, "update", ""))
        if (
            str(
                services.BOARD_PROFILES[board_key].get("artifact_kind") or "esp32"
            ).lower()
            != "uf2"
        ):
            if not normal.name.lower().endswith("-update.bin"):
                raise services.FlasherError(
                    "Firmware-Sicherheitsprüfung: normales Update ist weder *-update.bin noch eindeutig typisiert."
                )
            if "webflasher" in normal.name.lower() or normal.name.lower().endswith(
                "-factory.bin"
            ):
                raise services.FlasherError(
                    "Firmware-Sicherheitsprüfung: Webflasher-/Factory-Datei darf nicht als Update dienen."
                )

    _validate_local_board_evidence(services, bundle, board_key)
    kind, files = _flash_files(services, bundle)
    _validate_checksums(services, bundle, files)
    _validate_magic(services, kind, files)

    result = {
        "board_key": board_key,
        "kind": kind,
        "version": version,
        "artifact": artifact_name,
        "files": [path.name for path in files],
        "local": bool(getattr(bundle, "local_source", None)),
    }
    _emit(
        f"ARTIFACT GUARD PASS board={board_key!r} kind={kind!r} version={version!r} "
        f"files={result['files']!r} local={int(result['local'])}"
    )
    return result


def install(services: Any) -> None:
    """Validate every GitHub/local bundle again immediately before destructive flash."""
    global _INSTALLED
    if _INSTALLED or getattr(services, "_jarnsen_artifact_guard_v1", False):
        return
    _INSTALLED = True

    base_resolve = services.GitHubFirmwareClient.resolve_latest
    base_flash = services.flash_bundle

    def resolve_latest(self: Any, board_key: str):
        bundle = base_resolve(self, board_key)
        validate_bundle(services, bundle, board_key)
        return bundle

    def flash_bundle(
        port: str, bundle: Any, log: Callable[[str], None] | None = None
    ) -> None:
        expected_board = str(getattr(bundle, "board_key", "") or "") or None
        try:
            record = services.flash_transactions.active(port)
            if (
                record is not None
                and str(getattr(record, "board_key", "") or "").strip()
            ):
                expected_board = str(record.board_key).strip()
        except Exception:
            pass
        validate_bundle(services, bundle, expected_board)
        if log:
            log("Firmware-Sicherheitsprüfung · Board/Version/SHA256/Imageformat OK")
        return base_flash(port, bundle, log=log)

    services.GitHubFirmwareClient.resolve_latest = resolve_latest
    services.flash_bundle = flash_bundle
    services.validate_firmware_bundle = (
        lambda bundle, expected_board=None: validate_bundle(
            services, bundle, expected_board
        )
    )
    services._jarnsen_artifact_guard_v1 = True
    _emit(
        "ARTIFACT GUARD installed github=1 local=1 pre-flash=1 sha256=1 image-magic=1 board-gate=1"
    )
