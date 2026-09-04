from __future__ import annotations

import types
from typing import Any


def _emit(message: str) -> None:
    try:
        import diagnostics
        diagnostics._emit(message)
    except Exception:
        pass


def install(services: Any) -> None:
    """Map profile progress and install post-runtime service controls."""
    import customtkinter as ctk

    original_root_init = ctk.CTk.__init__

    def root_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_root_init(self, *args, **kwargs)

        def patch_app() -> None:
            if not hasattr(self, "_set_progress") or not hasattr(self, "_append_log"):
                try:
                    self.after(100, patch_app)
                except Exception:
                    pass
                return
            if getattr(self, "_jarnsen_profile_progress_ui", False):
                return
            self._jarnsen_profile_progress_ui = True

            def profile_progress(fraction: float, stage: str, detail: str = "") -> None:
                fraction = max(0.0, min(1.0, float(fraction)))
                overall = 0.79 + 0.07 * fraction
                suffix = f" · {detail}" if detail else ""
                self._set_progress(overall, f"{stage}{suffix}")

            services._jarnsen_profile_progress_callback = profile_progress
            _emit("PROFILE PROGRESS UI installed overall-range=0.79..0.86")

        try:
            self.after(320, patch_app)
        except Exception:
            pass

    ctk.CTk.__init__ = root_init

    from profile_specials_fix import install as install_profile_specials_fix
    install_profile_specials_fix(services)

    from firmware_only import install as install_firmware_only
    install_firmware_only(services)

    from usb_log_download import install as install_usb_log_download
    install_usb_log_download(services)

    from profile_editor import install as install_profile_editor
    install_profile_editor(services)

    from profile_dropdowns import install as install_profile_dropdowns
    install_profile_dropdowns(services)

    from firmware_status_ui import install as install_firmware_status
    install_firmware_status(services)

    from dashboard_cleanup import install as install_dashboard_cleanup
    install_dashboard_cleanup(services)

    from ui_action_polish import install as install_ui_action_polish
    install_ui_action_polish(services)

    from ui_overlap_guard import install as install_ui_overlap_guard
    install_ui_overlap_guard(services)

    from ui_final_layout import install as install_ui_final_layout
    install_ui_final_layout(services)

    from ui_target_layout import install as install_ui_target_layout
    install_ui_target_layout(services)

    from ui_1080_fit import install as install_ui_1080_fit
    install_ui_1080_fit(services)

    # Absolute final visual layer. Unlike the legacy CTk height calculations this
    # uses the actual body dimensions and the proportions measured from the user-
    # approved 1920x1080 reference. That keeps the result stable under Windows DPI.
    from ui_reference_exact import install as install_ui_reference_exact
    install_ui_reference_exact(services)

    _emit(
        "PROFILE PROGRESS UI layer installed + firmware-only + usb-log + "
        "profile-specials-fix + profile-editor + profile-dropdowns + "
        "firmware-status + dashboard-cleanup + ui-action-polish + overlap-guard + "
        "final-layout + target-layout + 1080-fit + reference-exact"
    )
