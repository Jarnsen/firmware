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
    """Keep the dashboard readable while still fitting smaller logical desktops."""
    try:
        width = int(root.winfo_screenwidth())
        height = int(root.winfo_screenheight())
    except Exception:
        return 0.92

    if height <= 780:
        return 0.78
    if height <= 850:
        return 0.82
    if height <= 920:
        return 0.86
    if height <= 1000:
        return 0.91
    if height <= 1100:
        return 0.96
    if width >= 2500:
        return 1.00
    return 0.98


def install(services: Any) -> None:
    """Use the whole Full-HD window with a fixed two-column dashboard."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    # Replace only the root-level CTkScrollableFrame. The main dashboard no
    # longer has a canvas or scrollbar. Scrollable dialogs are left untouched.
    def scrollable_factory(master: Any, *args: Any, **kwargs: Any):
        if _is_main_root(master):
            frame = ctk.CTkFrame(
                master,
                fg_color=kwargs.get("fg_color", "transparent"),
                corner_radius=0,
            )
            frame._jarnsen_dashboard = True
            frame._jarnsen_card_index = 0
            frame.grid_columnconfigure(0, weight=1, uniform="jarnsen-fullhd")
            frame.grid_columnconfigure(1, weight=1, uniform="jarnsen-fullhd")

            # Fill the entire available height. The first three rows keep the
            # operational cards balanced; the protocol gets most spare space.
            frame.grid_rowconfigure(0, weight=1, minsize=140)
            frame.grid_rowconfigure(1, weight=1, minsize=165)
            frame.grid_rowconfigure(2, weight=1, minsize=135)
            frame.grid_rowconfigure(3, weight=4, minsize=230)
            return frame
        return _ORIGINAL_SCROLLABLE(master, *args, **kwargs)

    ctk.CTkScrollableFrame = scrollable_factory  # type: ignore[assignment]

    # app.py packs its six cards. Turn only the direct dashboard cards into a
    # grid so the left and right columns use the complete width and height.
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
                    padx=5,
                    pady=(0, 8),
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

    # DPI-aware scaling. Build 42 fitted, but 0.84 scaling made Full HD look
    # unnecessarily tiny. Keep controls near native size on a real 1080p screen.
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
                f"widget_scaling={scale:.2f} main_scrollbar=none fill_height=1"
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
                width = max(1100, min(1780, sw - 30))
                height = max(700, min(1000, sh - 45))
                geometry_string = f"{width}x{height}"
            except Exception:
                geometry_string = "1600x900"
        return original_geometry(self, geometry_string)

    ctk.CTk.geometry = geometry  # type: ignore[assignment]

    original_minsize = ctk.CTk.minsize

    def minsize(self: Any, width: int | None = None, height: int | None = None):
        if width == 780 and height == 820:
            width, height = 1100, 680
        return original_minsize(self, width, height)

    ctk.CTk.minsize = minsize  # type: ignore[assignment]

    # The old one-column labels wrapped at 740 px. Restrict that only enough to
    # stay inside a dashboard column; keep normal dialog typography unchanged.
    original_label_init = ctk.CTkLabel.__init__

    def label_init(self: Any, master: Any, *args: Any, **kwargs: Any) -> None:
        if _is_main_window_widget(master):
            wrap = int(kwargs.get("wraplength", 0) or 0)
            if wrap >= 700:
                kwargs["wraplength"] = 650
        original_label_init(self, master, *args, **kwargs)

    ctk.CTkLabel.__init__ = label_init  # type: ignore[assignment]

    # Do NOT compress the protocol textbox anymore. It is the best use of the
    # otherwise empty lower half of a 1080p display and already packs expand=True.

    try:
        import diagnostics

        diagnostics._emit(
            "UI TUNING installed mode=fullhd-fill layout=2col main_scrollbar=none "
            "target=1920x1080 protocol=expand"
        )
    except Exception:
        pass
