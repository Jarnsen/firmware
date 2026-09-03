from __future__ import annotations

import re
import shutil
import time
import zipfile
from pathlib import Path
from typing import Any


def _emit(message: str) -> None:
    try:
        import diagnostics
        diagnostics._emit(message)
    except Exception:
        pass


def _safe_extract(source: Path, target: Path) -> None:
    root = target.resolve()
    with zipfile.ZipFile(source, "r") as archive:
        for member in archive.infolist():
            resolved = (target / member.filename).resolve()
            try:
                resolved.relative_to(root)
            except ValueError as exc:
                raise RuntimeError(f"Unsicherer ZIP-Pfad: {member.filename}") from exc
        archive.extractall(target)


def _infer_board(services: Any, names: list[str], expected: str | None) -> str:
    if expected and expected in services.BOARD_PROFILES:
        return expected
    text = "\n".join(names).upper().replace("_", "-").replace(" ", "-")
    strong = {
        "wio": ("SEEED-WIO-TRACKER-L1", "WIO-TRACKER-L1"),
        "repeater": ("JARNSEN-MESH-HELTEC-V3", "HELTEC-V3"),
        "tracker": ("JARNSEN-MESH-HELTEC-TRACKER-V1.1", "HELTEC-WIRELESS-TRACKER", "WIRELESS-TRACKER-V1.1"),
    }
    for key, tokens in strong.items():
        if key in services.BOARD_PROFILES and any(token in text for token in tokens):
            return key
    for key, profile in services.BOARD_PROFILES.items():
        values = (profile.get("artifact_prefix"), profile.get("pio_env"), profile.get("label"))
        for value in values:
            token = str(value or "").upper().replace("_", "-").replace(" ", "-")
            if token and token in text:
                return key
    raise services.FlasherError(
        "Board des lokalen Firmwarepakets konnte nicht eindeutig bestimmt werden. "
        "Bitte zuerst das Zielboard auswählen oder ein originales JARNSEN-MESH-Artifact verwenden."
    )


def _version_build(names: list[str], base_version: str) -> tuple[str, int, str]:
    for name in names:
        match = re.search(
            rf"(?i)(JARNSEN-MESH-.+?-v({re.escape(base_version)}(?:-[A-Za-z0-9][A-Za-z0-9.-]*)?)-Build-(\d+))",
            name,
        )
        if match:
            return match.group(2), int(match.group(3)), match.group(1)
    return f"{base_version}-local", 0, "JARNSEN-MESH-LOCAL"


def _copy_neighbours(source: Path, target: Path) -> None:
    build = re.search(r"(?i)Build[-_ ]?(\d+)", source.name)
    build_no = build.group(1) if build else ""
    copied = 0
    for item in source.parent.iterdir():
        if not item.is_file() or item.suffix.lower() not in {".bin", ".uf2", ".txt"}:
            continue
        lower = item.name.lower()
        if build_no and re.search(rf"(?i)Build[-_ ]?{re.escape(build_no)}\b", item.name):
            shutil.copy2(item, target / item.name); copied += 1
        elif item == source or lower == "sha256sums.txt" or lower.startswith("firmware-"):
            shutil.copy2(item, target / item.name); copied += 1
    if copied == 0:
        shutil.copy2(source, target / source.name)


def prepare_local_bundle(services: Any, selected: Path, expected_board: str | None = None):
    selected = Path(selected)
    if not selected.exists():
        raise services.FlasherError("Ausgewählte Firmware-Datei existiert nicht.")

    root = services.PATHS.firmware / "local" / f"{time.strftime('%Y%m%d-%H%M%S')}-{selected.stem[:50]}"
    root.mkdir(parents=True, exist_ok=True)
    if selected.suffix.lower() == ".zip":
        try:
            _safe_extract(selected, root)
        except (zipfile.BadZipFile, RuntimeError) as exc:
            raise services.FlasherError(f"Firmware-ZIP konnte nicht gelesen werden: {exc}") from exc
    else:
        _copy_neighbours(selected, root)

    files = [p for p in root.rglob("*") if p.is_file()]
    names = [selected.name, *[p.name for p in files]]
    board_key = _infer_board(services, names, expected_board)
    version, build, artifact_name = _version_build(names, services.JARNSEN_BASE_VERSION)

    client = services.GitHubFirmwareClient()
    resolver = getattr(client, "_resolve_bundle_files", None)
    if not callable(resolver):
        raise services.FlasherError("Lokaler Firmware-Resolver ist noch nicht geladen.")
    try:
        bundle = resolver(
            board_key=board_key,
            run_id=0,
            run_number=build,
            artifact_id=0,
            artifact_name=artifact_name,
            cache_root=root,
            version=version,
        )
    except Exception as exc:
        raise services.FlasherError(
            "Lokales Paket ist nicht vollständig. Am sichersten das komplette JARNSEN-MESH-Artifact-ZIP auswählen. "
            f"Details: {exc}"
        ) from exc

    bundle.local_source = str(selected)
    bundle.local_source_name = selected.name
    _emit(
        f"LOCAL FIRMWARE READY source={str(selected)!r} board={board_key!r} "
        f"version={version!r} build={build} files={[p.name for p in files]!r}"
    )
    return bundle


def install(services: Any) -> None:
    original_resolve = services.GitHubFirmwareClient.resolve_latest
    services._jarnsen_local_firmware_bundle = None

    def resolve_latest(self, board_key: str):
        local = getattr(services, "_jarnsen_local_firmware_bundle", None)
        if local is not None and getattr(local, "board_key", None) == board_key:
            _emit(
                f"FIRMWARE SOURCE local board={board_key!r} source={getattr(local, 'local_source', '')!r}"
            )
            return local
        return original_resolve(self, board_key)

    services.GitHubFirmwareClient.resolve_latest = resolve_latest

    try:
        import customtkinter as ctk
        from tkinter import filedialog, messagebox
        import types

        original_root_init = ctk.CTk.__init__

        def root_init(self: Any, *args: Any, **kwargs: Any) -> None:
            original_root_init(self, *args, **kwargs)

            def patch_app() -> None:
                if not hasattr(self, "check_firmware") or not hasattr(self, "firmware_var"):
                    try: self.after(100, patch_app)
                    except Exception: pass
                    return
                if getattr(self, "_jarnsen_local_firmware_ui", False):
                    return
                self._jarnsen_local_firmware_ui = True

                def walk(widget: Any):
                    yield widget
                    for child in widget.winfo_children():
                        yield from walk(child)

                firmware_button = None
                for widget in walk(self):
                    if isinstance(widget, ctk.CTkButton):
                        try: text = str(widget.cget("text"))
                        except Exception: text = ""
                        if text == "Neueste Firmware prüfen":
                            firmware_button = widget; break
                if firmware_button is None:
                    _emit("LOCAL FIRMWARE UI button-target not found")
                    return

                card = firmware_button.master
                row = ctk.CTkFrame(card, fg_color="transparent")
                row.pack(fill="x", padx=18, pady=(0, 14))

                def choose_local() -> None:
                    filename = filedialog.askopenfilename(
                        parent=self,
                        title="JARNSEN-MESH Firmware-Datei vom PC auswählen",
                        filetypes=[
                            ("JARNSEN-MESH Artifact", "*.zip *.bin *.uf2 *.txt"),
                            ("ZIP-Artifact", "*.zip"),
                            ("Firmware", "*.bin *.uf2"),
                            ("Alle Dateien", "*.*"),
                        ],
                    )
                    if not filename:
                        return
                    try:
                        expected = self._selected_board_key()
                        bundle = prepare_local_bundle(services, Path(filename), expected)
                        services._jarnsen_local_firmware_bundle = bundle
                        self.bundle = bundle
                        self.firmware_var.set(
                            f"{bundle.display_name} · PC-Datei: {Path(filename).name}"
                        )
                        self._append_log(
                            f"FIRMWAREQUELLE · PC-Datei · {filename} · Board={services.BOARD_PROFILES[bundle.board_key]['label']}"
                        )
                        self._set_status(f"Lokale Firmware bereit · {Path(filename).name}")
                    except Exception as exc:
                        self._show_error(exc)

                ctk.CTkButton(
                    row,
                    text="Datei vom PC auswählen",
                    command=choose_local,
                    fg_color=("gray72", "gray28"),
                    hover_color=("gray65", "gray35"),
                ).pack(side="left")

                original_check = self.check_firmware
                def check_github(app_self: Any) -> None:
                    services._jarnsen_local_firmware_bundle = None
                    app_self._append_log("FIRMWAREQUELLE · GitHub · lokale Auswahl verworfen")
                    return original_check()
                self.check_firmware = types.MethodType(check_github, self)
                try: firmware_button.configure(command=self.check_firmware)
                except Exception: pass
                _emit("LOCAL FIRMWARE UI installed")

            try: self.after(180, patch_app)
            except Exception: pass

        ctk.CTk.__init__ = root_init
    except Exception as exc:
        _emit(f"LOCAL FIRMWARE UI failed type={type(exc).__name__} message={exc}")

    _emit("LOCAL FIRMWARE installed zip/bin/uf2 selection=1")
