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
    """Expose every supported board as a safe manual fallback and install final runtime layers."""
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

    from unified_service_v2 import install as install_unified_service_v2
    install_unified_service_v2(services)

    from unified_release_resolver import install as install_unified_release_resolver
    install_unified_release_resolver(services)

    from device_core import install as install_device_core
    install_device_core(services)

    from write_choice_guard import install as install_write_choice_guard
    install_write_choice_guard(services)

    from role_write_finalize import install as install_role_write_finalize
    install_role_write_finalize(services)

    from name_write_finalize import install as install_name_write_finalize
    install_name_write_finalize(services)

    from write_choice_ui_fix import install as install_write_choice_ui_fix
    install_write_choice_ui_fix()

    from firmware_identity_reliable import install as install_firmware_identity_reliable
    install_firmware_identity_reliable(services)

    from v3_runtime_stability import install as install_v3_runtime_stability
    install_v3_runtime_stability(services)

    from v3_usb_log_stability import install as install_v3_usb_log_stability
    install_v3_usb_log_stability(services)

    from firmware_identity_sha_match import install as install_firmware_identity_sha_match
    install_firmware_identity_sha_match(services)

    from radio_profile_runtime_stability import install as install_radio_profile_runtime_stability
    install_radio_profile_runtime_stability(services)

    from profile_runtime_efficiency import install as install_profile_runtime_efficiency
    install_profile_runtime_efficiency(services)

    from profile_runtime_stability_v2 import install as install_profile_runtime_stability_v2
    install_profile_runtime_stability_v2(services)

    from profile_preflight_feedback import install as install_profile_preflight_feedback
    install_profile_preflight_feedback(services)
    if not getattr(services, "_jarnsen_profile_preflight_feedback", False):
        raise RuntimeError("Profile preflight feedback layer is not active")

    from build261_hardening import install as install_build261_hardening
    install_build261_hardening(services)
    if not getattr(services, "_jarnsen_build261_hardening", False):
        raise RuntimeError("Build 261 hardening layer is not active")

    from profile_role_choice_fix import install as install_profile_role_choice_fix
    install_profile_role_choice_fix(services)
    if not getattr(services, "_jarnsen_profile_role_choice_fix", False):
        raise RuntimeError("Profile role choice fix layer is not active")

    from review_team_hardening import install as install_review_team_hardening
    install_review_team_hardening(services)
    if not getattr(services, "_jarnsen_review_team_hardening", False):
        raise RuntimeError("Review-team hardening layer is not active")

    from review_team_provisioning_v2 import install as install_review_team_provisioning_v2
    install_review_team_provisioning_v2(services)
    if not getattr(services, "_jarnsen_review_team_provisioning_v2", False):
        raise RuntimeError("Review-team provisioning V2 layer is not active")

    from review_team_provisioning_guard import install as install_review_team_provisioning_guard
    install_review_team_provisioning_guard(services)
    if not getattr(services, "_jarnsen_review_team_provisioning_guard", False):
        raise RuntimeError("Review-team provisioning guard is not active")

    # Final hardening services are intentionally installed as one ordered chain.
    # profile_contract must exist before transaction_flow captures its verifier.
    from profile_contract import install as install_profile_contract
    install_profile_contract(services)

    from transaction_flow import install as install_transaction_flow
    install_transaction_flow(services)

    from artifact_guard import install as install_artifact_guard
    install_artifact_guard(services)

    from recovery_mode import install as install_recovery_mode
    install_recovery_mode(services)

    from system_diagnostics import install as install_system_diagnostics
    install_system_diagnostics(services)

    from port_reconnect_hardening import install as install_port_reconnect_hardening
    install_port_reconnect_hardening(services)
    if not getattr(services, "_jarnsen_port_reconnect_hardening", False):
        raise RuntimeError("Port reconnect hardening layer is not active")

    from series_report import install as install_series_report
    install_series_report(services)

    # Install the final action binding before parity validation: six_board_parity
    # explicitly checks that both native_actions and reference_dashboard expose
    # the all-board dynamic firmware-only handler.
    from firmware_only_stability import install as install_firmware_only_stability
    install_firmware_only_stability(services)

    from six_board_parity import validate as validate_six_board_parity
    validate_six_board_parity(services)

    # _build_version.py installs advanced_flasher after this hook, keeping its
    # resilient baud-retry wrapper as the final public flash_bundle binding.
    from final_hardening_contract import install as install_final_hardening_contract
    install_final_hardening_contract(services)
