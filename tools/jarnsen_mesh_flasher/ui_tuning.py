from __future__ import annotations

from typing import Any

import customtkinter as ctk


_INSTALLED = False
REFERENCE_WIDGET_SCALE = 1.16


def install(services: Any) -> None:
    """Keep startup geometry/DPI handling lightweight; reference UI owns final chrome."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    # The approved screenshot is 1325x750 and is rendered at 1920x1080 on the
    # 125%-scaled Windows runner.  Its geometric source-to-target factor is ~1.45,
    # while Windows DPI already contributes 1.25.  A CustomTkinter *widget* scale of
    # 1.16 supplies the remaining 1.45/1.25 factor without touching window/DPI
    # geometry.  Build 139 proved the card positions are already close, but buttons,
    # labels, icons and inputs were visibly too small inside those cards.
    ctk.set_widget_scaling(REFERENCE_WIDGET_SCALE)

    original_root_init = ctk.CTk.__init__

    def root_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_root_init(self, *args, **kwargs)

        def maximize() -> None:
            # The reference layer owns its borderless DPI-correct geometry. Do not
            # re-enable Tk fullscreen here: at 125% that state is DPI-virtualized and
            # caused the 1536x864/2400x1350 oscillation seen in Builds 137/138.
            if bool(getattr(self, "_jarnsen_reference_fullscreen", False)):
                return
            try:
                self.state("zoomed")
            except Exception:
                try:
                    self.attributes("-zoomed", True)
                except Exception:
                    pass

        try:
            self.after_idle(maximize)
        except Exception:
            pass

    ctk.CTk.__init__ = root_init

    original_geometry = ctk.CTk.geometry

    def geometry(self: Any, geometry_string: str | None = None):
        if geometry_string and geometry_string.strip().startswith("860x960"):
            try:
                sw = int(self.winfo_screenwidth())
                sh = int(self.winfo_screenheight())
                geometry_string = f"{max(1280, sw - 24)}x{max(720, sh - 48)}"
            except Exception:
                geometry_string = "1600x900"
        return original_geometry(self, geometry_string)

    ctk.CTk.geometry = geometry

    original_minsize = ctk.CTk.minsize

    def minsize(self: Any, width: int | None = None, height: int | None = None):
        if width == 780 and height == 820:
            width, height = 1180, 720
        return original_minsize(self, width, height)

    ctk.CTk.minsize = minsize

    try:
        import diagnostics

        diagnostics._emit(
            "UI TUNING installed lightweight=1 native-dashboard=1 "
            f"dpi=windows-automatic widget-scale={REFERENCE_WIDGET_SCALE:.2f} "
            "reference=1920x1080@125% reference-chrome-owner=1"
        )
    except Exception:
        pass
