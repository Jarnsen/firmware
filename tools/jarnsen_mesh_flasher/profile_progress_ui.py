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
    """Install the final reference dashboard as FlasherApp's only UI construction path.

    Runtime configuration is loaded before ``FlasherApp`` is instantiated.  We hook
    ``CTk.__init__`` only long enough to replace the instance's ``_build_ui`` method.
    Therefore the legacy scrollable dashboard is never constructed and there is no
    destroy/rebuild or delayed overlay phase at startup.
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

            from reference_dashboard import _build_dashboard

            _emit("REFERENCE DASHBOARD build start trigger=FlasherApp._build_ui direct=1 legacy-build=0")
            _build_dashboard(app_self, services)

            if not getattr(app_self, "_jarnsen_profile_progress_ui", False):
                app_self._jarnsen_profile_progress_ui = True

                def profile_progress(fraction: float, stage: str, detail: str = "") -> None:
                    fraction = max(0.0, min(1.0, float(fraction)))
                    overall = 0.79 + 0.07 * fraction
                    suffix = f" · {detail}" if detail else ""
                    app_self._set_progress(overall, f"{stage}{suffix}")

                services._jarnsen_profile_progress_callback = profile_progress
                _emit("PROFILE PROGRESS attached reference-dashboard=1 overall-range=0.79..0.86")

            app_self._jarnsen_native_build_override = True
            _emit("REFERENCE DASHBOARD build complete trigger=FlasherApp._build_ui first-ui=reference-v2")

        self._build_ui = types.MethodType(direct_build_ui, self)
        self._jarnsen_native_build_override = True

    ctk.CTk.__init__ = root_init
    _emit("PROFILE PROGRESS layer installed reference-dashboard-trigger=_build_ui legacy-build=0")
