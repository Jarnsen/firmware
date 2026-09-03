from __future__ import annotations

from typing import Any

import customtkinter as ctk


_INSTALLED = False
_CARD_TITLES = (
    "1 · GERÄT",
    "2 · GRUNDEINSTELLUNGEN",
    "3 · FIRMWARE",
    "4 · GERÄTENAME",
    "5 · AUTOMATISCHER ABLAUF",
    "PROTOKOLL",
)


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
    """Target 1920x1080 even when Windows DPI exposes only ~1536x864 to Tk."""
    try:
        width = int(root.winfo_screenwidth())
        height = int(root.winfo_screenheight())
    except Exception:
        return 0.76

    if height <= 780:
        return 0.68
    if height <= 840:
        return 0.70
    if height <= 900:
        return 0.74
    if height <= 1000:
        return 0.78
    if height <= 1100:
        return 0.82
    if width >= 2500:
        return 0.90
    return 0.84


def _walk(widget: Any):
    try:
        children = list(widget.winfo_children())
    except Exception:
        children = []
    for child in children:
        yield child
        yield from _walk(child)


def _label_text(widget: Any) -> str:
    try:
        if isinstance(widget, ctk.CTkLabel):
            return str(widget.cget("text") or "")
    except Exception:
        pass
    return ""


def _card_title(frame: Any) -> str:
    try:
        for child in frame.winfo_children():
            text = _label_text(child)
            if text in _CARD_TITLES:
                return text
    except Exception:
        pass
    return ""


def _hide_scrollbar(container: Any) -> None:
    """Remove the main vertical scrollbar once the dashboard fits in Full HD."""
    candidates = [container]
    parent = getattr(container, "master", None)
    if parent is not None:
        candidates.append(parent)

    for candidate in candidates:
        scrollbar = getattr(candidate, "_scrollbar", None)
        if scrollbar is not None:
            for method in ("grid_forget", "pack_forget", "place_forget"):
                try:
                    getattr(scrollbar, method)()
                except Exception:
                    pass
            try:
                scrollbar.configure(width=0)
            except Exception:
                pass

        canvas = getattr(candidate, "_parent_canvas", None)
        if canvas is not None:
            try:
                canvas.configure(yscrollcommand="", highlightthickness=0)
            except Exception:
                pass
            try:
                canvas.yview_moveto(0.0)
            except Exception:
                pass


def _discover_and_reflow(root: Any, attempt: int = 0) -> None:
    """Find the six cards by their visible titles and force a two-column dashboard.

    This deliberately does not depend on CTkScrollableFrame internals. It works
    after CustomTkinter has finished creating its private canvas/frame hierarchy.
    """
    frames_by_parent: dict[int, list[tuple[Any, str]]] = {}
    parents: dict[int, Any] = {}

    for widget in _walk(root):
        if not isinstance(widget, ctk.CTkFrame):
            continue
        title = _card_title(widget)
        if not title:
            continue
        parent = getattr(widget, "master", None)
        if parent is None:
            continue
        key = id(parent)
        parents[key] = parent
        frames_by_parent.setdefault(key, []).append((widget, title))

    target_parent = None
    cards: dict[str, Any] = {}
    for key, items in frames_by_parent.items():
        found = {title: frame for frame, title in items}
        if all(title in found for title in _CARD_TITLES):
            target_parent = parents[key]
            cards = found
            break

    if target_parent is None:
        if attempt < 12:
            try:
                root.after(120, lambda: _discover_and_reflow(root, attempt + 1))
            except Exception:
                pass
        else:
            try:
                import diagnostics
                diagnostics._emit("UI REFLOW FAILED cards-not-found after=12")
            except Exception:
                pass
        return

    positions = {
        "1 · GERÄT": (0, 0, 1, 1),
        "2 · GRUNDEINSTELLUNGEN": (1, 0, 1, 1),
        "3 · FIRMWARE": (2, 0, 1, 1),
        "4 · GERÄTENAME": (0, 1, 1, 1),
        "5 · AUTOMATISCHER ABLAUF": (1, 1, 2, 1),
        "PROTOKOLL": (3, 0, 1, 2),
    }

    try:
        for title in _CARD_TITLES:
            frame = cards[title]
            try:
                frame.pack_forget()
            except Exception:
                pass
            try:
                frame.grid_forget()
            except Exception:
                pass

        target_parent.grid_columnconfigure(0, weight=1, uniform="jarnsen-fullhd")
        target_parent.grid_columnconfigure(1, weight=1, uniform="jarnsen-fullhd")
        for row in range(4):
            target_parent.grid_rowconfigure(row, weight=0)

        for title in _CARD_TITLES:
            row, column, rowspan, columnspan = positions[title]
            cards[title].grid(
                row=row,
                column=column,
                rowspan=rowspan,
                columnspan=columnspan,
                sticky="nsew",
                padx=4,
                pady=(0, 6),
            )

        _hide_scrollbar(target_parent)

        # Also hide a scrollable ancestor's bar if the actual card parent is an
        # internal frame/canvas created by CustomTkinter.
        node = target_parent
        for _ in range(5):
            if node is None:
                break
            _hide_scrollbar(node)
            node = getattr(node, "master", None)

        try:
            root.update_idletasks()
        except Exception:
            pass

        try:
            import diagnostics
            diagnostics._emit(
                "UI REFLOW OK layout=2col scrollbar=removed cards=6 "
                f"screen={root.winfo_screenwidth()}x{root.winfo_screenheight()} "
                f"parent={target_parent.__class__.__name__} attempt={attempt}"
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
    """Install a DPI-aware, scrollbar-free Full-HD dashboard."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    try:
        original_root_init = ctk.CTk.__init__

        def root_init(self: Any, *args: Any, **kwargs: Any) -> None:
            original_root_init(self, *args, **kwargs)
            scale = _responsive_scale(self)
            try:
                ctk.set_widget_scaling(scale)
            except Exception:
                pass

            def finalize() -> None:
                try:
                    self.state("zoomed")
                except Exception:
                    try:
                        self.attributes("-zoomed", True)
                    except Exception:
                        pass
                _discover_and_reflow(self)

            try:
                self.after(250, finalize)
            except Exception:
                pass

            try:
                import diagnostics
                diagnostics._emit(
                    "UI FULLHD ROOT "
                    f"screen={self.winfo_screenwidth()}x{self.winfo_screenheight()} "
                    f"widget_scaling={scale:.2f} maximize=1 scrollbar_target=0"
                )
            except Exception:
                pass

        ctk.CTk.__init__ = root_init  # type: ignore[assignment]
    except Exception:
        pass

    try:
        original_geometry = ctk.CTk.geometry

        def geometry(self: Any, geometry_string: str | None = None):
            if geometry_string and geometry_string.strip().startswith("860x960"):
                try:
                    sw = int(self.winfo_screenwidth())
                    sh = int(self.winfo_screenheight())
                    width = max(1080, min(1700, sw - 30))
                    height = max(640, min(940, sh - 50))
                    geometry_string = f"{width}x{height}"
                except Exception:
                    geometry_string = "1500x820"
            return original_geometry(self, geometry_string)

        ctk.CTk.geometry = geometry  # type: ignore[assignment]
    except Exception:
        pass

    try:
        original_minsize = ctk.CTk.minsize

        def minsize(self: Any, width: int | None = None, height: int | None = None):
            if width == 780 and height == 820:
                width, height = 960, 600
            return original_minsize(self, width, height)

        ctk.CTk.minsize = minsize  # type: ignore[assignment]
    except Exception:
        pass

    # Compact Full-HD labels without making normal dialogs tiny.
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

    try:
        original_textbox_init = ctk.CTkTextbox.__init__

        def textbox_init(self: Any, master: Any, *args: Any, **kwargs: Any) -> None:
            if _is_main_window_widget(master) and int(kwargs.get("height", 0) or 0) >= 170:
                kwargs["height"] = 66
            original_textbox_init(self, master, *args, **kwargs)

        ctk.CTkTextbox.__init__ = textbox_init  # type: ignore[assignment]
    except Exception:
        pass

    try:
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
    except Exception:
        pass

    try:
        import diagnostics
        diagnostics._emit(
            "UI TUNING installed mode=forced-fullhd target=1920x1080 dpi-aware "
            "layout=discover-postbuild-2col scrollbar=removed log_height=66"
        )
    except Exception:
        pass
