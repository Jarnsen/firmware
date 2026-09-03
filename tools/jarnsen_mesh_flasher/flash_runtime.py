from __future__ import annotations

import threading
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


def _notify_backup(services: Any, done: int, total: int, stage: str) -> None:
    callback = getattr(services, "_jarnsen_backup_progress_callback", None)
    if callable(callback):
        try:
            callback(int(done), int(total), str(stage))
        except Exception as exc:
            _emit(f"BACKUP UI CALLBACK ERROR type={type(exc).__name__} message={exc}")


def install(services: Any) -> None:
    """Fix ESP32 full-backup UX and Unified-Core dual-slot flashing.

    The Unified-Core *.webflasher.bin is already one contiguous image containing
    app0 at offset 0 within the file, padding up to the second slot, and app1.
    It therefore has to be written once at flash address 0x10000. Passing the
    same file again at 0x340000 makes esptool correctly reject the overlap.
    """

    base_backup_flash = services.backup_flash
    base_flash_bundle = services.flash_bundle

    def backup_flash(port: str, board_key: str) -> Path:
        # Wio uses the config-only UF2 safety backup supplied by wio_support.
        if board_key == "wio":
            return base_backup_flash(port, board_key)

        _notify_backup(services, 0, 1, "Flash-Größe ermitteln")
        result = services.esptool(port, "flash-id", timeout=45)
        text = "\n".join(filter(None, (result.stdout, result.stderr)))

        import re

        match = re.search(r"Detected flash size:\s*(\d+)MB", text, re.IGNORECASE)
        if not match:
            raise services.FlasherError("Flash-Größe konnte nicht ermittelt werden.")
        size = int(match.group(1)) * 1024 * 1024

        services.PATHS.backups.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = services.PATHS.backups / f"{board_key}-{port}-{timestamp}.bin"

        stop = threading.Event()
        last_bucket = {-1}

        def monitor() -> None:
            while not stop.wait(0.45):
                try:
                    done = target.stat().st_size if target.exists() else 0
                except Exception:
                    done = 0
                done = max(0, min(int(done), size))
                percent = int((done * 100) / size) if size else 0
                bucket = min(20, percent // 5)
                if bucket != last_bucket[0]:
                    last_bucket[0] = bucket
                    _notify_backup(services, done, size, "Sicherheitsbackup lesen")
                    _emit(
                        f"BACKUP PROGRESS port={port} board={board_key} "
                        f"percent={percent} bytes={done}/{size}"
                    )

        watcher = threading.Thread(target=monitor, name="jarnsen-backup-progress", daemon=True)
        watcher.start()
        started = time.monotonic()
        try:
            services.esptool(
                port,
                "read-flash",
                "0x0",
                hex(size),
                str(target),
                timeout=900,
            )
        finally:
            stop.set()
            watcher.join(timeout=1.0)

        if not target.exists() or target.stat().st_size != size:
            actual = target.stat().st_size if target.exists() else 0
            raise services.FlasherError(
                f"Sicherheitsbackup wurde nicht vollständig erstellt ({actual}/{size} Bytes)."
            )

        _notify_backup(services, size, size, "Sicherheitsbackup vollständig")
        _emit(
            f"BACKUP COMPLETE port={port} board={board_key} bytes={size} "
            f"duration={time.monotonic() - started:.1f}s target={str(target)!r}"
        )
        return target

    def flash_bundle(port: str, bundle: Any, log: Callable[[str], None] | None = None) -> None:
        if getattr(bundle, "board_key", None) == "wio":
            return base_flash_bundle(port, bundle, log=log)

        factory = Path(bundle.factory)
        webflasher = Path(bundle.webflasher)
        if not factory.exists() or not webflasher.exists():
            raise services.FlasherError("Factory-/Webflasher-Datei fehlt im Firmwarepaket.")

        if log:
            log(
                f"JARNSEN-MESH v{bundle.version} · Factory={factory.name} · "
                f"Dual-Slot={webflasher.name}"
            )
            log("Flashplan · 0x0 Factory · 0x10000 Dual-Slot-Webflasher (app0 + app1)")

        _emit(
            f"FLASH PLAN port={port} board={bundle.board_key} factory=0x0:{factory.name!r} "
            f"dual_slot=0x10000:{webflasher.name!r} duplicate_app1_write=0"
        )

        services.esptool(port, "erase-flash", timeout=180)
        services.esptool(
            port,
            "--baud",
            "921600",
            "write-flash",
            "--flash-mode",
            "dio",
            "--flash-freq",
            "80m",
            "--flash-size",
            "keep",
            "0x0",
            str(factory),
            timeout=600,
        )

        # The build pipeline creates webflasher.bin as:
        #   app0 + 0xff padding to SLOT_SIZE + app1
        # and documents it for writing at 0x10000. Do not add a second 0x340000
        # address/file pair: that overlaps the first file's app1 region.
        services.esptool(
            port,
            "--baud",
            "921600",
            "write-flash",
            "--flash-mode",
            "dio",
            "--flash-freq",
            "80m",
            "--flash-size",
            "keep",
            "0x10000",
            str(webflasher),
            timeout=600,
        )
        services.esptool(port, "run", timeout=30, check=False)

    services.backup_flash = backup_flash
    services.flash_bundle = flash_bundle

    # Profile restore is deliberately installed here as part of the flash
    # runtime so app.py imports the safe staged restore/reboot functions from
    # services after runtime_config has completed.
    try:
        from profile_restore import install as install_profile_restore

        install_profile_restore(services)
        _emit("FLASH RUNTIME profile-restore-layer=installed")
    except Exception as exc:
        _emit(
            f"FLASH RUNTIME profile-restore-layer=failed "
            f"type={type(exc).__name__} message={exc}"
        )
        raise

    # Connect backup progress to the existing full-HD progress bar without
    # rewriting app.py. _perform_flash still owns the overall 0.27..0.42 range.
    try:
        import customtkinter as ctk

        original_root_init = ctk.CTk.__init__

        def root_init(self: Any, *args: Any, **kwargs: Any) -> None:
            original_root_init(self, *args, **kwargs)

            def patch_app() -> None:
                if not hasattr(self, "_perform_flash") or not hasattr(self, "_set_progress"):
                    try:
                        self.after(100, patch_app)
                    except Exception:
                        pass
                    return
                if getattr(self, "_jarnsen_flash_runtime_patch", False):
                    return
                self._jarnsen_flash_runtime_patch = True

                original_perform = self._perform_flash

                def perform_flash(
                    app_self: Any,
                    port: str,
                    board_key: str,
                    long_name: str,
                    short_name: str,
                    *,
                    series_index: int | None = None,
                    strict_preflight: bool = False,
                ):
                    prefix = f"Serie #{series_index} · " if series_index is not None else ""
                    callback_ref: dict[str, Any] = {}

                    def progress(done: int, total: int, stage: str) -> None:
                        if total <= 0:
                            return
                        if total == 1:
                            app_self._set_progress(0.27, f"{prefix}{stage} …")
                            return
                        fraction = max(0.0, min(1.0, float(done) / float(total)))
                        value = 0.27 + 0.15 * fraction
                        pct = int(round(fraction * 100.0))
                        done_mb = done / (1024 * 1024)
                        total_mb = total / (1024 * 1024)
                        app_self._set_progress(
                            value,
                            f"{prefix}{stage} · {pct}% · {done_mb:.1f}/{total_mb:.1f} MB",
                        )

                    callback_ref["value"] = progress
                    services._jarnsen_backup_progress_callback = progress
                    try:
                        return original_perform(
                            port,
                            board_key,
                            long_name,
                            short_name,
                            series_index=series_index,
                            strict_preflight=strict_preflight,
                        )
                    finally:
                        if getattr(services, "_jarnsen_backup_progress_callback", None) is callback_ref["value"]:
                            services._jarnsen_backup_progress_callback = None

                self._perform_flash = types.MethodType(perform_flash, self)
                _emit("FLASH RUNTIME APP PATCH installed backup-progress=1 range=0.27..0.42")

            try:
                self.after(120, patch_app)
            except Exception:
                pass

        ctk.CTk.__init__ = root_init  # type: ignore[assignment]
    except Exception as exc:
        _emit(f"FLASH RUNTIME UI PATCH failed type={type(exc).__name__} message={exc}")

    _emit(
        "FLASH RUNTIME installed backup-progress=5pct unified-dual-slot=single-write "
        "esptool-v5-hyphen-commands=1 staged-profile-restore=1"
    )
