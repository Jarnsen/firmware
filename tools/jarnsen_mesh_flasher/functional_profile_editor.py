from __future__ import annotations

from pathlib import Path
from tkinter import messagebox
from typing import Any

import yaml
from functional_profile_fields import (
    CATEGORY_ORDER,
    KEEP_VALUE,
    apply_profile_values,
    build_field_specs,
    shown_value,
)
from profile_catalog import board_for_profile, register_profile
from profile_editor_model import compatibility_notes, field_meta, format_change_preview, profile_changes
from profile_utils import format_summary, summary_from_profile_file


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _resolve_functional(source: Path, services: Any) -> Any | None:
    from functional_profiles import active_profile, function_id_for_path, functional_profile

    profile_id = function_id_for_path(source, services)
    if profile_id is None:
        active_path = Path(services.PATHS.active_profile)
        try:
            is_active = source.resolve() == active_path.resolve()
        except Exception:
            is_active = source == active_path
        if is_active:
            selected = active_profile(services)
            profile_id = selected.identifier if selected is not None else None
    return functional_profile(profile_id) if profile_id else None


def open_functional_profile_editor(root: Any, services: Any, source: Path, functional: Any, *, ctk: Any) -> Path | None:
    source = Path(source)
    try:
        loaded = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError("Profil muss ein Mapping sein.")
    except Exception as exc:
        messagebox.showerror("Profil bearbeiten", str(exc), parent=root)
        return None

    from functional_profiles import normalise_profile_data, profile_path

    original = normalise_profile_data(loaded, functional)
    specs = build_field_specs(original, functional)
    target = Path(profile_path(services, functional))
    saved: dict[str, Path | None] = {"path": None}
    board_key = None
    if hasattr(root, "_selected_board_key"):
        try:
            board_key = root._selected_board_key()
        except Exception:
            pass
    board_key = board_key or board_for_profile(source)

    window = ctk.CTkToplevel(root)
    window.title(f"JARNSEN MESH · Profil bearbeiten · {functional.label}")
    window.geometry("1320x840")
    window.minsize(1040, 680)
    window.transient(root)

    header = ctk.CTkFrame(window, fg_color="transparent")
    header.pack(fill="x", padx=22, pady=(18, 8))
    ctk.CTkLabel(header, text="Profil bearbeiten", font=ctk.CTkFont(size=24, weight="bold")).pack(side="left")
    dirty_var = ctk.StringVar(value="Gespeichert")
    dirty_label = ctk.CTkLabel(header, textvariable=dirty_var, font=ctk.CTkFont(size=12, weight="bold"), text_color=("gray40", "gray65"))
    dirty_label.pack(side="right", pady=(7, 0))
    ctk.CTkLabel(window, textvariable=ctk.StringVar(value=format_summary(summary_from_profile_file(source))), anchor="w", font=ctk.CTkFont(size=12), text_color=("gray40", "gray65")).pack(fill="x", padx=22, pady=(0, 6))
    ctk.CTkLabel(
        window,
        text=(
            f"{functional.label}: Nur die Funktionsrolle ist fest. Alle übrigen Einstellungen sind bearbeitbar. "
            f"„{KEEP_VALUE}“ schreibt keinen Wert: Beim Erstflash gilt der Firmware-Standard, später bleibt der aktuelle Node-Wert erhalten."
        ),
        anchor="w",
        justify="left",
        wraplength=1240,
        font=ctk.CTkFont(size=11, weight="bold"),
        text_color=("#0E6A36", "#86EFAC"),
    ).pack(fill="x", padx=22, pady=(0, 8))

    tabs = ctk.CTkTabview(window)
    tabs.pack(fill="both", expand=True, padx=22, pady=(0, 12))
    form = tabs.add("Formular")
    form.grid_columnconfigure(1, weight=1)
    form.grid_rowconfigure(0, weight=1)
    nav = ctk.CTkScrollableFrame(form, width=190, fg_color=("gray90", "gray17"))
    nav.grid(row=0, column=0, sticky="nsw", padx=(8, 8), pady=8)
    content = ctk.CTkScrollableFrame(form, fg_color="transparent")
    content.grid(row=0, column=1, sticky="nsew", padx=(0, 8), pady=8)
    content.grid_columnconfigure(0, weight=1)

    controls: dict[tuple[str, ...], Any] = {}
    frames: dict[str, Any] = {}
    state = {"dirty": False, "building": True}

    def mark_dirty(*_args: Any) -> None:
        if state["building"]:
            return
        state["dirty"] = True
        dirty_var.set("● Ungespeicherte Änderungen")
        dirty_label.configure(text_color=("#9A6700", "#F2C94C"))

    grouped: dict[str, list[Any]] = {}
    for spec in specs:
        grouped.setdefault(spec.category, []).append(spec)

    def show_category(name: str) -> None:
        for key, frame in frames.items():
            frame.grid() if key == name else frame.grid_remove()

    from profile_editor_choices import field_allows_custom_value, field_values_for_label

    for category in CATEGORY_ORDER:
        rows = grouped.get(category, [])
        if not rows:
            continue
        ctk.CTkButton(nav, text=category, anchor="w", fg_color=("gray78", "gray25"), hover_color=("gray70", "gray31"), command=lambda name=category: show_category(name)).pack(fill="x", padx=5, pady=4)
        frame = ctk.CTkFrame(content, fg_color="transparent")
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(1, weight=1)
        frames[category] = frame
        ctk.CTkLabel(frame, text=category, font=ctk.CTkFont(size=18, weight="bold")).grid(row=0, column=0, sticky="w", padx=8, pady=(5, 12))
        ctk.CTkLabel(frame, text="Dropdowns werden automatisch aus der installierten Meshtastic-Version erzeugt.", font=ctk.CTkFont(size=10), text_color=("gray42", "gray62")).grid(row=0, column=1, columnspan=2, sticky="e", padx=8, pady=(5, 12))

        for row, spec in enumerate(rows, start=1):
            meta = field_meta(spec.path)
            desc = ctk.CTkFrame(frame, fg_color="transparent", width=330)
            desc.grid(row=row, column=0, sticky="new", padx=(8, 14), pady=6)
            ctk.CTkLabel(desc, text=meta.title, anchor="w", font=ctk.CTkFont(size=12, weight="bold")).pack(fill="x")
            ctk.CTkLabel(desc, text=meta.help, anchor="w", justify="left", wraplength=320, font=ctk.CTkFont(size=10), text_color=("gray42", "gray62")).pack(fill="x", pady=(1, 0))
            if spec.locked:
                ctk.CTkLabel(desc, text="Funktionsrolle · über Profilwahl gesteuert", anchor="w", font=ctk.CTkFont(size=10, weight="bold"), text_color=("#A16207", "#FCD34D")).pack(fill="x", pady=(2, 0))

            var = ctk.StringVar(value=shown_value(spec))
            controls[spec.path] = var
            choices: list[str] = []
            allow_custom = False
            if spec.kind == "bool":
                choices = [KEEP_VALUE, "Ein", "Aus"]
            elif spec.kind == "enum":
                choices = [KEEP_VALUE, *spec.choices]
            else:
                suggestions = field_values_for_label(spec.label, shown_value(spec))
                if suggestions:
                    choices = [KEEP_VALUE, *suggestions]
                    allow_custom = field_allows_custom_value(spec.label)
            if spec.locked:
                choices = [str(getattr(functional, "meshtastic_role", "") or shown_value(spec))]
                var.set(choices[0])

            values = list(dict.fromkeys(str(item) for item in choices if str(item)))
            if values:
                widget = ctk.CTkComboBox(frame, variable=var, values=values) if allow_custom or len(values) >= 10 else ctk.CTkOptionMenu(frame, variable=var, values=values)
            else:
                widget = ctk.CTkEntry(frame, textvariable=var)
            widget.grid(row=row, column=1, sticky="ew", padx=(0, 8), pady=6)
            if spec.locked:
                try:
                    widget.configure(state="disabled")
                except Exception:
                    pass
            else:
                var.trace_add("write", mark_dirty)
                ctk.CTkButton(frame, text="BEIBEHALTEN", width=105, height=28, fg_color=("gray72", "gray28"), hover_color=("gray65", "gray35"), command=lambda variable=var: variable.set(KEEP_VALUE)).grid(row=row, column=2, sticky="e", padx=(0, 8), pady=6)

    first = next((name for name in CATEGORY_ORDER if name in frames), None)
    if first:
        show_category(first)
    state["building"] = False

    def selected_data() -> dict[str, Any]:
        raw = {path: str(var.get()) for path, var in controls.items()}
        return normalise_profile_data(apply_profile_values(original, specs, raw, functional), functional)

    def check_compatibility(data: dict[str, Any]) -> tuple[list[str], list[str]]:
        radio = None
        try:
            radio = services.load_radio_profile_settings()
        except Exception:
            pass
        return compatibility_notes(data, assigned_board=board_for_profile(target) or board_for_profile(source), selected_board=board_key, board_profiles=services.BOARD_PROFILES, radio_settings=radio)

    def validate_only() -> None:
        try:
            errors, warnings = check_compatibility(selected_data())
            if errors:
                raise ValueError("\n".join(f"• {item}" for item in errors))
            text = "Profil ist gültig."
            if warnings:
                text += "\n\nHinweise:\n" + "\n".join(f"• {item}" for item in warnings)
            messagebox.showinfo("Profilprüfung", text, parent=window)
        except Exception as exc:
            messagebox.showerror("Profilprüfung", str(exc), parent=window)

    def save_profile() -> None:
        try:
            data = selected_data()
            errors, warnings = check_compatibility(data)
        except Exception as exc:
            messagebox.showerror("Profil speichern", str(exc), parent=window)
            return
        if errors:
            messagebox.showerror("Profil nicht kompatibel", "\n".join(errors), parent=window)
            return
        changes = profile_changes(original, data)
        if not changes:
            messagebox.showinfo("Keine Änderungen", "Das Profil wurde nicht verändert.", parent=window)
            return
        warning_text = "\n\nHinweise:\n" + "\n".join(f"⚠ {item}" for item in warnings) if warnings else ""
        if not messagebox.askyesno("Änderungen übernehmen?", f"Folgende Änderungen werden gespeichert:\n\n{format_change_preview(changes)}{warning_text}\n\nJetzt speichern?", parent=window):
            return

        from profile_manager import activate_profile, archive_existing

        target.parent.mkdir(parents=True, exist_ok=True)
        archive = services.PATHS.profiles / "archive"
        archive.mkdir(parents=True, exist_ok=True)
        if target.exists():
            archive_existing(target, archive)
        temp = target.with_suffix(target.suffix + ".tmp")
        try:
            temp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
            checked = yaml.safe_load(temp.read_text(encoding="utf-8")) or {}
            if not isinstance(checked, dict):
                raise ValueError("Gespeichertes Profil ist kein Mapping.")
            temp.replace(target)
        finally:
            temp.unlink(missing_ok=True)
        registration_board = board_for_profile(source) or board_key
        if registration_board in services.BOARD_PROFILES:
            register_profile(target, registration_board, summary_from_profile_file(target), source="functional-profile-form")
        activate_profile(target, root, services, status_prefix="Profil gespeichert")
        saved["path"] = target
        state["dirty"] = False
        _emit(f"FUNCTIONAL PROFILE FORM SAVE file={target.name!r} role={getattr(functional, 'meshtastic_role', '')!r} changes={len(changes)}")
        window.destroy()

    footer = ctk.CTkFrame(window, fg_color="transparent")
    footer.pack(fill="x", padx=22, pady=(0, 18))
    ctk.CTkButton(footer, text="Profil prüfen", width=120, fg_color=("gray72", "gray28"), hover_color=("gray65", "gray35"), command=validate_only).pack(side="left")
    ctk.CTkButton(footer, text="Verwerfen", width=110, fg_color=("gray72", "gray28"), hover_color=("gray65", "gray35"), command=window.destroy).pack(side="right")
    ctk.CTkButton(footer, text="SPEICHERN", width=130, command=save_profile).pack(side="right", padx=(0, 8))

    def close_request() -> None:
        if state["dirty"] and not messagebox.askyesno("Änderungen verwerfen?", "Es gibt ungespeicherte Änderungen. Fenster trotzdem schließen?", parent=window):
            return
        window.destroy()

    window.protocol("WM_DELETE_WINDOW", close_request)
    window.after(120, window.focus_force)
    window.grab_set()
    root.wait_window(window)
    return saved["path"]


def install(services: Any) -> None:
    import profile_editor

    original_open = profile_editor.open_profile_editor
    if getattr(original_open, "_jarnsen_functional_form_editor", False):
        services._jarnsen_functional_form_editor = True
        return

    def open_profile_editor(root: Any, runtime_services: Any, source: Path) -> Path | None:
        functional = _resolve_functional(Path(source), runtime_services)
        if functional is None:
            return original_open(root, runtime_services, source)
        return open_functional_profile_editor(root, runtime_services, Path(source), functional, ctk=profile_editor.ctk)

    open_profile_editor._jarnsen_functional_form_editor = True  # type: ignore[attr-defined]
    profile_editor.open_profile_editor = open_profile_editor
    services._jarnsen_functional_form_editor = True
    services._jarnsen_profile_yaml_editor_visible = False
    _emit("FUNCTIONAL PROFILE FORM EDITOR installed form-only=1 yaml-tab=0 virtual-protobuf-fields=1 dropdown-when-possible=1 firmware-default-inherit=1")
