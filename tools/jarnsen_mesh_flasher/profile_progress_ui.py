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
    """Map profile-restore progress into the existing 79..86% workflow range."""
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
                # The original workflow uses 79% for profile restore and moves to
                # name/reboot stages afterwards. Keep those later milestones intact.
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
    _emit("PROFILE PROGRESS UI layer installed")
