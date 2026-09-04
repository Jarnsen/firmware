from __future__ import annotations

import types
from typing import Any


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _walk(widget: Any):
    for child in widget.winfo_children():
        yield child
        yield from _walk(child)


def _replace_header_brand(app: Any) -> None:
    """Replace the temporary blue J with the JARNSEN mountain mark and wordmark."""
    import customtkinter as ctk

    header = None
    badge = None
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

    if header is None or badge is None:
        raise RuntimeError("Reference header J badge was not found for branding replacement")

    from generate_windows_icon import _build_source

    source = _build_source()
    app._jarnsen_header_logo_image = ctk.CTkImage(
        light_image=source,
        dark_image=source,
        size=(32, 32),
    )

    grid = badge.grid_info()
    badge.destroy()

    brand = ctk.CTkFrame(header, fg_color="transparent", width=78, height=42)
    brand.grid(
        row=int(grid.get("row", 0)),
        column=int(grid.get("column", 0)),
        rowspan=int(grid.get("rowspan", 1)),
        sticky="w",
        padx=(0, 12),
    )
    brand.grid_propagate(False)

    ctk.CTkLabel(
        brand,
        text="",
        image=app._jarnsen_header_logo_image,
        width=32,
        height=32,
    ).pack(anchor="center", pady=(0, 0))
    ctk.CTkLabel(
        brand,
        text="JARNSEN MESH",
        font=ctk.CTkFont(size=6, weight="bold"),
        text_color="#EAF0F7",
    ).pack(anchor="center", pady=(-2, 0))

    app._jarnsen_header_brand = brand
    app._jarnsen_header_brand_v2 = True
    _emit("HEADER BRAND applied mark=mountain wordmark=JARNSEN-MESH legacy-J=0")


def _apply_reference_geometry(app: Any) -> None:
    """Apply the approved screenshot geometry before the first mainloop iteration.

    The approved design is deliberately asymmetric below row 2: SERVICE is shorter
    than FIRMWARE while AUTOMATISCHER ABLAUF is taller than Hinweise. A shared grid
    row can never reproduce that screenshot; the eight dashboard cards therefore use
    proportional placement inside the already-built body.
    """
    import customtkinter as ctk

    body = app.body
    cards = list(body.winfo_children())
    if len(cards) != 8:
        raise RuntimeError(f"Reference geometry requires 8 dashboard cards, got {len(cards)}")

    device, profile, identity, service, firmware, automatic, hints, protocol = cards

    placements = (
        (device, 0.000, 0.000, 1.000, 0.181),
        (profile, 0.000, 0.190, 0.496, 0.176),
        (identity, 0.504, 0.190, 0.496, 0.176),
        (service, 0.000, 0.375, 0.496, 0.112),
        (firmware, 0.504, 0.375, 0.496, 0.166),
        (automatic, 0.000, 0.496, 0.496, 0.239),
        (hints, 0.504, 0.553, 0.496, 0.182),
        (protocol, 0.000, 0.744, 1.000, 0.240),
    )

    for widget, relx, rely, relwidth, relheight in placements:
        try:
            widget.grid_forget()
        except Exception:
            pass
        try:
            widget.pack_forget()
        except Exception:
            pass
        widget.place(relx=relx, rely=rely, relwidth=relwidth, relheight=relheight)

    toggle = None
    for child in _walk(protocol):
        if isinstance(child, ctk.CTkButton):
            try:
                if str(child.cget("text")) == "PROTOKOLL GROSS":
                    toggle = child
                    break
            except Exception:
                pass

    if toggle is not None:
        expanded = {"value": False}

        def restore_cards() -> None:
            for widget, relx, rely, relwidth, relheight in placements:
                widget.place(relx=relx, rely=rely, relwidth=relwidth, relheight=relheight)

        def toggle_protocol() -> None:
            expanded["value"] = not expanded["value"]
            if expanded["value"]:
                for widget in (profile, identity, service, firmware, automatic, hints):
                    widget.place_forget()
                protocol.place(relx=0.0, rely=0.190, relwidth=1.0, relheight=0.794)
                toggle.configure(text="PROTOKOLL KOMPAKT")
            else:
                restore_cards()
                toggle.configure(text="PROTOKOLL GROSS")

        toggle.configure(command=toggle_protocol)

    app._jarnsen_reference_dashboard_v3 = True
    app._jarnsen_reference_geometry = "approved-1325x750-proportional"
    _emit(
        "REFERENCE GEOMETRY applied revision=v3 manager=place "
        "asymmetric-service-firmware=1 asynchronous-reflow=0"
    )


def _primary_physical_size(app: Any) -> tuple[int, int]:
    """Return the primary desktop size in physical pixels for diagnostics."""
    try:
        import ctypes

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        hdc = user32.GetDC(None)
        if hdc:
            try:
                width = int(gdi32.GetDeviceCaps(hdc, 118))  # DESKTOPHORZRES
                height = int(gdi32.GetDeviceCaps(hdc, 117))  # DESKTOPVERTRES
                if width > 0 and height > 0:
                    return width, height
            finally:
                user32.ReleaseDC(None, hdc)
    except Exception:
        pass

    try:
        logical_w = int(app.winfo_screenwidth())
        logical_h = int(app.winfo_screenheight())
        scaling = float(app.tk.call("tk", "scaling")) / (96.0 / 72.0)
        if scaling > 0:
            return round(logical_w * scaling), round(logical_h * scaling)
    except Exception:
        pass
    return 1920, 1080


def _primary_logical_size(app: Any) -> tuple[int, int]:
    """Return the Tk geometry size that maps to the current physical desktop.

    On the 125% reference runner Tk geometry units are DPI-scaled: requesting
    1920x1080 creates a 2400x1350 HWND. Build 138 demonstrated that directly.
    The correct borderless geometry is therefore Tk's logical screen size
    (1536x864 on that runner), which Windows renders as exactly 1920x1080 pixels.
    """
    try:
        width = int(app.winfo_screenwidth())
        height = int(app.winfo_screenheight())
        if width > 0 and height > 0:
            return width, height
    except Exception:
        pass
    return 1536, 864


def _apply_reference_window_chrome(app: Any) -> None:
    """Apply one borderless, DPI-correct reference window with custom controls."""
    import customtkinter as ctk
    from PIL import Image, ImageDraw

    roots = list(app.winfo_children())
    if len(roots) < 3:
        raise RuntimeError(f"Reference chrome requires header/body/footer, got {len(roots)} root widgets")
    header = roots[0]

    app._jarnsen_reference_fullscreen = True
    app._jarnsen_reference_dashboard_v4 = True
    app._jarnsen_design_revision = "reference-v4-fullscreen-asymmetric-place-pil-icons"
    app._jarnsen_reference_window = "1920x1080-125-fullscreen-custom-chrome"

    def set_fullscreen(enabled: bool, *, reveal: bool = True) -> None:
        app._jarnsen_reference_fullscreen = bool(enabled)
        try:
            app.attributes("-fullscreen", False)
        except Exception:
            pass

        if enabled:
            logical_w, logical_h = _primary_logical_size(app)
            physical_w, physical_h = _primary_physical_size(app)
            app._jarnsen_reference_logical_size = f"{logical_w}x{logical_h}"
            app._jarnsen_reference_physical_size = f"{physical_w}x{physical_h}"
            try:
                app.overrideredirect(True)
            except Exception:
                pass
            if reveal:
                try:
                    app.state("normal")
                except Exception:
                    pass
            try:
                app.geometry(f"{logical_w}x{logical_h}+0+0")
            except Exception:
                pass
            try:
                app.update_idletasks()
            except Exception:
                pass
        else:
            try:
                app.overrideredirect(False)
            except Exception:
                pass

    # Startup stays withdrawn while every final widget, geometry and custom-chrome
    # operation is applied. The root is revealed exactly once after construction.
    set_fullscreen(True, reveal=False)

    def make_icon(kind: str) -> ctk.CTkImage:
        scale = 4
        image = Image.new("RGBA", (16 * scale, 16 * scale), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        color = "#C9D4DF"
        width = 1.35 * scale
        if kind == "min":
            draw.line(
                (4 * scale, 10 * scale, 12 * scale, 10 * scale),
                fill=color,
                width=max(1, round(width)),
            )
        elif kind == "max":
            draw.rounded_rectangle(
                (4 * scale, 4 * scale, 12 * scale, 12 * scale),
                radius=1 * scale,
                outline=color,
                width=max(1, round(width)),
            )
        else:
            draw.line(
                (4 * scale, 4 * scale, 12 * scale, 12 * scale),
                fill=color,
                width=max(1, round(width)),
            )
            draw.line(
                (12 * scale, 4 * scale, 4 * scale, 12 * scale),
                fill=color,
                width=max(1, round(width)),
            )
        image = image.resize((32, 32), Image.Resampling.LANCZOS)
        return ctk.CTkImage(light_image=image, dark_image=image, size=(16, 16))

    icons = {
        "min": make_icon("min"),
        "max": make_icon("max"),
        "close": make_icon("close"),
    }
    app._jarnsen_window_control_images = icons

    controls = ctk.CTkFrame(header, fg_color="transparent")
    controls.grid(row=0, column=5, sticky="e", padx=(18, 0))

    def minimize() -> None:
        try:
            set_fullscreen(False)
            app.iconify()
        except Exception:
            pass

    def toggle_maximize() -> None:
        if bool(getattr(app, "_jarnsen_reference_fullscreen", True)):
            set_fullscreen(False)
            try:
                sw, sh = _primary_logical_size(app)
                width = max(1000, int(sw * 0.82))
                height = max(650, int(sh * 0.82))
                x = max(0, int((sw - width) / 2))
                y = max(0, int((sh - height) / 2))
                app.geometry(f"{width}x{height}+{x}+{y}")
            except Exception:
                pass
        else:
            set_fullscreen(True)

    def close_window() -> None:
        try:
            app.destroy()
        except Exception:
            pass

    def window_button(command, image, *, close: bool = False):
        return ctk.CTkButton(
            controls,
            text="",
            image=image,
            command=command,
            width=30,
            height=28,
            corner_radius=5,
            border_width=0,
            fg_color="transparent",
            hover_color="#7F1D1D" if close else "#18283A",
        )

    window_button(minimize, icons["min"]).pack(side="left", padx=(0, 2))
    window_button(toggle_maximize, icons["max"]).pack(side="left", padx=2)
    window_button(close_window, icons["close"], close=True).pack(side="left", padx=(2, 0))

    logical = getattr(app, "_jarnsen_reference_logical_size", "unknown")
    physical = getattr(app, "_jarnsen_reference_physical_size", "unknown")
    _emit(
        "REFERENCE WINDOW applied revision=v4 borderless=1 native-titlebar=0 "
        f"custom-controls=1 logical={logical} physical={physical} target=1920x1080@125 startup-hidden=1"
    )


def install(services: Any) -> None:
    """Install the final reference dashboard as FlasherApp's only UI build path."""
    import customtkinter as ctk

    from profile_specials_fix import install as install_profile_specials_fix

    install_profile_specials_fix(services)

    original_root_init = ctk.CTk.__init__

    def root_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_root_init(self, *args, **kwargs)

        # Prevent the legacy construction geometry and the final fullscreen geometry
        # from becoming visible as several successive "opens". Build everything while
        # withdrawn and reveal the finished dashboard only once.
        try:
            self.withdraw()
            self._jarnsen_startup_hidden = True
            self._jarnsen_startup_single_reveal = True
        except Exception:
            pass

        def direct_build_ui(app_self: Any) -> None:
            if getattr(app_self, "_jarnsen_native_dashboard_ready", False):
                return

            from reference_dashboard import _build_dashboard

            _emit("REFERENCE DASHBOARD build start trigger=FlasherApp._build_ui direct=1 legacy-build=0 hidden=1")
            _build_dashboard(app_self, services)
            _replace_header_brand(app_self)
            _apply_reference_geometry(app_self)
            _apply_reference_window_chrome(app_self)

            if not getattr(app_self, "_jarnsen_profile_progress_ui", False):
                app_self._jarnsen_profile_progress_ui = True

                def profile_progress(fraction: float, stage: str, detail: str = "") -> None:
                    fraction = max(0.0, min(1.0, float(fraction)))
                    overall = 0.79 + 0.07 * fraction
                    suffix = f" · {detail}" if detail else ""
                    app_self._set_progress(overall, f"{stage}{suffix}")

                services._jarnsen_profile_progress_callback = profile_progress
                _emit("PROFILE PROGRESS attached reference-dashboard=1 overall-range=0.79..0.86")

            app_self._jarnsen_native_build_override = True

            def reveal_once() -> None:
                if getattr(app_self, "_jarnsen_startup_revealed", False):
                    return
                app_self._jarnsen_startup_revealed = True
                try:
                    app_self.deiconify()
                except Exception:
                    try:
                        app_self.state("normal")
                    except Exception:
                        pass
                try:
                    app_self.lift()
                except Exception:
                    pass
                _emit("STARTUP WINDOW reveal count=1 final-dashboard=1")

            try:
                app_self.after_idle(reveal_once)
            except Exception:
                reveal_once()

            _emit("REFERENCE DASHBOARD build complete trigger=FlasherApp._build_ui first-ui=reference-v4 single-reveal=1")

        self._build_ui = types.MethodType(direct_build_ui, self)
        self._jarnsen_native_build_override = True

    ctk.CTk.__init__ = root_init
    _emit("PROFILE PROGRESS layer installed reference-dashboard-trigger=_build_ui legacy-build=0 single-reveal=1")
