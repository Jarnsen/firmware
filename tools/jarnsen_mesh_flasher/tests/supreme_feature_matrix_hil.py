from __future__ import annotations

import json
import time
import traceback
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import supreme_full_hil as base


EXPECTED_BOARD = base.EXPECTED_BOARD
CANONICAL_PROFILE = "tak"
CANONICAL_LONG = base.TEST_LONG_NAME
CANONICAL_SHORT = base.TEST_SHORT_NAME

ROLE_CASES: tuple[tuple[str, str, str], ...] = (
    ("tak_tracker", "JARNSEN HIL Tracker", "HTR"),
    ("tak_repeater", "JARNSEN HIL Repeater", "HRP"),
    (CANONICAL_PROFILE, CANONICAL_LONG, CANONICAL_SHORT),
)


def _load_report() -> dict[str, Any]:
    try:
        value = json.loads(base.REPORT_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _activate_profile(services: Any, functional_profiles: Any, profile_id: str) -> Path:
    functional_profiles.ensure_profiles(services)
    source = Path(functional_profiles.profile_path(services, profile_id))
    if not source.exists():
        raise RuntimeError(f"HIL-Funktionsprofil fehlt: {source}")
    services.import_profile_file(source)
    selected = functional_profiles.active_profile_id(services)
    if selected != profile_id:
        raise RuntimeError(
            f"HIL-Funktionsprofil wurde nicht aktiviert: expected={profile_id!r} actual={selected!r}"
        )
    active = Path(services.PATHS.active_profile)
    if not active.exists():
        raise RuntimeError("Aktives HIL-Profil fehlt nach der Aktivierung.")
    base._append(f"MATRIX PROFILE READY | function={profile_id} | file={active.name}")
    return active


def _read_role(services: Any, provisioning: Any, port: str, expected_role: str) -> dict[str, str]:
    line = provisioning._raw_command(
        port,
        "JARNSEN_TOOL_ROLE_INFO",
        expected="===JARNSEN_ROLE===",
        timeout=4.0,
        attempts=2,
        services=services,
    )
    data = provisioning._parse_role_info(line)
    actual = str(data.get("role") or "").strip().casefold()
    wanted = str(expected_role or "").strip().casefold()
    if actual != wanted:
        raise AssertionError(
            f"ROLE_INFO role={data.get('role')!r}, erwartet {expected_role!r}: {line}"
        )
    for key in ("known", "persisted", "allowed", "role_api"):
        if data.get(key) != "1":
            raise AssertionError(
                f"ROLE_INFO {key}={data.get(key)!r}, erwartet '1': {line}"
            )
    return data


def _verify_state(
    services: Any,
    provisioning: Any,
    port: str,
    *,
    expected_profile: str,
    expected_long: str,
    expected_short: str,
    expected_version: str | None = None,
    expected_build: int | None = None,
) -> dict[str, Any]:
    from profile_utils import summary_from_info_text

    live_port = str(getattr(services, "resolve_live_port", lambda value: value)(port))
    info = services.verify_node(live_port, expected_board=EXPECTED_BOARD)
    board = services.detect_board_from_text(info)
    if board != EXPECTED_BOARD:
        raise AssertionError(f"Board={board!r}, erwartet {EXPECTED_BOARD!r}")

    active = Path(services.PATHS.active_profile)
    services.verify_written_profile(live_port, active, board_key=EXPECTED_BOARD)

    summary = summary_from_info_text(info)
    if summary.long_name.strip() != expected_long:
        raise AssertionError(
            f"Long Name {summary.long_name!r} != {expected_long!r}"
        )
    if summary.short_name.strip() != expected_short:
        raise AssertionError(
            f"Short Name {summary.short_name!r} != {expected_short!r}"
        )

    role = _read_role(services, provisioning, live_port, expected_profile)
    identity = services.query_jarnsen_identity(live_port)
    if identity is None or not bool(getattr(identity, "is_jarnsen", False)):
        raise AssertionError("JARNSEN-Firmwareidentität fehlt.")

    version = str(getattr(identity, "version", "") or "").strip()
    build = int(getattr(identity, "build", 0) or 0)
    if expected_version is not None and version != str(expected_version).strip():
        raise AssertionError(f"Firmwareversion {version!r} != {expected_version!r}")
    if expected_build is not None and build != int(expected_build):
        raise AssertionError(f"Firmwarebuild {build!r} != {expected_build!r}")

    state = {
        "port": live_port,
        "board": board,
        "version": version,
        "build": build,
        "profile": expected_profile,
        "long_name": summary.long_name.strip(),
        "short_name": summary.short_name.strip(),
        "role": role.get("role", ""),
        "role_persisted": role.get("persisted", ""),
        "role_api": role.get("role_api", ""),
    }
    base._append(
        "MATRIX STATE OK | "
        f"port={live_port} | profile={expected_profile} | "
        f"name={state['long_name']!r}/{state['short_name']!r} | "
        f"version={version} | build={build} | role_api={state['role_api']}"
    )
    return state


def _apply_profile(
    services: Any,
    functional_profiles: Any,
    provisioning: Any,
    port: str,
    profile_id: str,
    long_name: str,
    short_name: str,
    *,
    expected_version: str | None = None,
    expected_build: int | None = None,
) -> dict[str, Any]:
    profile = _activate_profile(services, functional_profiles, profile_id)
    prepare = getattr(services, "prepare_profile_write", None)
    if callable(prepare):
        prepare(port, long_name, short_name)
    services.restore_profile(port, profile)
    services.set_names(port, long_name, short_name)
    services.reboot_node(port)
    services.wait_for_serial(port, timeout=90)
    return _verify_state(
        services,
        provisioning,
        port,
        expected_profile=profile_id,
        expected_long=long_name,
        expected_short=short_name,
        expected_version=expected_version,
        expected_build=expected_build,
    )


class _HeadlessValue:
    def __init__(self) -> None:
        self.value = ""

    def set(self, value: Any) -> None:
        self.value = str(value)


class _HeadlessFlasher:
    """Minimal UI facade for exercising FlasherApp._perform_flash unchanged."""

    def __init__(self, log) -> None:
        self.bundle = None
        self.firmware_var = _HeadlessValue()
        self.series_last_identity = ""
        self._log = log

    def after(self, _delay: int, callback, *args):
        return callback(*args)

    def _set_progress(self, fraction: float, text: str) -> None:
        self._log(f"APP PROGRESS | {float(fraction):.3f} | {text}")

    def _append_log(self, text: str) -> None:
        self._log("APP | " + str(text))

    @staticmethod
    def _device_identity(info_text: str) -> str:
        from app import FlasherApp

        return FlasherApp._device_identity(info_text)


def main() -> int:
    started = time.monotonic()
    report = _load_report()
    report.setdefault("schema", 1)
    report["feature_matrix"] = {
        "status": "running",
        "roles": [item[0] for item in ROLE_CASES],
        "one_node_scope": True,
    }
    base._write_report(report)

    snapshot: dict[Path, bytes | None] = {}

    try:
        base._ensure_destructive_context()

        import _build_version  # noqa: F401 - install the same runtime layers as the Flasher
        import functional_profiles
        import review_team_provisioning_v2 as provisioning
        import services
        from app import FlasherApp
        from unified_service_v2 import flash_firmware_only_bundle
        from usb_log_download import BEGIN, END, download_tracker_usb_log

        discovered = base._discover_supreme(services)
        if discovered is None:
            report["feature_matrix"]["status"] = "skipped"
            report["feature_matrix"]["skip_reason"] = "no-tbeam-supreme-connected"
            base._write_report(report)
            return 0

        port, _info = discovered
        report["feature_matrix"]["port"] = port

        state_paths = [
            Path(services.PATHS.active_profile),
            Path(functional_profiles._state_path(services)),
        ]
        snapshot = base._snapshot(state_paths)

        with base._phase(report, "matrix-canonical-local-profile"):
            _activate_profile(services, functional_profiles, CANONICAL_PROFILE)

        with base._phase(report, "matrix-resolve-firmware"):
            bundle = services.GitHubFirmwareClient().resolve_latest(EXPECTED_BOARD)
            wanted_version = str(getattr(bundle, "version", "") or "").strip()
            wanted_build = int(getattr(bundle, "run_number", 0) or 0)
            report["feature_matrix"]["target"] = {
                "version": wanted_version,
                "build": wanted_build,
                "artifact": str(getattr(bundle, "artifact_name", "") or ""),
            }
            base._append(
                f"MATRIX TARGET | version={wanted_version} | build={wanted_build} | "
                f"artifact={report['feature_matrix']['target']['artifact']}"
            )

        with base._phase(report, "matrix-preflight-all-modes"):
            preflights: dict[str, str] = {}
            for mode in ("update", "repair", "factory"):
                result = services.run_flash_preflight(port, EXPECTED_BOARD, bundle, mode)
                preflights[mode] = result.format()
                for line in result.format().splitlines():
                    if line:
                        base._append(f"MATRIX PREFLIGHT {mode.upper()} | {line}")
                if not result.ready:
                    raise RuntimeError(
                        f"Hardware-Preflight {mode!r} ist nicht bereit:\n{result.format()}"
                    )
            report["feature_matrix"]["preflights"] = preflights

        with base._phase(report, "matrix-master-profile-export"):
            exported = Path(services.export_profile(port))
            if not exported.exists() or exported.stat().st_size <= 0:
                raise RuntimeError(f"Profil-Export fehlt/ist leer: {exported}")
            report["feature_matrix"]["profile_export"] = {
                "name": exported.name,
                "bytes": exported.stat().st_size,
            }
            base._append(
                f"MATRIX PROFILE EXPORT OK | {exported.name} | {exported.stat().st_size} bytes"
            )

        role_results: dict[str, Any] = {}
        for profile_id, long_name, short_name in ROLE_CASES:
            with base._phase(report, f"matrix-role-{profile_id}"):
                role_results[profile_id] = _apply_profile(
                    services,
                    functional_profiles,
                    provisioning,
                    port,
                    profile_id,
                    long_name,
                    short_name,
                    expected_version=wanted_version,
                    expected_build=wanted_build,
                )
        report["feature_matrix"]["role_transitions"] = role_results

        with base._phase(report, "matrix-double-reboot-persistence"):
            reboot_states: list[dict[str, Any]] = []
            for index in range(1, 3):
                services.reboot_node(port)
                services.wait_for_serial(port, timeout=90)
                reboot_states.append(
                    _verify_state(
                        services,
                        provisioning,
                        port,
                        expected_profile=CANONICAL_PROFILE,
                        expected_long=CANONICAL_LONG,
                        expected_short=CANONICAL_SHORT,
                        expected_version=wanted_version,
                        expected_build=wanted_build,
                    )
                )
                base._append(f"MATRIX REBOOT PERSISTENCE OK | pass={index}/2")
            report["feature_matrix"]["reboot_persistence"] = reboot_states

        with base._phase(report, "matrix-firmware-only-update-persistence"):
            flash_firmware_only_bundle(
                services,
                port,
                EXPECTED_BOARD,
                bundle,
                lambda message: base._append("MATRIX UPDATE | " + str(message)),
            )
            services.wait_for_serial(port, timeout=120)
            report["feature_matrix"]["firmware_only_update"] = _verify_state(
                services,
                provisioning,
                port,
                expected_profile=CANONICAL_PROFILE,
                expected_long=CANONICAL_LONG,
                expected_short=CANONICAL_SHORT,
                expected_version=wanted_version,
                expected_build=wanted_build,
            )

        with base._phase(report, "matrix-usb-diagnostic-log"):
            services.reboot_node(port)
            services.wait_for_serial(port, timeout=90)
            time.sleep(1.0)
            live_port = str(getattr(services, "resolve_live_port", lambda value: value)(port))
            target = download_tracker_usb_log(
                live_port,
                Path(services.PATHS.logs) / "NODE-LOGS",
                progress=lambda fraction, detail: base._append(
                    f"MATRIX USBLOG | {float(fraction):.3f} | {detail}"
                ),
                log=lambda message: base._append("MATRIX USBLOG | " + str(message)),
            )
            payload = target.read_bytes()
            if BEGIN not in payload or END not in payload:
                raise AssertionError(
                    f"USB-Diagnoselog enthält nicht beide Protokollmarker: {target}"
                )
            report["feature_matrix"]["usb_log"] = {
                "name": target.name,
                "bytes": len(payload),
            }
            base._append(f"MATRIX USB LOG OK | {target.name} | {len(payload)} bytes")
            services.reboot_node(live_port)
            services.wait_for_serial(live_port, timeout=90)

        with base._phase(report, "matrix-production-repair-flow"):
            _activate_profile(services, functional_profiles, CANONICAL_PROFILE)
            fake = _HeadlessFlasher(base._append)
            repaired_bundle, backup, _identity = FlasherApp._perform_flash(
                fake,
                port,
                EXPECTED_BOARD,
                CANONICAL_LONG,
                CANONICAL_SHORT,
                flash_mode="repair",
            )
            report["feature_matrix"]["repair"] = {
                "backup": Path(backup).name,
                "backup_bytes": Path(backup).stat().st_size if Path(backup).exists() else 0,
                "bundle_version": str(getattr(repaired_bundle, "version", "") or ""),
                "bundle_build": int(getattr(repaired_bundle, "run_number", 0) or 0),
                "state": _verify_state(
                    services,
                    provisioning,
                    port,
                    expected_profile=CANONICAL_PROFILE,
                    expected_long=CANONICAL_LONG,
                    expected_short=CANONICAL_SHORT,
                    expected_version=wanted_version,
                    expected_build=wanted_build,
                ),
            }

        with base._phase(report, "matrix-final-device-rescan"):
            devices = list(services.scan_devices())
            supreme = [
                item
                for item in devices
                if str(getattr(item, "board_key", "") or "") == EXPECTED_BOARD
            ]
            if len(supreme) != 1:
                raise AssertionError(
                    f"Abschlussscan erwartet genau eine Supreme, gefunden={len(supreme)} "
                    f"devices={[getattr(item, 'port', '') for item in devices]!r}"
                )
            final_port = str(getattr(supreme[0], "port", "") or port)
            report["feature_matrix"]["final_scan"] = {
                "devices": len(devices),
                "supreme_port": final_port,
                "state": _verify_state(
                    services,
                    provisioning,
                    final_port,
                    expected_profile=CANONICAL_PROFILE,
                    expected_long=CANONICAL_LONG,
                    expected_short=CANONICAL_SHORT,
                    expected_version=wanted_version,
                    expected_build=wanted_build,
                ),
            }

        report["feature_matrix"]["status"] = "passed"
        report["feature_matrix"]["seconds"] = round(time.monotonic() - started, 2)
        report["status"] = "passed"
        base._write_report(report)
        base._append(
            f"MATRIX PASSED | total={report['feature_matrix']['seconds']:.2f}s | "
            "coverage=preflight/export/roles/names/reboots/update/usblog/repair/rescan"
        )
        return 0

    except Exception as exc:
        report["feature_matrix"]["status"] = "failed"
        report["feature_matrix"]["seconds"] = round(time.monotonic() - started, 2)
        report["feature_matrix"]["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        report["status"] = "failed"
        base._write_report(report)
        base._append(
            f"MATRIX FAILED | {type(exc).__name__}: {str(exc)[:600]} | "
            f"total={report['feature_matrix']['seconds']:.2f}s"
        )
        return 1

    finally:
        if snapshot:
            base._restore_snapshot(snapshot)
            base._append("MATRIX RUNNER STATE RESTORED | active profile/state restored")


if __name__ == "__main__":
    raise SystemExit(main())
