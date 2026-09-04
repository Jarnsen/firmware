from __future__ import annotations

from typing import Any


def _emit(message: str) -> None:
    try:
        import diagnostics
        diagnostics._emit(message)
    except Exception:
        pass


def install(services: Any) -> None:
    """Attach profile progress and reveal only the finished native dashboard.

    FlasherApp still constructs its legacy widget tree as a compatibility scaffold.  Showing
    that scaffold and then replacing it at mainloop entry caused the visible "two UIs on top
    of each other" startup effect on Windows, especially at 125% DPI.  The root is now hidden
    immediately after CTk construction, the legacy tree is allowed to finish safely, and the
    window is revealed only after native_dashboard has replaced the complete tree.

    This keeps the fix for the old CTkScrollableFrame canvas race while making the first frame
    the user sees the final dashboard instead of the legacy layout.
    """
    import customtkinter as ctk

    from profile_specials_fix import install as install_profile_specials_fix

    install_profile_specials_fix(services)

    original_root_init = ctk.CTk.__init__

    def root_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_root_init(self, *args, **kwargs)

        # Never paint the compatibility/legacy scaffold.  It is destroyed at mainloop entry
        # after all CTk constructors have completed, then the native dashboard is shown once.
        try:
            self.withdraw()
            self._jarnsen_startup_hidden = True
        except Exception as exc:
            _emit(f"NATIVE DASHBOARD withdraw warning type={type(exc).__name__} message={exc}")

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

            _emit("NATIVE DASHBOARD build start trigger=mainloop app-init-complete=1 visible=0")
            _build_dashboard(self, services)

            # Force one complete layout pass while still hidden, then reveal the finished UI.
            try:
                self.update_idletasks()
            except Exception as exc:
                _emit(f"NATIVE DASHBOARD postflush warning type={type(exc).__name__} message={exc}")

            try:
                self.deiconify()
                try:
                    self.state("zoomed")
                except Exception:
                    try:
                        self.attributes("-zoomed", True)
                    except Exception:
                        pass
                self.update_idletasks()
                self._jarnsen_startup_hidden = False
            except Exception as exc:
                _emit(f"NATIVE DASHBOARD reveal warning type={type(exc).__name__} message={exc}")

            _emit("NATIVE DASHBOARD build complete trigger=mainloop first-visible=native-only")

        return original_mainloop(self, *args, **kwargs)

    ctk.CTk.mainloop = mainloop
    _emit("PROFILE PROGRESS layer installed native-dashboard-trigger=mainloop startup-hidden=1")
