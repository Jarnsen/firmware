from __future__ import annotations

from typing import Any

import customtkinter as ctk

import radio_profiles


BG_INNER = "#091522"
BORDER = "#2A4057"
INPUT = "#081522"
CONTROL = "#15273A"
CONTROL_HOVER = "#1D354D"
TEXT = "#EAF0F7"
MUTED = "#93A6BA"
GREEN = "#86EFAC"
WARN = "#FBBF24"
FONT = "Segoe UI"


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _walk(widget: Any):
    yield widget
    try:
        children = widget.winfo_children()
    except Exception:
        children = []
    for child in children:
        yield from _walk(child)


def _find_profile_card(app: Any) -> Any | None:
    body = getattr(app, "body", None)
    if body is None:
        return None
    try:
        candidates = list(body.winfo_children())
    except Exception:
        return None
    for candidate in candidates:
        for child in _walk(candidate):
            if not isinstance(child, ctk.CTkLabel):
                continue
            try:
                text = str(child.cget("text") or "").strip()
            except Exception:
                continue
            if text == "2. GRUNDEINSTELLUNGEN":
                return candidate
    return None


def _font(size: int, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT, size=size, weight=weight)


def _attach_radio_controls(app: Any, services: Any) -> None:
    if getattr(app, "_jarnsen_radio_profile_ui_ready", False):
        return
    profile = _find_profile_card(app)
    if profile is None:
        _emit("RADIO PROFILE UI skipped profile-card-not-found=1")
        return

    app._jarnsen_radio_profile_ui_ready = True
    try:
        app.body.grid_rowconfigure(1, minsize=180)
    except Exception:
        pass

    settings = radio_profiles.load_settings(services)
    app.radio_profile_var = ctk.StringVar(
        value=radio_profiles.PROFILE_LABELS.get(settings.get("selected"), "Standard")
    )
    app.jarnsen_1_frequency_var = ctk.StringVar(value=str(settings.get("jarnsen_1_mhz") or ""))
    app.jarnsen_2_frequency_var = ctk.StringVar(value=str(settings.get("jarnsen_2_mhz") or ""))
    app.radio_profile_status_var = ctk.StringVar(value=radio_profiles.summary(settings))

    radio = ctk.CTkFrame(
        profile,
        fg_color=BG_INNER,
        corner_radius=6,
        border_width=1,
        border_color=BORDER,
        height=34,
    )
    radio.pack(fill="x", padx=12, pady=(0, 6))
    radio.grid_columnconfigure(6, weight=1)

    ctk.CTkLabel(
        radio,
        text="Funkprofil",
        font=_font(8, "bold"),
        text_color=MUTED,
    ).grid(row=0, column=0, sticky="w", padx=(8, 5), pady=4)

    profile_menu = ctk.CTkOptionMenu(
        radio,
        variable=app.radio_profile_var,
        values=["Standard", "Jarnsen 1", "Jarnsen 2"],
        width=116,
        height=25,
        corner_radius=5,
        fg_color=CONTROL,
        button_color=CONTROL_HOVER,
        button_hover_color="#29445E",
        font=_font(9),
        dropdown_font=_font(9),
    )
    profile_menu.grid(row=0, column=1, sticky="w", padx=(0, 9), pady=4)

    ctk.CTkLabel(radio, text="J1 MHz", font=_font(8), text_color=MUTED).grid(
        row=0, column=2, sticky="e", padx=(0, 4), pady=4
    )
    j1_entry = ctk.CTkEntry(
        radio,
        textvariable=app.jarnsen_1_frequency_var,
        width=88,
        height=25,
        corner_radius=5,
        fg_color=INPUT,
        border_color="#344A5F",
        font=_font(9),
        placeholder_text="z. B. 915.000",
    )
    j1_entry.grid(row=0, column=3, sticky="w", padx=(0, 9), pady=4)

    ctk.CTkLabel(radio, text="J2 MHz", font=_font(8), text_color=MUTED).grid(
        row=0, column=4, sticky="e", padx=(0, 4), pady=4
    )
    j2_entry = ctk.CTkEntry(
        radio,
        textvariable=app.jarnsen_2_frequency_var,
        width=88,
        height=25,
        corner_radius=5,
        fg_color=INPUT,
        border_color="#344A5F",
        font=_font(9),
        placeholder_text="z. B. 915.500",
    )
    j2_entry.grid(row=0, column=5, sticky="w", padx=(0, 9), pady=4)

    status_label = ctk.CTkLabel(
        radio,
        textvariable=app.radio_profile_status_var,
        anchor="w",
        font=_font(8, "bold"),
        text_color=GREEN,
    )
    status_label.grid(row=0, column=6, sticky="ew", padx=(0, 8), pady=4)

    def persist(*_args: Any) -> None:
        selected = radio_profiles.PROFILE_KEYS_BY_LABEL.get(
            str(app.radio_profile_var.get()),
            radio_profiles.PROFILE_STANDARD,
        )
        saved = radio_profiles.save_settings(
            {
                "selected": selected,
                "jarnsen_1_mhz": app.jarnsen_1_frequency_var.get(),
                "jarnsen_2_mhz": app.jarnsen_2_frequency_var.get(),
            },
            services,
        )
        # Always reflect normalized values back into the fields.
        app.jarnsen_1_frequency_var.set(str(saved.get("jarnsen_1_mhz") or ""))
        app.jarnsen_2_frequency_var.set(str(saved.get("jarnsen_2_mhz") or ""))
        try:
            checked = radio_profiles.validate_settings(saved)
            app.radio_profile_status_var.set(radio_profiles.summary(checked))
            status_label.configure(text_color=GREEN)
        except Exception as exc:
            # Invalid values may be stored while the user is still entering them,
            # but destructive flashing is blocked by the service preflight.
            app.radio_profile_status_var.set(str(exc))
            status_label.configure(text_color=WARN)

    profile_menu.configure(command=lambda _value: persist())
    j1_entry.bind("<FocusOut>", persist, add="+")
    j2_entry.bind("<FocusOut>", persist, add="+")
    j1_entry.bind("<Return>", persist, add="+")
    j2_entry.bind("<Return>", persist, add="+")

    # Validate the loaded selection without rewriting the file on every startup.
    try:
        checked = radio_profiles.validate_settings(settings)
        app.radio_profile_status_var.set(radio_profiles.summary(checked))
        status_label.configure(text_color=GREEN)
    except Exception as exc:
        app.radio_profile_status_var.set(str(exc))
        status_label.configure(text_color=WARN)

    _emit(
        "RADIO PROFILE UI ready controls=3 persistent=1 "
        f"selected={settings.get('selected')} j1={settings.get('jarnsen_1_mhz')!r} j2={settings.get('jarnsen_2_mhz')!r}"
    )


def install(services: Any) -> None:
    if getattr(services, "_jarnsen_radio_profiles_ui_installed", False):
        return
    services._jarnsen_radio_profiles_ui_installed = True

    import reference_dashboard

    original = reference_dashboard._build_dashboard
    if getattr(original, "_jarnsen_radio_profile_wrapper", False):
        return

    def build_dashboard(app: Any, runtime_services: Any) -> None:
        original(app, runtime_services)
        _attach_radio_controls(app, runtime_services)

    build_dashboard._jarnsen_radio_profile_wrapper = True  # type: ignore[attr-defined]
    reference_dashboard._build_dashboard = build_dashboard
    _emit("RADIO PROFILE UI installed active-dashboard-wrapper=1")
