from __future__ import annotations

import os
import queue
import re
import subprocess
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


def _notify_flash(services: Any, fraction: float, stage: str, detail: str = "") -> None:
    callback = getattr(services, "_jarnsen_flash_progress_callback", None)
    if callable(callback):
        try:
            callback(max(0.0, min(1.0, float(fraction))), str(stage), str(detail))
        except Exception as exc:
            _emit(f"FLASH UI CALLBACK ERROR type={type(exc).__name__} message={exc}")


def _stream_esptool(
    services: Any,
    port: str,
    args: list[str],
    *,
    timeout: int,
    stage: str,
    phase_start: float,
    phase_end: float,
    log: Callable[[str], None] | None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    cmd = services.helper_command() + ["esptool", "--port", port, *[str(a) for a in args]]
    safe_cmd = subprocess.list2cmdline(cmd)
    _emit(
        f"FLASH PROCESS START stage={stage!r} port={port!r} timeout={timeout}s "
        f"phase={phase_start:.3f}..{phase_end:.3f} cmd={safe_cmd}"
    )
    if log:
        log(f"FLASH TOOL START · {stage} · Port={port} · Timeout={timeout}s")
        log(f"FLASH TOOL CMD · esptool --port {port} {' '.join(str(a) for a in args)}")

    _notify_flash(services, phase_start, stage, "Start")
    started = time.monotonic()
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        startupinfo=services._startupinfo(),
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )

    lines: list[str] = []
    output_queue: queue.Queue[str | None] = queue.Queue()

    def reader() -> None:
        try:
            if proc.stdout is not None:
                for raw in proc.stdout:
                    output_queue.put(raw.rstrip("\r\n"))
        finally:
            output_queue.put(None)

    threading.Thread(target=reader, name=f"flash-output-{stage}", daemon=True).start()
    reader_done = False
    last_percent = -1.0
    deadline = started + timeout

    while True:
        now = time.monotonic()
        if now >= deadline and proc.poll() is None:
            try:
                proc.kill()
            except Exception:
                pass
            elapsed = now - started
            message = f"{stage}: esptool Zeitlimit nach {elapsed:.1f}s erreicht."
            if log:
                log(f"FLASH TOOL TIMEOUT · {message}")
            _emit(message)
            raise subprocess.TimeoutExpired(cmd, timeout, output="\n".join(lines))

        try:
            item = output_queue.get(timeout=0.15)
        except queue.Empty:
            item = "__NO_LINE__"

        if item is None:
            reader_done = True
        elif item != "__NO_LINE__":
            line = str(item)
            if line:
                lines.append(line)
                if log:
                    log(f"esptool · {stage} · {line}")
                _emit(f"FLASH TOOL OUTPUT stage={stage!r}> {line}")
                matches = re.findall(r"(\d+(?:\.\d+)?)\s*%", line)
                if matches:
                    try:
                        percent = max(0.0, min(100.0, float(matches[-1])))
                    except Exception:
                        percent = -1.0
                    if percent >= 0 and (percent >= last_percent + 0.5 or percent >= 100.0):
                        last_percent = percent
                        phase = phase_start + (phase_end - phase_start) * (percent / 100.0)
                        _notify_flash(services, phase, stage, f"{percent:.1f}%")

        if proc.poll() is not None and reader_done and output_queue.empty():
            break

    returncode = int(proc.wait())
    elapsed = time.monotonic() - started
    output = "\n".join(lines)
    _notify_flash(services, phase_end, stage, f"fertig · {elapsed:.1f}s")
    _emit(f"FLASH PROCESS END stage={stage!r} exit={returncode} duration={elapsed:.3f}s")
    if log:
        log(f"FLASH TOOL ENDE · {stage} · Exit={returncode} · Dauer={elapsed:.1f}s")
    result = subprocess.CompletedProcess(cmd, returncode, output, "")
    if check and returncode != 0:
        raise services.FlasherError(output.strip() or f"{stage} fehlgeschlagen (Exit {returncode})")
    return result


def install(services: Any) -> None:
    """Full-backup UX plus detailed, streamed Unified-Core flashing."""

    base_backup_flash = services.backup_flash
    base_flash_bundle = services.flash_bundle
    services._jarnsen_flash_baud = str(getattr(services, "_jarnsen_flash_baud", "921600"))

    def backup_flash(port: str, board_key: str) -> Path:
        if board_key == "wio":
            return base_backup_flash(port, board_key)

        _notify_backup(services, 0, 1, "Flash-Größe ermitteln")
        result = services.esptool(port, "flash-id", timeout=45)
        text = "\n".join(filter(None, (result.stdout, result.stderr)))
        match = re.search(r"Detected flash size:\s*(\d+)MB", text, re.IGNORECASE)
        if not match:
            raise services.FlasherError("Flash-Größe konnte nicht ermittelt werden.")
        size = int(match.group(1)) * 1024 * 1024

        services.PATHS.backups.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = services.PATHS.backups / f"{board_key}-{port}-{timestamp}.bin"
        _emit(f"BACKUP START port={port} board={board_key} bytes={size} target={str(target)!r}")

        stop = threading.Event()
        last_percent = {-1}

        def monitor() -> None:
            while not stop.wait(0.25):
                try:
                    done = target.stat().st_size if target.exists() else 0
                except Exception:
                    done = 0
                done = max(0, min(int(done), size))
                percent = int((done * 100) / size) if size else 0
                if percent != last_percent[0]:
                    last_percent[0] = percent
                    _notify_backup(services, done, size, "Sicherheitsbackup lesen")
                    _emit(
                        f"BACKUP PROGRESS port={port} board={board_key} "
                        f"percent={percent} bytes={done}/{size}"
                    )

        watcher = threading.Thread(target=monitor, name="jarnsen-backup-progress", daemon=True)
        watcher.start()
        started = time.monotonic()
        try:
            services.esptool(port, "read-flash", "0x0", hex(size), str(target), timeout=900)
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
            _notify_flash(services, 0.0, "Wio UF2", "Bootloader vorbereiten")
            result = base_flash_bundle(port, bundle, log=log)
            _notify_flash(services, 1.0, "Wio UF2", "übertragen")
            return result

        factory = Path(bundle.factory)
        webflasher = Path(bundle.webflasher)
        if not factory.exists() or not webflasher.exists():
            raise services.FlasherError("Factory-/Webflasher-Datei fehlt im Firmwarepaket.")

        baud = str(getattr(services, "_jarnsen_flash_baud", "921600"))
        if baud not in {"115200", "230400", "460800", "921600"}:
            baud = "921600"
        local_source = getattr(bundle, "local_source", "")
        source_text = f"PC-Datei={local_source}" if local_source else f"GitHub-Artifact={bundle.artifact_name}"

        if log:
            log(
                f"FLASH START · Board={services.BOARD_PROFILES[bundle.board_key]['label']} · "
                f"Port={port} · Baud={baud} · {source_text}"
            )
            log(f"FLASH DATEI · Factory={factory.name} · {factory.stat().st_size} Bytes")
            log(f"FLASH DATEI · Dual-Slot={webflasher.name} · {webflasher.stat().st_size} Bytes")
            log("FLASHPLAN · Löschen → 0x0 Factory → 0x10000 Dual-Slot-Webflasher (app0 + app1) → Start")

        _emit(
            f"FLASH PLAN port={port} board={bundle.board_key} baud={baud} "
            f"factory=0x0:{factory.name!r}:{factory.stat().st_size} "
            f"dual_slot=0x10000:{webflasher.name!r}:{webflasher.stat().st_size} "
            f"source={source_text!r} duplicate_app1_write=0"
        )

        _stream_esptool(
            services, port, ["erase-flash"], timeout=180,
            stage="Flash löschen", phase_start=0.00, phase_end=0.05, log=log,
        )
        _stream_esptool(
            services,
            port,
            [
                "--baud", baud, "write-flash", "--flash-mode", "dio", "--flash-freq", "80m",
                "--flash-size", "keep", "0x0", str(factory),
            ],
            timeout=600,
            stage="Factory schreiben",
            phase_start=0.05,
            phase_end=0.30,
            log=log,
        )
        _stream_esptool(
            services,
            port,
            [
                "--baud", baud, "write-flash", "--flash-mode", "dio", "--flash-freq", "80m",
                "--flash-size", "keep", "0x10000", str(webflasher),
            ],
            timeout=900,
            stage="Dual-Slot schreiben",
            phase_start=0.30,
            phase_end=0.98,
            log=log,
        )
        _stream_esptool(
            services, port, ["run"], timeout=30,
            stage="Node starten", phase_start=0.98, phase_end=1.00, log=log, check=False,
        )
        if log:
            log("FLASH ENDE · alle Images geschrieben · Node-Start ausgelöst")

    services.backup_flash = backup_flash
    services.flash_bundle = flash_bundle

    try:
        from profile_restore import install as install_profile_restore
        install_profile_restore(services)
        _emit("FLASH RUNTIME profile-restore-layer=installed")
    except Exception as exc:
        _emit(
            f"FLASH RUNTIME profile-restore-layer=failed type={type(exc).__name__} message={exc}"
        )
        raise

    try:
        import customtkinter as ctk
        original_root_init = ctk.CTk.__init__

        def root_init(self: Any, *args: Any, **kwargs: Any) -> None:
            original_root_init(self, *args, **kwargs)

            def patch_app() -> None:
                if not hasattr(self, "_perform_flash") or not hasattr(self, "_set_progress"):
                    try: self.after(100, patch_app)
                    except Exception: pass
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
                    backup_ref: dict[str, Any] = {}
                    flash_ref: dict[str, Any] = {}

                    def backup_progress(done: int, total: int, stage: str) -> None:
                        if total <= 0:
                            return
                        if total == 1:
                            app_self._set_progress(0.27, f"{prefix}{stage} …")
                            return
                        fraction = max(0.0, min(1.0, float(done) / float(total)))
                        value = 0.27 + 0.15 * fraction
                        pct = fraction * 100.0
                        done_mb = done / (1024 * 1024)
                        total_mb = total / (1024 * 1024)
                        app_self._set_progress(
                            value,
                            f"{prefix}{stage} · {pct:.1f}% · {done_mb:.2f}/{total_mb:.2f} MB",
                        )

                    def flash_progress(fraction: float, stage: str, detail: str) -> None:
                        value = 0.42 + 0.28 * max(0.0, min(1.0, fraction))
                        suffix = f" · {detail}" if detail else ""
                        app_self._set_progress(value, f"{prefix}{stage}{suffix}")

                    backup_ref["value"] = backup_progress
                    flash_ref["value"] = flash_progress
                    services._jarnsen_backup_progress_callback = backup_progress
                    services._jarnsen_flash_progress_callback = flash_progress
                    try:
                        app_self._append_log(
                            f"{prefix}ABLAUF START · Port={port} · Board={services.BOARD_PROFILES[board_key]['label']} · "
                            f"Baud={getattr(services, '_jarnsen_flash_baud', '921600')}"
                        )
                        return original_perform(
                            port, board_key, long_name, short_name,
                            series_index=series_index, strict_preflight=strict_preflight,
                        )
                    finally:
                        if getattr(services, "_jarnsen_backup_progress_callback", None) is backup_ref["value"]:
                            services._jarnsen_backup_progress_callback = None
                        if getattr(services, "_jarnsen_flash_progress_callback", None) is flash_ref["value"]:
                            services._jarnsen_flash_progress_callback = None

                self._perform_flash = types.MethodType(perform_flash, self)
                _emit("FLASH RUNTIME APP PATCH installed backup-progress=1pct flash-live-progress=1")

            try: self.after(120, patch_app)
            except Exception: pass

        ctk.CTk.__init__ = root_init  # type: ignore[assignment]
    except Exception as exc:
        _emit(f"FLASH RUNTIME UI PATCH failed type={type(exc).__name__} message={exc}")

    _emit(
        "FLASH RUNTIME installed backup-progress=1pct streamed-esptool=1 selectable-baud=1 "
        "unified-dual-slot=single-write staged-profile-restore=1"
    )
