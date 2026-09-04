from __future__ import annotations

from typing import Any

import customtkinter as ctk


_INSTALLED = False
REFERENCE_WIDGET_SCALE = 1.00
REFERENCE_FONT_SCALE = 1.28
CONTENT_BASE_FONT_SIZE = 13


def install(services: Any) -> None:
    """Keep startup geometry/DPI handling lightweight; reference UI owns final chrome."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    # Keep card/control geometry stable.  Scale typography independently so the
    # approved 1920x1080 layout is not stretched.
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

    # User-approved visual tuning: use the available vertical space in Hinweise and
    # keep the protocol body at exactly the same base text size.  This is deliberately
    # targeted instead of globally enlarging controls/buttons again.
    original_label_init = ctk.CTkLabel.__init__

    def label_init(self: Any, master: Any, *args: Any, **kwargs: Any) -> None:
        text = kwargs.get("text")
        if isinstance(text, str) and text.startswith("• Vor dem Flashen"):
            kwargs["font"] = ctk.CTkFont(size=CONTENT_BASE_FONT_SIZE)
        original_label_init(self, master, *args, **kwargs)

    ctk.CTkLabel.__init__ = label_init

    original_textbox_init = ctk.CTkTextbox.__init__

    def textbox_init(self: Any, master: Any, *args: Any, **kwargs: Any) -> None:
        font = kwargs.get("font")
        family = ""
        try:
            family = str(font.cget("family")) if font is not None else ""
        except Exception:
            family = ""
        if family.lower() == "consolas":
            kwargs["font"] = ctk.CTkFont(family="Consolas", size=CONTENT_BASE_FONT_SIZE)
        original_textbox_init(self, master, *args, **kwargs)

    ctk.CTkTextbox.__init__ = textbox_init

    original_root_init = ctk.CTk.__init__

    def root_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_root_init(self, *args, **kwargs)

        def maximize() -> None:
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
            f"font-scale={REFERENCE_FONT_SCALE:.2f} content-base-font={CONTENT_BASE_FONT_SIZE} "
            "reference=1920x1080@125% reference-chrome-owner=1"
        )
    except Exception:
        pass
