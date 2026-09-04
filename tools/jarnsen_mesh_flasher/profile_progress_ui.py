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


def _apply_reference_geometry(app: Any) -> None:
    """Apply the approved screenshot geometry before the first mainloop iteration.

    The approved design is deliberately asymmetric below row 2: SERVICE is shorter
    than FIRMWARE while AUTOMATISCHER ABLAUF is taller than Hinweise.  A shared grid
    row can never reproduce that screenshot; it creates the large blank SERVICE area
    seen in earlier builds.  The eight dashboard cards therefore use proportional
    placement inside the already-built body.  This is still a single startup pass:
    nothing is delayed, destroyed or rebuilt after the window becomes visible.
    """
    import customtkinter as ctk

    body = app.body
    cards = list(body.winfo_children())
    if len(cards) != 8:
        raise RuntimeError(f"Reference geometry requires 8 dashboard cards, got {len(cards)}")

    device, profile, identity, service, firmware, automatic, hints, protocol = cards

    # Ratios measured from the approved 1325x750 reference and intentionally scaled
    # with the body, so 1920x1080 at Windows 125% keeps the same proportions.
    placements = (
        (device,    0.000, 0.000, 1.000, 0.181),
        (profile,   0.000, 0.190, 0.496, 0.176),
        (identity,  0.504, 0.190, 0.496, 0.176),
        (service,   0.000, 0.375, 0.496, 0.112),
        (firmware,  0.504, 0.375, 0.496, 0.166),
        (automatic, 0.000, 0.496, 0.496, 0.239),
        (hints,     0.504, 0.553, 0.496, 0.182),
        (protocol,  0.000, 0.744, 1.000, 0.240),
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
        widget.place(
            relx=relx,
            rely=rely,
            relwidth=relwidth,
            relheight=relheight,
        )

    # The original protocol expand closure was written for the former shared grid.
    # Replace only that command so protocol expansion remains functional with the
    # final proportional geometry.
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
                widget.place(
                    relx=relx,
                    rely=rely,
                    relwidth=relwidth,
                    relheight=relheight,
                )

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
    app._jarnsen_design_revision = "reference-v3-asymmetric-place-pil-icons"
    app._jarnsen_reference_geometry = "approved-1325x750-proportional"
    _emit(
        "REFERENCE GEOMETRY applied revision=v3 manager=place "
        "asymmetric-service-firmware=1 asynchronous-reflow=0"
    )


def install(services: Any) -> None:
    """Install the final reference dashboard as FlasherApp's only UI construction path.

    Runtime configuration is loaded before ``FlasherApp`` is instantiated.  We hook
    ``CTk.__init__`` only long enough to replace the instance's ``_build_ui`` method.
    Therefore the legacy scrollable dashboard is never constructed and there is no
    destroy/rebuild or delayed overlay phase at startup.
    """
    import customtkinter as ctk

    from profile_specials_fix import install as install_profile_specials_fix

    install_profile_specials_fix(services)

    original_root_init = ctk.CTk.__init__

    def root_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_root_init(self, *args, **kwargs)

        def direct_build_ui(app_self: Any) -> None:
            if getattr(app_self, "_jarnsen_native_dashboard_ready", False):
                return

            from reference_dashboard import _build_dashboard

            _emit("REFERENCE DASHBOARD build start trigger=FlasherApp._build_ui direct=1 legacy-build=0")
            _build_dashboard(app_self, services)
            _apply_reference_geometry(app_self)

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
            _emit("REFERENCE DASHBOARD build complete trigger=FlasherApp._build_ui first-ui=reference-v3")

        self._build_ui = types.MethodType(direct_build_ui, self)
        self._jarnsen_native_build_override = True

    ctk.CTk.__init__ = root_init
    _emit("PROFILE PROGRESS layer installed reference-dashboard-trigger=_build_ui legacy-build=0")
