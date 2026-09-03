from __future__ import annotations

import re
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


def _grid_main_card(frame: Any, master: Any) -> bool:
    """Place the six main cards in a compact two-column Full-HD dashboard."""
    if not isinstance(master, ctk.CTkScrollableFrame):
        return False
    if not _is_main_window_widget(master):
        return False

    index = int(getattr(master, "_jarnsen_main_card_index", 0))
    setattr(master, "_jarnsen_main_card_index", index + 1)

    # app.py creates cards in this order:
    # 0 device, 1 profile, 2 firmware, 3 names, 4 actions/series, 5 protocol.
    positions = {
        0: dict(row=0, column=0),
        1: dict(row=1, column=0),
        2: dict(row=2, column=0),
        3: dict(row=0, column=1),
        4: dict(row=1, column=1, rowspan=2),
        5: dict(row=3, column=0, columnspan=2),
    }
    position = positions.get(index)
    if position is None:
        return False

    try:
        master.grid_columnconfigure(0, weight=1, uniform="jarnsen-main")
        master.grid_columnconfigure(1, weight=1, uniform="jarnsen-main")
        frame.grid(sticky="nsew", padx=5, pady=(0, 10), **position)
        return True
    except Exception:
        return False


def install(services: Any) -> None:
    """Arrange the main flasher as a clean dashboard for a 1920x1080 display."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    # Keep controls readable while recovering enough vertical space for the
    # protocol and series controls on a 1080-pixel-high desktop.
    try:
        ctk.set_widget_scaling(0.90)
    except Exception:
        pass

    # Wider, lower normal window. A maximized 1920x1080 window uses the same
    # two-column structure and normally needs no scrolling for core controls.
    try:
        original_geometry = ctk.CTk.geometry

        def geometry(self: Any, geometry_string: str | None = None):
            if geometry_string and re.fullmatch(r"\s*860x960(?:[+-].*)?\s*", geometry_string):
                geometry_string = "1500x900"
            return original_geometry(self, geometry_string)

        ctk.CTk.geometry = geometry  # type: ignore[assignment]
    except Exception:
        pass

    try:
        original_minsize = ctk.CTk.minsize

        def minsize(self: Any, width: int | None = None, height: int | None = None):
            if width == 780 and height == 820:
                width, height = 1100, 700
            return original_minsize(self, width, height)

        ctk.CTk.minsize = minsize  # type: ignore[assignment]
    except Exception:
        pass

    # Convert only direct main-body cards from pack() to grid(). All nested
    # frames keep their original layout, and profile-manager dialogs are untouched.
    try:
        original_frame_pack = ctk.CTkFrame.pack

        def frame_pack(self: Any, *args: Any, **kwargs: Any):
            master = getattr(self, "master", None)
            if _grid_main_card(self, master):
                return None
            return original_frame_pack(self, *args, **kwargs)

        ctk.CTkFrame.pack = frame_pack  # type: ignore[assignment]
    except Exception:
        pass

    # Long labels were designed for an 840px single column. In the new left/right
    # cards they wrap at a useful width instead of forcing an oversized column.
    try:
        original_label_init = ctk.CTkLabel.__init__

        def label_init(self: Any, master: Any, *args: Any, **kwargs: Any) -> None:
            if _is_main_window_widget(master):
                wrap = int(kwargs.get("wraplength", 0) or 0)
                if wrap >= 700:
                    kwargs["wraplength"] = 560
            original_label_init(self, master, *args, **kwargs)

        ctk.CTkLabel.__init__ = label_init  # type: ignore[assignment]
    except Exception:
        pass

    # Keep the detailed log visible without letting it dominate the dashboard.
    try:
        original_textbox_init = ctk.CTkTextbox.__init__

        def textbox_init(self: Any, master: Any, *args: Any, **kwargs: Any) -> None:
            if _is_main_window_widget(master) and int(kwargs.get("height", 0) or 0) >= 170:
                kwargs["height"] = 105
            original_textbox_init(self, master, *args, **kwargs)

        ctk.CTkTextbox.__init__ = textbox_init  # type: ignore[assignment]
    except Exception:
        pass

    # Slightly reduce only large main action buttons. Normal buttons and profile
    # manager controls retain their familiar sizes.
    try:
        original_button_init = ctk.CTkButton.__init__

        def button_init(self: Any, master: Any, *args: Any, **kwargs: Any) -> None:
            if _is_main_window_widget(master):
                height = int(kwargs.get("height", 0) or 0)
                if height >= 50:
                    kwargs["height"] = 42
                elif height >= 42:
                    kwargs["height"] = 37
            original_button_init(self, master, *args, **kwargs)

        ctk.CTkButton.__init__ = button_init  # type: ignore[assignment]
    except Exception:
        pass

    try:
        import diagnostics

        diagnostics._emit(
            "UI TUNING installed layout=two-column target=1920x1080 "
            "widget_scaling=0.90 default=1500x900 log_height=105"
        )
    except Exception:
        pass
