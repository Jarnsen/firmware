from __future__ import annotations

import copy
import os
import re
import shutil
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any

import customtkinter as ctk
import yaml

from profile_catalog import board_for_profile, register_profile
from profile_editor_model import (
    compatibility_notes,
    field_meta,
    format_change_preview,
    profile_changes,
)
from profile_utils import ProfileSummary, format_summary, summary_from_profile_file


CATEGORY_ORDER = [
    "Gerät",
    "LoRa",
    "Position",
    "Power",
    "Bluetooth",
    "Display",
    "Netzwerk",
    "MQTT",
    "Telemetrie",
    "Module",
    "Sonstiges",
]

CATEGORY_MAP = {
    "device": "Gerät",
    "owner": "Gerät",
    "owner_short": "Gerät",
    "long_name": "Gerät",
    "longname": "Gerät",
    "short_name": "Gerät",
    "shortname": "Gerät",
    "lora": "LoRa",
    "position": "Position",
    "power": "Power",
    "bluetooth": "Bluetooth",
    "display": "Display",
    "network": "Netzwerk",
    "ethernet": "Netzwerk",
    "wifi": "Netzwerk",
    "mqtt": "MQTT",
    "telemetry": "Telemetrie",
}

WRAPPERS = {"config", "module_config"}
PROFILE_EDITOR_NATIVE_CHOICES = True


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


def _button_text(widget: Any) -> str:
    try:
        return str(widget.cget("text") or "")
    except Exception:
        return ""


def _flatten(value: Any, prefix: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], Any]]:
    result: list[tuple[tuple[str, ...], Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            result.extend(_flatten(child, (*prefix, str(key))))
        return result
    # Lists stay one editable YAML value. This keeps channel/module arrays intact.
    result.append((prefix, value))
    return result


def _category(path: tuple[str, ...]) -> str:
    visible = [part for part in path if part not in WRAPPERS]
    if not visible:
        return "Sonstiges"
    first = visible[0].lower()
    if path and path[0] == "module_config":
        if first == "mqtt":
            return "MQTT"
        if first == "telemetry":
            return "Telemetrie"
        return "Module"
    return CATEGORY_MAP.get(first, "Sonstiges")


def _display_path(path: tuple[str, ...]) -> str:
    visible = [part for part in path if part not in WRAPPERS]
    return ".".join(visible or path)


def _set_path(root: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    node: Any = root
    for part in path[:-1]:
        if not isinstance(node, dict):
            raise ValueError(f"Pfad ist kein Mapping: {'.'.join(path)}")
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    if path:
        node[path[-1]] = value


def _coerce(text: str, original: Any) -> Any:
    if isinstance(original, bool):
        return str(text).strip().lower() in {"true", "1", "yes", "on"}
    if isinstance(original, int) and not isinstance(original, bool):
        return int(str(text).strip(), 0)
    if isinstance(original, float):
        return float(str(text).strip())
    if isinstance(original, (list, dict)):
        parsed = yaml.safe_load(text)
        if not isinstance(parsed, type(original)):
            raise ValueError(f"Erwartet {type(original).__name__}, erhalten {type(parsed).__name__}")
        return parsed
    if original is None:
        return yaml.safe_load(text)
    return str(text)


def _summary_from_data(data: dict[str, Any], services: Any) -> ProfileSummary:
    temp = services.PATHS.profiles / ".profile-editor-summary.yaml"
    try:
        temp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return summary_from_profile_file(temp)
    finally:
        try:
            temp.unlink(missing_ok=True)
        except Exception:
            pass


def _safe_target_for_internal(data: dict[str, Any], services: Any) -> Path:
    from profile_manager import stable_profile_name

    summary = _summary_from_data(data, services)
    return services.PATHS.profiles / stable_profile_name(summary, ".yaml")


def open_profile_editor(root: Any, services: Any, source: Path) -> Path | None:
    source = Path(source)
    if not source.exists():
        messagebox.showerror("Profil bearbeiten", f"Profil nicht gefunden:\n{source}", parent=root)
        return None

    try:
        loaded = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        messagebox.showerror("Profil bearbeiten", f"YAML konnte nicht gelesen werden.\n\n{exc}", parent=root)
        return None
    if not isinstance(loaded, dict):
        messagebox.showerror("Profil bearbeiten", "Das Profil muss ein YAML-Mapping enthalten.", parent=root)
        return None

    original_data: dict[str, Any] = copy.deepcopy(loaded)
    functional = None
    try:
        from functional_profiles import (
            active_profile as active_functional_profile,
            function_id_for_path,
            normalise_profile_data,
        )

        functional_id = function_id_for_path(source, services)
        if functional_id is None:
            active = active_functional_profile(services)
            try:
                is_active_copy = source.resolve() == Path(services.PATHS.active_profile).resolve()
            except Exception:
                is_active_copy = source == Path(services.PATHS.active_profile)
            if active is not None and is_active_copy:
                functional_id = active.identifier
        if functional_id is not None:
            functional = active_functional_profile(services)
            if functional is None or functional.identifier != functional_id:
                from functional_profiles import functional_profile

                functional = functional_profile(functional_id)
            original_data = normalise_profile_data(original_data, functional)
    except Exception:
        # The generic editor must still open legacy/imported profiles even if
        # the functional-profile layer is unavailable.
        functional = None
    current_source = source
    saved_result: dict[str, Path | None] = {"path": None}
    assigned_source_board = board_for_profile(source)
    board_key = None
    if hasattr(root, "_selected_board_key"):
        try:
            board_key = root._selected_board_key()
        except Exception:
            board_key = None
    board_key = board_key or assigned_source_board

    window = ctk.CTkToplevel(root)
    window.title(f"JARNSEN MESH · Profil bearbeiten · {source.name}")
    window.geometry("1180x760")
    window.minsize(940, 640)
    window.transient(root)

    header = ctk.CTkFrame(window, fg_color="transparent")
    header.pack(fill="x", padx=22, pady=(18, 10))
    title = ctk.CTkLabel(header, text="Profil bearbeiten", font=ctk.CTkFont(size=24, weight="bold"))
    title.pack(side="left")
    dirty_var = ctk.StringVar(value="Gespeichert")
    dirty_label = ctk.CTkLabel(
        header,
        textvariable=dirty_var,
        font=ctk.CTkFont(size=12, weight="bold"),
        text_color=("gray40", "gray65"),
    )
    dirty_label.pack(side="right", pady=(7, 0))

    summary_var = ctk.StringVar(value=format_summary(summary_from_profile_file(source)))
    ctk.CTkLabel(
        window,
        textvariable=summary_var,
        anchor="w",
        font=ctk.CTkFont(size=12),
        text_color=("gray40", "gray65"),
    ).pack(fill="x", padx=22, pady=(0, 8))

    if functional is not None:
        ctk.CTkLabel(
            window,
            text=(
                f"{functional.label}: Funktionskern ist gesperrt – Rolle, Schlaf- und Serviceverhalten "
                "werden beim Speichern und Schreiben wiederhergestellt."
            ),
            anchor="w",
            justify="left",
            wraplength=1110,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("#0E6A36", "#86EFAC"),
        ).pack(fill="x", padx=22, pady=(0, 8))

    tabs = ctk.CTkTabview(window)
    tabs.pack(fill="both", expand=True, padx=22, pady=(0, 12))
    form_tab = tabs.add("Formular")
    yaml_tab = tabs.add("YAML")

    form_tab.grid_columnconfigure(1, weight=1)
    nav = ctk.CTkScrollableFrame(form_tab, width=180, fg_color=("gray90", "gray17"))
    nav.grid(row=0, column=0, sticky="nsw", padx=(8, 8), pady=8)
    content = ctk.CTkScrollableFrame(form_tab, fg_color="transparent")
    content.grid(row=0, column=1, sticky="nsew", padx=(0, 8), pady=8)
    form_tab.grid_rowconfigure(0, weight=1)

    yaml_box = ctk.CTkTextbox(yaml_tab, wrap="none", font=("Consolas", 12))
    yaml_box.pack(fill="both", expand=True, padx=8, pady=8)
    baseline_yaml = yaml.safe_dump(original_data, allow_unicode=True, sort_keys=False)
    yaml_box.insert("1.0", baseline_yaml)

    controls: dict[tuple[str, ...], tuple[Any, Any, tuple[str, ...] | None]] = {}
    category_frames: dict[str, Any] = {}
    dirty_state = {"form": False, "yaml": False}

    def functional_field_locked(path: tuple[str, ...]) -> bool:
        if functional is None:
            return False
        try:
            from functional_profiles import is_locked_path

            return is_locked_path(functional, path)
        except Exception:
            return False

    def mark_form_dirty(*_args: Any) -> None:
        dirty_state["form"] = True
        dirty_var.set("● Ungespeicherte Änderungen")
        dirty_label.configure(text_color=("#9A6700", "#F2C94C"))

    def mark_yaml_dirty(_event: Any = None) -> None:
        current = yaml_box.get("1.0", "end-1c")
        dirty_state["yaml"] = current.strip() != baseline_yaml.strip()
        if dirty_state["yaml"]:
            dirty_var.set("● Ungespeicherte Änderungen")
            dirty_label.configure(text_color=("#9A6700", "#F2C94C"))

    yaml_box.bind("<KeyRelease>", mark_yaml_dirty, add="+")

    flat = _flatten(original_data)
    grouped: dict[str, list[tuple[tuple[str, ...], Any]]] = {}
    for path, value in flat:
        grouped.setdefault(_category(path), []).append((path, value))

    def show_category(name: str) -> None:
        for category_name, frame in category_frames.items():
            if category_name == name:
                frame.grid()
            else:
                frame.grid_remove()

    for name in CATEGORY_ORDER:
        if name not in grouped:
            continue
        ctk.CTkButton(
            nav,
            text=name,
            anchor="w",
            fg_color=("gray78", "gray25"),
            hover_color=("gray70", "gray31"),
            command=lambda category=name: show_category(category),
        ).pack(fill="x", padx=5, pady=4)

        frame = ctk.CTkFrame(content, fg_color="transparent")
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(1, weight=1)
        category_frames[name] = frame
        ctk.CTkLabel(
            frame,
            text=name,
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=8, pady=(5, 12))
        ctk.CTkLabel(
            frame,
            text="Tipp: In lange Auswahllisten tippen, um die Treffer zu filtern.",
            font=ctk.CTkFont(size=10),
            text_color=("gray42", "gray62"),
        ).grid(row=0, column=1, sticky="e", padx=8, pady=(5, 12))

        for row, (path, value) in enumerate(grouped[name], start=1):
            label = _display_path(path)
            metadata = field_meta(path)
            locked = functional_field_locked(path)
            description = ctk.CTkFrame(frame, fg_color="transparent", width=310)
            description.grid(row=row, column=0, sticky="new", padx=(8, 14), pady=6)
            ctk.CTkLabel(
                description,
                text=metadata.title,
                anchor="w",
                font=ctk.CTkFont(size=12, weight="bold"),
            ).pack(fill="x")
            ctk.CTkLabel(
                description,
                text=metadata.help,
                anchor="w",
                justify="left",
                wraplength=300,
                font=ctk.CTkFont(size=10),
                text_color=("gray42", "gray62"),
            ).pack(fill="x", pady=(1, 0))
            if locked:
                ctk.CTkLabel(
                    description,
                    text="Funktionskern – nicht änderbar",
                    anchor="w",
                    font=ctk.CTkFont(size=10, weight="bold"),
                    text_color=("#A16207", "#FCD34D"),
                ).pack(fill="x", pady=(2, 0))
            strict_values: tuple[str, ...] | None = None
            if isinstance(value, bool):
                var = ctk.StringVar(value="true" if value else "false")
                widget = ctk.CTkSwitch(
                    frame,
                    text="Ein",
                    variable=var,
                    onvalue="true",
                    offvalue="false",
                    command=mark_form_dirty,
                )
            else:
                if isinstance(value, (list, dict)):
                    shown = yaml.safe_dump(value, allow_unicode=True, default_flow_style=True).strip()
                elif value is None:
                    shown = "null"
                else:
                    shown = str(value)
                var = ctk.StringVar(value=shown)
                var.trace_add("write", mark_form_dirty)
                from profile_editor_choices import field_allows_custom_value, field_values_for_label

                values = field_values_for_label(label, shown)
                custom_value = field_allows_custom_value(label)
                if values and (custom_value or len(values) >= 10):
                    widget = ctk.CTkComboBox(frame, variable=var, values=values)
                    if not custom_value:
                        strict_values = tuple(values)

                        def filter_values(
                            *_args: Any,
                            combo: Any = widget,
                            variable: Any = var,
                            available: tuple[str, ...] = strict_values,
                        ) -> None:
                            entered = str(variable.get() or "").strip().casefold()
                            matches = [item for item in available if entered in item.casefold()]
                            try:
                                combo.configure(values=matches or list(available))
                            except Exception:
                                pass

                        var.trace_add("write", filter_values)
                elif values:
                    strict_values = tuple(values)
                    widget = ctk.CTkOptionMenu(frame, variable=var, values=values)
                else:
                    widget = ctk.CTkEntry(frame, textvariable=var)
            widget.grid(row=row, column=1, sticky="ew", padx=(0, 8), pady=6)
            if locked:
                try:
                    widget.configure(state="disabled")
                except Exception:
                    pass
            controls[path] = (var, value, strict_values)

    content.grid_columnconfigure(0, weight=1)
    first_category = next((name for name in CATEGORY_ORDER if name in category_frames), None)
    if first_category:
        show_category(first_category)

    def data_from_form() -> dict[str, Any]:
        result = copy.deepcopy(original_data)
        for path, (var, old_value, strict_values) in controls.items():
            try:
                if strict_values is not None and str(var.get()) not in strict_values:
                    raise ValueError("Bitte einen vollständigen Wert aus der Auswahlliste wählen.")
                new_value = _coerce(var.get(), old_value)
            except Exception as exc:
                raise ValueError(f"{_display_path(path)}: {exc}") from exc
            _set_path(result, path, new_value)
        return result

    def selected_data() -> dict[str, Any]:
        raw = yaml_box.get("1.0", "end-1c")
        raw_changed = raw.strip() != baseline_yaml.strip()
        selected: dict[str, Any]
        if raw_changed and dirty_state["form"]:
            use_yaml = messagebox.askyesno(
                "Formular und YAML geändert",
                "Es wurden sowohl Formularfelder als auch der YAML-Text geändert.\n\n"
                "Soll der YAML-Text gespeichert werden?\n"
                "Nein = Formularwerte verwenden.",
                parent=window,
            )
            if use_yaml:
                parsed = yaml.safe_load(raw) or {}
                if not isinstance(parsed, dict):
                    raise ValueError("YAML muss ein Mapping enthalten.")
                selected = parsed
            else:
                selected = data_from_form()
        elif raw_changed:
            parsed = yaml.safe_load(raw) or {}
            if not isinstance(parsed, dict):
                raise ValueError("YAML muss ein Mapping enthalten.")
            selected = parsed
        else:
            selected = data_from_form()

        if functional is not None:
            from functional_profiles import normalise_profile_data

            return normalise_profile_data(selected, functional)
        return selected

    def validate_only() -> None:
        try:
            data = selected_data()
            summary = _summary_from_data(data, services)
            messagebox.showinfo(
                "Profilprüfung",
                "Profil ist gültiges YAML.\n\n" + format_summary(summary),
                parent=window,
            )
        except Exception as exc:
            messagebox.showerror("Profilprüfung", str(exc), parent=window)

    def write_profile(*, save_as: bool) -> None:
        nonlocal current_source, original_data, baseline_yaml
        try:
            data = selected_data()
            summary = _summary_from_data(data, services)
        except Exception as exc:
            messagebox.showerror("Profil speichern", f"Profil ist ungültig.\n\n{exc}", parent=window)
            return

        target = current_source
        if functional is not None:
            from functional_profiles import profile_path

            target = profile_path(services, functional)
            if save_as:
                messagebox.showinfo(
                    "Funktionsprofil",
                    "Ein Funktionsprofil bleibt eine der vier festen Profil-Dateien. "
                    "Änderungen werden in diesem Profil gespeichert; eine fünfte Profilkopie wird nicht angelegt.",
                    parent=window,
                )
                return
        else:
            is_internal = target.name.startswith(".") or target == services.PATHS.active_profile
            outside_profiles = target.parent.resolve() != services.PATHS.profiles.resolve()
            if is_internal or outside_profiles:
                target = _safe_target_for_internal(data, services)

        if save_as and functional is None:
            suggested = _safe_target_for_internal(data, services)
            chosen = filedialog.asksaveasfilename(
                parent=window,
                title="Profil speichern unter",
                initialdir=str(services.PATHS.profiles),
                initialfile=suggested.name,
                defaultextension=".yaml",
                filetypes=[("YAML-Profil", "*.yaml *.yml"), ("Alle Dateien", "*.*")],
            )
            if not chosen:
                return
            target = Path(chosen)

        assigned_board = board_for_profile(current_source) or assigned_source_board
        radio_settings = None
        try:
            radio_settings = services.load_radio_profile_settings()
        except Exception:
            pass
        errors, warnings = compatibility_notes(
            data,
            assigned_board=assigned_board,
            selected_board=board_key,
            board_profiles=services.BOARD_PROFILES,
            radio_settings=radio_settings,
        )
        if errors:
            messagebox.showerror(
                "Profil nicht kompatibel",
                "Das Profil kann so nicht gespeichert werden:\n\n" + "\n".join(f"• {item}" for item in errors),
                parent=window,
            )
            return

        changes = profile_changes(original_data, data)
        if not changes and not save_as:
            messagebox.showinfo("Keine Änderungen", "Das Profil wurde nicht verändert.", parent=window)
            return
        preview = format_change_preview(changes) if changes else "• Unveränderte Kopie unter neuem Namen speichern"
        warning_text = ""
        if warnings:
            warning_text = "\n\nHinweise:\n" + "\n".join(f"⚠ {item}" for item in warnings)
        if not messagebox.askyesno(
            "Änderungen übernehmen?",
            f"Folgende Änderungen werden gespeichert:\n\n{preview}{warning_text}\n\nJetzt speichern?",
            parent=window,
        ):
            return

        target.parent.mkdir(parents=True, exist_ok=True)
        archive_dir = services.PATHS.profiles / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)

        from profile_manager import archive_existing, activate_profile

        payload = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        temporary = target.with_suffix(target.suffix + ".tmp")
        try:
            temporary.write_text(payload, encoding="utf-8")
            checked = yaml.safe_load(temporary.read_text(encoding="utf-8"))
            if not isinstance(checked, dict):
                raise ValueError("Gespeichertes Profil ist kein YAML-Mapping.")
            if target.exists() and target.resolve() != services.PATHS.active_profile.resolve():
                archive_existing(target, archive_dir)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)

        registration_board = assigned_board or board_key
        if registration_board in services.BOARD_PROFILES:
            register_profile(target, registration_board, summary, source="profile-editor")

        try:
            activate_profile(target, root, services, status_prefix="Profil gespeichert")
        except Exception:
            shutil.copy2(target, services.PATHS.active_profile)

        current_source = target
        original_data = copy.deepcopy(data)
        baseline_yaml = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        yaml_box.delete("1.0", "end")
        yaml_box.insert("1.0", baseline_yaml)
        fresh_values = dict(_flatten(data))
        for path in list(controls):
            if path not in fresh_values:
                del controls[path]
                continue
            var, _old_value, strict_values = controls[path]
            fresh = fresh_values[path]
            if isinstance(fresh, bool):
                shown = "true" if fresh else "false"
            elif isinstance(fresh, (list, dict)):
                shown = yaml.safe_dump(fresh, allow_unicode=True, default_flow_style=True).strip()
            elif fresh is None:
                shown = "null"
            else:
                shown = str(fresh)
            if strict_values is not None and shown not in strict_values:
                strict_values = (shown, *strict_values)
            var.set(shown)
            controls[path] = (var, fresh, strict_values)
        saved_result["path"] = target
        dirty_state["form"] = False
        dirty_state["yaml"] = False
        dirty_var.set("Gespeichert")
        dirty_label.configure(text_color=("gray40", "gray65"))
        summary_var.set(format_summary(summary))
        window.title(f"JARNSEN MESH · Profil bearbeiten · {target.name}")
        _emit(
            f"PROFILE EDITOR SAVE file={target.name!r} board={registration_board!r} "
            f"role={summary.role!r} long={summary.long_name!r} short={summary.short_name!r}"
        )
        messagebox.showinfo(
            "Profil gespeichert",
            f"Profil gespeichert und als aktives Profil übernommen.\n\n{target}\n\n"
            "Die vorherige Version wurde – falls vorhanden – im Archiv gesichert.",
            parent=window,
        )

    def restore_previous() -> None:
        from profile_manager import activate_profile, archived_versions, restore_latest_version

        target = current_source
        if target.name.startswith(".") or target == services.PATHS.active_profile:
            target = _safe_target_for_internal(original_data, services)
        archive_dir = services.PATHS.profiles / "archive"
        versions = archived_versions(target, archive_dir)
        if not versions:
            messagebox.showinfo(
                "Vorherige Version",
                "Für dieses Profil ist noch keine ältere Version im Archiv vorhanden.",
                parent=window,
            )
            return
        selected = versions[0]
        if not messagebox.askyesno(
            "Vorherige Version wiederherstellen?",
            f"Diese Version wird wiederhergestellt:\n\n{selected.name}\n\n"
            "Die aktuelle Version wird vorher automatisch archiviert.",
            parent=window,
        ):
            return
        restored = restore_latest_version(target, archive_dir)
        if functional is not None:
            try:
                from functional_profiles import normalise_profile_data

                restored_data = yaml.safe_load(restored.read_text(encoding="utf-8")) or {}
                if isinstance(restored_data, dict):
                    restored.write_text(
                        yaml.safe_dump(
                            normalise_profile_data(restored_data, functional),
                            allow_unicode=True,
                            sort_keys=False,
                        ),
                        encoding="utf-8",
                    )
            except Exception as exc:
                messagebox.showerror("Funktionsprofil", f"Funktionskern konnte nicht wiederhergestellt werden.\n\n{exc}", parent=window)
                return
        summary = summary_from_profile_file(restored)
        assigned = board_for_profile(current_source) or board_key
        if assigned in services.BOARD_PROFILES:
            register_profile(restored, assigned, summary, source="profile-editor-restore")
        activate_profile(restored, root, services, status_prefix="Vorherige Profilversion wiederhergestellt")
        saved_result["path"] = restored
        _emit(f"PROFILE EDITOR RESTORE file={restored.name!r} archived={selected.name!r}")
        window.destroy()
        root.after(80, lambda: open_profile_editor(root, services, restored))

    footer = ctk.CTkFrame(window, fg_color="transparent")
    footer.pack(fill="x", padx=22, pady=(0, 18))
    ctk.CTkButton(
        footer,
        text="Profil prüfen",
        width=120,
        fg_color=("gray72", "gray28"),
        hover_color=("gray65", "gray35"),
        command=validate_only,
    ).pack(side="left")
    ctk.CTkButton(
        footer,
        text="Vorherige Version",
        width=150,
        fg_color=("gray72", "gray28"),
        hover_color=("gray65", "gray35"),
        command=restore_previous,
    ).pack(side="left", padx=(8, 0))
    ctk.CTkButton(
        footer,
        text="Verwerfen",
        width=110,
        fg_color=("gray72", "gray28"),
        hover_color=("gray65", "gray35"),
        command=window.destroy,
    ).pack(side="right")
    if functional is None:
        ctk.CTkButton(
            footer,
            text="Speichern unter …",
            width=145,
            fg_color=("gray72", "gray28"),
            hover_color=("gray65", "gray35"),
            command=lambda: write_profile(save_as=True),
        ).pack(side="right", padx=(0, 8))
    ctk.CTkButton(
        footer,
        text="SPEICHERN",
        width=130,
        command=lambda: write_profile(save_as=False),
    ).pack(side="right", padx=(0, 8))

    def close_request() -> None:
        raw_changed = yaml_box.get("1.0", "end-1c").strip() != baseline_yaml.strip()
        if dirty_state["form"] or raw_changed:
            if not messagebox.askyesno(
                "Änderungen verwerfen?",
                "Es gibt ungespeicherte Änderungen. Fenster trotzdem schließen?",
                parent=window,
            ):
                return
        window.destroy()

    window.protocol("WM_DELETE_WINDOW", close_request)
    window.after(120, window.focus_force)
    window.grab_set()
    root.wait_window(window)
    return saved_result["path"]


def enhanced_select_profile_dialog(
    root: Any,
    services: Any,
    *,
    board_key: str | None = None,
    title: str = "JARNSEN MESH · Profil auswählen",
) -> Path | None:
    from profile_manager import list_profile_records, open_profile_folder

    selected: dict[str, Path | None] = {"path": None}
    window = ctk.CTkToplevel(root)
    window.title(title)
    window.geometry("1080x620")
    window.minsize(900, 500)
    window.transient(root)

    header = ctk.CTkFrame(window, fg_color="transparent")
    header.pack(fill="x", padx=22, pady=(20, 12))
    ctk.CTkLabel(header, text="Profile", font=ctk.CTkFont(size=24, weight="bold")).pack(side="left")
    subtitle = "Auswählen, bearbeiten und archiviert speichern"
    ctk.CTkLabel(
        header,
        text=subtitle,
        font=ctk.CTkFont(size=12),
        text_color=("gray40", "gray65"),
    ).pack(side="left", padx=(12, 0), pady=(7, 0))

    columns = ctk.CTkFrame(window, fg_color=("gray88", "gray19"), corner_radius=10)
    columns.pack(fill="x", padx=22, pady=(0, 6))
    headings = ((0, "Rolle", 145), (1, "Long Name", 240), (2, "Short", 70), (3, "Board", 200), (4, "Geändert", 110))
    for col, text, width in headings:
        columns.grid_columnconfigure(col, weight=1 if col in (1, 3) else 0, minsize=width)
        ctk.CTkLabel(columns, text=text, font=ctk.CTkFont(size=11, weight="bold"), anchor="w").grid(
            row=0, column=col, sticky="ew", padx=10, pady=8
        )
    columns.grid_columnconfigure(5, minsize=190)

    list_frame = ctk.CTkScrollableFrame(window, fg_color="transparent")
    list_frame.pack(fill="both", expand=True, padx=18, pady=(0, 10))
    for col in range(6):
        list_frame.grid_columnconfigure(col, weight=1 if col in (1, 3) else 0)

    def choose(path: Path) -> None:
        selected["path"] = path
        window.destroy()

    def clear_rows() -> None:
        for child in list_frame.winfo_children():
            child.destroy()

    def refresh_rows() -> None:
        clear_rows()
        records = list_profile_records(services, board_key=board_key)
        if not records:
            ctk.CTkLabel(
                list_frame,
                text="Noch keine passenden gespeicherten Profile vorhanden.",
                text_color=("gray40", "gray65"),
            ).grid(row=0, column=0, columnspan=6, sticky="w", padx=10, pady=24)
            return

        for row_index, record in enumerate(records):
            label = services.BOARD_PROFILES.get(record.board_key or "", {}).get("label", "nicht zugeordnet")
            values = (
                record.summary.role or "–",
                record.summary.long_name or "–",
                record.summary.short_name or "–",
                label,
                record.modified.strftime("%d.%m. %H:%M"),
            )
            widths = (145, 240, 70, 200, 110)
            for col, (value, width) in enumerate(zip(values, widths)):
                ctk.CTkLabel(list_frame, text=value, anchor="w", width=width, font=ctk.CTkFont(size=12)).grid(
                    row=row_index, column=col, sticky="ew", padx=8, pady=6
                )
            actions = ctk.CTkFrame(list_frame, fg_color="transparent")
            actions.grid(row=row_index, column=5, sticky="e", padx=5, pady=4)
            ctk.CTkButton(
                actions,
                text="Bearbeiten",
                width=90,
                fg_color=("gray72", "gray28"),
                hover_color=("gray65", "gray35"),
                command=lambda path=record.path: (open_profile_editor(root, services, path), refresh_rows()),
            ).pack(side="left", padx=(0, 6))
            ctk.CTkButton(
                actions,
                text="Auswählen",
                width=90,
                command=lambda path=record.path: choose(path),
            ).pack(side="left")

    refresh_rows()

    footer = ctk.CTkFrame(window, fg_color="transparent")
    footer.pack(fill="x", padx=22, pady=(0, 18))
    ctk.CTkButton(
        footer,
        text="Profilordner öffnen",
        fg_color=("gray72", "gray28"),
        hover_color=("gray65", "gray35"),
        command=lambda: open_profile_folder(services),
    ).pack(side="left")
    ctk.CTkLabel(
        footer,
        text=f"Ordner: {services.PATHS.profiles}",
        text_color=("gray40", "gray65"),
        font=ctk.CTkFont(size=10),
    ).pack(side="left", padx=(12, 0))
    ctk.CTkButton(
        footer,
        text="Abbrechen",
        width=110,
        fg_color=("gray72", "gray28"),
        hover_color=("gray65", "gray35"),
        command=window.destroy,
    ).pack(side="right")

    window.protocol("WM_DELETE_WINDOW", window.destroy)
    window.after(100, window.focus_force)
    window.grab_set()
    root.wait_window(window)
    return selected["path"]


def install(services: Any) -> None:
    """Install editable profile manager and a main-window profile editor button."""
    import profile_manager

    profile_manager.select_profile_dialog = enhanced_select_profile_dialog

    original_root_init = ctk.CTk.__init__

    def root_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_root_init(self, *args, **kwargs)

        def patch_app() -> None:
            if getattr(self, "_jarnsen_profile_editor_installed", False):
                return
            if not hasattr(self, "profile_path_var"):
                try:
                    self.after(180, patch_app)
                except Exception:
                    pass
                return

            select_button = next((w for w in _walk(self) if _button_text(w) == "Profil auswählen"), None)
            if select_button is None:
                try:
                    self.after(180, patch_app)
                except Exception:
                    pass
                return

            parent = getattr(select_button, "master", None)
            if parent is None:
                return
            self._jarnsen_profile_editor_installed = True

            def edit_current() -> None:
                raw = str(self.profile_path_var.get() or "").strip()
                path = Path(raw) if raw and raw != "Kein Profil geladen" else services.PATHS.active_profile
                if not path.exists():
                    messagebox.showwarning("Profil bearbeiten", "Bitte zuerst ein Profil auswählen oder vom Master einlesen.", parent=self)
                    return
                open_profile_editor(self, services, path)

            button = ctk.CTkButton(
                parent,
                text="PROFIL BEARBEITEN",
                fg_color=("gray72", "gray28"),
                hover_color=("gray65", "gray35"),
                command=edit_current,
            )
            button.pack(side="left", padx=(10, 0))
            self.profile_edit_button = button
            _emit("PROFILE EDITOR main button installed")

        try:
            self.after(880, patch_app)
        except Exception:
            pass

    ctk.CTk.__init__ = root_init
    _emit("PROFILE EDITOR installed form=1 yaml=1 archive-on-save=1 save-as=1 manager-edit=1")
