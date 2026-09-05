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
    """Resolve unified JARNSEN-MESH artifact filenames for ESP32 and UF2 boards."""

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
        artifact_kind = str(profile.get("artifact_kind") or "esp32").lower()
        all_files = [
            path
            for path in cache_root.rglob("*")
            if path.is_file() and path.name != ".complete"
        ]

        _emit(
            f"FIRMWARE FILE RESOLVE artifact={artifact_name!r} board={board_key!r} "
            f"kind={artifact_kind!r} files={[p.name for p in all_files]!r}"
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

        checksums = pick(
            "SHA256SUMS",
            exact=("SHA256SUMS.txt",),
            suffix=("-sha256sums.txt",),
        )
        expected = services._read_checksum_manifest(checksums)

        if artifact_kind == "uf2":
            uf2 = pick(
                "UF2-Firmware",
                exact=("firmware.uf2", f"firmware-{env_name}.uf2"),
                suffix=("-firmware.uf2", ".uf2"),
            )
            wanted = expected.get(uf2.name)
            if not wanted:
                raise services.FlasherError(f"{checksums.name} enthält {uf2.name} nicht.")
            actual = services._sha256(uf2)
            if actual != wanted:
                raise services.FlasherError(
                    f"SHA256-Prüfung fehlgeschlagen: {uf2.name}\n"
                    f"Erwartet: {wanted}\nIst: {actual}"
                )
            _emit(f"FIRMWARE SHA256 OK file={uf2.name!r}")
            bundle = services.FirmwareBundle(
                board_key=board_key,
                run_id=run_id,
                run_number=run_number,
                artifact_id=artifact_id,
                artifact_name=artifact_name,
                root=cache_root,
                factory=uf2,
                update=uf2,
                webflasher=uf2,
                checksums=checksums,
                version=version,
            )
            _emit(f"FIRMWARE BUNDLE READY {bundle.display_name} kind=uf2")
            return bundle

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
        _emit(f"FIRMWARE BUNDLE READY {bundle.display_name} kind=esp32")
        return bundle

    client_type._resolve_bundle_files = resolve_bundle_files
    _emit("FIRMWARE ARTIFACT COMPAT installed: unified ESP32/UF2 suffix resolver")
