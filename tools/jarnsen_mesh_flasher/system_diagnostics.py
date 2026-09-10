from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from serial.tools import list_ports


def _emit(message: str) -> None:
    try:
        import diagnostics
        diagnostics._emit(message)
    except Exception:
        pass


@dataclass
class DiagnosticCheck:
    key: str
    label: str
    status: str
    detail: str = ""


@dataclass
class DiagnosticReport:
    port: str
    board_key: str
    board_label: str
    started_at: str
    checks: list[DiagnosticCheck]
    result: str
    report_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "port": self.port,
            "board_key": self.board_key,
            "board_label": self.board_label,
            "started_at": self.started_at,
            "checks": [asdict(item) for item in self.checks],
            "result": self.result,
            "report_path": self.report_path,
        }


def _decode(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _add(checks: list[DiagnosticCheck], key: str, label: str, status: str, detail: str = "") -> None:
    item = DiagnosticCheck(key, label, status, detail)
    checks.append(item)
    _emit(f"SYSTEM CHECK key={key} status={status} detail={detail[:500]!r}")


def _overall(checks: list[DiagnosticCheck]) -> str:
    statuses = {item.status for item in checks}
    if "FAIL" in statuses:
        return "FAIL"
    if "WARN" in statuses:
        return "WARN"
    return "PASS"


def run_system_check(
    services: Any,
    port: str,
    board_key: str | None = None,
    *,
    check_github: bool = True,
    compare_profile: bool = True,
) -> DiagnosticReport:
    port = str(port or "").strip()
    if not port:
        raise services.FlasherError("Systemprüfung benötigt einen seriellen Port.")

    started = datetime.now().isoformat(timespec="seconds")
    checks: list[DiagnosticCheck] = []
    visible = {str(item.device).upper(): item for item in list_ports.comports()}
    if port.upper() in visible:
        item = visible[port.upper()]
        _add(
            checks,
            "usb_port",
            "USB/COM",
            "PASS",
            f"{item.device} · {item.description or 'serielles Gerät'}",
        )
    else:
        _add(checks, "usb_port", "USB/COM", "FAIL", f"{port} ist nicht sichtbar.")

    manager = getattr(services, "device_sessions", None)
    if manager is not None:
        owner = manager.owner(port)
        if owner:
            _add(checks, "session", "Device Session", "WARN", f"Port wird gerade verwendet: {owner}")
        else:
            _add(checks, "session", "Device Session", "PASS", "Port-Arbitration frei und aktiv")
    else:
        _add(checks, "session", "Device Session", "FAIL", "Zentraler Session-Manager fehlt")

    info = ""
    try:
        result = services.meshtastic(port, "--info", timeout=35, check=False)
        info = "\n".join(
            part for part in (_decode(result.stdout), _decode(result.stderr)) if part
        )
        if info.strip():
            _add(checks, "meshtastic", "Meshtastic-Verbindung", "PASS", f"{len(info)} Zeichen Antwort")
        else:
            _add(checks, "meshtastic", "Meshtastic-Verbindung", "FAIL", "Keine --info-Antwort")
    except Exception as exc:
        _add(checks, "meshtastic", "Meshtastic-Verbindung", "FAIL", f"{type(exc).__name__}: {exc}")

    detected = services.detect_board_from_text(info) if info else None
    effective_board = board_key or detected or ""
    if detected:
        if board_key and detected != board_key:
            _add(
                checks,
                "board",
                "Board-Erkennung",
                "FAIL",
                f"Erwartet {services.BOARD_PROFILES[board_key]['label']}, "
                f"gelesen {services.BOARD_PROFILES[detected]['label']}",
            )
        else:
            _add(
                checks,
                "board",
                "Board-Erkennung",
                "PASS",
                services.BOARD_PROFILES[detected]["label"],
            )
    elif board_key:
        _add(
            checks,
            "board",
            "Board-Erkennung",
            "WARN",
            f"Nicht aus --info bestätigt; manuell {services.BOARD_PROFILES[board_key]['label']}",
        )
    else:
        _add(checks, "board", "Board-Erkennung", "FAIL", "Board unbekannt")

    identity = None
    query = getattr(services, "query_jarnsen_identity", None)
    if callable(query):
        try:
            identity = query(port, timeout=3.2)
            if identity is not None and bool(getattr(identity, "is_jarnsen", False)):
                _add(
                    checks,
                    "firmware_identity",
                    "JARNSEN-Firmware",
                    "PASS",
                    f"v{getattr(identity, 'version', '')} · Build {getattr(identity, 'build', '?')} "
                    f"· {getattr(identity, 'hardware', '')}",
                )
            elif identity is not None:
                _add(
                    checks,
                    "firmware_identity",
                    "JARNSEN-Firmware",
                    "WARN",
                    f"Firmware erkannt, aber kein JARNSEN-Service: {getattr(identity, 'product', '')}",
                )
            else:
                _add(checks, "firmware_identity", "JARNSEN-Firmware", "WARN", "Identity-Service antwortet nicht")
        except Exception as exc:
            _add(
                checks,
                "firmware_identity",
                "JARNSEN-Firmware",
                "WARN",
                f"{type(exc).__name__}: {exc}",
            )
    else:
        _add(checks, "firmware_identity", "JARNSEN-Firmware", "FAIL", "Identity-Funktion fehlt")

    if effective_board and effective_board in getattr(services, "BOARD_CAPABILITIES", {}):
        capability = services.BOARD_CAPABILITIES[effective_board]
        missing = [
            feature
            for feature in getattr(capability, "features", ())
            if not services.board_capability_matrix().get(effective_board, {}).get(feature, False)
        ]
        if missing:
            _add(checks, "capabilities", "Funktionsvertrag", "FAIL", ", ".join(missing))
        else:
            _add(
                checks,
                "capabilities",
                "Funktionsvertrag",
                "PASS",
                f"{len(getattr(capability, 'features', ()))} Funktionen · {capability.flash_transport}",
            )
    else:
        _add(checks, "capabilities", "Funktionsvertrag", "FAIL", "Board-Capability-Profil fehlt")

    service_hooks = (
        "backup_flash",
        "flash_bundle",
        "restore_profile",
        "set_names",
        "reboot_node",
        "verify_node",
        "load_radio_profile_settings",
        "save_radio_profile_settings",
        "diff_profile_to_node",
        "verify_written_profile",
    )
    missing_hooks = [name for name in service_hooks if not callable(getattr(services, name, None))]
    if missing_hooks:
        _add(checks, "service_hooks", "Servicefunktionen", "FAIL", ", ".join(missing_hooks))
    else:
        _add(checks, "service_hooks", "Servicefunktionen", "PASS", f"{len(service_hooks)}/{len(service_hooks)} vorhanden")

    resume = None
    try:
        resume = services.flash_transaction_resume_plan(port)
    except Exception:
        pass
    if resume and resume.get("failed_stage"):
        _add(
            checks,
            "transaction",
            "Transaktionszustand",
            "WARN",
            f"Fortsetzbar ab {resume.get('resume_from') or '?'} · letzter Fehler {resume.get('failed_stage')}",
        )
    else:
        _add(checks, "transaction", "Transaktionszustand", "PASS", "Kein offener Fehlerzustand")

    active_profile = Path(services.PATHS.active_profile)
    if active_profile.exists() and callable(getattr(services, "check_profile_compatibility", None)):
        try:
            compatibility = services.check_profile_compatibility(
                active_profile,
                effective_board or None,
                identity,
            )
            if compatibility["compatible"]:
                detail = f"Schema {compatibility['schema']}"
                warnings = list(compatibility.get("warnings") or [])
                if warnings:
                    _add(checks, "profile_contract", "Profilvertrag", "WARN", detail + " · " + " | ".join(warnings))
                else:
                    _add(checks, "profile_contract", "Profilvertrag", "PASS", detail)
            else:
                _add(
                    checks,
                    "profile_contract",
                    "Profilvertrag",
                    "FAIL",
                    " | ".join(compatibility.get("errors") or []),
                )
        except Exception as exc:
            _add(checks, "profile_contract", "Profilvertrag", "FAIL", f"{type(exc).__name__}: {exc}")

        if compare_profile and info:
            try:
                differences = services.diff_profile_to_node(port, active_profile)
                status = "PASS" if not differences else "WARN"
                preview = ", ".join(item["key"] for item in differences[:8])
                detail = f"{len(differences)} Abweichung(en)"
                if preview:
                    detail += f" · {preview}"
                _add(checks, "profile_diff", "Node ↔ Profil", status, detail)
            except Exception as exc:
                _add(checks, "profile_diff", "Node ↔ Profil", "WARN", f"Vergleich nicht möglich: {exc}")
    else:
        _add(checks, "profile_contract", "Profilvertrag", "WARN", "Kein aktives Profil")

    if check_github and effective_board:
        try:
            bundle = services.GitHubFirmwareClient().resolve_latest(effective_board)
            _add(
                checks,
                "github_firmware",
                "GitHub-Firmware",
                "PASS",
                f"v{bundle.version} · Build {bundle.run_number} · {bundle.artifact_name}",
            )
        except Exception as exc:
            _add(checks, "github_firmware", "GitHub-Firmware", "WARN", f"{type(exc).__name__}: {exc}")
    elif not check_github:
        _add(checks, "github_firmware", "GitHub-Firmware", "PASS", "Online-Prüfung übersprungen")

    report = DiagnosticReport(
        port=port,
        board_key=effective_board,
        board_label=str(services.BOARD_PROFILES.get(effective_board, {}).get("label", "")),
        started_at=started,
        checks=checks,
        result=_overall(checks),
    )
    services.PATHS.logs.mkdir(parents=True, exist_ok=True)
    target = Path(services.PATHS.logs) / (
        "system-check-"
        + re.sub(r"[^A-Za-z0-9_.-]+", "-", port)
        + "-"
        + datetime.now().strftime("%Y%m%d-%H%M%S")
        + ".json"
    )
    report.report_path = str(target)
    target.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _emit(
        f"SYSTEM CHECK COMPLETE port={port} board={effective_board!r} "
        f"result={report.result} checks={len(checks)} report={str(target)!r}"
    )
    return report


def install(services: Any) -> None:
    if getattr(services, "_jarnsen_system_diagnostics_v1", False):
        return

    def runner(port: str, board_key: str | None = None, *, check_github: bool = True, compare_profile: bool = True):
        return run_system_check(
            services,
            port,
            board_key,
            check_github=check_github,
            compare_profile=compare_profile,
        )

    services.run_system_check = runner
    services._jarnsen_system_diagnostics_v1 = True
    _emit(
        "SYSTEM DIAGNOSTICS installed all-boards=1 safe-readonly-check=1 "
        "profile-diff=1 github-check=1 json-report=1"
    )
