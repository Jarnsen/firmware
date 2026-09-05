from __future__ import annotations

import copy
import time
from pathlib import Path
from typing import Any


def _emit(message: str) -> None:
    try:
        import diagnostics
        diagnostics._emit(message)
    except Exception:
        pass


def _ui_log(services: Any, message: str) -> None:
    callback = getattr(services, "_jarnsen_ui_log_callback", None)
    if callable(callback):
        try:
            callback(str(message))
        except Exception:
            pass


def _notify(services: Any, fraction: float, stage: str, detail: str) -> None:
    callback = getattr(services, "_jarnsen_profile_progress_callback", None)
    if callable(callback):
        try:
            callback(max(0.0, min(1.0, float(fraction))), stage, detail)
        except Exception:
            pass


def _pop_key(mapping: dict[str, Any], wanted: str) -> Any:
    target = wanted.replace("_", "").replace("-", "").lower()
    for key in list(mapping):
        norm = str(key).replace("_", "").replace("-", "").lower()
        if norm == target:
            return mapping.pop(key)
    return None


def install(services: Any) -> None:
    """Keep special admin messages out of Meshtastic's settings transaction.

    `meshtastic --configure` opens a settings transaction before it applies
    top-level `canned_messages`. On the freshly flashed Tracker this special
    admin message can wait for an ACK while the transaction is still open,
    which is exactly the 49/49 stall seen in the Flasher. Ordinary config is
    committed first; canned messages/ringtone are then sent as standalone
    admin commands outside the transaction.
    """
    base_restore = services.restore_profile
    work_dir = Path(services.PATHS.root) / "restore-work"
    work_dir.mkdir(parents=True, exist_ok=True)

    def restore_profile(port: str, profile: Path | None = None) -> None:
        source = Path(profile or services.PATHS.active_profile)
        if not source.exists():
            return base_restore(port, profile)

        try:
            import yaml

            raw = yaml.safe_load(source.read_text(encoding="utf-8", errors="replace")) or {}
        except Exception:
            return base_restore(port, profile)
        if not isinstance(raw, dict):
            return base_restore(port, profile)

        staged = copy.deepcopy(raw)
        canned = _pop_key(staged, "canned_messages")
        ringtone = _pop_key(staged, "ringtone")
        if canned is None and ringtone is None:
            return base_restore(port, profile)

        stamp = str(int(time.time() * 1000))
        temp = work_dir / f"{port}-{stamp}-transaction-safe.yaml"
        temp.write_text(
            yaml.safe_dump(staged, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        _emit(
            f"PROFILE SPECIALS SPLIT port={port} canned={int(canned is not None)} "
            f"ringtone={int(ringtone is not None)} source={source.name!r}"
        )

        try:
            base_restore(port, temp)
        finally:
            try:
                temp.unlink(missing_ok=True)
            except Exception:
                pass

        if canned is not None and str(canned):
            value = str(canned)
            _notify(services, 0.91, "Grundeinstellungen", "Canned Messages außerhalb Transaktion schreiben")
            _ui_log(services, "Grundeinstellungen · Sonderwert canned_messages außerhalb Konfigurations-Transaktion")
            _emit(f"PROFILE SPECIAL CANNED START port={port} chars={len(value)}")
            result = services.meshtastic(
                port,
                "--set-canned-message",
                value,
                timeout=60,
                check=False,
            )
            output = "\n".join(filter(None, (result.stdout, result.stderr)))
            if result.returncode != 0:
                raise services.FlasherError(
                    "Canned Messages konnten nach der Grundeinstellung nicht geschrieben werden.\n\n"
                    + (output[-1500:] if output else f"Exit {result.returncode}")
                )
            _emit(f"PROFILE SPECIAL CANNED OK port={port} chars={len(value)}")

        if ringtone is not None and str(ringtone):
            value = str(ringtone)
            _notify(services, 0.94, "Grundeinstellungen", "Ringtone außerhalb Transaktion schreiben")
            _ui_log(services, "Grundeinstellungen · Sonderwert ringtone außerhalb Konfigurations-Transaktion")
            _emit(f"PROFILE SPECIAL RINGTONE START port={port} chars={len(value)}")
            result = services.meshtastic(
                port,
                "--set-ringtone",
                value,
                timeout=60,
                check=False,
            )
            output = "\n".join(filter(None, (result.stdout, result.stderr)))
            if result.returncode != 0:
                raise services.FlasherError(
                    "Ringtone konnte nach der Grundeinstellung nicht geschrieben werden.\n\n"
                    + (output[-1500:] if output else f"Exit {result.returncode}")
                )
            _emit(f"PROFILE SPECIAL RINGTONE OK port={port} chars={len(value)}")

        _notify(services, 1.0, "Grundeinstellungen", "Transaktion + Sonderwerte fertig")

    services.restore_profile = restore_profile
    _emit("PROFILE SPECIALS FIX installed canned-outside-transaction=1 ringtone-outside-transaction=1")
