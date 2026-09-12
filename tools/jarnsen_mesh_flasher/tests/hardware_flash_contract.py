from __future__ import annotations

import json
import os
import sys
import time
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from hil_reference import resolve_reference_bundle  # noqa: E402


# Dedicated destructive lab node. This exact USB serial was independently
# observed as LILYGO T-Beam Supreme in multiple prior Flasher hardware logs.
# Never broaden this to COM number or VID/PID: other attached nodes share 303A:1001.
SUPREME_RECOVERY_SERIAL = "48:CA:43:5C:2F:EC"


def _configured_ports() -> dict[str, str]:
    raw = os.environ.get("JARNSEN_FLASHER_HW_PORTS", "").strip()
    if not raw:
        return {}
    if raw.startswith("{"):
        value = json.loads(raw)
        return {str(key): str(port) for key, port in value.items()}
    result: dict[str, str] = {}
    for item in raw.split(","):
        key, separator, port = item.partition("=")
        if separator and key.strip() and port.strip():
            result[key.strip()] = port.strip()
    return result


def _usb_fingerprint(entry) -> str:
    vid = getattr(entry, "vid", None)
    pid = getattr(entry, "pid", None)
    vid_pid = (
        f"{int(vid):04X}:{int(pid):04X}"
        if vid is not None and pid is not None
        else "unknown"
    )
    serial_number = str(getattr(entry, "serial_number", "") or "-")
    location = str(getattr(entry, "location", "") or "-")
    manufacturer = str(getattr(entry, "manufacturer", "") or "-")
    product = str(getattr(entry, "product", "") or "-")
    description = str(getattr(entry, "description", "") or "-")
    hwid = str(getattr(entry, "hwid", "") or "-")
    return (
        f"vidpid={vid_pid} serial={serial_number!r} location={location!r} "
        f"manufacturer={manufacturer!r} product={product!r} "
        f"description={description!r} hwid={hwid!r}"
    )


def _auto_discover_ports(services) -> dict[str, str]:
    """Safely discover attached wired boards for read-only HIL checks.

    Auto discovery never enables flashing by itself. It only replaces the old
    need to hard-code COM25/COMx for the read/preflight contract on the
    self-hosted Windows runner. Bluetooth serial ports are ignored because they
    normally do not expose a USB VID/PID.

    A freshly rebooted ESP32-S3 can enumerate before its serial service is ready,
    so discovery gives each physical USB port a small, bounded retry window.
    """
    if os.environ.get("JARNSEN_FLASHER_HW_AUTODISCOVER", "1").strip() == "0":
        return {}

    try:
        from serial.tools import list_ports
    except Exception as exc:
        print(f"Hardware auto-discovery unavailable: {type(exc).__name__}: {exc}")
        return {}

    discovered: dict[str, str] = {}
    fingerprints: dict[str, str] = {}
    usb_ports = []
    for entry in list_ports.comports():
        if getattr(entry, "vid", None) is None:
            continue
        port = str(getattr(entry, "device", "") or "").strip()
        if port:
            usb_ports.append((port, entry))
            fingerprints[port] = _usb_fingerprint(entry)
            print(f"Hardware USB candidate: {port} | {fingerprints[port]}")

    if not usb_ports:
        print("Hardware auto-discovery: no USB serial ports with VID/PID visible")

    recovery_matches = [
        (port, entry)
        for port, entry in usb_ports
        if str(getattr(entry, "serial_number", "") or "").strip().casefold()
        == SUPREME_RECOVERY_SERIAL.casefold()
    ]
    if _supreme_full_cycle_enabled() and len(recovery_matches) > 1:
        ports = ", ".join(port for port, _entry in recovery_matches)
        raise RuntimeError(
            "Historische Supreme-USB-Identität ist mehrfach sichtbar "
            f"({ports}); destruktiver HIL stoppt."
        )

    for port, entry in usb_ports:
        info = None
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                info = services.verify_node(port)
                break
            except Exception as exc:
                last_error = exc
                if attempt < 3:
                    print(
                        f"Hardware auto-discovery retry {attempt}/3 for {port}: "
                        f"{type(exc).__name__}: {str(exc)[:180]}"
                    )
                    time.sleep(1.5)
        if info is None:
            entry_serial = str(
                getattr(entry, "serial_number", "") or ""
            ).strip()
            if (
                _supreme_full_cycle_enabled()
                and entry_serial.casefold() == SUPREME_RECOVERY_SERIAL.casefold()
            ):
                previous = discovered.get("tbeam_supreme")
                if previous and previous != port:
                    raise RuntimeError(
                        "Mehrere Supreme-Kandidaten trotz exakter physischer Bindung: "
                        f"{previous}, {port}."
                    )
                manager = getattr(services, "device_sessions", None)
                remember = getattr(manager, "remember", None)
                if callable(remember):
                    fingerprint = remember(port)
                    if fingerprint is not None:
                        print(
                            "Hardware Supreme recovery lock: "
                            f"{port} serial={fingerprint.serial_number!r} "
                            f"location={fingerprint.location!r}"
                        )
                discovered["tbeam_supreme"] = port
                print(
                    "Hardware auto-discovery recovery candidate: "
                    f"tbeam_supreme={port} exact-serial={entry_serial!r}; "
                    "live app identity unavailable, destructive HIL must restore and re-verify it"
                )
                continue

            detail = (
                f"{type(last_error).__name__}: {str(last_error)[:180]}"
                if last_error is not None
                else "no device information"
            )
            print(
                f"Hardware auto-discovery ignored {port} | {fingerprints.get(port, _usb_fingerprint(entry))}: {detail}"
            )
            continue

        board_key = services.detect_board_from_text(info)
        if not board_key or board_key not in services.BOARD_PROFILES:
            print(
                f"Hardware auto-discovery could not classify {port} | "
                f"{fingerprints.get(port, _usb_fingerprint(entry))}; "
                f"info={str(info)[:240]!r}"
            )
            continue
        previous = discovered.get(board_key)
        if previous and previous != port:
            raise RuntimeError(
                f"Mehrere angeschlossene Boards fuer {board_key}: {previous}, {port}. "
                f"{previous}=[{fingerprints.get(previous, '-')}]; "
                f"{port}=[{fingerprints.get(port, '-')}]. "
                "JARNSEN_FLASHER_HW_PORTS explizit setzen."
            )
        manager = getattr(services, "device_sessions", None)
        remember = getattr(manager, "remember", None)
        if callable(remember):
            fingerprint = remember(port)
            if fingerprint is not None:
                print(
                    f"Hardware physical lock: {board_key}={port} "
                    f"serial={fingerprint.serial_number!r} location={fingerprint.location!r}"
                )
        discovered[board_key] = port
        print(
            f"Hardware auto-discovery: {board_key}={port} | "
            f"{fingerprints.get(port, _usb_fingerprint(entry))}"
        )
    return discovered


def _bound_live_port(services, port: str, board_key: str, timeout: int = 45) -> str:
    """Follow only the same remembered physical USB device across COM changes."""
    original = str(port or "").strip()
    manager = getattr(services, "device_sessions", None)
    remember = getattr(manager, "remember", None)
    if callable(remember):
        try:
            remember(original)
        except Exception:
            pass
    waiter = getattr(services, "wait_for_device_reconnect", None)
    if callable(waiter):
        return str(waiter(original, timeout=timeout, expected_board=board_key)).strip()
    resolver = getattr(services, "resolve_live_port", None)
    if callable(resolver):
        return str(resolver(original) or original).strip()
    return original


def _verify_bound_node(
    services, port: str, board_key: str, *, timeout: int = 45
) -> tuple[str, str]:
    """Wait for a physically bound node and verify its board with bounded retries."""
    deadline = time.monotonic() + max(5, int(timeout))
    current = str(port or "").strip()
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            current = _bound_live_port(services, current, board_key, timeout=8)
            info = services.verify_node(current, expected_board=board_key)
            detected = services.detect_board_from_text(info)
            if detected != board_key:
                raise RuntimeError(
                    f"{current}: Board {detected!r}, erwartet {board_key!r}"
                )
            return current, info
        except Exception as exc:
            last_error = exc
            time.sleep(1.0)
    raise RuntimeError(
        f"{port}: physisch gebundenes {board_key}-Gerät wurde nicht stabil erreichbar: "
        f"{type(last_error).__name__ if last_error else 'unknown'}: {last_error}"
    ) from last_error


def _read_role_with_fallback(services, provisioning, port: str) -> dict[str, str]:
    """Use the enhanced JARNSEN role service when present, otherwise CLI readback."""
    try:
        line = provisioning._raw_command(
            port,
            "JARNSEN_TOOL_ROLE_INFO",
            expected="===JARNSEN_ROLE===",
            timeout=2.5,
            attempts=1,
            services=services,
        )
        parsed = provisioning._parse_role_info(line)
        if parsed.get("role_api") == "1" and str(parsed.get("role") or "").strip():
            parsed["source"] = "jarnsen-role-api"
            return parsed
    except Exception as exc:
        print(
            "ROLE_INFO enhanced service unavailable; validating supported Meshtastic fallback: "
            f"{type(exc).__name__}: {str(exc)[:180]}"
        )

    from profile_utils import summary_from_info_text

    result = services.meshtastic(port, "--info", timeout=45, check=False)
    output = "\n".join(
        str(part or "") for part in (result.stdout, result.stderr) if part
    )
    role = summary_from_info_text(output).role.strip()
    if not role:
        raise RuntimeError(f"{port}: Rolle weder über ROLE_INFO noch --info lesbar.")
    return {
        "role": role,
        "known": "1",
        "persisted": "readback",
        "allowed": "1",
        "role_api": "0",
        "source": "meshtastic-info",
    }


def _supreme_full_cycle_enabled() -> bool:
    """Arm the destructive Supreme lab node only in the intended context."""
    if os.environ.get("GITHUB_ACTIONS", "").strip().casefold() == "true":
        return (
            os.environ.get("GITHUB_REF", "").strip()
            == "refs/heads/feat/mini-serial-flasher"
        )
    return (
        os.environ.get("JARNSEN_SUPREME_HIL_CONFIRM", "").strip()
        == "I_ACCEPT_SUPREME_FACTORY_FLASH"
    )


class HardwareFlashContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        import _build_version  # noqa: F401 - installs the packaged runtime layers
        import services

        cls.services = services
        cls.ports = _configured_ports() or _auto_discover_ports(services)
        supreme_required = _supreme_full_cycle_enabled()

        # On the dedicated feature branch the Supreme is the destructive release
        # gate. A clean unittest skip used to make the Actions step look green
        # even though no real HIL had run. Treat missing/undetected lab hardware
        # as a hard infrastructure failure there; other branches retain the
        # optional read-only contract semantics.
        if not cls.ports:
            if supreme_required:
                raise RuntimeError(
                    "Supreme Full-HIL ist auf feat/mini-serial-flasher verpflichtend, "
                    "aber keine USB-Test-Hardware wurde erkannt."
                )
            raise unittest.SkipTest(
                "Keine angeschlossene Test-Hardware gefunden. Optional explizit: "
                "JARNSEN_FLASHER_HW_PORTS=tracker=COM3,repeater=COM4"
            )

        if supreme_required and "tbeam_supreme" not in cls.ports:
            raise RuntimeError(
                "Supreme Full-HIL ist auf feat/mini-serial-flasher verpflichtend, "
                f"erkannt wurden nur: {', '.join(sorted(cls.ports))}."
            )

    def test_configured_boards_read_and_preflight(self) -> None:
        unknown = sorted(set(self.ports).difference(self.services.BOARD_PROFILES))
        self.assertFalse(unknown, f"Unbekannte Board-Keys: {unknown}")
        for board_key, port in sorted(self.ports.items()):
            with self.subTest(board=board_key, port=port):
                live_port, info = _verify_bound_node(
                    self.services, port, board_key, timeout=45
                )
                self.ports[board_key] = live_port
                detected = self.services.detect_board_from_text(info)
                self.assertEqual(detected, board_key)
                bundle = resolve_reference_bundle(self.services, board_key)
                report = None
                for attempt in range(1, 4):
                    report = self.services.run_flash_preflight(
                        live_port, board_key, bundle, "update"
                    )
                    if report.ready:
                        break
                    if attempt < 3:
                        time.sleep(1.0)
                        live_port, _ = _verify_bound_node(
                            self.services, live_port, board_key, timeout=20
                        )
                        self.ports[board_key] = live_port
                self.assertIsNotNone(report)
                self.assertTrue(report.ready, report.format())

    def test_role_readback_service_or_legacy_fallback(self) -> None:
        """Require a real role readback without making the enhanced service mandatory."""
        import review_team_provisioning_v2 as provisioning

        for board_key, port in sorted(self.ports.items()):
            with self.subTest(board=board_key, port=port):
                live_port, _ = _verify_bound_node(
                    self.services, port, board_key, timeout=45
                )
                self.ports[board_key] = live_port
                parsed = _read_role_with_fallback(
                    self.services, provisioning, live_port
                )
                self.assertTrue(str(parsed.get("role") or "").strip())
                self.assertIn(
                    parsed.get("source"),
                    {"jarnsen-role-api", "meshtastic-info"},
                )
                print(
                    f"Role readback {board_key} {live_port}: "
                    f"role={parsed.get('role')!r} source={parsed.get('source')}"
                )

    def test_optional_update_and_postflash_verification(self) -> None:
        enabled = os.environ.get("JARNSEN_FLASHER_HW_FLASH", "").strip() == "1"
        armed = (
            os.environ.get("JARNSEN_FLASHER_HW_FLASH_CONFIRM", "").strip()
            == "I_ACCEPT_FIRMWARE_FLASH"
        )
        if not (enabled and armed):
            self.skipTest(
                "Hardware-Flash ist sicher gesperrt; Read/Preflight/ROLE_INFO wurden "
                "trotzdem automatisch ausgefuehrt."
            )

        from unified_service_v2 import flash_firmware_only_bundle

        for board_key, port in sorted(self.ports.items()):
            with self.subTest(board=board_key, port=port):
                before = self.services.query_jarnsen_identity(port)
                bundle = resolve_reference_bundle(self.services, board_key)
                flash_firmware_only_bundle(
                    self.services, port, board_key, bundle, print
                )
                self.services.wait_for_serial(port, timeout=120)
                self.services.verify_node(port, expected_board=board_key)
                after = self.services.query_jarnsen_identity(port)
                self.assertIsNotNone(after)
                self.assertEqual(getattr(after, "version", ""), bundle.version)
                self.assertEqual(getattr(after, "build", None), bundle.run_number)
                if before is not None:
                    print(
                        f"{board_key}: Build {getattr(before, 'build', None)} "
                        f"-> {getattr(after, 'build', None)}"
                    )

    def test_00_supreme_full_first_flash_cycle(self) -> None:
        """Run the destructive one-node Supreme HIL including the feature matrix."""
        if "tbeam_supreme" not in self.ports:
            self.skipTest(
                "Keine LILYGO T-Beam Supreme angeschlossen; destruktiver Full-HIL uebersprungen."
            )
        if not _supreme_full_cycle_enabled():
            self.skipTest(
                "Supreme Full-HIL ist nur auf feat/mini-serial-flasher automatisch "
                "oder lokal mit expliziter Bestaetigung freigegeben."
            )

        import supreme_full_hil

        original_port = self.ports["tbeam_supreme"]
        manager = getattr(self.services, "device_sessions", None)
        fingerprint = None
        remember = getattr(manager, "remember", None)
        if callable(remember):
            fingerprint = remember(original_port)
        old_env = {
            name: os.environ.get(name)
            for name in (
                "JARNSEN_SUPREME_HIL_PORT",
                "JARNSEN_SUPREME_HIL_SERIAL",
                "JARNSEN_SUPREME_HIL_LOCATION",
            )
        }
        os.environ["JARNSEN_SUPREME_HIL_PORT"] = original_port
        if fingerprint is not None:
            if fingerprint.serial_number:
                os.environ["JARNSEN_SUPREME_HIL_SERIAL"] = fingerprint.serial_number
            if fingerprint.location:
                os.environ["JARNSEN_SUPREME_HIL_LOCATION"] = fingerprint.location
        try:
            result = supreme_full_hil.main()
        finally:
            for name, value in old_env.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
        self.assertEqual(
            result,
            0,
            "Supreme First-Flash HIL ist fehlgeschlagen; siehe "
            "ci-logs/supreme-hil/report.json und trace.txt.",
        )
        try:
            full_report = json.loads(
                supreme_full_hil.REPORT_PATH.read_text(encoding="utf-8")
            )
        except Exception as exc:
            self.fail(f"Supreme Full-HIL Report konnte nicht gelesen werden: {exc}")
        self.assertEqual(
            full_report.get("status"),
            "passed",
            "Supreme Full-HIL wurde nicht vollständig ausgeführt: "
            f"status={full_report.get('status')!r} "
            f"reason={full_report.get('skip_reason')!r}",
        )

        import supreme_feature_matrix_hil

        matrix_result = supreme_feature_matrix_hil.main()
        self.assertEqual(
            matrix_result,
            0,
            "Supreme Feature-Matrix HIL ist fehlgeschlagen; siehe "
            "ci-logs/supreme-hil/report.json und trace.txt.",
        )

        # The recovery candidate is accepted only long enough to run the
        # destructive Supreme cycle. From here on all ordinary contracts require
        # an active Meshtastic response that independently proves the board again.
        live_port, info = _verify_bound_node(
            self.services, original_port, "tbeam_supreme", timeout=90
        )
        detected = self.services.detect_board_from_text(info)
        self.assertEqual(detected, "tbeam_supreme")
        self.ports["tbeam_supreme"] = live_port
        print(
            "Supreme recovery re-verified: "
            f"{original_port} -> {live_port} board={detected}"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
