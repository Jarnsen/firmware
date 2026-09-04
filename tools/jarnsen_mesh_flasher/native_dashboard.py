from __future__ import annotations

from typing import Any

import customtkinter as ctk

import native_dashboard_base as _base


_original_build_dashboard = _base._build_dashboard


def _integrate_progress_percent(app: Any) -> None:
    """Move the percent label into the progress bar and let the bar use the full row width."""
    progress = getattr(app, "progress", None)
    if progress is None:
        return

    progress_row = getattr(progress, "master", None)
    if progress_row is None:
        return

    try:
        progress.configure(height=18, corner_radius=9)
        progress.pack_configure(side="left", fill="x", expand=True)
    except Exception:
        pass

    percent_label = None
    try:
        for child in progress_row.winfo_children():
            if child is progress or not isinstance(child, ctk.CTkLabel):
                continue
            try:
                text = str(child.cget("text") or "").strip()
            except Exception:
                text = ""
            try:
                textvariable = child.cget("textvariable")
            except Exception:
                textvariable = None
            if text.endswith("%") or textvariable:
                percent_label = child
                break
    except Exception:
        return

    if percent_label is None:
        return

    try:
        percent_label.pack_forget()
        percent_label.configure(
            width=52,
            height=18,
            anchor="center",
            text_color="white",
            fg_color="transparent",
            font=ctk.CTkFont(size=9, weight="bold"),
        )
        percent_label.place(relx=0.5, rely=0.5, anchor="center")
        percent_label.lift()
    except Exception:
        pass


def _build_dashboard(app: Any, services: Any) -> None:
    _original_build_dashboard(app, services)
    _integrate_progress_percent(app)


# Keep the original install/bootstrap behavior, but route its delayed dashboard build
# through the layout-adjusted implementation above.
_base._build_dashboard = _build_dashboard
install = _base.install


def __getattr__(name: str) -> Any:
    return getattr(_base, name)
