from __future__ import annotations

import copy
import re
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

import serial
import yaml

import radio_profiles


RADIO_INFO_MARKER = "===JARNSEN_RADIO==="
RADIO_OK_MARKER = "===JARNSEN_RADIO_OK==="
RADIO_ERROR_MARKER = "===JARNSEN_RADIO_ERROR==="
ACTIVE_RE = re.compile(r"\bactive=(standard|jarnsen1|jarnsen2)\b", re.IGNORECASE)
JARNSEN_REGION = "US"
JARNSEN_PROFILES = (
    radio_profiles.PROFILE_JARNSEN_1,
    radio_profiles.PROFILE_JARNSEN_2,
)


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _frequency_key(profile: str) -> str:
    return "jarnsen_1_mhz" if profile == radio_profiles.PROFILE_JARNSEN_1 else "jarnsen_2_mhz"


def _raw_command(port: str, command: str, *, expected: str, timeout: float = 10.0) -> str:
    deadline = time.monotonic() + timeout
    buffer = bytearray()
    with serial.Serial(port=port, baudrate=115200, timeout=0.12, write_timeout=2.0) as ser:
        try:
            ser.reset_input_buffer()
        except Exception:
            pass
        time.sleep(0.20)
        payload = (command.rstrip() + "\n").encode("ascii", errors="strict")
        ser.write(payload)
        ser.flush()
        _emit(f"RADIO NODE SYNC command={command!r} port={port}")

        while time.monotonic() < deadline:
            chunk = ser.read(512)
            if chunk:
                buffer.extend(chunk)
                text = buffer.decode("utf-8", errors="replace")
                for line in text.replace("\r", "\n").split("\n")[:-1]:
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith(RADIO_ERROR_MARKER):
                        raise RuntimeError(line)
                    if line.startswith(expected):
                        _emit(f"RADIO NODE SYNC response={line!r} port={port}")
                        return line
            else:
                time.sleep(0.03)

    seen = buffer.decode("utf-8", errors="replace")[-600:]
    raise TimeoutError(
        f"Keine Antwort auf {command!r} von {port}. "
        f"Die installierte Firmware unterstützt die 3 Funkprofil-Slots möglicherweise noch nicht. "
        f"Empfangen: {seen!r}"
    )


def _reboot_to_raw(port: str, services: Any) -> None:
    try:
        services.reboot_node(port)
    except Exception as exc:
        _emit(f"RADIO NODE SYNC reboot-warning port={port} type={type(exc).__name__} message={exc}")
    services.wait_for_serial(port, timeout=90)
    time.sleep(1.0)


def _read_active_profile(port: str, services: Any) -> str:
    _reboot_to_raw(port, services)
    line = _raw_command(port, "JARNSEN_TOOL_RADIO_INFO", expected=RADIO_INFO_MARKER)
    match = ACTIVE_RE.search(line)
    if not match:
        raise RuntimeError(f"Aktives Funkprofil konnte nicht aus der Firmware-Antwort gelesen werden: {line}")
    active = match.group(1).lower()
    _emit(f"RADIO NODE SYNC active-before={active} port={port}")
    return active


def _frequency_for(settings: dict[str, Any], profile: str) -> str:
    key = _frequency_key(profile)
    fallback = radio_profiles.JARNSEN_FREQUENCIES[profile]
    value = settings.get(key, fallback)
    return f"{float(value):.3f}"


def _extract_region(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    config = data.get("config")
    if isinstance(config, dict):
        lora = config.get("lora")
        if isinstance(lora, dict):
            return str(lora.get("region") or "").strip().upper()
    lora = data.get("lora")
    if isinstance(lora, dict):
        return str(lora.get("region") or "").strip().upper()
    return ""


def _profile_region(profile: Path | None) -> str:
    if profile is None:
        return ""
    try:
        if not profile.exists():
            return ""
        data = yaml.safe_load(profile.read_text(encoding="utf-8", errors="replace")) or {}
        return _extract_region(data)
    except Exception as exc:
        _emit(f"RADIO NODE SYNC profile-region-warning type={type(exc).__name__} message={exc}")
        return ""


def _export_current_region(port: str, services: Any) -> str:
    work_dir = Path(services.PATHS.root) / "restore-work"
    work_dir.mkdir(parents=True, exist_ok=True)
    target = work_dir / f"radio-region-{re.sub(r'[^A-Za-z0-9_.-]+', '-', str(port))}-{time.time_ns()}.yaml"
    try:
        services.meshtastic(port, "--export-config", str(target), timeout=90)
        if not target.exists():
            raise RuntimeError("Meshtastic hat für die Regionsprüfung kein Profil erzeugt.")
        data = yaml.safe_load(target.read_text(encoding="utf-8", errors="replace")) or {}
        region = _extract_region(data)
        if not region:
            raise RuntimeError("Die Standard-Region konnte nicht aus der Node gelesen werden.")
        _emit(f"RADIO NODE SYNC standard-region-read port={port} region={region}")
        return region
    finally:
        try:
            target.unlink(missing_ok=True)
        except Exception:
            pass


def _set_node_region(port: str, region: str, services: Any) -> None:
    target = str(region or "").strip().upper()
    if not target:
        raise RuntimeError("Leere LoRa-Region kann nicht geschrieben werden.")
    _emit(f"RADIO NODE SYNC region-set port={port} region={target}")
    services.meshtastic(port, "--set", "lora.region", target, timeout=90)
    services.wait_for_serial(port, timeout=90)
    time.sleep(0.8)


def _select_raw(port: str, profile: str, services: Any) -> None:
    _raw_command(
        port,
        f"JARNSEN_TOOL_RADIO_SELECT {profile}",
        expected=RADIO_OK_MARKER,
    )
    time.sleep(2.0)
    services.wait_for_serial(port, timeout=90)
    time.sleep(0.8)


def _install_us_region_policy(services: Any) -> None:
    """Make J1/J2 self-contained US profiles without changing Standard."""
    if getattr(radio_profiles, "_jarnsen_us_region_policy", False):
        services.load_radio_profile_settings = lambda: radio_profiles.load_settings(services)
        services.save_radio_profile_settings = lambda settings: radio_profiles.save_settings(settings, services)
        services.validate_radio_profile_settings = radio_profiles.validate_settings
        services.radio_profile_summary = radio_profiles.summary
        services.apply_radio_profile_overlay = radio_profiles.apply_overlay
        return

    radio_profiles._jarnsen_us_region_policy = True
    base_validate_settings = radio_profiles.validate_settings
    base_load_settings = radio_profiles.load_settings
    base_save_settings = radio_profiles.save_settings
    base_apply_overlay = radio_profiles.apply_overlay
    base_summary = radio_profiles.summary
    base_validate_frequency = radio_profiles.validate_frequency_for_region

    def validate_settings(settings: dict[str, Any]) -> dict[str, Any]:
        checked = base_validate_settings(settings)
        for profile in JARNSEN_PROFILES:
            key = _frequency_key(profile)
            frequency = Decimal(str(checked[key]))
            base_validate_frequency(
                frequency,
                JARNSEN_REGION,
                label=radio_profiles.PROFILE_LABELS[profile],
            )
            checked[f"{profile}_region"] = JARNSEN_REGION
        return checked

    def load_settings(runtime_services: Any) -> dict[str, Any]:
        loaded = base_load_settings(runtime_services)
        try:
            return validate_settings(loaded)
        except Exception as exc:
            recovered = dict(loaded)
            for profile in JARNSEN_PROFILES:
                recovered[_frequency_key(profile)] = f"{radio_profiles.JARNSEN_FREQUENCIES[profile]:.3f}"
            _emit(
                "RADIO PROFILE US REGION RECOVER "
                f"type={type(exc).__name__} message={exc} defaults-restored=1"
            )
            return validate_settings(recovered)

    def save_settings(settings: dict[str, Any], runtime_services: Any) -> dict[str, Any]:
        checked = validate_settings(settings)
        checked["jarnsen1_region"] = JARNSEN_REGION
        checked["jarnsen2_region"] = JARNSEN_REGION
        return base_save_settings(checked, runtime_services)

    def validate_frequency_for_region(frequency: Decimal, region: Any, *, label: str) -> None:
        effective_region = JARNSEN_REGION if str(label or "").strip().lower().startswith("jarnsen") else region
        return base_validate_frequency(frequency, effective_region, label=label)

    def apply_overlay(data: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
        checked = validate_settings(settings)
        selected = checked["selected"]
        source = data
        if selected in JARNSEN_PROFILES:
            source = copy.deepcopy(data)
            lora = radio_profiles._lora_mapping(source)
            lora["region"] = JARNSEN_REGION
        staged = base_apply_overlay(source, checked)
        if selected in JARNSEN_PROFILES:
            radio_profiles._lora_mapping(staged)["region"] = JARNSEN_REGION
        return staged

    def summary(settings: dict[str, Any]) -> str:
        checked = validate_settings(settings)
        text = base_summary(checked)
        if checked["selected"] in JARNSEN_PROFILES and "Region US" not in text:
            label = radio_profiles.PROFILE_LABELS[checked["selected"]]
            text = text.replace(f"{label} ·", f"{label} · Region US ·", 1)
        return text

    radio_profiles.validate_settings = validate_settings
    radio_profiles.load_settings = load_settings
    radio_profiles.save_settings = save_settings
    radio_profiles.validate_frequency_for_region = validate_frequency_for_region
    radio_profiles.apply_overlay = apply_overlay
    radio_profiles.summary = summary
    radio_profiles.JARNSEN_REGION = JARNSEN_REGION

    services.load_radio_profile_settings = lambda: load_settings(services)
    services.save_radio_profile_settings = lambda settings: save_settings(settings, services)
    services.validate_radio_profile_settings = validate_settings
    services.radio_profile_summary = summary
    services.apply_radio_profile_overlay = apply_overlay

    try:
        import radio_profiles_ui

        if not getattr(radio_profiles_ui, "_jarnsen_us_region_editor_badge", False):
            radio_profiles_ui._jarnsen_us_region_editor_badge = True
            controller = radio_profiles_ui._RadioEditorController
            base_build_radio_tab = controller.build_radio_tab
            base_save_profile = controller._save_profile

            def build_radio_tab(self: Any, tab: Any, profile: str) -> None:
                base_build_radio_tab(self, tab, profile)
                if profile not in JARNSEN_PROFILES:
                    return
                status_var = self.status_vars.get(profile)
                if status_var is not None and "Region US" not in str(status_var.get()):
                    status_var.set(f"{status_var.get()} · Region US")
                for widget in radio_profiles_ui._walk(tab):
                    if not isinstance(widget, radio_profiles_ui.ctk.CTkLabel):
                        continue
                    try:
                        text = str(widget.cget("text") or "")
                    except Exception:
                        continue
                    if text.startswith("Dieses Funkprofil wird") and "Region: US" not in text:
                        widget.configure(
                            text=text
                            + "\nRegion: US · automatisch für Jarnsen 1/2 · Standard-Region bleibt unverändert."
                        )
                        break

            def save_profile(self: Any, profile: str) -> None:
                result = base_save_profile(self, profile)
                if profile in JARNSEN_PROFILES and not self.dirty.get(profile):
                    status_var = self.status_vars.get(profile)
                    if status_var is not None and "Region US" not in str(status_var.get()):
                        status_var.set(f"{status_var.get()} · Region US")
                return result

            controller.build_radio_tab = build_radio_tab
            controller._save_profile = save_profile
    except Exception as exc:
        _emit(f"RADIO PROFILE US REGION editor-badge-warning type={type(exc).__name__} message={exc}")

    _emit(
        "RADIO PROFILE US REGION policy installed jarnsen-region=US standard-region-preserved=1 "
        "overlay-region=US editor-badge=1 custom-frequency-us-validation=1"
    )


def _write_firmware_slots(
    port: str,
    settings: dict[str, Any],
    active_before: str,
    standard_region: str,
    services: Any,
) -> None:
    standard_region = str(standard_region or "").strip().upper()
    if not standard_region:
        standard_region = _export_current_region(port, services)

    _reboot_to_raw(port, services)
    _raw_command(
        port,
        "JARNSEN_TOOL_RADIO_CAPTURE_STANDARD",
        expected=RADIO_OK_MARKER,
    )

    temporary_us_standard = standard_region != JARNSEN_REGION
    write_error: Exception | None = None

    try:
        if temporary_us_standard:
            _set_node_region(port, JARNSEN_REGION, services)
            _reboot_to_raw(port, services)
            _raw_command(
                port,
                "JARNSEN_TOOL_RADIO_CAPTURE_STANDARD",
                expected=RADIO_OK_MARKER,
            )
            _emit(
                "RADIO NODE SYNC temporary-standard "
                f"port={port} from={standard_region} to={JARNSEN_REGION} purpose=jarnsen-slot-template"
            )

        for profile in JARNSEN_PROFILES:
            frequency = _frequency_for(settings, profile)
            modem = radio_profiles.modem_preset_for(settings, profile) or "LONG_FAST"
            hops = radio_profiles.hop_limit_for(settings, profile)
            _raw_command(
                port,
                f"JARNSEN_TOOL_RADIO_SET {profile} {frequency} {modem} {hops}",
                expected=RADIO_OK_MARKER,
            )
    except Exception as exc:
        write_error = exc
    finally:
        if temporary_us_standard:
            try:
                _set_node_region(port, standard_region, services)
                _reboot_to_raw(port, services)
                _raw_command(
                    port,
                    "JARNSEN_TOOL_RADIO_CAPTURE_STANDARD",
                    expected=RADIO_OK_MARKER,
                )
                _emit(
                    "RADIO NODE SYNC standard-restored "
                    f"port={port} region={standard_region} after-jarnsen-template=1"
                )
            except Exception as restore_exc:
                if write_error is None:
                    write_error = restore_exc
                else:
                    _emit(
                        "RADIO NODE SYNC standard-restore-error "
                        f"port={port} type={type(restore_exc).__name__} message={restore_exc}"
                    )

    target = active_before if active_before in radio_profiles.PROFILE_KEYS else radio_profiles.PROFILE_STANDARD
    try:
        _select_raw(port, target, services)
    except Exception as select_exc:
        if write_error is None:
            write_error = select_exc
        else:
            _emit(
                "RADIO NODE SYNC active-restore-error "
                f"port={port} target={target} type={type(select_exc).__name__} message={select_exc}"
            )

    if write_error is not None:
        raise write_error

    line = _raw_command(port, "JARNSEN_TOOL_RADIO_INFO", expected=RADIO_INFO_MARKER)
    match = ACTIVE_RE.search(line)
    active_after = match.group(1).lower() if match else ""
    if active_after != target:
        raise RuntimeError(
            f"Funkprofil-Verifikation fehlgeschlagen: erwartet {target}, Firmware meldet {active_after or line}"
        )
    _emit(
        "RADIO NODE SYNC complete "
        f"port={port} standard=1 standard-region={standard_region} "
        f"jarnsen1=1 jarnsen1-region={JARNSEN_REGION} "
        f"jarnsen2=1 jarnsen2-region={JARNSEN_REGION} "
        f"active-before={active_before} active-after={active_after}"
    )


def _sync_existing_slots(port: str, services: Any) -> None:
    settings = dict(services.load_radio_profile_settings())
    active_before = _read_active_profile(port, services)

    # A manual sync can be triggered while J1/J2 is active. Switch to the real
    # Standard slot first so CAPTURE_STANDARD can never clone the active Jarnsen slot.
    if active_before != radio_profiles.PROFILE_STANDARD:
        _select_raw(port, radio_profiles.PROFILE_STANDARD, services)

    standard_region = _export_current_region(port, services)
    _write_firmware_slots(port, settings, active_before, standard_region, services)


def install(services: Any) -> None:
    """Write all three radio profiles into firmware slots while preserving the node's active selection."""
    _install_us_region_policy(services)

    if getattr(services, "_jarnsen_radio_profile_node_sync_installed", False):
        return
    services._jarnsen_radio_profile_node_sync_installed = True

    base_restore = services.restore_profile

    def restore_profile(port: str, profile: Path | None = None) -> None:
        # A profile-only write must remain a single Meshtastic transaction.  The
        # firmware schedules a reboot as soon as that transaction is committed.
        # Exporting the region or touching the persistent radio slots here used
        # to reopen the same serial port during that reboot window.  Apart from
        # making the just-written values appear lost, this caused a cascade of
        # USB disconnects/restarts on ESP32-S3 boards.  Radio-slot maintenance is
        # deliberately kept in sync_radio_profiles_to_node() and in full-flash
        # provisioning, where the lifecycle owns those extra connections.
        manager = getattr(services, "flash_transactions", None)
        try:
            record = manager.active(port) if manager is not None else None
        except Exception:
            record = None
        if str(getattr(record, "kind", "") or "") == "profile_only":
            _emit(
                f"RADIO NODE SYNC BYPASS port={port} profile-only=1 "
                "yaml-transaction=single slot-sync=deferred serial-reopen=0"
            )
            return base_restore(port, profile)

        settings = dict(services.load_radio_profile_settings())
        active_before = _read_active_profile(port, services)
        source = Path(profile or services.PATHS.active_profile)
        standard_region = _profile_region(source)

        # radio_profiles.restore_profile historically staged only the currently
        # selected overlay. Force that wrapper to write Standard to config.lora;
        # the two JARNSEN variants are stored separately afterwards.
        original_load = radio_profiles.load_settings
        forced_standard = dict(settings)
        forced_standard["selected"] = radio_profiles.PROFILE_STANDARD
        radio_profiles.load_settings = lambda _services: dict(forced_standard)
        try:
            base_restore(port, profile)
        finally:
            radio_profiles.load_settings = original_load

        if not standard_region:
            standard_region = _export_current_region(port, services)
        _write_firmware_slots(port, settings, active_before, standard_region, services)

    services.restore_profile = restore_profile
    services.sync_radio_profiles_to_node = lambda port: _sync_existing_slots(port, services)

    _emit(
        "RADIO NODE SYNC installed slots=standard,jarnsen1,jarnsen2 preserve-active=1 "
        "standard-via-profile=1 jarnsen-via-firmware-service=1 jarnsen-region=US "
        "temporary-us-template=1 standard-region-restored=1 verification=1"
    )
