from __future__ import annotations

import ctypes
import os
import shutil
import time
import types
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _uf2_drives() -> list[Path]:
    drives: list[Path] = []
    if os.name != "nt":
        return drives
    try:
        mask = int(ctypes.windll.kernel32.GetLogicalDrives())
    except Exception:
        mask = 0
    for index in range(26):
        if mask and not (mask & (1 << index)):
            continue
        root = Path(f"{chr(ord('A') + index)}:\\")
        try:
            info = root / "INFO_UF2.TXT"
            if root.exists() and info.exists():
                drives.append(root)
                try:
                    preview = info.read_text(encoding="utf-8", errors="replace")[:2000]
                except Exception:
                    preview = ""
                _emit(f"WIO UF2 DRIVE root={str(root)!r} info={preview!r}")
        except Exception:
            continue
    return drives


def _touch_1200(port: str) -> None:
    try:
        import serial

        handle = serial.Serial(port=port, baudrate=1200, timeout=0.2, write_timeout=0.2)
        try:
            handle.dtr = False
            handle.rts = False
            time.sleep(0.15)
        finally:
            handle.close()
        _emit(f"WIO UF2 1200-BAUD TOUCH port={port} result=ok")
    except Exception as exc:
        _emit(f"WIO UF2 1200-BAUD TOUCH port={port} result=ignored error={type(exc).__name__}:{exc}")


def _wait_for_uf2_drive(
    *,
    before: set[str],
    timeout: float,
    log: Callable[[str], None] | None,
) -> Path:
    deadline = time.monotonic() + timeout
    last_seen: list[Path] = []
    while time.monotonic() < deadline:
        current = _uf2_drives()
        last_seen = current
        new = [path for path in current if str(path).casefold() not in before]
        if len(new) == 1:
            return new[0]
        if not before and len(current) == 1:
            return current[0]
        time.sleep(0.5)

    visible = ", ".join(str(path) for path in last_seen) or "keines"
    raise RuntimeError(
        "Wio Tracker L1: UF2-Bootloader-Laufwerk nicht gefunden. "
        "Bitte RESET zweimal schnell drücken, bis das UF2-Laufwerk erscheint, "
        f"und erneut starten. Sichtbare UF2-Laufwerke: {visible}"
    )


def install(services: Any) -> None:
    """Add Seeed Wio Tracker L1 as a first-class JARNSEN-MESH board."""
    services.BOARD_PROFILES["wio"] = {
        "label": "Seeed Wio Tracker L1",
        "pio_env": "seeed_wio_tracker_L1",
        "branch": services.UNIFIED_BRANCH,
        "workflow_path": services.UNIFIED_WORKFLOW_PATH,
        "artifact_prefix": f"JARNSEN-MESH-Seeed-Wio-Tracker-L1-v{services.JARNSEN_BASE_VERSION}",
        "artifact_kind": "uf2",
        "match": (
            "WIO_TRACKER_L1",
            "WIO TRACKER L1",
            "SEEED WIO TRACKER L1",
            "SEEED_WIO_TRACKER_L1",
            "seeed_wio_tracker_L1",
        ),
    }

    base_detect = services.detect_board_from_text

    def detect_board_from_text(text: str) -> str | None:
        detected = base_detect(text)
        if detected:
            return detected
        upper = (text or "").upper().replace("-", "_")
        for token in services.BOARD_PROFILES["wio"]["match"]:
            if str(token).upper().replace("-", "_") in upper:
                _emit(f"WIO BOARD DETECTION matched={token!r}")
                return "wio"
        return None

    services.detect_board_from_text = detect_board_from_text

    # Existing FirmwareBundle fields are Path-based. For UF2 bundles the single
    # verified UF2 image is stored in factory/update/webflasher aliases so the
    # rest of the UI can keep using one bundle type.
    base_backup_flash = services.backup_flash

    def backup_flash(port: str, board_key: str) -> Path:
        if board_key != "wio":
            return base_backup_flash(port, board_key)
        services.PATHS.backups.mkdir(parents=True, exist_ok=True)
        target = services.PATHS.backups / (
            f"wio-{port}-{datetime.now().strftime('%Y%m%d-%H%M%S')}-config.yaml"
        )
        services.meshtastic(port, "--export-config", str(target), timeout=90)
        if not target.exists() or target.stat().st_size < 20:
            raise services.FlasherError("Wio-Konfigurationsbackup wurde nicht vollständig erstellt.")
        _emit(f"WIO SAFETY BACKUP config={str(target)!r}")
        return target

    services.backup_flash = backup_flash

    base_flash_bundle = services.flash_bundle

    def flash_bundle(port: str, bundle: Any, log: Callable[[str], None] | None = None) -> None:
        if bundle.board_key != "wio":
            return base_flash_bundle(port, bundle, log=log)

        uf2 = Path(bundle.update)
        if not uf2.exists() or uf2.suffix.lower() != ".uf2":
            raise services.FlasherError(f"Wio UF2-Datei fehlt oder ist ungültig: {uf2}")

        if log:
            log(f"Wio Tracker L1 · UF2={uf2.name} · Bootloader wird gesucht")
            log("Falls kein Laufwerk erscheint: RESET am Wio zweimal schnell drücken.")

        before = {str(path).casefold() for path in _uf2_drives()}
        _touch_1200(port)
        try:
            drive = _wait_for_uf2_drive(before=before, timeout=60.0, log=log)
        except RuntimeError as exc:
            raise services.FlasherError(str(exc)) from exc

        target = drive / uf2.name
        _emit(f"WIO UF2 COPY START source={str(uf2)!r} target={str(target)!r} bytes={uf2.stat().st_size}")
        try:
            with uf2.open("rb") as source, target.open("wb") as destination:
                shutil.copyfileobj(source, destination, length=1024 * 1024)
                destination.flush()
                try:
                    os.fsync(destination.fileno())
                except Exception:
                    pass
        except Exception as exc:
            raise services.FlasherError(f"Wio UF2-Kopie fehlgeschlagen: {exc}") from exc

        _emit(f"WIO UF2 COPY END target={str(target)!r}")
        if log:
            log(f"Wio UF2 übertragen · {drive}")

        # The bootloader normally unmounts itself after accepting the UF2.
        deadline = time.monotonic() + 25.0
        while time.monotonic() < deadline:
            try:
                if not (drive / "INFO_UF2.TXT").exists():
                    break
            except Exception:
                break
            time.sleep(0.5)

    services.flash_bundle = flash_bundle

    # Add Wio to the existing board OptionMenu without changing app.py.
    try:
        import customtkinter as ctk

        original_option_init = ctk.CTkOptionMenu.__init__

        def option_init(self: Any, master: Any, *args: Any, **kwargs: Any) -> None:
            values = list(kwargs.get("values") or [])
            if "Automatisch" in values and services.BOARD_PROFILES["tracker"]["label"] in values:
                wio_label = services.BOARD_PROFILES["wio"]["label"]
                if wio_label not in values:
                    values.append(wio_label)
                    kwargs["values"] = values
            original_option_init(self, master, *args, **kwargs)

        ctk.CTkOptionMenu.__init__ = option_init

        # Once the concrete FlasherApp instance exists, make manual board
        # selection generic and keep an already resolved firmware bundle during
        # serial refreshes when the selected board has not changed.
        original_root_init = ctk.CTk.__init__

        def root_init(self: Any, *args: Any, **kwargs: Any) -> None:
            original_root_init(self, *args, **kwargs)

            def patch_app() -> None:
                if not hasattr(self, "_selected_board_key"):
                    try:
                        self.after(100, patch_app)
                    except Exception:
                        pass
                    return
                if getattr(self, "_jarnsen_wio_app_patch", False):
                    return
                self._jarnsen_wio_app_patch = True

                original_selected = self._selected_board_key

                def selected_board_key(app_self: Any) -> str | None:
                    manual = str(app_self.board_var.get())
                    for key, profile in services.BOARD_PROFILES.items():
                        if manual == str(profile["label"]):
                            return key
                    return original_selected()

                self._selected_board_key = types.MethodType(selected_board_key, self)

                original_changed = self._device_changed

                def device_changed(app_self: Any, value: str | None = None) -> None:
                    existing = getattr(app_self, "bundle", None)
                    before_key = None
                    try:
                        before_key = app_self._selected_board_key()
                    except Exception:
                        pass
                    original_changed(value)
                    if existing is not None and before_key == getattr(existing, "board_key", None):
                        app_self.bundle = existing
                        try:
                            app_self.firmware_var.set(existing.display_name)
                        except Exception:
                            pass
                        _emit(
                            f"FIRMWARE PRESERVED AFTER DEVICE REFRESH board={existing.board_key!r} "
                            f"artifact={existing.artifact_name!r}"
                        )

                self._device_changed = types.MethodType(device_changed, self)
                _emit("WIO APP PATCH installed: manual-board + firmware-preserve")

            try:
                self.after(100, patch_app)
            except Exception:
                pass

        ctk.CTk.__init__ = root_init
    except Exception as exc:
        _emit(f"WIO UI PATCH failed type={type(exc).__name__} message={exc}")

    _emit("WIO SUPPORT installed: board + UF2 flash + config backup")
