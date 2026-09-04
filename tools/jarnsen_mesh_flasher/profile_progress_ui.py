from __future__ import annotations

from typing import Any


def _emit(message: str) -> None:
    try:
        import diagnostics
        diagnostics._emit(message)
    except Exception:
        pass


def install(services: Any) -> None:
    """Attach profile progress and replace the legacy dashboard only after app init is complete.

    The previous implementation installed native_dashboard from CTk.__init__.  That allowed an
    ``after_idle`` callback to destroy the legacy CTkScrollableFrame while its constructor was
    still configuring the internal canvas.  On Windows this could raise
    ``invalid command name '.!ctkframe2.!canvas'`` and also leave legacy widgets behind.

    Building at mainloop entry guarantees that FlasherApp.__init__ and _build_ui have returned.
    We flush pending idle geometry work while the legacy widgets are still valid, then replace
    the complete tree exactly once before the normal event loop starts.
    """
    import customtkinter as ctk

    from profile_specials_fix import install as install_profile_specials_fix

    install_profile_specials_fix(services)

    original_root_init = ctk.CTk.__init__

    def root_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_root_init(self, *args, **kwargs)

        def attach_progress(attempt: int = 0) -> None:
            if getattr(self, "_jarnsen_profile_progress_ui", False):
                return
            if not hasattr(self, "_set_progress"):
                if attempt < 20:
                    try:
                        self.after(10, lambda: attach_progress(attempt + 1))
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
            self.after(10, attach_progress)
        except Exception:
            pass

    ctk.CTk.__init__ = root_init

    original_mainloop = ctk.CTk.mainloop

    def mainloop(self: Any, *args: Any, **kwargs: Any):
        if not getattr(self, "_jarnsen_native_dashboard_ready", False):
            try:
                # Finish all geometry/configure idle work before destroying the legacy tree.
                # This specifically prevents CTkScrollableFrame from touching a canvas that
                # has already been removed by the replacement dashboard.
                self.update_idletasks()
            except Exception as exc:
                _emit(f"NATIVE DASHBOARD preflush warning type={type(exc).__name__} message={exc}")

            from native_dashboard import _build_dashboard

            _emit("NATIVE DASHBOARD build start trigger=mainloop app-init-complete=1")
            _build_dashboard(self, services)
            _emit("NATIVE DASHBOARD build complete trigger=mainloop legacy-construction-complete=1")

        return original_mainloop(self, *args, **kwargs)

    ctk.CTk.mainloop = mainloop
    _emit("PROFILE PROGRESS layer installed native-dashboard-trigger=mainloop legacy-ui-race=disabled")
