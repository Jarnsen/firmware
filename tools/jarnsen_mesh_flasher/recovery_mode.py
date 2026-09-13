from __future__ import annotations

import re
from typing import Any

from serial.tools import list_ports

_INSTALLED = False

_EXPECTED_RECOVERY_CHIPS = {
    "tbeam_supreme": "ESP32-S3",
}


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _decode(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _proven_chip_from_esptool(output: Any) -> str:
    """Return a chip only after esptool explicitly reports a completed connection."""
    text = _decode(output)
    match = re.search(
        r"(?im)^\s*Connected to\s+(ESP32(?:-[A-Z0-9]+)?)\s+on\s+.+:\s*$",
        text,
    )
    return match.group(1).upper() if match else ""


def _port_detail(port: str) -> dict[str, str]:
    for item in list_ports.comports():
        if str(item.device).upper() == str(port).upper():
            return {
                "device": str(item.device),
                "description": str(item.description or ""),
                "hwid": str(item.hwid or ""),
                "vid": f"{int(item.vid):04X}" if item.vid is not None else "",
                "pid": f"{int(item.pid):04X}" if item.pid is not None else "",
                "serial": str(item.serial_number or ""),
            }
    return {
        "device": str(port),
        "description": "",
        "hwid": "",
        "vid": "",
        "pid": "",
        "serial": "",
    }


def probe(services: Any, port: str, board_key: str | None = None) -> dict[str, Any]:
    """Read-only recovery classification; never erases or writes firmware."""
    port = str(port or "").strip()
    if not port:
        raise services.FlasherError("Recovery-Prüfung benötigt einen COM-Port.")
    if board_key and board_key not in services.BOARD_PROFILES:
        raise services.FlasherError(
            f"Recovery-Prüfung: unbekanntes Board {board_key!r}."
        )

    detail = _port_detail(port)
    result: dict[str, Any] = {
        "port": port,
        "requested_board": board_key or "",
        "detected_board": "",
        "mode": "unknown",
        "transport": "none",
        "ready": False,
        "detail": detail,
        "guidance": "",
    }

    info = ""
    try:
        proc = services.meshtastic(port, "--info", timeout=18, check=False)
        info = "\n".join(
            part for part in (_decode(proc.stdout), _decode(proc.stderr)) if part
        )
    except Exception as exc:
        info = "\n".join(
            part
            for part in (
                _decode(getattr(exc, "stdout", "")),
                _decode(getattr(exc, "stderr", "")),
                _decode(getattr(exc, "output", "")),
            )
            if part
        )
    detected = services.detect_board_from_text(info) if info else None
    if detected:
        result.update(
            detected_board=detected,
            mode="normal",
            transport="meshtastic",
            ready=(not board_key or detected == board_key),
            guidance="Node antwortet normal; kein Recovery-Modus erforderlich.",
        )
        if board_key and detected != board_key:
            result["guidance"] = (
                f"Board-Widerspruch: erwartet {services.BOARD_PROFILES[board_key]['label']}, "
                f"gelesen {services.BOARD_PROFILES[detected]['label']}. Nicht flashen."
            )
        _emit(
            f"RECOVERY PROBE mode=normal port={port} detected={detected!r} ready={int(result['ready'])}"
        )
        return result

    if board_key == "wio":
        try:
            from wio_support import _uf2_drives

            drives = _uf2_drives()
        except Exception:
            drives = []
        result.update(
            detected_board="wio" if drives else "",
            mode="uf2-recovery" if drives else "uf2-waiting",
            transport="uf2",
            ready=bool(drives),
            uf2_drives=[str(path) for path in drives],
            guidance=(
                f"UF2-Bootloader bereit: {drives[0]}"
                if len(drives) == 1
                else "RESET zweimal schnell drücken, bis genau ein UF2-Laufwerk erscheint."
            ),
        )
        _emit(
            f"RECOVERY PROBE mode={result['mode']} port={port} board=wio "
            f"drives={len(drives)} ready={int(result['ready'])}"
        )
        return result

    output = ""
    returncode = 1
    try:
        proc = services.esptool(port, "chip-id", timeout=20, check=False)
        returncode = int(getattr(proc, "returncode", 1) or 0)
        output = "\n".join(
            part for part in (_decode(proc.stdout), _decode(proc.stderr)) if part
        )
    except Exception as exc:
        output = "\n".join(
            part
            for part in (
                _decode(getattr(exc, "stdout", "")),
                _decode(getattr(exc, "stderr", "")),
                _decode(getattr(exc, "output", "")),
                _decode(exc),
            )
            if part
        )

    proven_chip = _proven_chip_from_esptool(output)
    expected_chip = _EXPECTED_RECOVERY_CHIPS.get(board_key or "")
    chip_mismatch = bool(
        board_key and expected_chip and proven_chip and proven_chip != expected_chip
    )
    degraded_expected_chip = bool(
        returncode != 0
        and board_key
        and expected_chip
        and proven_chip == expected_chip
    )

    if chip_mismatch:
        result.update(
            mode="esp-bootloader-mismatch",
            transport="esptool",
            ready=False,
            guidance=(
                f"ESP-Bootloader meldet {proven_chip}, für "
                f"{services.BOARD_PROFILES[board_key]['label']} wird {expected_chip} erwartet. "
                "Nicht flashen."
            ),
        )
    elif returncode == 0:
        if board_key:
            result.update(
                detected_board=board_key,
                mode="esp-bootloader",
                transport="esptool",
                ready=True,
                guidance=(
                    f"ESP-Bootloader antwortet. Board bleibt manuell bestätigt als "
                    f"{services.BOARD_PROFILES[board_key]['label']}."
                ),
            )
        else:
            result.update(
                mode="esp-bootloader-ambiguous",
                transport="esptool",
                ready=False,
                guidance=(
                    "ESP-Bootloader antwortet, aber das physische Board ist nicht eindeutig. "
                    "Board manuell bestätigen, bevor ein Flash freigegeben wird."
                ),
            )
    elif degraded_expected_chip:
        result.update(
            detected_board=board_key,
            mode="esp-bootloader-degraded",
            transport="esptool",
            ready=True,
            guidance=(
                f"ESP-Bootloader wurde eindeutig als {proven_chip} verbunden, danach ging der "
                "Windows-COM-Port verloren oder wurde neu konfiguriert. Dieser Nachweis gilt nur "
                "für die Recovery-Präsenz; vor Backup, Erase oder Flash muss die exakte physische "
                "USB-Identität erneut bestätigt werden."
            ),
        )
    elif proven_chip:
        result.update(
            mode="esp-bootloader-ambiguous",
            transport="esptool",
            ready=False,
            guidance=(
                f"ESP-Bootloader wurde als {proven_chip} erkannt, aber der Prozess endete mit "
                f"Exit {returncode} und das physische Board ist nicht ausreichend bestätigt. "
                "Nicht flashen."
            ),
        )
    else:
        result.update(
            mode="unresponsive",
            transport="none",
            ready=False,
            guidance=(
                "Weder Meshtastic noch ein vollständig bestätigter ESP-Bootloader antworten. "
                "USB-Kabel/Port prüfen und das Board ggf. manuell in den Bootloader versetzen."
            ),
        )
    result["probe_output"] = output[-1200:]
    result["proven_chip"] = proven_chip
    _emit(
        f"RECOVERY PROBE mode={result['mode']} port={port} board={board_key!r} "
        f"esptool_exit={returncode} proven_chip={proven_chip!r} ready={int(result['ready'])}"
    )
    return result


def install(services: Any) -> None:
    global _INSTALLED
    if _INSTALLED or getattr(services, "_jarnsen_recovery_probe_v1", False):
        return
    _INSTALLED = True
    services.recovery_probe = lambda port, board_key=None: probe(
        services, port, board_key
    )
    services._jarnsen_recovery_probe_v1 = True
    _emit(
        "RECOVERY MODE installed read-only-probe=1 esp-chip-id=1 UF2-detect=1 ambiguous-flash-block=1"
    )
