from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable


_INSTALLED = False


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _register_profiles(services: Any) -> None:
    common = {
        "branch": services.UNIFIED_BRANCH,
        "workflow_path": services.UNIFIED_WORKFLOW_PATH,
        "artifact_kind": "esp32",
        "flash_strategy": "factory_only",
    }
    services.BOARD_PROFILES.setdefault(
        "heltec_v4",
        {
            **common,
            "label": "Heltec V4",
            "pio_env": "heltec-v4",
            "artifact_prefix": f"JARNSEN-MESH-Heltec-V4-v{services.JARNSEN_BASE_VERSION}",
            "match": (
                "HELTEC_V4",
                "HELTEC V4",
                "HELTEC-V4",
                "HELTEC WIFI LORA 32 V4",
                "heltec-v4",
            ),
        },
    )
    services.BOARD_PROFILES.setdefault(
        "tbeam",
        {
            **common,
            "label": "LILYGO T-Beam",
            "pio_env": "tbeam",
            "artifact_prefix": f"JARNSEN-MESH-LILYGO-T-Beam-v{services.JARNSEN_BASE_VERSION}",
            "match": (
                "T-BEAM",
                "T_BEAM",
                "TBEAM",
                "LILYGO T-BEAM",
                "LILYGO_T_BEAM",
                "tbeam",
            ),
        },
    )
    services.BOARD_PROFILES.setdefault(
        "tbeam_supreme",
        {
            **common,
            "label": "LILYGO T-Beam Supreme",
            "pio_env": "tbeam-s3-core",
            "artifact_prefix": f"JARNSEN-MESH-LILYGO-T-Beam-Supreme-v{services.JARNSEN_BASE_VERSION}",
            "match": (
                "T-BEAM SUPREME",
                "T_BEAM_SUPREME",
                "TBEAM SUPREME",
                "TBEAM_SUPREME",
                "LILYGO T-BEAM SUPREME",
                "LILYGO_T_BEAM_SUPREME",
                "tbeam-s3-core",
            ),
        },
    )

    # Existing boards use their current proven flash paths.
    for key in ("tracker", "repeater"):
        profile = services.BOARD_PROFILES.get(key)
        if isinstance(profile, dict):
            profile.setdefault("artifact_kind", "esp32")
            profile.setdefault("flash_strategy", "dual_slot")
    wio = services.BOARD_PROFILES.get("wio")
    if isinstance(wio, dict):
        wio.setdefault("artifact_kind", "uf2")
        wio.setdefault("flash_strategy", "uf2")


def _patch_board_detection(services: Any) -> None:
    try:
        import board_detection
    except Exception as exc:
        _emit(f"UNIFIED BOARD SUPPORT detection patch skipped type={type(exc).__name__} message={exc}")
        return

    if getattr(board_detection, "_jarnsen_six_board_detection", False):
        return

    base_detect = board_detection.detect

    def normalized(value: str) -> str:
        return re.sub(r"[^A-Z0-9]+", "_", str(value or "").upper()).strip("_")

    def contains(source: str, token: str) -> bool:
        haystack = f"_{normalized(source)}_"
        needle = normalized(token)
        return bool(needle and f"_{needle}_" in haystack)

    def detect(text: str, board_profiles: dict[str, Any] | None = None):
        source = text or ""
        profiles = board_profiles or services.BOARD_PROFILES

        # Longest/specific identities first so T-Beam Supreme can never be
        # collapsed into the shorter T-Beam family.
        ordered = (
            (
                "tbeam_supreme",
                (
                    "T-BEAM SUPREME",
                    "T_BEAM_SUPREME",
                    "TBEAM SUPREME",
                    "TBEAM_SUPREME",
                    "TBEAM-S3-CORE",
                    "tbeam-s3-core",
                ),
            ),
            (
                "heltec_v4",
                (
                    "HELTEC V4",
                    "HELTEC_V4",
                    "HELTEC-V4",
                    "HELTEC WIFI LORA 32 V4",
                    "heltec-v4",
                ),
            ),
            (
                "tbeam",
                (
                    "LILYGO T-BEAM",
                    "LILYGO_T_BEAM",
                    "T-BEAM",
                    "T_BEAM",
                    "TBEAM",
                ),
            ),
        )
        for board_key, tokens in ordered:
            if board_key not in profiles:
                continue
            for token in tokens:
                if contains(source, token):
                    result = board_detection.Detection(
                        board_key,
                        1200,
                        f"extended exact hardware phrase={token}",
                    )
                    _emit(
                        "UNIFIED BOARD DETECTION "
                        f"board={board_key!r} score={result.score} reason={result.reason!r}"
                    )
                    return result

        return base_detect(source, profiles)

    board_detection.detect = detect
    board_detection._jarnsen_six_board_detection = True
    _emit("UNIFIED BOARD SUPPORT detection extended boards=Heltec-V4,T-Beam,T-Beam-Supreme")


def _patch_board_menu(services: Any) -> None:
    try:
        import customtkinter as ctk
    except Exception:
        return

    if getattr(ctk.CTkOptionMenu, "_jarnsen_six_board_menu", False):
        return

    original_init = ctk.CTkOptionMenu.__init__

    def option_init(self: Any, master: Any, *args: Any, **kwargs: Any) -> None:
        values = list(kwargs.get("values") or [])
        tracker_label = str(services.BOARD_PROFILES.get("tracker", {}).get("label") or "")
        if "Automatisch" in values and tracker_label and tracker_label in values:
            desired = ["Automatisch"]
            for profile in services.BOARD_PROFILES.values():
                label = str(profile.get("label") or "").strip()
                if label and label not in desired:
                    desired.append(label)
            kwargs["values"] = desired
        original_init(self, master, *args, **kwargs)

    ctk.CTkOptionMenu.__init__ = option_init
    ctk.CTkOptionMenu._jarnsen_six_board_menu = True
    _emit(
        "UNIFIED BOARD SUPPORT board-menu="
        + ",".join(str(profile.get("label") or "") for profile in services.BOARD_PROFILES.values())
    )


def _patch_artifact_resolver(services: Any) -> None:
    client_type = services.GitHubFirmwareClient
    if getattr(client_type, "_jarnsen_factory_only_resolver", False):
        return

    base_resolver = client_type._resolve_bundle_files

    def resolve_bundle_files(
        self: Any,
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
        strategy = str(profile.get("flash_strategy") or "dual_slot").lower()
        if strategy != "factory_only":
            return base_resolver(
                self,
                board_key=board_key,
                run_id=run_id,
                run_number=run_number,
                artifact_id=artifact_id,
                artifact_name=artifact_name,
                cache_root=cache_root,
                version=version,
            )

        all_files = [
            path
            for path in cache_root.rglob("*")
            if path.is_file() and path.name != ".complete"
        ]

        def pick(label: str, suffixes: tuple[str, ...]) -> Path:
            lowered = tuple(value.lower() for value in suffixes)
            matches = [
                path for path in all_files
                if path.name.lower().endswith(lowered)
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
            return unique[0]

        checksums = pick("SHA256SUMS", ("-sha256sums.txt", "sha256sums.txt"))
        factory = pick("Factory-Image", ("-factory.bin", ".factory.bin"))
        update = pick("Update-Image", ("-update.bin",))

        expected = services._read_checksum_manifest(checksums)
        for file_path in (factory, update):
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
            _emit(f"UNIFIED BOARD SHA256 OK board={board_key!r} file={file_path.name!r}")

        # The Unified-Core build validates these same invariants before upload.
        # Recheck them in the flasher so a corrupted/mismatched local artifact can
        # never erase a board.
        update_bytes = update.read_bytes()
        if not update_bytes or update_bytes[0] != 0xE9:
            raise services.FlasherError(
                f"Ungültiges ESP32-Anwendungsimage: {update.name}"
            )
        factory_bytes = factory.read_bytes()
        app_offset = 0x10000
        if len(factory_bytes) < app_offset + len(update_bytes):
            raise services.FlasherError(
                f"Factory-Image ist zu klein für das Anwendungsimage: {factory.name}"
            )
        if factory_bytes[0x8000:0x8002] != b"\xaa\x50":
            raise services.FlasherError(
                f"Factory-Partitionstabelle ist ungültig: {factory.name}"
            )
        if factory_bytes[app_offset] != 0xE9:
            raise services.FlasherError(
                f"Factory-App-Header bei 0x{app_offset:x} ist ungültig: {factory.name}"
            )
        if factory_bytes[app_offset:app_offset + len(update_bytes)] != update_bytes:
            raise services.FlasherError(
                f"Factory- und Update-Anwendungsimage passen nicht zusammen: {factory.name}"
            )
        _emit(
            f"UNIFIED BOARD FACTORY VERIFIED board={board_key!r} "
            f"app_offset=0x{app_offset:x} update_bytes={len(update_bytes)}"
        )

        bundle = services.FirmwareBundle(
            board_key=board_key,
            run_id=run_id,
            run_number=run_number,
            artifact_id=artifact_id,
            artifact_name=artifact_name,
            root=cache_root,
            factory=factory,
            update=update,
            # Compatibility field: factory-only boards intentionally have no
            # dual-slot webflasher artifact in the Unified-Core workflow.
            webflasher=update,
            checksums=checksums,
            version=version,
        )
        bundle.flash_strategy = "factory_only"
        _emit(
            f"UNIFIED BOARD BUNDLE READY board={board_key!r} strategy=factory_only "
            f"factory={factory.name!r} update={update.name!r}"
        )
        return bundle

    client_type._resolve_bundle_files = resolve_bundle_files
    client_type._jarnsen_factory_only_resolver = True
    _emit("UNIFIED BOARD SUPPORT artifact resolver factory-only=1")


def _patch_flash_runtime(services: Any) -> None:
    if getattr(services, "_jarnsen_factory_only_flash", False):
        return

    base_flash_bundle = services.flash_bundle

    def flash_bundle(port: str, bundle: Any, log: Callable[[str], None] | None = None) -> None:
        profile = services.BOARD_PROFILES.get(getattr(bundle, "board_key", ""), {})
        strategy = str(profile.get("flash_strategy") or getattr(bundle, "flash_strategy", "") or "dual_slot").lower()
        if strategy != "factory_only":
            return base_flash_bundle(port, bundle, log=log)

        factory = Path(bundle.factory)
        update = Path(bundle.update)
        if not factory.exists() or not update.exists():
            raise services.FlasherError(
                "Factory-/Update-Datei fehlt im Firmwarepaket."
            )

        baud = str(getattr(services, "_jarnsen_flash_baud", "921600"))
        if baud not in {"115200", "230400", "460800", "921600"}:
            baud = "921600"

        try:
            from flash_runtime import _stream_esptool
        except Exception as exc:
            raise services.FlasherError(
                f"Streaming-Flashlaufzeit nicht verfügbar: {exc}"
            ) from exc

        source = getattr(bundle, "local_source", "")
        source_text = f"PC-Datei={source}" if source else f"GitHub-Artifact={bundle.artifact_name}"
        board_label = str(profile.get("label") or bundle.board_key)

        if log:
            log(
                f"FLASH START · Board={board_label} · Port={port} · Baud={baud} · {source_text}"
            )
            log(f"FLASH DATEI · Factory={factory.name} · {factory.stat().st_size} Bytes")
            log(f"FLASH DATEI · Update-Prüfimage={update.name} · {update.stat().st_size} Bytes")
            log(
                "FLASHPLAN · vollständiges Backup liegt vor → Flash löschen → "
                "validiertes Factory-Image an 0x0 → Start"
            )

        _emit(
            f"UNIFIED FACTORY FLASH PLAN port={port!r} board={bundle.board_key!r} "
            f"baud={baud} factory={factory.name!r} bytes={factory.stat().st_size} "
            f"strategy=factory_only source={source_text!r}"
        )

        _stream_esptool(
            services,
            port,
            ["erase-flash"],
            timeout=180,
            stage="Flash löschen",
            phase_start=0.00,
            phase_end=0.08,
            log=log,
        )
        _stream_esptool(
            services,
            port,
            [
                "--baud",
                baud,
                "write-flash",
                "--flash-size",
                "keep",
                "0x0",
                str(factory),
            ],
            timeout=900,
            stage="Factory schreiben",
            phase_start=0.08,
            phase_end=0.98,
            log=log,
        )
        _stream_esptool(
            services,
            port,
            ["run"],
            timeout=30,
            stage="Node starten",
            phase_start=0.98,
            phase_end=1.00,
            log=log,
            check=False,
        )
        if log:
            log("FLASH ENDE · Factory-Image vollständig geschrieben · Node-Start ausgelöst")

    services.flash_bundle = flash_bundle
    services._jarnsen_factory_only_flash = True
    _emit("UNIFIED BOARD SUPPORT flash strategy factory-only=1")


def install(services: Any) -> None:
    """Enable every board currently built by the JARNSEN-MESH Unified-Core workflow."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    _register_profiles(services)
    _patch_board_detection(services)
    _patch_board_menu(services)
    _patch_artifact_resolver(services)
    _patch_flash_runtime(services)

    labels = [str(profile.get("label") or "") for profile in services.BOARD_PROFILES.values()]
    _emit(
        "UNIFIED BOARD SUPPORT installed "
        f"count={len(labels)} boards={labels!r} "
        "strategies=dual-slot/factory-only/uf2"
    )
