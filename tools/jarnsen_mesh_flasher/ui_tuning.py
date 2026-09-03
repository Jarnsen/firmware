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


def install(services: Any) -> None:
    """Compact the main flasher UI so all controls fit comfortably at 1920x1080."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    # CustomTkinter scales widget dimensions and geometry-manager padding with
    # widget scaling. 0.84 keeps text readable on 1080p while removing a large
    # amount of unused vertical whitespace from the old single-column layout.
    try:
        ctk.set_widget_scaling(0.84)
    except Exception:
        pass

    # Give the app a wider, lower default footprint. Maximized windows still
    # use the full desktop; this only improves the normal 1920x1080 layout.
    try:
        original_geometry = ctk.CTk.geometry

        def geometry(self: Any, geometry_string: str | None = None):
            if geometry_string:
                match = re.fullmatch(r"\s*860x960(?:[+-].*)?\s*", geometry_string)
                if match:
                    geometry_string = "1280x900"
            return original_geometry(self, geometry_string)

        ctk.CTk.geometry = geometry  # type: ignore[assignment]
    except Exception:
        pass

    try:
        original_minsize = ctk.CTk.minsize

        def minsize(self: Any, width: int | None = None, height: int | None = None):
            if width == 780 and height == 820:
                width, height = 980, 700
            return original_minsize(self, width, height)

        ctk.CTk.minsize = minsize  # type: ignore[assignment]
    except Exception:
        pass

    # The protocol window was the biggest vertical block. Keep enough history
    # visible for troubleshooting while avoiding a second screen-height of log.
    try:
        original_textbox_init = ctk.CTkTextbox.__init__

        def textbox_init(self: Any, master: Any, *args: Any, **kwargs: Any) -> None:
            if _is_main_window_widget(master) and int(kwargs.get("height", 0) or 0) >= 170:
                kwargs["height"] = 112
            original_textbox_init(self, master, *args, **kwargs)

        ctk.CTkTextbox.__init__ = textbox_init  # type: ignore[assignment]
    except Exception:
        pass

    # Slightly reduce only the large action buttons in the main window. Normal
    # buttons and the profile-manager dialog keep their familiar dimensions.
    try:
        original_button_init = ctk.CTkButton.__init__

        def button_init(self: Any, master: Any, *args: Any, **kwargs: Any) -> None:
            if _is_main_window_widget(master):
                height = int(kwargs.get("height", 0) or 0)
                if height >= 50:
                    kwargs["height"] = 42
                elif height >= 42:
                    kwargs["height"] = 36
            original_button_init(self, master, *args, **kwargs)

        ctk.CTkButton.__init__ = button_init  # type: ignore[assignment]
    except Exception:
        pass

    try:
        import diagnostics

        diagnostics._emit(
            "UI TUNING installed widget_scaling=0.84 default=1280x900 log_height=112 target=1920x1080"
        )
    except Exception:
        pass
