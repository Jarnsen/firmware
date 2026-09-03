from __future__ import annotations

from typing import Any

import customtkinter as ctk


_INSTALLED = False


def _is_main_window_widget(master: Any) -> bool:
    """True for widgets below the main CTk root, false for CTkToplevel dialogs."""
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
    """Choose a compact scale from the logical desktop size.

    A 1920x1080 Windows display at 125% DPI often exposes only roughly
    1536x864 logical pixels to Tk. The layout therefore targets the logical
    work area rather than assuming that 1080 physical pixels are available.
    """
    try:
        width = int(root.winfo_screenwidth())
        height = int(root.winfo_screenheight())
    except Exception:
        return 0.80

    if height <= 820:
        return 0.72
    if height <= 900:
        return 0.76
    if height <= 1000:
        return 0.80
    if height <= 1100:
        return 0.84
    if width >= 2500:
        return 0.90
    return 0.86


def _reflow_main_body(body: Any) -> None:
    """Reflow all six completed main cards into a real two-column dashboard."""
    cards = list(getattr(body, "_jarnsen_main_cards", []))
    if len(cards) < 6 or getattr(body, "_jarnsen_reflow_done", False):
        return

    setattr(body, "_jarnsen_reflow_done", True)

    # app.py creates exactly these cards in order:
    # Gerät, Grundeinstellungen, Firmware, Gerätename, Ablauf/Serie, Protokoll.
    positions = (
        (0, 0, 1, 1),
        (1, 0, 1, 1),
        (2, 0, 1, 1),
        (0, 1, 1, 1),
        (1, 1, 2, 1),
        (3, 0, 1, 2),
    )

    try:
        for card in cards[:6]:
            try:
                card.pack_forget()
            except Exception:
                pass
            try:
                card.grid_forget()
            except Exception:
                pass

        body.grid_columnconfigure(0, weight=1, uniform="jarnsen-fullhd")
        body.grid_columnconfigure(1, weight=1, uniform="jarnsen-fullhd")
        body.grid_rowconfigure(0, weight=0)
        body.grid_rowconfigure(1, weight=0)
        body.grid_rowconfigure(2, weight=0)
        body.grid_rowconfigure(3, weight=0)

        for card, (row, column, rowspan, columnspan) in zip(cards[:6], positions):
            card.grid(
                row=row,
                column=column,
                rowspan=rowspan,
                columnspan=columnspan,
                sticky="nsew",
                padx=5,
                pady=(0, 8),
            )

        # Reset the scroll position. On Full HD the dashboard should now fit;
        # scrolling remains only as a fallback for genuinely smaller desktops.
        try:
            body._parent_canvas.yview_moveto(0.0)
        except Exception:
            pass

        try:
            import diagnostics

            root = body.winfo_toplevel()
            diagnostics._emit(
                "UI REFLOW OK layout=2col cards=6 "
                f"screen={root.winfo_screenwidth()}x{root.winfo_screenheight()}"
            )
        except Exception:
            pass
    except Exception as exc:
        try:
            import diagnostics

            diagnostics._emit(f"UI REFLOW ERROR {exc!r}")
        except Exception:
            pass


def install(services: Any) -> None:
    """Install a DPI-aware Full-HD layout before app.py creates its widgets."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    # Configure scaling as soon as the root exists but before FlasherApp creates
    # its child widgets. This handles 1920x1080 displays with 100-150% Windows DPI.
    try:
        original_root_init = ctk.CTk.__init__

        def root_init(self: Any, *args: Any, **kwargs: Any) -> None:
            original_root_init(self, *args, **kwargs)
            scale = _responsive_scale(self)
            try:
                ctk.set_widget_scaling(scale)
            except Exception:
                pass

            # Maximize after FlasherApp has completed its own geometry calls.
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
                    f"widget_scaling={scale:.2f} maximize=1"
                )
            except Exception:
                pass

        ctk.CTk.__init__ = root_init  # type: ignore[assignment]
    except Exception:
        pass

    # Do not let app.py's old portrait geometry/minimum force a tall window.
    try:
        original_geometry = ctk.CTk.geometry

        def geometry(self: Any, geometry_string: str | None = None):
            if geometry_string and geometry_string.strip().startswith("860x960"):
                try:
                    sw = int(self.winfo_screenwidth())
                    sh = int(self.winfo_screenheight())
                    width = max(1100, min(1600, sw - 60))
                    height = max(680, min(900, sh - 90))
                    geometry_string = f"{width}x{height}"
                except Exception:
                    geometry_string = "1400x780"
            return original_geometry(self, geometry_string)

        ctk.CTk.geometry = geometry  # type: ignore[assignment]
    except Exception:
        pass

    try:
        original_minsize = ctk.CTk.minsize

        def minsize(self: Any, width: int | None = None, height: int | None = None):
            if width == 780 and height == 820:
                width, height = 980, 620
            return original_minsize(self, width, height)

        ctk.CTk.minsize = minsize  # type: ignore[assignment]
    except Exception:
        pass

    # Collect direct cards while they are created. Crucially, do NOT switch
    # geometry managers during pack(); wait until all six cards and their child
    # widgets are fully built, then reflow them in one after_idle operation.
    try:
        original_frame_init = ctk.CTkFrame.__init__

        def frame_init(self: Any, master: Any, *args: Any, **kwargs: Any) -> None:
            original_frame_init(self, master, *args, **kwargs)
            if isinstance(master, ctk.CTkScrollableFrame) and _is_main_window_widget(master):
                cards = getattr(master, "_jarnsen_main_cards", None)
                if cards is None:
                    cards = []
                    setattr(master, "_jarnsen_main_cards", cards)
                cards.append(self)
                if len(cards) == 6:
                    try:
                        master.after_idle(lambda body=master: _reflow_main_body(body))
                    except Exception:
                        pass

        ctk.CTkFrame.__init__ = frame_init  # type: ignore[assignment]
    except Exception:
        pass

    # Old single-column labels used a 740px wrap width. Each Full-HD column is
    # narrower, so use a stable compact wrap width instead of expanding the card.
    try:
        original_label_init = ctk.CTkLabel.__init__

        def label_init(self: Any, master: Any, *args: Any, **kwargs: Any) -> None:
            if _is_main_window_widget(master):
                wrap = int(kwargs.get("wraplength", 0) or 0)
                if wrap >= 700:
                    kwargs["wraplength"] = 500
            original_label_init(self, master, *args, **kwargs)

        ctk.CTkLabel.__init__ = label_init  # type: ignore[assignment]
    except Exception:
        pass

    # The protocol stays visible, but no longer consumes a large part of a
    # 864px logical desktop at 125% Windows scaling.
    try:
        original_textbox_init = ctk.CTkTextbox.__init__

        def textbox_init(self: Any, master: Any, *args: Any, **kwargs: Any) -> None:
            if _is_main_window_widget(master) and int(kwargs.get("height", 0) or 0) >= 170:
                kwargs["height"] = 76
            original_textbox_init(self, master, *args, **kwargs)

        ctk.CTkTextbox.__init__ = textbox_init  # type: ignore[assignment]
    except Exception:
        pass

    # Compact only the tall primary buttons. Normal controls and dialogs keep
    # their regular usable target size.
    try:
        original_button_init = ctk.CTkButton.__init__

        def button_init(self: Any, master: Any, *args: Any, **kwargs: Any) -> None:
            if _is_main_window_widget(master):
                height = int(kwargs.get("height", 0) or 0)
                if height >= 50:
                    kwargs["height"] = 38
                elif height >= 42:
                    kwargs["height"] = 34
            original_button_init(self, master, *args, **kwargs)

        ctk.CTkButton.__init__ = button_init  # type: ignore[assignment]
    except Exception:
        pass

    try:
        import diagnostics

        diagnostics._emit(
            "UI TUNING installed mode=responsive-fullhd target=1920x1080 dpi-aware "
            "layout=postbuild-2col log_height=76"
        )
    except Exception:
        pass
