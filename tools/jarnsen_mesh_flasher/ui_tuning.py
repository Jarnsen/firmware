from __future__ import annotations

from typing import Any

import customtkinter as ctk


_INSTALLED = False
REFERENCE_WIDGET_SCALE = 1.00
REFERENCE_FONT_SCALE = 1.28


def install(services: Any) -> None:
    """Keep startup geometry/DPI handling lightweight; reference UI owns final chrome."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    # Build 140 proved that enlarging the complete CustomTkinter widget geometry was
    # the wrong lever: the 1920x1080 card grid was already in the right places and the
    # 1.16 widget scale started clipping the firmware status strip.  What still differs
    # from the approved reference is primarily text/glyph density.  Keep control/card
    # geometry at 1.00 and scale only CTkFont sizes.
    ctk.set_widget_scaling(REFERENCE_WIDGET_SCALE)

    original_font_init = ctk.CTkFont.__init__

    def font_init(self: Any, *args: Any, **kwargs: Any) -> None:
        args_list = list(args)
        if "size" in kwargs and kwargs["size"] is not None:
            try:
                kwargs["size"] = max(1, int(round(float(kwargs["size"]) * REFERENCE_FONT_SCALE)))
            except Exception:
                pass
        elif len(args_list) >= 2 and args_list[1] is not None:
            try:
                args_list[1] = max(1, int(round(float(args_list[1]) * REFERENCE_FONT_SCALE)))
            except Exception:
                pass
        original_font_init(self, *args_list, **kwargs)

    ctk.CTkFont.__init__ = font_init

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
            f"font-scale={REFERENCE_FONT_SCALE:.2f} "
            "reference=1920x1080@125% reference-chrome-owner=1"
        )
    except Exception:
        pass
