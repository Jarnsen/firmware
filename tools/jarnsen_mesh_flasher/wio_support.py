from __future__ import annotations

import ctypes
import os
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


def _notify_flash(services: Any, fraction: float, stage: str, detail: str = "") -> None:
    callback = getattr(services, "_jarnsen_flash_progress_callback", None)
    if callable(callback):
        try:
            callback(max(0.0, min(1.0, float(fraction))), stage, detail)
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
    progress: Callable[[float], None] | None = None,
) -> Path:
    started = time.monotonic()
    deadline = started + timeout
    last_seen: list[Path] = []
    last_second = -1
    while time.monotonic() < deadline:
        elapsed = time.monotonic() - started
        second = int(elapsed)
        if second != last_second:
            last_second = second
            if progress:
                progress(min(1.0, elapsed / timeout))
            if log and second and second % 5 == 0:
                log(f"Wio UF2 · Bootloader-Laufwerk suchen · {second}s/{int(timeout)}s")
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
        _emit(f"WIO SAFETY BACKUP config={str(target)!r} bytes={target.stat().st_size}")
        return target

    services.backup_flash = backup_flash
    base_flash_bundle = services.flash_bundle

    def flash_bundle(port: str, bundle: Any, log: Callable[[str], None] | None = None) -> None:
        if bundle.board_key != "wio":
            return base_flash_bundle(port, bundle, log=log)

        uf2 = Path(bundle.update)
        if not uf2.exists() or uf2.suffix.lower() != ".uf2":
            raise services.FlasherError(f"Wio UF2-Datei fehlt oder ist ungültig: {uf2}")

        total = uf2.stat().st_size
        if log:
            log(f"Wio Tracker L1 · UF2={uf2.name} · Größe={total} Bytes · Bootloader wird gesucht")
            log("Wio UF2 · Falls kein Laufwerk erscheint: RESET zweimal schnell drücken.")
        _notify_flash(services, 0.01, "Wio UF2", "1200-Baud Bootloader-Anforderung")

        before = {str(path).casefold() for path in _uf2_drives()}
        _touch_1200(port)
        try:
            drive = _wait_for_uf2_drive(
                before=before,
                timeout=60.0,
                log=log,
                progress=lambda f: _notify_flash(
                    services, 0.02 + 0.10 * f, "Wio UF2", f"Bootloader suchen · {f*100:.0f}%"
                ),
            )
        except RuntimeError as exc:
            raise services.FlasherError(str(exc)) from exc

        target = drive / uf2.name
        _emit(f"WIO UF2 COPY START source={str(uf2)!r} target={str(target)!r} bytes={total}")
        if log:
            log(f"Wio UF2 · Laufwerk gefunden: {drive} · Ziel={target.name}")

        copied = 0
        last_percent = -1
        try:
            with uf2.open("rb") as source, target.open("wb") as destination:
                while True:
                    chunk = source.read(128 * 1024)
                    if not chunk:
                        break
                    destination.write(chunk)
                    copied += len(chunk)
                    fraction = copied / total if total else 1.0
                    percent = int(fraction * 100)
                    _notify_flash(
                        services,
                        0.12 + 0.80 * fraction,
                        "Wio UF2 schreiben",
                        f"{percent}% · {copied/(1024*1024):.2f}/{total/(1024*1024):.2f} MB",
                    )
                    if log and (percent != last_percent) and (percent % 2 == 0 or percent >= 100):
                        last_percent = percent
                        log(
                            f"Wio UF2 · Schreiben {percent}% · "
                            f"{copied/(1024*1024):.2f}/{total/(1024*1024):.2f} MB"
                        )
                destination.flush()
                try:
                    os.fsync(destination.fileno())
                except Exception:
                    pass
        except Exception as exc:
            raise services.FlasherError(f"Wio UF2-Kopie fehlgeschlagen: {exc}") from exc

        _emit(f"WIO UF2 COPY END target={str(target)!r} bytes={copied}")
        if log:
            log(f"Wio UF2 vollständig übertragen · {drive} · {copied} Bytes")
        _notify_flash(services, 0.94, "Wio UF2", "Bootloader-Neustart abwarten")

        deadline = time.monotonic() + 25.0
        while time.monotonic() < deadline:
            try:
                if not (drive / "INFO_UF2.TXT").exists():
                    break
            except Exception:
                break
            time.sleep(0.5)
        _notify_flash(services, 1.0, "Wio UF2", "fertig")

    services.flash_bundle = flash_bundle

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
        original_root_init = ctk.CTk.__init__

        def root_init(self: Any, *args: Any, **kwargs: Any) -> None:
            original_root_init(self, *args, **kwargs)

            def patch_app() -> None:
                if not hasattr(self, "_selected_board_key"):
                    try: self.after(100, patch_app)
                    except Exception: pass
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
                    try: before_key = app_self._selected_board_key()
                    except Exception: pass
                    original_changed(value)
                    if existing is not None and before_key == getattr(existing, "board_key", None):
                        app_self.bundle = existing
                        try: app_self.firmware_var.set(existing.display_name)
                        except Exception: pass
                        _emit(
                            f"FIRMWARE PRESERVED AFTER DEVICE REFRESH board={existing.board_key!r} "
                            f"artifact={existing.artifact_name!r}"
                        )

                self._device_changed = types.MethodType(device_changed, self)
                _emit("WIO APP PATCH installed: manual-board + firmware-preserve")

            try: self.after(100, patch_app)
            except Exception: pass

        ctk.CTk.__init__ = root_init
    except Exception as exc:
        _emit(f"WIO UI PATCH failed type={type(exc).__name__} message={exc}")

    _emit("WIO SUPPORT installed: board + UF2 flash + config backup + live-progress")
