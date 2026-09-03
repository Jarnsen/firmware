from __future__ import annotations

from pathlib import Path
from typing import Any


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def install(services: Any) -> None:
    """Resolve both unified JARNSEN-MESH and legacy firmware filenames.

    Unified Core artifacts are named after the complete product/version/build,
    e.g. JARNSEN-MESH-Heltec-Tracker-V1.1-v2.0.0-alpha.4-Build-101-factory.bin.
    The original flasher expected PlatformIO-style firmware-<env> names.
    """

    client_type = services.GitHubFirmwareClient

    def resolve_bundle_files(
        self,
        *,
        board_key: str,
        run_id: int,
        run_number: int,
        artifact_id: int,
        artifact_name: str,
        cache_root: Path,
        version: str,
    ):
        profile = services.BOARD_PROFILES[board_key]
        env_name = str(profile["pio_env"])
        all_files = [
            path
            for path in cache_root.rglob("*")
            if path.is_file() and path.name != ".complete"
        ]

        _emit(
            f"FIRMWARE FILE RESOLVE artifact={artifact_name!r} board={board_key!r} "
            f"files={[p.name for p in all_files]!r}"
        )

        def pick(label: str, *, exact: tuple[str, ...] = (), suffix: tuple[str, ...] = ()) -> Path:
            exact_lower = {name.lower() for name in exact}
            suffix_lower = tuple(value.lower() for value in suffix)
            matches = [
                path
                for path in all_files
                if path.name.lower() in exact_lower
                or (suffix_lower and path.name.lower().endswith(suffix_lower))
            ]
            # De-duplicate in case one name satisfies both exact and suffix rules.
            unique: list[Path] = []
            seen: set[Path] = set()
            for path in matches:
                resolved = path.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    unique.append(path)
            if len(unique) != 1:
                available = ", ".join(sorted(path.name for path in all_files)) or "<leer>"
                raise services.FlasherError(
                    f"Artifact {artifact_name}: {label} nicht eindeutig gefunden "
                    f"({len(unique)} Treffer).\nVerfügbare Dateien: {available}"
                )
            _emit(f"FIRMWARE FILE PICK label={label!r} file={unique[0].name!r}")
            return unique[0]

        factory = pick(
            "Factory-Image",
            exact=(f"firmware-{env_name}.factory.bin",),
            suffix=("-factory.bin", ".factory.bin"),
        )
        update = pick(
            "Update-Image",
            exact=(f"firmware-{env_name}.bin",),
            suffix=("-update.bin",),
        )
        webflasher = pick(
            "Webflasher-Image",
            exact=(f"firmware-{env_name}.webflasher.bin",),
            suffix=("-webflasher.bin", ".webflasher.bin"),
        )
        checksums = pick(
            "SHA256SUMS",
            exact=("SHA256SUMS.txt",),
            suffix=("-sha256sums.txt",),
        )

        expected = services._read_checksum_manifest(checksums)
        for file_path in (factory, update, webflasher):
            wanted = expected.get(file_path.name)
            if not wanted:
                raise services.FlasherError(
                    f"{checksums.name} enthält {file_path.name} nicht."
                )
            actual = services._sha256(file_path)
            if actual != wanted:
                raise services.FlasherError(
                    f"SHA256-Prüfung fehlgeschlagen: {file_path.name}\n"
                    f"Erwartet: {wanted}\nIst: {actual}"
                )
            _emit(f"FIRMWARE SHA256 OK file={file_path.name!r}")

        bundle = services.FirmwareBundle(
            board_key=board_key,
            run_id=run_id,
            run_number=run_number,
            artifact_id=artifact_id,
            artifact_name=artifact_name,
            root=cache_root,
            factory=factory,
            update=update,
            webflasher=webflasher,
            checksums=checksums,
            version=version,
        )
        _emit(f"FIRMWARE BUNDLE READY {bundle.display_name}")
        return bundle

    client_type._resolve_bundle_files = resolve_bundle_files
    _emit("FIRMWARE ARTIFACT COMPAT installed: unified suffix resolver")
