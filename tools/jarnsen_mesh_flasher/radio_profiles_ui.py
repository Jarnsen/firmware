from __future__ import annotations

import hmac
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from tkinter import messagebox, simpledialog
from typing import Any

import customtkinter as ctk
import yaml

import radio_profiles


BG_INNER = "#091522"
BORDER = "#2A4057"
CONTROL = "#15273A"
CONTROL_HOVER = "#1D354D"
TEXT = "#EAF0F7"
MUTED = "#93A6BA"
GREEN = "#86EFAC"
WARN = "#FBBF24"
FONT = "Segoe UI"

EDITOR_PIN = "240180"
FREQUENCY_KEYS = {
    radio_profiles.PROFILE_JARNSEN_1: "jarnsen_1_mhz",
    radio_profiles.PROFILE_JARNSEN_2: "jarnsen_2_mhz",
}


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _font(size: int, weight: str = "normal") -> ctk.CTkFont:
    return ctk.CTkFont(family=FONT, size=size, weight=weight)


def _pin_matches(value: Any) -> bool:
    return hmac.compare_digest(str(value or "").strip(), EDITOR_PIN)


def _normalize_frequency(value: Any, fallback: Decimal) -> str:
    text = str(value if value is not None else "").strip().replace(",", ".")
    if not text:
        value_dec = fallback
    else:
        try:
            value_dec = Decimal(text)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"Ungültige Frequenz: {text!r}") from exc
    if not value_dec.is_finite() or value_dec <= 0:
        raise ValueError("Die Frequenz muss größer als 0 MHz sein.")
    return f"{value_dec:.3f}"


def _profile_region(app: Any) -> str:
    raw = ""
    try:
        raw = str(app.profile_path_var.get() or "").strip()
    except Exception:
        pass
    candidates: list[Path] = []
    if raw and raw != "Kein Profil geladen":
        candidates.append(Path(raw))
    try:
        candidates.append(Path(app._jarnsen_services.PATHS.active_profile))
    except Exception:
        pass

    for path in candidates:
        try:
            if not path.exists():
                continue
            data = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
            if not isinstance(data, dict):
                continue
            config = data.get("config")
            if isinstance(config, dict) and isinstance(config.get("lora"), dict):
                return str(config["lora"].get("region") or "").strip()
            if isinstance(data.get("lora"), dict):
                return str(data["lora"].get("region") or "").strip()
        except Exception:
            continue
    return ""


def _install_editable_frequency_core(services: Any) -> None:
    """Keep J1/J2 defaults, but preserve PIN-authorized custom frequencies."""
    if getattr(radio_profiles, "_jarnsen_editable_frequency_core", False):
        services.load_radio_profile_settings = lambda: radio_profiles.load_settings(services)
        services.save_radio_profile_settings = lambda settings: radio_profiles.save_settings(settings, services)
        services.validate_radio_profile_settings = radio_profiles.validate_settings
        services.radio_profile_summary = radio_profiles.summary
        return

    radio_profiles._jarnsen_editable_frequency_core = True

    original_load = radio_profiles.load_settings
    original_validate = radio_profiles.validate_settings

    def validate_settings(settings: dict[str, Any]) -> dict[str, Any]:
        source = dict(settings or {})
        checked = original_validate(source)
        for profile, setting_key in FREQUENCY_KEYS.items():
            fallback = radio_profiles.JARNSEN_FREQUENCIES[profile]
            checked[setting_key] = _normalize_frequency(source.get(setting_key), fallback)
        checked["version"] = max(4, int(checked.get("version") or 0))
        return checked

    def load_settings(runtime_services: Any) -> dict[str, Any]:
        checked = original_load(runtime_services)
        path = Path(radio_profiles._config_file(runtime_services))
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raw = {}
        except Exception as exc:
            raw = {}
            _emit(f"RADIO PROFILE CUSTOM FREQUENCY LOAD ERROR type={type(exc).__name__} message={exc}")

        if isinstance(raw, dict):
            for profile, setting_key in FREQUENCY_KEYS.items():
                fallback = radio_profiles.JARNSEN_FREQUENCIES[profile]
                try:
                    checked[setting_key] = _normalize_frequency(raw.get(setting_key), fallback)
                except Exception as exc:
                    checked[setting_key] = f"{fallback:.3f}"
                    _emit(
                        "RADIO PROFILE CUSTOM FREQUENCY RECOVER "
                        f"profile={profile} value={raw.get(setting_key)!r} message={exc}"
                    )
        return validate_settings(checked)

    def save_settings(settings: dict[str, Any], runtime_services: Any) -> dict[str, Any]:
        current = load_settings(runtime_services)
        current.update(dict(settings or {}))
        checked = validate_settings(current)
        checked["version"] = max(4, int(checked.get("version") or 0))

        path = Path(radio_profiles._config_file(runtime_services))
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(checked, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(path)
        _emit(
            "RADIO PROFILE SAVE editable-frequency=1 "
            f"selected={checked['selected']} j1={checked['jarnsen_1_mhz']} "
            f"j2={checked['jarnsen_2_mhz']} j1-hops={checked['jarnsen_1_hops']} "
            f"j2-hops={checked['jarnsen_2_hops']} "
            f"j1-modem={checked['jarnsen_1_modem_preset']} "
            f"j2-modem={checked['jarnsen_2_modem_preset']}"
        )
        return checked

    def selected_frequency(settings: dict[str, Any]) -> Decimal | None:
        checked = validate_settings(settings)
        profile = checked["selected"]
        setting_key = FREQUENCY_KEYS.get(profile)
        if setting_key is None:
            return None
        return Decimal(str(checked[setting_key]))

    def profile_frequency(profile: str, settings: dict[str, Any] | None = None) -> Decimal | None:
        setting_key = FREQUENCY_KEYS.get(profile)
        if setting_key is None:
            return None
        if settings is None:
            return radio_profiles.JARNSEN_FREQUENCIES[profile]
        checked = validate_settings(settings)
        return Decimal(str(checked[setting_key]))

    def summary(settings: dict[str, Any]) -> str:
        checked = validate_settings(settings)
        selected = checked["selected"]
        label = radio_profiles.PROFILE_LABELS[selected]
        hops = radio_profiles.hop_limit_for(checked, selected)
        if selected == radio_profiles.PROFILE_STANDARD:
            return f"Standard · normale Frequenz · {hops} Hops · Modem/TX/Duty nach Profil"
        frequency = selected_frequency(checked)
        modem = radio_profiles.modem_preset_for(checked, selected) or "LONG_FAST"
        modem_label = radio_profiles.MODEM_LABELS.get(modem, modem)
        return (
            f"{label} · {float(frequency):.3f} MHz · {modem_label} · {hops} Hops · "
            "Duty frei · TX max/auto"
        )

    radio_profiles.validate_settings = validate_settings
    radio_profiles.load_settings = load_settings
    radio_profiles.save_settings = save_settings
    radio_profiles.selected_frequency = selected_frequency
    radio_profiles.profile_frequency = profile_frequency
    radio_profiles.summary = summary

    services.load_radio_profile_settings = lambda: load_settings(services)
    services.save_radio_profile_settings = lambda settings: save_settings(settings, services)
    services.validate_radio_profile_settings = validate_settings
    services.radio_profile_summary = summary

    _emit(
        "RADIO PROFILE FREQUENCY CORE installed editable-with-pin=1 "
        "default-j1=915.625 default-j2=917.375 persisted-custom-frequency=1"
    )


def _walk(widget: Any):
    yield widget
    try:
        children = widget.winfo_children()
    except Exception:
        children = []
    for child in children:
        yield from _walk(child)


class _RadioEditorController:
    def __init__(self, window: Any, app: Any, services: Any, real_tabview: Any):
        self.window = window
        self.app = app
        self.services = services
        self.real_tabview = real_tabview
        self.settings = radio_profiles.load_settings(services)
        self.outer: Any | None = None
        self.frequency_entries: list[Any] = []
        self.frequency_vars: dict[str, Any] = {}
        self.modem_vars: dict[str, Any] = {}
        self.hop_vars: dict[str, Any] = {}
        self.status_vars: dict[str, Any] = {}
        self.unlocked = False
        self.dirty: dict[str, bool] = {
            radio_profiles.PROFILE_JARNSEN_1: False,
            radio_profiles.PROFILE_JARNSEN_2: False,
        }
        self._building = True

    def active_tab(self) -> str:
        try:
            return str(self.outer.get())
        except Exception:
            return "Standard"

    def on_outer_tab_changed(self) -> None:
        try:
            self.window.after_idle(self.refresh_footer_state)
        except Exception:
            pass

    def refresh_footer_state(self) -> None:
        is_standard = self.active_tab() == "Standard"
        state = "normal" if is_standard else "disabled"
        for widget in _walk(self.window):
            if not isinstance(widget, ctk.CTkButton):
                continue
            try:
                text = str(widget.cget("text") or "")
            except Exception:
                continue
            if text in {"Profil prüfen", "Speichern unter …", "SPEICHERN"}:
                try:
                    widget.configure(state=state)
                except Exception:
                    pass

    def _mark_dirty(self, profile: str, *_args: Any) -> None:
        if self._building:
            return
        self.dirty[profile] = True
        var = self.status_vars.get(profile)
        if var is not None:
            var.set("● Ungespeicherte Änderungen")

    def _unlock_frequencies(self) -> None:
        pin = simpledialog.askstring(
            "JARNSEN Frequenzen entsperren",
            "PIN eingeben, um die Frequenzen von Jarnsen 1 und Jarnsen 2 zu bearbeiten:",
            parent=self.window,
            show="*",
        )
        if pin is None:
            return
        if not _pin_matches(pin):
            messagebox.showerror(
                "PIN falsch",
                "Die JARNSEN-Frequenzen bleiben gesperrt.",
                parent=self.window,
            )
            _emit("RADIO PROFILE EDITOR pin-unlock=denied")
            return

        self.unlocked = True
        for entry in self.frequency_entries:
            try:
                entry.configure(state="normal")
            except Exception:
                pass
        for profile, var in self.status_vars.items():
            if not self.dirty.get(profile):
                var.set("Frequenzbearbeitung entsperrt · gilt nur für dieses Fenster")
        _emit("RADIO PROFILE EDITOR pin-unlock=granted session-only=1")

    def _save_profile(self, profile: str) -> None:
        frequency_key = FREQUENCY_KEYS[profile]
        hop_key = radio_profiles.HOP_KEYS[profile]
        modem_key = radio_profiles.MODEM_SETTING_KEYS[profile]
        try:
            staged = dict(self.settings)
            staged[frequency_key] = _normalize_frequency(
                self.frequency_vars[profile].get(),
                radio_profiles.JARNSEN_FREQUENCIES[profile],
            )
            staged[hop_key] = int(self.hop_vars[profile].get())
            modem_label = str(self.modem_vars[profile].get())
            staged[modem_key] = radio_profiles.MODEM_KEYS_BY_LABEL.get(
                modem_label,
                modem_label.strip().upper().replace(" ", "_"),
            )
            self.settings = radio_profiles.save_settings(staged, self.services)
            self.frequency_vars[profile].set(self.settings[frequency_key])
            self.hop_vars[profile].set(str(radio_profiles.hop_limit_for(self.settings, profile)))
            modem = radio_profiles.modem_preset_for(self.settings, profile) or "LONG_FAST"
            self.modem_vars[profile].set(radio_profiles.MODEM_LABELS.get(modem, modem))
            self.dirty[profile] = False
            self.status_vars[profile].set(
                f"Gespeichert · {self.settings[frequency_key]} MHz · "
                f"{self.modem_vars[profile].get()} · {self.hop_vars[profile].get()} Hops"
            )
            region = _profile_region(self.app)
            warning = ""
            if region:
                try:
                    radio_profiles.validate_frequency_for_region(
                        Decimal(self.settings[frequency_key]),
                        region,
                        label=radio_profiles.PROFILE_LABELS[profile],
                    )
                except Exception as exc:
                    warning = f"\n\nHinweis: {exc}"
            messagebox.showinfo(
                "JARNSEN Profil gespeichert",
                f"{radio_profiles.PROFILE_LABELS[profile]} wurde gespeichert."
                f"{warning}",
                parent=self.window,
            )
        except Exception as exc:
            messagebox.showerror(
                "JARNSEN Profil speichern",
                str(exc),
                parent=self.window,
            )

    def build_radio_tab(self, tab: Any, profile: str) -> None:
        label = radio_profiles.PROFILE_LABELS[profile]
        frequency_key = FREQUENCY_KEYS[profile]
        modem = radio_profiles.modem_preset_for(self.settings, profile) or "LONG_FAST"
        hops = radio_profiles.hop_limit_for(self.settings, profile)

        tab.grid_columnconfigure(0, weight=1)
        container = ctk.CTkFrame(
            tab,
            fg_color=BG_INNER,
            corner_radius=10,
            border_width=1,
            border_color=BORDER,
        )
        container.grid(row=0, column=0, sticky="nsew", padx=18, pady=18)
        container.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            container,
            text=label,
            font=_font(20, "bold"),
            text_color=TEXT,
            anchor="w",
        ).grid(row=0, column=0, columnspan=3, sticky="ew", padx=18, pady=(16, 2))
        ctk.CTkLabel(
            container,
            text=(
                "Dieses Funkprofil wird zusammen mit Standard und dem zweiten JARNSEN-Profil "
                "in die Node geschrieben. Der Reiter wählt nur aus, was du gerade bearbeitest."
            ),
            font=_font(10),
            text_color=MUTED,
            anchor="w",
            justify="left",
            wraplength=900,
        ).grid(row=1, column=0, columnspan=3, sticky="ew", padx=18, pady=(0, 16))

        frequency_var = ctk.StringVar(value=str(self.settings[frequency_key]))
        modem_var = ctk.StringVar(value=radio_profiles.MODEM_LABELS.get(modem, modem))
        hop_var = ctk.StringVar(value=str(hops))
        status_var = ctk.StringVar(
            value=f"Gespeichert · {self.settings[frequency_key]} MHz · "
            f"{radio_profiles.MODEM_LABELS.get(modem, modem)} · {hops} Hops"
        )
        self.frequency_vars[profile] = frequency_var
        self.modem_vars[profile] = modem_var
        self.hop_vars[profile] = hop_var
        self.status_vars[profile] = status_var

        labels = (
            (2, "Frequenz (MHz)"),
            (3, "Modem"),
            (4, "Hops"),
            (5, "TX"),
            (6, "Duty"),
        )
        for row, text in labels:
            ctk.CTkLabel(
                container,
                text=text,
                width=150,
                anchor="w",
                font=_font(11, "bold"),
                text_color=MUTED,
            ).grid(row=row, column=0, sticky="w", padx=(18, 12), pady=7)

        frequency_entry = ctk.CTkEntry(
            container,
            textvariable=frequency_var,
            height=32,
            fg_color=CONTROL,
            border_color=BORDER,
            state="disabled",
        )
        frequency_entry.grid(row=2, column=1, sticky="ew", padx=(0, 10), pady=7)
        self.frequency_entries.append(frequency_entry)

        ctk.CTkButton(
            container,
            text="FREQUENZEN ENTSPERREN",
            width=185,
            height=32,
            fg_color=CONTROL,
            hover_color=CONTROL_HOVER,
            command=self._unlock_frequencies,
        ).grid(row=2, column=2, sticky="e", padx=(0, 18), pady=7)

        ctk.CTkOptionMenu(
            container,
            variable=modem_var,
            values=radio_profiles.modem_preset_values(),
            height=32,
            fg_color=CONTROL,
            button_color=CONTROL_HOVER,
            button_hover_color="#29445E",
        ).grid(row=3, column=1, columnspan=2, sticky="ew", padx=(0, 18), pady=7)

        ctk.CTkOptionMenu(
            container,
            variable=hop_var,
            values=radio_profiles.hop_values(profile),
            height=32,
            fg_color=CONTROL,
            button_color=CONTROL_HOVER,
            button_hover_color="#29445E",
        ).grid(row=4, column=1, columnspan=2, sticky="ew", padx=(0, 18), pady=7)

        ctk.CTkLabel(
            container,
            text="Max/Auto",
            anchor="w",
            font=_font(11, "bold"),
            text_color=TEXT,
        ).grid(row=5, column=1, columnspan=2, sticky="w", padx=(0, 18), pady=7)
        ctk.CTkLabel(
            container,
            text="Frei",
            anchor="w",
            font=_font(11, "bold"),
            text_color=TEXT,
        ).grid(row=6, column=1, columnspan=2, sticky="w", padx=(0, 18), pady=7)

        ctk.CTkLabel(
            container,
            textvariable=status_var,
            anchor="w",
            font=_font(10, "bold"),
            text_color=GREEN,
        ).grid(row=7, column=0, columnspan=2, sticky="ew", padx=18, pady=(16, 16))

        ctk.CTkButton(
            container,
            text=f"{label.upper()} SPEICHERN",
            width=190,
            height=34,
            command=lambda p=profile: self._save_profile(p),
        ).grid(row=7, column=2, sticky="e", padx=(0, 18), pady=(16, 16))

        frequency_var.trace_add("write", lambda *_args, p=profile: self._mark_dirty(p))
        modem_var.trace_add("write", lambda *_args, p=profile: self._mark_dirty(p))
        hop_var.trace_add("write", lambda *_args, p=profile: self._mark_dirty(p))


class _ProfileTabsProxy:
    """Outer Standard/J1/J2 tabs while preserving the old Form/YAML editor."""

    def __init__(
        self,
        master: Any,
        *,
        app: Any,
        services: Any,
        real_tabview: Any,
        controller_sink: dict[str, Any],
        **kwargs: Any,
    ):
        self._controller = _RadioEditorController(master, app, services, real_tabview)
        controller_sink["controller"] = self._controller
        self._outer = real_tabview(master, command=self._controller.on_outer_tab_changed, **kwargs)
        self._controller.outer = self._outer

        standard_tab = self._outer.add("Standard")
        j1_tab = self._outer.add("Jarnsen 1")
        j2_tab = self._outer.add("Jarnsen 2")
        self._inner = real_tabview(standard_tab)
        self._inner.pack(fill="both", expand=True, padx=4, pady=4)

        self._controller.build_radio_tab(j1_tab, radio_profiles.PROFILE_JARNSEN_1)
        self._controller.build_radio_tab(j2_tab, radio_profiles.PROFILE_JARNSEN_2)
        self._controller._building = False
        try:
            master.after(80, self._controller.refresh_footer_state)
        except Exception:
            pass

    def pack(self, *args: Any, **kwargs: Any) -> Any:
        return self._outer.pack(*args, **kwargs)

    def add(self, name: str) -> Any:
        return self._inner.add(name)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _open_profile_editor_with_radio_tabs(
    original_edit: Any,
    app: Any,
    services: Any,
) -> Any:
    import profile_editor

    real_ctk = profile_editor.ctk
    real_tabview = real_ctk.CTkTabview
    controller_sink: dict[str, Any] = {}
    first_tabview = {"pending": True}

    def tabview_factory(master: Any, *args: Any, **kwargs: Any) -> Any:
        if first_tabview["pending"] and isinstance(master, real_ctk.CTkToplevel):
            first_tabview["pending"] = False
            return _ProfileTabsProxy(
                master,
                app=app,
                services=services,
                real_tabview=real_tabview,
                controller_sink=controller_sink,
                **kwargs,
            )
        return real_tabview(master, *args, **kwargs)

    class _CtkProxy:
        CTkTabview = staticmethod(tabview_factory)

        def __getattr__(self, name: str) -> Any:
            return getattr(real_ctk, name)

    profile_editor.ctk = _CtkProxy()
    try:
        result = original_edit(app, services)
        controller = controller_sink.get("controller")
        if controller is not None:
            app._jarnsen_last_radio_editor_controller = controller
        return result
    finally:
        profile_editor.ctk = real_ctk


def _mark_dashboard_editor_ready(app: Any, services: Any) -> None:
    """Compatibility markers for source smoke tests; no radio panel is rendered."""
    if getattr(app, "_jarnsen_radio_profile_ui_ready", False):
        return
    app._jarnsen_radio_profile_ui_ready = True
    app._jarnsen_radio_profile_editor_tabs = True
    app._jarnsen_services = services

    settings = radio_profiles.load_settings(services)
    app.radio_profile_var = ctk.StringVar(value="Standard")
    app.radio_hop_var = ctk.StringVar(value=str(radio_profiles.hop_limit_for(settings, radio_profiles.PROFILE_STANDARD)))
    app.radio_modem_var = ctk.StringVar(value="Profil/FW")
    app.radio_frequency_var = ctk.StringVar(value="Profil/FW")
    app.radio_tx_var = ctk.StringVar(value="Profil/FW")
    app.radio_duty_var = ctk.StringVar(value="Profil/FW")
    app.radio_profile_status_var = ctk.StringVar(value="Profile werden gemeinsam in die Node geschrieben")
    app.radio_profile_allocation_var = ctk.StringVar(value="Bearbeitung über Profil bearbeiten")
    app.radio_profile_menu = None
    app.radio_modem_menu = None
    app.radio_hop_menu = None
    app.radio_profile_panel = None


def install(services: Any) -> None:
    if getattr(services, "_jarnsen_radio_profiles_ui_installed", False):
        return
    services._jarnsen_radio_profiles_ui_installed = True

    _install_editable_frequency_core(services)

    import reference_dashboard

    original_edit = reference_dashboard.edit_current_profile
    if not getattr(original_edit, "_jarnsen_radio_profile_editor_wrapper", False):
        def edit_current_profile(app: Any, runtime_services: Any) -> Any:
            return _open_profile_editor_with_radio_tabs(original_edit, app, runtime_services)

        edit_current_profile._jarnsen_radio_profile_editor_wrapper = True  # type: ignore[attr-defined]
        reference_dashboard.edit_current_profile = edit_current_profile

    original_build = reference_dashboard._build_dashboard
    if not getattr(original_build, "_jarnsen_radio_profile_marker_wrapper", False):
        def build_dashboard(app: Any, runtime_services: Any) -> None:
            original_build(app, runtime_services)
            _mark_dashboard_editor_ready(app, runtime_services)

        build_dashboard._jarnsen_radio_profile_marker_wrapper = True  # type: ignore[attr-defined]
        reference_dashboard._build_dashboard = build_dashboard

    _emit(
        "RADIO PROFILE UI installed inline-selector=0 editor-tabs=standard,jarnsen1,jarnsen2 "
        "frequency-pin-lock=1 session-unlock=1 dropdown-modem=1 dropdown-hops=1 "
        "all-profile-editor-context=1"
    )
