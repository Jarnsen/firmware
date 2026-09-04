from __future__ import annotations

from typing import Any

import customtkinter as ctk

import native_dashboard_base as _base


_original_build_dashboard = _base._build_dashboard


def _replace_header_mark(app: Any) -> None:
    """Replace the temporary blue J badge with the JARNSEN MESH mark and wordmark."""
    header = None
    badge = None

    try:
        for child in app.winfo_children():
            if not isinstance(child, ctk.CTkFrame):
                continue
            for item in child.winfo_children():
                if not isinstance(item, ctk.CTkLabel):
                    continue
                try:
                    if str(item.cget("text") or "").strip() == "J":
                        header = child
                        badge = item
                        break
                except Exception:
                    continue
            if badge is not None:
                break
    except Exception:
        return

    if header is None or badge is None:
        return

    try:
        from generate_windows_icon import _build_source

        source = _build_source()
        app._jarnsen_header_logo_image = ctk.CTkImage(
            light_image=source,
            dark_image=source,
            size=(38, 38),
        )
    except Exception:
        return

    try:
        grid = badge.grid_info()
        badge.destroy()

        brand = ctk.CTkFrame(header, fg_color="transparent", width=76, height=50)
        brand.grid(
            row=int(grid.get("row", 0)),
            column=int(grid.get("column", 0)),
            rowspan=int(grid.get("rowspan", 2)),
            sticky="w",
            padx=(0, 12),
        )
        brand.grid_propagate(False)

        ctk.CTkLabel(
            brand,
            text="",
            image=app._jarnsen_header_logo_image,
            width=38,
            height=38,
        ).pack(anchor="center", pady=(0, 0))
        ctk.CTkLabel(
            brand,
            text="JARNSEN MESH",
            font=ctk.CTkFont(size=7, weight="bold"),
            text_color=_base.TEXT,
        ).pack(anchor="center", pady=(-2, 0))

        app._jarnsen_header_brand = brand
    except Exception:
        pass


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
    _replace_header_mark(app)
    _integrate_progress_percent(app)


# Keep the original install/bootstrap behavior, but route its delayed dashboard build
# through the layout-adjusted implementation above.
_base._build_dashboard = _build_dashboard
install = _base.install


def __getattr__(name: str) -> Any:
    return getattr(_base, name)
