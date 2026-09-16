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
            _emit(
                f"BACKUP STABILITY UI CALLBACK ERROR type={type(exc).__name__} message={exc}"
            )


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
        # esptool can lose a high-speed read stream even though the ROM
        # bootloader and USB identity are both valid. These are exactly the
        # conditions the descending backup baud ladder is meant to recover.
        "serial data stream stopped",
        "serial noise or corruption",
        "possible serial noise",
        "invalid head of packet",
        "no serial data received",
    )
    return any(token in text for token in tokens)


def _remove_partial(target: Path) -> None:
    try:
        target.unlink(missing_ok=True)
    except Exception as exc:
        _emit(
            f"BACKUP STABILITY PARTIAL CLEANUP WARNING target={str(target)!r} "
            f"type={type(exc).__name__} message={exc}"
        )


def _remember_physical_device(services: Any, port: str) -> None:
    manager = getattr(services, "device_sessions", None)
    remember = getattr(manager, "remember", None)
    if not callable(remember):
        return
    fingerprint = remember(port)
    if fingerprint is None:
        return
    _emit(
        "BACKUP STABILITY PHYSICAL LOCK "
        f"logical={port} serial={getattr(fingerprint, 'serial_number', '')!r} "
        f"location={getattr(fingerprint, 'location', '')!r}"
    )


def _reacquire_same_device(
    services: Any,
    logical_port: str,
    board_key: str,
    current_port: str,
) -> str:
    """Reacquire only the already bound physical node before a retry.

    reconnect_identity_guard owns the actual identity decision. If a strong USB
    serial/location is known, it never degrades to VID/PID. A failed identity
    reacquire is therefore fatal instead of risking a retry on another board.
    """
    wait = getattr(services, "wait_for_device_reconnect", None)
    if callable(wait):
        live = str(
            wait(logical_port, timeout=25, expected_board=board_key) or ""
        ).strip()
        if not live:
            raise services.FlasherError(
                f"{logical_port}: Backup-Retry konnte dasselbe physische USB-Gerät "
                "nicht eindeutig wiederfinden."
            )
        _emit(
            f"BACKUP STABILITY REACQUIRE logical={logical_port} live={live} "
            f"board={board_key}"
        )
        return live

    resolver = getattr(services, "resolve_live_port", None)
    if callable(resolver):
        live = str(resolver(logical_port) or "").strip()
        if live:
            return live
    return current_port or logical_port


def install(services: Any) -> None:
    """Replace the ESP32 full-backup step with a monitored, retryable variant."""

    previous_backup = services.backup_flash

    def backup_flash(port: str, board_key: str) -> Path:
        if board_key == "wio":
            return previous_backup(port, board_key)

        logical_port = str(port)
        current_port = logical_port
        _remember_physical_device(services, logical_port)

        _notify(services, 0, 1, "Flash-Größe ermitteln")
        _ui(
            services,
            f"BACKUP · Flash-Größe ermitteln · Port={logical_port} · Board={board_key}",
        )
        result = services.esptool(current_port, "flash-id", timeout=45)
        text = "\n".join(filter(None, (result.stdout, result.stderr)))
        match = re.search(r"Detected flash size:\s*(\d+)MB", text, re.IGNORECASE)
        if not match:
            raise services.FlasherError("Flash-Größe konnte nicht ermittelt werden.")

        size = int(match.group(1)) * 1024 * 1024
        services.PATHS.backups.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = services.PATHS.backups / f"{board_key}-{logical_port}-{timestamp}.bin"

        # The normal firmware writer already uses 921600 successfully on the
        # supported ESP32 boards. Use the same rate for the safety read first,
        # but retain conservative automatic fallbacks for marginal USB links.
        attempts = ("921600", "460800", "230400", "115200")
        _ui(
            services,
            f"BACKUP START · Ziel={target} · Größe={size / (1024 * 1024):.1f} MB · "
            f"Versuche={len(attempts)} · Baudfolge={' → '.join(attempts)}",
        )
        _emit(
            f"BACKUP STABILITY START port={logical_port} board={board_key} bytes={size} "
            f"target={str(target)!r} bauds={attempts!r}"
        )

        last_error: BaseException | None = None
        overall_started = time.monotonic()

        for attempt_index, baud in enumerate(attempts, start=1):
            _remove_partial(target)

            stop = threading.Event()
            state = {
                "last_percent": -1,
                "last_done": -1,
                "last_ui": 0.0,
            }
            attempt_started = time.monotonic()

            def monitor(
                stop=stop,
                state=state,
                attempt_started=attempt_started,
                attempt_index=attempt_index,
                baud=baud,
                target=target,
                current_port=current_port,
            ) -> None:
                while not stop.wait(0.25):
                    try:
                        done = target.stat().st_size if target.exists() else 0
                    except Exception:
                        done = 0
                    done = max(0, min(int(done), size))
                    percent = int((done * 100) / size) if size else 0
                    now = time.monotonic()
                    changed = (
                        percent != state["last_percent"] or done != state["last_done"]
                    )
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
                        f"BACKUP STABILITY PROGRESS port={current_port} attempt={attempt_index} baud={baud} "
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
                    f"BACKUP VERSUCH {attempt_index}/{len(attempts)} · Port={current_port} · Baud={baud} · Start",
                )
                services.esptool(
                    current_port,
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
                    f"BACKUP STABILITY ATTEMPT FAILED port={current_port} attempt={attempt_index} "
                    f"baud={baud} bytes={actual}/{size} type={type(exc).__name__} message={exc}"
                )
                _remove_partial(target)
                if attempt_index >= len(attempts) or not _retryable(exc):
                    raise

                next_baud = attempts[attempt_index]
                _notify(
                    services,
                    0,
                    size,
                    f"Backup-Verbindung unterbrochen · Gerät erneut binden · {next_baud} Baud",
                )
                _ui(
                    services,
                    f"BACKUP RETRY · serieller Fehler erkannt · physisches Gerät erneut prüfen · "
                    f"nächster Versuch mit {next_baud} Baud",
                )
                try:
                    current_port = _reacquire_same_device(
                        services,
                        logical_port,
                        board_key,
                        current_port,
                    )
                except BaseException as reconnect_exc:
                    _emit(
                        f"BACKUP STABILITY REACQUIRE FAILED logical={logical_port} "
                        f"board={board_key} type={type(reconnect_exc).__name__} "
                        f"message={reconnect_exc}"
                    )
                    raise services.FlasherError(
                        f"{logical_port}: Backup wurde nach einem seriellen Fehler gestoppt, "
                        "weil dasselbe physische USB-Gerät nicht sicher wiedergebunden werden "
                        f"konnte. Ursache: {reconnect_exc}"
                    ) from reconnect_exc
                time.sleep(0.5)
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
                _remove_partial(target)
                if attempt_index < len(attempts):
                    next_baud = attempts[attempt_index]
                    _notify(
                        services,
                        0,
                        size,
                        f"Backup unvollständig · Gerät erneut binden · {next_baud} Baud",
                    )
                    current_port = _reacquire_same_device(
                        services,
                        logical_port,
                        board_key,
                        current_port,
                    )
                    time.sleep(0.5)
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
                f"BACKUP STABILITY COMPLETE port={current_port} logical={logical_port} "
                f"board={board_key} bytes={size} attempt={attempt_index} baud={baud} "
                f"duration={duration:.1f}s target={str(target)!r}"
            )
            return target

        _remove_partial(target)
        if last_error is not None:
            raise last_error
        raise services.FlasherError(
            "Sicherheitsbackup ist ohne Ergebnis beendet worden."
        )

    services.backup_flash = backup_flash
    _emit(
        "BACKUP STABILITY installed monitor-fix=1 heartbeat=2s retries=4 "
        "baud-fallback=921600,460800,230400,115200 physical-rebind=1 "
        "partial-cleanup=1 serial-noise-retry=1"
    )
