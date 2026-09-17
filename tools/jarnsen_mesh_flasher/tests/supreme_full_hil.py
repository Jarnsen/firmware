from __future__ import annotations

import json
import os
import sys
import time
import traceback
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from serial.tools import list_ports

APP_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_DIR.parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

EXPECTED_BOARD = "tbeam_supreme"
TEST_FUNCTION = "tak"
TEST_LONG_NAME = "JARNSEN HIL Supreme"
TEST_SHORT_NAME = "HIL"

REPORT_DIR = REPO_ROOT / "ci-logs" / "supreme-hil"
TRACE_PATH = REPORT_DIR / "trace.txt"
REPORT_PATH = REPORT_DIR / "report.json"


def _append(message: str) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now().isoformat(timespec='seconds')} | {message}"

    # Preserve the exact UTF-8 evidence even when the self-hosted Windows
    # runner still exposes a legacy cp1252 console. Console rendering must never
    # be allowed to abort a destructive HIL run just because a status line
    # contains symbols such as ✓/✗/•.
    with TRACE_PATH.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")

    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    console_line = line.encode(encoding, errors="replace").decode(
        encoding, errors="replace"
    )
    print(console_line, flush=True)


def _write_report(report: dict[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    temp = REPORT_PATH.with_suffix(".tmp")
    temp.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    temp.replace(REPORT_PATH)


@contextmanager
def _phase(report: dict[str, Any], name: str) -> Iterator[None]:
    started = time.monotonic()
    _append(f"PHASE START | {name}")
    try:
        yield
    except Exception:
        elapsed = time.monotonic() - started
        report.setdefault("phases", {})[name] = {
            "status": "failed",
            "seconds": round(elapsed, 2),
        }
        _append(f"PHASE FAIL  | {name} | {elapsed:.2f}s")
        _write_report(report)
        raise
    else:
        elapsed = time.monotonic() - started
        report.setdefault("phases", {})[name] = {
            "status": "passed",
            "seconds": round(elapsed, 2),
        }
        _append(f"PHASE OK    | {name} | {elapsed:.2f}s")
        _write_report(report)


def _snapshot(paths: list[Path]) -> dict[Path, bytes | None]:
    result: dict[Path, bytes | None] = {}
    for path in paths:
        try:
            result[path] = path.read_bytes() if path.exists() else None
        except Exception:
            result[path] = None
    return result


def _restore_snapshot(snapshot: dict[Path, bytes | None]) -> None:
    for path, payload in snapshot.items():
        try:
            if payload is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                temp = path.with_suffix(path.suffix + ".hil-restore")
                temp.write_bytes(payload)
                temp.replace(path)
        except Exception as exc:
            _append(
                f"RUNNER STATE RESTORE WARNING | {path} | "
                f"{type(exc).__name__}: {exc}"
            )


def _ensure_destructive_context() -> None:
    github_actions = os.environ.get("GITHUB_ACTIONS", "").strip().casefold() == "true"
    if github_actions:
        ref = os.environ.get("GITHUB_REF", "").strip()
        if ref != "refs/heads/feat/mini-serial-flasher":
            raise RuntimeError(
                "Destruktiver Supreme-HIL ist nur auf feat/mini-serial-flasher freigegeben. "
                f"Aktueller Ref: {ref or '<leer>'}"
            )
        return

    confirmation = os.environ.get("JARNSEN_SUPREME_HIL_CONFIRM", "").strip()
    if confirmation != "I_ACCEPT_SUPREME_FACTORY_FLASH":
        raise RuntimeError(
            "Lokaler destruktiver Supreme-HIL ist gesperrt. "
            "Zum bewussten lokalen Start JARNSEN_SUPREME_HIL_CONFIRM="
            "I_ACCEPT_SUPREME_FACTORY_FLASH setzen."
        )


def _follow_supreme(services: Any, port: str, timeout: int = 60) -> str:
    waiter = getattr(services, "wait_for_device_reconnect", None)
    if callable(waiter):
        return str(waiter(port, timeout=timeout, expected_board=EXPECTED_BOARD)).strip()
    resolver = getattr(services, "resolve_live_port", None)
    if callable(resolver):
        return str(resolver(port) or port).strip()
    return str(port or "").strip()


def _prebound_supreme(services: Any) -> tuple[str, str] | None:
    """Recover the Supreme proven by the outer hardware contract by USB identity."""
    hint = os.environ.get("JARNSEN_SUPREME_HIL_PORT", "").strip()
    serial = os.environ.get("JARNSEN_SUPREME_HIL_SERIAL", "").strip().casefold()
    location = os.environ.get("JARNSEN_SUPREME_HIL_LOCATION", "").strip().casefold()
    if not hint and not serial and not location:
        return None

    manager = getattr(services, "device_sessions", None)
    remember = getattr(manager, "remember", None)
    if hint and callable(remember):
        try:
            remember(hint)
        except Exception:
            pass

    def matches(entry: Any) -> bool:
        candidate_serial = (
            str(getattr(entry, "serial_number", "") or "").strip().casefold()
        )
        candidate_location = (
            str(getattr(entry, "location", "") or "").strip().casefold()
        )
        if serial and candidate_serial != serial:
            return False
        if location and candidate_location != location:
            return False
        return bool(serial or location)

    candidates = [
        entry
        for entry in list_ports.comports()
        if getattr(entry, "vid", None) is not None and matches(entry)
    ]
    if len(candidates) > 1:
        raise RuntimeError(
            "Vorab gebundene Supreme-USB-Identität ist mehrfach sichtbar; destruktiver HIL stoppt."
        )
    live = str(getattr(candidates[0], "device", "") or "").strip() if candidates else ""
    if not live and hint:
        live = _follow_supreme(services, hint, timeout=60)
    if not live:
        raise RuntimeError(
            "Der zuvor physisch gebundene Supreme ist nicht mehr am USB-Bus sichtbar."
        )

    info = ""
    try:
        info = services.verify_node(live, expected_board=EXPECTED_BOARD)
        detected = services.detect_board_from_text(info)
        if detected != EXPECTED_BOARD:
            raise RuntimeError(
                f"Vorab gebundener Port {live} meldet Board {detected!r} statt Supreme."
            )
        proof = "board+physical-id"
    except Exception as exc:
        # The outer contract already proved this serial/location as Supreme. It
        # may currently be in ROM download mode, where Meshtastic --info cannot
        # answer. The physical identity remains authoritative; never fall back
        # to a different 303A:1001 device.
        if not (serial or location):
            raise
        proof = "physical-id-prebound"
        _append(
            f"SUPREME PREBOUND SERVICE WAIT | port={live} | "
            f"{type(exc).__name__}: {str(exc)[:240]}"
        )
    if callable(remember):
        try:
            remember(live)
        except Exception:
            pass
    _append(
        f"SUPREME PREBOUND LOCK | port={live} | serial={serial or '-'} | "
        f"location={location or '-'} | proof={proof}"
    )
    return live, info


def _discover_supreme(services: Any) -> tuple[str, str] | None:
    prebound = _prebound_supreme(services)
    if prebound is not None:
        return prebound

    candidates: list[tuple[str, str]] = []
    seen_usb_ports = 0

    for entry in list_ports.comports():
        # A VID is our hard boundary between wired USB and Bluetooth/virtual COM.
        if getattr(entry, "vid", None) is None:
            continue
        seen_usb_ports += 1
        port = str(getattr(entry, "device", "") or "").strip()
        if not port:
            continue

        try:
            info = services.verify_node(port)
            detected = services.detect_board_from_text(info)
        except Exception as exc:
            _append(
                f"DISCOVERY IGNORE | {port} | {type(exc).__name__}: "
                f"{str(exc)[:240]}"
            )
            continue

        label = (
            str(services.BOARD_PROFILES.get(detected, {}).get("label") or detected)
            if detected
            else "unbekannt"
        )
        _append(f"DISCOVERY USB | {port} | board={detected or 'unknown'} | {label}")
        if detected == EXPECTED_BOARD:
            candidates.append((port, info))

    if not candidates:
        _append(
            f"SKIP | keine {EXPECTED_BOARD}-Node gefunden | "
            f"wired-usb-ports={seen_usb_ports}"
        )
        return None

    if len(candidates) > 1:
        ports = ", ".join(port for port, _info in candidates)
        raise RuntimeError(
            "Mehrere T-Beam-Supreme-Testnodes gefunden "
            f"({ports}). Destruktiver HIL verweigert den Start."
        )

    port, first_info = candidates[0]

    # Independent second read immediately before the destructive test. This is
    # deliberately not inferred from a stale discovery cache.
    confirmed_info = services.verify_node(port, expected_board=EXPECTED_BOARD)
    confirmed = services.detect_board_from_text(confirmed_info)
    if confirmed != EXPECTED_BOARD:
        raise RuntimeError(
            f"{port}: zweite Boardprüfung ist nicht eindeutig Supreme "
            f"(erkannt={confirmed!r})."
        )

    _append(f"SUPREME LOCKED | port={port} | board={confirmed}")
    return port, confirmed_info or first_info


def _activate_test_profile(services: Any, functional_profiles: Any) -> Path:
    functional_profiles.ensure_profiles(services)
    source = Path(functional_profiles.profile_path(services, TEST_FUNCTION))
    if not source.exists():
        raise RuntimeError(f"TAK-Testprofil fehlt: {source}")
    services.import_profile_file(source)
    active = Path(services.PATHS.active_profile)
    if not active.exists():
        raise RuntimeError("Aktives Profil wurde für den HIL-Test nicht angelegt.")
    selected = functional_profiles.active_profile_id(services)
    if selected != TEST_FUNCTION:
        raise RuntimeError(
            f"TAK-Testprofil wurde nicht aktiviert (active={selected!r})."
        )
    _append(
        f"PROFILE READY | function={TEST_FUNCTION} | source={source.name} | "
        f"active={active.name}"
    )
    return active


def _role_contract(provisioning: Any, line: str) -> dict[str, str]:
    data = provisioning._parse_role_info(line)
    expected = {
        "role": TEST_FUNCTION,
        "known": "1",
        "persisted": "1",
        "allowed": "1",
        "role_api": "1",
    }
    actual_role = str(data.get("role") or "").strip().casefold()
    if actual_role != expected["role"]:
        raise AssertionError(
            f"ROLE_INFO meldet role={data.get('role')!r}, erwartet {TEST_FUNCTION!r}: {line}"
        )
    for key in ("known", "persisted", "allowed", "role_api"):
        if data.get(key) != expected[key]:
            raise AssertionError(
                f"ROLE_INFO {key}={data.get(key)!r}, erwartet {expected[key]!r}: {line}"
            )
    return data


def main() -> int:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        TRACE_PATH.unlink(missing_ok=True)
    except Exception:
        pass

    started = time.monotonic()
    report: dict[str, Any] = {
        "schema": 1,
        "test": "JARNSEN-MESH Flasher Supreme full-cycle HIL",
        "expected_board": EXPECTED_BOARD,
        "test_function": TEST_FUNCTION,
        "test_long_name": TEST_LONG_NAME,
        "test_short_name": TEST_SHORT_NAME,
        "github_ref": os.environ.get("GITHUB_REF", ""),
        "github_sha": os.environ.get("GITHUB_SHA", ""),
        "runner_name": os.environ.get("RUNNER_NAME", ""),
        "status": "running",
        "phases": {},
    }
    _write_report(report)

    snapshot: dict[Path, bytes | None] = {}

    try:
        _ensure_destructive_context()

        # Importing _build_version installs exactly the packaged runtime layers
        # used by the Windows Flasher before the GUI is constructed.
        import _build_version  # noqa: F401
        import functional_profiles
        import review_team_provisioning_v2 as provisioning
        import services
        from hil_reference import resolve_reference_bundle
        from profile_utils import summary_from_info_text

        # Reuse the Flasher's own progress/log callbacks so the Actions log shows
        # where a real profile transaction stalls instead of only reporting the
        # final exception.
        services._jarnsen_ui_log_callback = lambda message: _append(
            "UI | " + str(message)
        )
        services._jarnsen_profile_progress_callback = (
            lambda fraction, stage, detail="": _append(
                f"PROGRESS | {float(fraction):.3f} | {stage} | {detail}"
            )
        )

        if EXPECTED_BOARD not in services.BOARD_PROFILES:
            raise RuntimeError(
                f"Supreme board profile {EXPECTED_BOARD!r} ist nicht registriert."
            )

        report["runtime_flags"] = {
            "transaction_flow": bool(
                getattr(services, "_jarnsen_transaction_flow_v1", False)
            ),
            "provisioning_v2": bool(
                getattr(services, "_jarnsen_review_team_provisioning_v2", False)
            ),
            "provisioning_guard": bool(
                getattr(services, "_jarnsen_review_team_provisioning_guard", False)
            ),
            "factory_only": bool(
                getattr(services, "_jarnsen_factory_only_flash", False)
            ),
        }
        missing = [
            name for name, active in report["runtime_flags"].items() if not active
        ]
        if missing:
            raise RuntimeError(
                "Vollständige Flasher-Laufzeit ist nicht aktiv: " + ", ".join(missing)
            )

        with _phase(report, "discover-and-lock-supreme"):
            discovered = _discover_supreme(services)
        if discovered is None:
            report["status"] = "skipped"
            report["skip_reason"] = "no-tbeam-supreme-connected"
            report["total_seconds"] = round(time.monotonic() - started, 2)
            _write_report(report)
            return 0

        port, initial_info = discovered
        report["port"] = port
        initial_identity = services.query_jarnsen_identity(port)
        report["before"] = {
            "version": str(getattr(initial_identity, "version", "") or ""),
            "build": getattr(initial_identity, "build", None),
        }

        state_paths = [
            Path(services.PATHS.active_profile),
            Path(functional_profiles._state_path(services)),
        ]
        snapshot = _snapshot(state_paths)

        with _phase(report, "activate-tak-test-profile"):
            profile_path = _activate_test_profile(services, functional_profiles)

        with _phase(report, "resolve-reference-supreme-firmware"):
            bundle = resolve_reference_bundle(services, EXPECTED_BOARD)
            report["target"] = {
                "version": str(getattr(bundle, "version", "") or ""),
                "build": int(getattr(bundle, "run_number", 0) or 0),
                "artifact": str(getattr(bundle, "artifact_name", "") or ""),
            }
            _append(
                "TARGET | "
                f"{report['target']['version']} | Build {report['target']['build']} | "
                f"{report['target']['artifact']}"
            )

        with _phase(report, "provision-preflight"):
            preflight = services.run_flash_preflight(
                port, EXPECTED_BOARD, bundle, "provision"
            )
            report["preflight"] = preflight.format()
            for line in preflight.format().splitlines():
                if line:
                    _append("PREFLIGHT | " + line)
            if not preflight.ready:
                raise RuntimeError(preflight.format())

        with _phase(report, "full-safety-backup"):
            backup = Path(services.backup_flash(port, EXPECTED_BOARD))
            if not backup.exists() or backup.stat().st_size <= 0:
                raise RuntimeError(f"Sicherheitsbackup fehlt/ist leer: {backup}")
            report["backup"] = {
                "name": backup.name,
                "bytes": backup.stat().st_size,
            }
            _append(f"BACKUP OK | {backup.name} | {backup.stat().st_size} bytes")

        with _phase(report, "factory-flash"):
            services.flash_bundle(
                port,
                bundle,
                log=lambda message: _append("FLASH | " + str(message)),
            )

        with _phase(report, "post-flash-usb-return"):
            port = _follow_supreme(services, port, timeout=120)
            services.wait_for_serial(port, timeout=120)
            port = str(
                getattr(services, "resolve_live_port", lambda value: value)(port)
            )
            report.setdefault("port_history", []).append(port)

        with _phase(report, "profile-and-role-write"):
            prepare = getattr(services, "prepare_profile_write", None)
            if callable(prepare):
                prepare(port, TEST_LONG_NAME, TEST_SHORT_NAME)
            services.restore_profile(port, profile_path)
            port = _follow_supreme(services, port, timeout=90)
            services.wait_for_serial(port, timeout=90)

        with _phase(report, "name-write"):
            services.set_names(port, TEST_LONG_NAME, TEST_SHORT_NAME)
            port = _follow_supreme(services, port, timeout=90)

        with _phase(report, "reboot-and-stable-return"):
            services.reboot_node(port)
            port = _follow_supreme(services, port, timeout=90)
            services.wait_for_serial(port, timeout=90)
            report.setdefault("port_history", []).append(port)

        with _phase(report, "final-end-to-end-verification"):
            final_info = services.verify_node(port, expected_board=EXPECTED_BOARD)
            services.verify_written_profile(
                port,
                Path(services.PATHS.active_profile),
                board_key=EXPECTED_BOARD,
            )

            final_board = services.detect_board_from_text(final_info)
            if final_board != EXPECTED_BOARD:
                raise AssertionError(
                    f"Endprüfung Board={final_board!r}, erwartet {EXPECTED_BOARD!r}"
                )

            identity = services.query_jarnsen_identity(port)
            if identity is None or not bool(getattr(identity, "is_jarnsen", False)):
                raise AssertionError("JARNSEN-Firmwareidentität fehlt nach HIL-Flash.")

            actual_version = str(getattr(identity, "version", "") or "").strip()
            actual_build = int(getattr(identity, "build", 0) or 0)
            wanted_version = str(getattr(bundle, "version", "") or "").strip()
            wanted_build = int(getattr(bundle, "run_number", 0) or 0)
            if actual_version != wanted_version:
                raise AssertionError(
                    f"Firmwareversion {actual_version!r} != {wanted_version!r}"
                )
            if actual_build != wanted_build:
                raise AssertionError(
                    f"Firmwarebuild {actual_build!r} != {wanted_build!r}"
                )

            summary = summary_from_info_text(final_info)
            if summary.long_name.strip() != TEST_LONG_NAME:
                raise AssertionError(
                    f"Long Name {summary.long_name!r} != {TEST_LONG_NAME!r}"
                )
            if summary.short_name.strip() != TEST_SHORT_NAME:
                raise AssertionError(
                    f"Short Name {summary.short_name!r} != {TEST_SHORT_NAME!r}"
                )

            try:
                role_line = provisioning._raw_command(
                    port,
                    "JARNSEN_TOOL_ROLE_INFO",
                    expected="===JARNSEN_ROLE===",
                    timeout=2.5,
                    attempts=1,
                    services=services,
                )
                role_data = _role_contract(provisioning, role_line)
                role_data["source"] = "jarnsen-role-api"
            except Exception as exc:
                expected_role = functional_profiles.functional_profile(
                    TEST_FUNCTION
                ).meshtastic_role
                actual_role = summary.role.strip()
                if actual_role.casefold() != expected_role.casefold():
                    raise AssertionError(
                        f"Rollen-Readback {actual_role!r} != {expected_role!r}; "
                        f"ROLE_INFO fallback cause={type(exc).__name__}: {exc}"
                    ) from exc
                role_data = {
                    "role": actual_role,
                    "known": "1",
                    "persisted": "1",
                    "allowed": "1",
                    "role_api": "0",
                    "source": "meshtastic-info-after-reboot",
                }
                _append(
                    "ROLE FALLBACK OK | source=meshtastic-info-after-reboot | "
                    f"role={actual_role}"
                )

            report["after"] = {
                "board": final_board,
                "version": actual_version,
                "build": actual_build,
                "long_name": summary.long_name.strip(),
                "short_name": summary.short_name.strip(),
                "role": role_data.get("role", ""),
                "role_persisted": role_data.get("persisted", ""),
                "role_api": role_data.get("role_api", ""),
                "role_source": role_data.get("source", ""),
            }
            _append(
                "FINAL OK | "
                f"board={final_board} | version={actual_version} | build={actual_build} | "
                f"name={summary.long_name.strip()!r}/{summary.short_name.strip()!r} | "
                f"role={role_data.get('role')} | persisted={role_data.get('persisted')} | "
                f"role_api={role_data.get('role_api')}"
            )

        report["status"] = "passed"
        report["total_seconds"] = round(time.monotonic() - started, 2)
        _write_report(report)
        _append(f"HIL PASSED | total={report['total_seconds']:.2f}s")
        return 0

    except Exception as exc:
        report["status"] = "failed"
        report["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        report["total_seconds"] = round(time.monotonic() - started, 2)
        _write_report(report)
        _append(
            f"HIL FAILED | {type(exc).__name__}: {str(exc)[:600]} | "
            f"total={report['total_seconds']:.2f}s"
        )
        return 1

    finally:
        if snapshot:
            _restore_snapshot(snapshot)
            _append("RUNNER STATE RESTORED | active profile/state restored")


if __name__ == "__main__":
    raise SystemExit(main())
