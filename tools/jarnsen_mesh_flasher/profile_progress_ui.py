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
    """Replace FlasherApp._build_ui before the app instance reaches that call.

    Runtime configuration is installed before ``FlasherApp`` is instantiated.  We therefore
    hook ``CTk.__init__`` only long enough to install an instance-level ``_build_ui`` method.
    When ``FlasherApp.__init__`` later calls ``self._build_ui()``, it now builds the final
    native dashboard immediately instead of constructing the legacy UI first and replacing it
    at mainloop entry.

    This removes the old double-build startup path entirely: no legacy CTkScrollableFrame,
    no destroy/rebuild pass, no delayed mainloop replacement, and no visible overlay/flicker.
    """
    import customtkinter as ctk

    from profile_specials_fix import install as install_profile_specials_fix

    install_profile_specials_fix(services)

    original_root_init = ctk.CTk.__init__

    def root_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_root_init(self, *args, **kwargs)

        def direct_build_ui(app_self: Any) -> None:
            if getattr(app_self, "_jarnsen_native_dashboard_ready", False):
                return

            from native_dashboard import _build_dashboard

            _emit("NATIVE DASHBOARD build start trigger=FlasherApp._build_ui direct=1 legacy-build=0")
            _build_dashboard(app_self, services)

            if not getattr(app_self, "_jarnsen_profile_progress_ui", False):
                app_self._jarnsen_profile_progress_ui = True

                def profile_progress(fraction: float, stage: str, detail: str = "") -> None:
                    fraction = max(0.0, min(1.0, float(fraction)))
                    overall = 0.79 + 0.07 * fraction
                    suffix = f" · {detail}" if detail else ""
                    app_self._set_progress(overall, f"{stage}{suffix}")

                services._jarnsen_profile_progress_callback = profile_progress
                _emit("PROFILE PROGRESS attached native-dashboard=1 overall-range=0.79..0.86")

            app_self._jarnsen_native_build_override = True
            _emit("NATIVE DASHBOARD build complete trigger=FlasherApp._build_ui direct=1 first-ui=native")

        # FlasherApp.__init__ calls self._build_ui() only after all state variables and
        # service methods needed by native_dashboard already exist.  Installing the method
        # here prevents the legacy class implementation from ever running for this instance.
        self._build_ui = types.MethodType(direct_build_ui, self)
        self._jarnsen_native_build_override = True

    ctk.CTk.__init__ = root_init
    _emit("PROFILE PROGRESS layer installed native-dashboard-trigger=_build_ui legacy-build=0")
