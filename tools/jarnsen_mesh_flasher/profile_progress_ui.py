from __future__ import annotations

from typing import Any


def _emit(message: str) -> None:
    try:
        import diagnostics
        diagnostics._emit(message)
    except Exception:
        pass


def install(services: Any) -> None:
    """Keep profile progress mapping, then build exactly one native dashboard."""
    import customtkinter as ctk

    from profile_specials_fix import install as install_profile_specials_fix
    install_profile_specials_fix(services)

    from native_dashboard import install as install_native_dashboard
    install_native_dashboard(services)

    original_root_init = ctk.CTk.__init__

    def root_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_root_init(self, *args, **kwargs)

        def attach_progress(attempt: int = 0) -> None:
            if getattr(self, "_jarnsen_profile_progress_ui", False):
                return
            if not hasattr(self, "_set_progress"):
                if attempt < 20:
                    try:
                        self.after_idle(lambda: attach_progress(attempt + 1))
                    except Exception:
                        pass
                return

            self._jarnsen_profile_progress_ui = True

            def profile_progress(fraction: float, stage: str, detail: str = "") -> None:
                fraction = max(0.0, min(1.0, float(fraction)))
                overall = 0.79 + 0.07 * fraction
                suffix = f" · {detail}" if detail else ""
                self._set_progress(overall, f"{stage}{suffix}")

            services._jarnsen_profile_progress_callback = profile_progress
            _emit("PROFILE PROGRESS attached native-dashboard=1 overall-range=0.79..0.86")

        try:
            self.after_idle(attach_progress)
        except Exception:
            pass

    ctk.CTk.__init__ = root_init
    _emit("PROFILE PROGRESS layer installed native-dashboard-only=1 legacy-ui-patches=0")
