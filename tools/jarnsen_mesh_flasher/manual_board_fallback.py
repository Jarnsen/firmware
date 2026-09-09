from __future__ import annotations

from typing import Any

import customtkinter as ctk


_INSTALLED = False
_PREFERRED_ORDER = (
    "tracker",
    "repeater",
    "wio",
    "heltec_v4",
    "tbeam",
    "tbeam_supreme",
)


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _board_values(services: Any) -> list[str]:
    values = ["Automatisch"]
    seen: set[str] = set()
    for key in _PREFERRED_ORDER:
        profile = services.BOARD_PROFILES.get(key)
        if not profile:
            continue
        label = str(profile.get("label") or key).strip()
        if label and label not in seen:
            values.append(label)
            seen.add(label)
    for key, profile in services.BOARD_PROFILES.items():
        label = str(profile.get("label") or key).strip()
        if label and label not in seen:
            values.append(label)
            seen.add(label)
    return values


def _manual_board_key(app: Any, services: Any) -> str | None:
    try:
        manual = str(app.board_var.get() or "").strip()
    except Exception:
        manual = ""
    if manual and manual != "Automatisch":
        for key, profile in services.BOARD_PROFILES.items():
            if manual == str(profile.get("label") or "").strip():
                return key
    return None


def install(services: Any) -> None:
    """Expose every supported board as a safe manual fallback.

    Original Meshtastic firmware can expose a serial port before `meshtastic --info`
    gives us a unique physical board identity. Auto detection remains preferred, but
    the operator must still be able to select T-Beam/T-Beam Supreme explicitly and
    continue with the normal full-flash safety path.
    """

    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    available_values = _board_values(services)
    label_to_key = {
        str(profile.get("label") or "").strip(): key
        for key, profile in services.BOARD_PROFILES.items()
        if str(profile.get("label") or "").strip()
    }

    original_root_init = ctk.CTk.__init__

    def root_init(app: Any, *args: Any, **kwargs: Any) -> None:
        original_root_init(app, *args, **kwargs)
        original_resolver = getattr(app, "_selected_board_key", None)
        if not callable(original_resolver):
            return

        def selected_board_key() -> str | None:
            manual = _manual_board_key(app, services)
            if manual:
                return manual
            return original_resolver()

        app._selected_board_key = selected_board_key
        app._jarnsen_manual_board_fallback = True
        app._jarnsen_manual_board_values = tuple(available_values)

    ctk.CTk.__init__ = root_init

    original_option_init = ctk.CTkOptionMenu.__init__

    def option_init(self: Any, master: Any, *args: Any, **kwargs: Any) -> None:
        values = list(kwargs.get("values") or [])
        variable = kwargs.get("variable")
        current = ""
        try:
            current = str(variable.get() or "") if variable is not None else ""
        except Exception:
            current = ""

        looks_like_board_menu = (
            current == "Automatisch"
            and "Automatisch" in values
            and any(label in values for label in label_to_key)
        )
        if looks_like_board_menu:
            kwargs["values"] = list(available_values)
            original_command = kwargs.get("command")

            def board_changed(value: str) -> None:
                if callable(original_command):
                    original_command(value)
                try:
                    app = master.winfo_toplevel()
                    app._jarnsen_manual_board_values = tuple(available_values)
                    key = label_to_key.get(str(value or "").strip())
                    if key:
                        app._append_log(
                            f"BOARD MANUELL · {services.BOARD_PROFILES[key]['label']} ausgewählt · "
                            "Auto-Erkennung wird für diesen Flash übersteuert"
                        )
                except Exception:
                    pass

            kwargs["command"] = board_changed

        original_option_init(self, master, *args, **kwargs)

    ctk.CTkOptionMenu.__init__ = option_init
    _emit("MANUAL BOARD FALLBACK installed values=" + ", ".join(available_values))

    # The generated _build_version.py always installs this manual fallback after
    # runtime_config. Use that stable hook to activate the final all-board service
    # layer in source runs and in the frozen EXE alike.
    from unified_service_v2 import install as install_unified_service_v2
    install_unified_service_v2(services)

    # Centralize every serial/raw action behind one per-device session manager.
    # It also remembers USB fingerprints and aliases a changed COM port after a
    # reboot so all boards get the same reconnect behavior.
    from device_core import install as install_device_core
    install_device_core(services)

    # Install the final write guard after all runtime/profile/service layers so
    # both "AUTOMATISCH FLASHEN" and "NUR PROFIL SCHREIBEN" use the same choices.
    from write_choice_guard import install as install_write_choice_guard
    install_write_choice_guard(services)

    # The write guard decides which role is authoritative. Keep that decision
    # through the staged restore/reboot and verify the role directly on the node.
    from role_write_finalize import install as install_role_write_finalize
    install_role_write_finalize(services)

    # Names are just as authoritative as the selected role. Verify Long/Short
    # directly on the node after every name write and retry once before failing.
    from name_write_finalize import install as install_name_write_finalize
    install_name_write_finalize(services)

    # Replace the compact legacy choice dialog with the centered reference-sized
    # dialog. The replacement happens after write_choice_guard is installed but
    # before any button can invoke it.
    from write_choice_ui_fix import install as install_write_choice_ui_fix
    install_write_choice_ui_fix()

    # Patch both the firmware-status module and service hook so the reference
    # dashboard does not bypass serial arbitration and does not trust stale scan
    # text after one failed raw identity probe.
    from firmware_identity_reliable import install as install_firmware_identity_reliable
    install_firmware_identity_reliable(services)

    # Heltec V3 keeps its CP210x COM port visible while the ESP32-S3 application
    # is still booting. Require a real Meshtastic response before profile restore,
    # avoid the destructive pre-profile reboot on V3 and remember a verified
    # firmware write so the dashboard cannot fall back to stale VANILLA scan data.
    from v3_runtime_stability import install as install_v3_runtime_stability
    install_v3_runtime_stability(services)

    # V3 raw diagnostics need a different readiness strategy from Meshtastic
    # protobuf: after reboot/open the CP210x can already be visible while the raw
    # service loop is not listening yet. Retry JARNSEN_TOOL_FULL until the firmware
    # returns its BEGIN marker; do not run --info in between because that would put
    # SerialConsole back into framed/protobuf mode.
    from v3_usb_log_stability import install as install_v3_usb_log_stability
    install_v3_usb_log_stability(services)

    # Unified-Core firmware can still report Meshtastic's legacy VANILLA edition
    # while its firmwareVersion contains the exact Git commit used by the JARNSEN
    # workflow. Correlate that SHA with successful board artifacts before falling
    # back to slow raw identity probes, so version/build are exact after restart.
    from firmware_identity_sha_match import install as install_firmware_identity_sha_match
    install_firmware_identity_sha_match(services)

    # Radio-profile service takeover no longer needs a Meshtastic reboot. Keep
    # the port/application ready and use the explicit JARNSEN_TOOL_* handshake.
    # This removes the 79%-stage native-USB re-enumeration race on T-Beam Supreme
    # and gives every supported board the same non-destructive radio preflight.
    from radio_profile_runtime_stability import install as install_radio_profile_runtime_stability
    install_radio_profile_runtime_stability(services)

    # Profile-only must be much lighter than a complete flash: do not rebuild the
    # persistent Jarnsen radio slots on every YAML write, combine Long/Short into
    # one persisted owner transaction, and block stale deferred role/power state
    # after a failed write from leaking into later Service actions.
    from profile_runtime_efficiency import install as install_profile_runtime_efficiency
    install_profile_runtime_efficiency(services)

    # Hard acceptance gate: every supported board must expose the same visible
    # feature contract. Board-specific transport implementations may differ, but
    # they are not allowed to remove a user-facing action for another board.
    from six_board_parity import validate as validate_six_board_parity
    validate_six_board_parity(services)
