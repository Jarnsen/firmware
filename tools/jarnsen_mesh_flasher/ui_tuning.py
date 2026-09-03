from __future__ import annotations

from typing import Any

import customtkinter as ctk


_INSTALLED = False
_ORIGINAL_SCROLLABLE = ctk.CTkScrollableFrame


def _is_main_root(master: Any) -> bool:
    return isinstance(master, ctk.CTk) and not isinstance(master, ctk.CTkToplevel)


def _is_main_window_widget(master: Any) -> bool:
    node = master
    seen: set[int] = set()
    while node is not None and id(node) not in seen:
        seen.add(id(node))
        if isinstance(node, ctk.CTkToplevel):
            return False
        if isinstance(node, ctk.CTk):
            return True
        node = getattr(node, "master", None)
    return False


def _responsive_scale(root: Any) -> float:
    try:
        width = int(root.winfo_screenwidth())
        height = int(root.winfo_screenheight())
    except Exception:
        return 0.78

    # 1920x1080 at 125% is typically ~1536x864 logical Tk pixels.
    if height <= 780:
        return 0.68
    if height <= 850:
        return 0.72
    if height <= 920:
        return 0.76
    if height <= 1000:
        return 0.80
    if height <= 1100:
        return 0.84
    if width >= 2500:
        return 0.90
    return 0.84


def install(services: Any) -> None:
    """Use a real, non-scrollable two-column dashboard for the main window.

    The old app creates CTkScrollableFrame for the main body. On some
    CustomTkinter/Windows combinations its private canvas hierarchy prevented
    reliable post-build reflow. For the root window only, replace that one
    constructor with a plain CTkFrame. Dialog scrollable frames are untouched.
    """
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    # Replace only the root-level CTkScrollableFrame (the main app body).
    def scrollable_factory(master: Any, *args: Any, **kwargs: Any):
        if _is_main_root(master):
            frame = ctk.CTkFrame(
                master,
                fg_color=kwargs.get("fg_color", "transparent"),
                corner_radius=0,
            )
            frame._jarnsen_dashboard = True
            frame._jarnsen_card_index = 0
            try:
                frame.grid_columnconfigure(0, weight=1, uniform="jarnsen-fullhd")
                frame.grid_columnconfigure(1, weight=1, uniform="jarnsen-fullhd")
            except Exception:
                pass
            return frame
        return _ORIGINAL_SCROLLABLE(master, *args, **kwargs)

    ctk.CTkScrollableFrame = scrollable_factory  # type: ignore[assignment]

    # app.py calls pack() for each of the six direct cards. Convert only those
    # direct children of the dashboard to grid at creation time. This avoids
    # mixing geometry managers later and guarantees that the layout is 2-column.
    original_frame_pack = ctk.CTkFrame.pack

    def frame_pack(self: Any, *args: Any, **kwargs: Any):
        parent = getattr(self, "master", None)
        if getattr(parent, "_jarnsen_dashboard", False):
            index = int(getattr(parent, "_jarnsen_card_index", 0))
            setattr(parent, "_jarnsen_card_index", index + 1)
            positions = {
                0: (0, 0, 1, 1),  # Gerät
                1: (1, 0, 1, 1),  # Grundeinstellungen
                2: (2, 0, 1, 1),  # Firmware
                3: (0, 1, 1, 1),  # Gerätename
                4: (1, 1, 2, 1),  # Ablauf + Serienmodus
                5: (3, 0, 1, 2),  # Protokoll
            }
            if index in positions:
                row, column, rowspan, columnspan = positions[index]
                self.grid(
                    row=row,
                    column=column,
                    rowspan=rowspan,
                    columnspan=columnspan,
                    sticky="nsew",
                    padx=4,
                    pady=(0, 6),
                )
                try:
                    import diagnostics
                    diagnostics._emit(
                        f"UI CARD GRID index={index} row={row} col={column} "
                        f"rowspan={rowspan} colspan={columnspan}"
                    )
                except Exception:
                    pass
                return None
        return original_frame_pack(self, *args, **kwargs)

    ctk.CTkFrame.pack = frame_pack  # type: ignore[assignment]

    # DPI-aware scale and maximize after app.py has applied its old portrait
    # geometry. The main body itself has no canvas and therefore no scrollbar.
    original_root_init = ctk.CTk.__init__

    def root_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_root_init(self, *args, **kwargs)
        scale = _responsive_scale(self)
        try:
            ctk.set_widget_scaling(scale)
        except Exception:
            pass

        def maximize() -> None:
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

        try:
            import diagnostics
            diagnostics._emit(
                "UI FULLHD ROOT "
                f"screen={self.winfo_screenwidth()}x{self.winfo_screenheight()} "
                f"widget_scaling={scale:.2f} main_scrollbar=none"
            )
        except Exception:
            pass

    ctk.CTk.__init__ = root_init  # type: ignore[assignment]

    original_geometry = ctk.CTk.geometry

    def geometry(self: Any, geometry_string: str | None = None):
        if geometry_string and geometry_string.strip().startswith("860x960"):
            try:
                sw = int(self.winfo_screenwidth())
                sh = int(self.winfo_screenheight())
                width = max(1100, min(1700, sw - 30))
                height = max(650, min(940, sh - 50))
                geometry_string = f"{width}x{height}"
            except Exception:
                geometry_string = "1500x820"
        return original_geometry(self, geometry_string)

    ctk.CTk.geometry = geometry  # type: ignore[assignment]

    original_minsize = ctk.CTk.minsize

    def minsize(self: Any, width: int | None = None, height: int | None = None):
        if width == 780 and height == 820:
            width, height = 960, 600
        return original_minsize(self, width, height)

    ctk.CTk.minsize = minsize  # type: ignore[assignment]

    # Compact only widgets in the main window; dialogs/profile manager retain
    # their normal sizing and may still use real scrollable frames.
    original_label_init = ctk.CTkLabel.__init__

    def label_init(self: Any, master: Any, *args: Any, **kwargs: Any) -> None:
        if _is_main_window_widget(master):
            wrap = int(kwargs.get("wraplength", 0) or 0)
            if wrap >= 700:
                kwargs["wraplength"] = 520
        original_label_init(self, master, *args, **kwargs)

    ctk.CTkLabel.__init__ = label_init  # type: ignore[assignment]

    original_textbox_init = ctk.CTkTextbox.__init__

    def textbox_init(self: Any, master: Any, *args: Any, **kwargs: Any) -> None:
        if _is_main_window_widget(master) and int(kwargs.get("height", 0) or 0) >= 170:
            kwargs["height"] = 68
        original_textbox_init(self, master, *args, **kwargs)

    ctk.CTkTextbox.__init__ = textbox_init  # type: ignore[assignment]

    original_button_init = ctk.CTkButton.__init__

    def button_init(self: Any, master: Any, *args: Any, **kwargs: Any) -> None:
        if _is_main_window_widget(master):
            height = int(kwargs.get("height", 0) or 0)
            if height >= 50:
                kwargs["height"] = 36
            elif height >= 42:
                kwargs["height"] = 32
        original_button_init(self, master, *args, **kwargs)

    ctk.CTkButton.__init__ = button_init  # type: ignore[assignment]

    try:
        import diagnostics
        diagnostics._emit(
            "UI TUNING installed mode=fixed-dashboard layout=2col "
            "main_scrollbar=none target=1920x1080"
        )
    except Exception:
        pass
