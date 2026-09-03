from __future__ import annotations

import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any


def _emit(message: str) -> None:
    try:
        import diagnostics
        diagnostics._emit(message)
    except Exception:
        pass


def _ui(services: Any, text: str) -> None:
    callback = getattr(services, "_jarnsen_ui_log_callback", None)
    if callable(callback):
        try:
            callback(str(text))
        except Exception:
            pass


def _notify(services: Any, done: int, total: int, stage: str) -> None:
    callback = getattr(services, "_jarnsen_backup_progress_callback", None)
    if callable(callback):
        try:
            callback(int(done), int(total), str(stage))
        except Exception as exc:
            _emit(f"BACKUP STABILITY UI CALLBACK ERROR type={type(exc).__name__} message={exc}")


def _retryable(exc: BaseException) -> bool:
    text = str(exc).lower()
    tokens = (
        "write timeout",
        "read timeout",
        "serial exception",
        "timed out",
        "timeout",
        "semaphore",
        "device couldn't be opened",
        "could not open port",
        "permissionerror",
        "clearcommerror",
    )
    return any(token in text for token in tokens)


def install(services: Any) -> None:
    """Replace the ESP32 full-backup step with a monitored, retryable variant."""

    previous_backup = services.backup_flash

    def backup_flash(port: str, board_key: str) -> Path:
        if board_key == "wio":
            return previous_backup(port, board_key)

        _notify(services, 0, 1, "Flash-Größe ermitteln")
        _ui(services, f"BACKUP · Flash-Größe ermitteln · Port={port} · Board={board_key}")
        result = services.esptool(port, "flash-id", timeout=45)
        text = "\n".join(filter(None, (result.stdout, result.stderr)))
        match = re.search(r"Detected flash size:\s*(\d+)MB", text, re.IGNORECASE)
        if not match:
            raise services.FlasherError("Flash-Größe konnte nicht ermittelt werden.")

        size = int(match.group(1)) * 1024 * 1024
        services.PATHS.backups.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = services.PATHS.backups / f"{board_key}-{port}-{timestamp}.bin"

        # Full backup is intentionally more conservative than the selected
        # write baud. A backup is safety data; reliability wins over speed.
        attempts = ("460800", "230400", "115200")
        _ui(
            services,
            f"BACKUP START · Ziel={target} · Größe={size / (1024 * 1024):.1f} MB · "
            f"Versuche={len(attempts)} · Baudfolge={' → '.join(attempts)}",
        )
        _emit(
            f"BACKUP STABILITY START port={port} board={board_key} bytes={size} "
            f"target={str(target)!r} bauds={attempts!r}"
        )

        last_error: BaseException | None = None
        overall_started = time.monotonic()

        for attempt_index, baud in enumerate(attempts, start=1):
            try:
                target.unlink(missing_ok=True)
            except Exception:
                pass

            stop = threading.Event()
            state = {
                "last_percent": -1,
                "last_done": -1,
                "last_ui": 0.0,
            }
            attempt_started = time.monotonic()

            def monitor() -> None:
                while not stop.wait(0.25):
                    try:
                        done = target.stat().st_size if target.exists() else 0
                    except Exception:
                        done = 0
                    done = max(0, min(int(done), size))
                    percent = int((done * 100) / size) if size else 0
                    now = time.monotonic()
                    changed = percent != state["last_percent"] or done != state["last_done"]
                    heartbeat = (now - state["last_ui"]) >= 2.0
                    if not changed and not heartbeat:
                        continue

                    state["last_percent"] = percent
                    state["last_done"] = done
                    state["last_ui"] = now
                    elapsed = now - attempt_started
                    stage = (
                        f"Sicherheitsbackup lesen · Versuch {attempt_index}/{len(attempts)} · "
                        f"{baud} Baud · {elapsed:.0f}s"
                    )
                    _notify(services, done, size, stage)
                    if changed or heartbeat:
                        _ui(
                            services,
                            f"BACKUP PROGRESS · Versuch={attempt_index}/{len(attempts)} · "
                            f"Baud={baud} · {percent}% · {done / (1024 * 1024):.2f}/"
                            f"{size / (1024 * 1024):.2f} MB · Zeit={elapsed:.1f}s",
                        )
                    _emit(
                        f"BACKUP STABILITY PROGRESS port={port} attempt={attempt_index} baud={baud} "
                        f"percent={percent} bytes={done}/{size} elapsed={elapsed:.1f}s"
                    )

            watcher = threading.Thread(
                target=monitor,
                name=f"jarnsen-backup-progress-{attempt_index}",
                daemon=True,
            )
            watcher.start()

            try:
                _ui(
                    services,
                    f"BACKUP VERSUCH {attempt_index}/{len(attempts)} · Port={port} · Baud={baud} · Start",
                )
                services.esptool(
                    port,
                    "--baud",
                    baud,
                    "read-flash",
                    "0x0",
                    hex(size),
                    str(target),
                    timeout=900,
                )
            except BaseException as exc:
                last_error = exc
                stop.set()
                watcher.join(timeout=1.0)
                try:
                    actual = target.stat().st_size if target.exists() else 0
                except Exception:
                    actual = 0
                _ui(
                    services,
                    f"BACKUP VERSUCH {attempt_index}/{len(attempts)} FEHLER · "
                    f"{actual / (1024 * 1024):.2f}/{size / (1024 * 1024):.2f} MB · "
                    f"{type(exc).__name__}: {exc}",
                )
                _emit(
                    f"BACKUP STABILITY ATTEMPT FAILED port={port} attempt={attempt_index} "
                    f"baud={baud} bytes={actual}/{size} type={type(exc).__name__} message={exc}"
                )
                if attempt_index >= len(attempts) or not _retryable(exc):
                    raise

                next_baud = attempts[attempt_index]
                _notify(
                    services,
                    actual,
                    size,
                    f"Backup-Verbindung unterbrochen · Neustart mit {next_baud} Baud",
                )
                _ui(
                    services,
                    f"BACKUP RETRY · serieller Fehler erkannt · 2s warten · "
                    f"nächster Versuch mit {next_baud} Baud",
                )
                time.sleep(2.0)
                continue
            finally:
                stop.set()
                watcher.join(timeout=1.0)

            try:
                actual = target.stat().st_size if target.exists() else 0
            except Exception:
                actual = 0

            if actual != size:
                last_error = services.FlasherError(
                    f"Sicherheitsbackup wurde nicht vollständig erstellt ({actual}/{size} Bytes)."
                )
                _ui(
                    services,
                    f"BACKUP VERSUCH {attempt_index}/{len(attempts)} UNVOLLSTÄNDIG · "
                    f"{actual}/{size} Bytes",
                )
                if attempt_index < len(attempts):
                    next_baud = attempts[attempt_index]
                    _notify(
                        services,
                        actual,
                        size,
                        f"Backup unvollständig · Neustart mit {next_baud} Baud",
                    )
                    time.sleep(2.0)
                    continue
                raise last_error

            duration = time.monotonic() - overall_started
            _notify(services, size, size, "Sicherheitsbackup vollständig")
            _ui(
                services,
                f"BACKUP ERFOLG · {size / (1024 * 1024):.2f} MB · "
                f"Versuch={attempt_index}/{len(attempts)} · Baud={baud} · Dauer={duration:.1f}s · {target}",
            )
            _emit(
                f"BACKUP STABILITY COMPLETE port={port} board={board_key} bytes={size} "
                f"attempt={attempt_index} baud={baud} duration={duration:.1f}s target={str(target)!r}"
            )
            return target

        if last_error is not None:
            raise last_error
        raise services.FlasherError("Sicherheitsbackup ist ohne Ergebnis beendet worden.")

    services.backup_flash = backup_flash
    _emit(
        "BACKUP STABILITY installed monitor-fix=1 heartbeat=2s retries=3 "
        "baud-fallback=460800,230400,115200"
    )
