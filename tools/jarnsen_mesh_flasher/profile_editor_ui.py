from __future__ import annotations

import copy
import shutil
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any

import customtkinter as ctk
import yaml

from profile_catalog import board_for_profile, register_profile
from profile_manager import stable_profile_name
from profile_utils import ProfileSummary, format_summary


ROLE_VALUES = [
    "CLIENT",
    "CLIENT_MUTE",
    "CLIENT_BASE",
    "ROUTER",
    "ROUTER_LATE",
    "ROUTER_CLIENT",
    "REPEATER",
    "TRACKER",
    "SENSOR",
    "TAK",
    "TAK_TRACKER",
]

REGION_VALUES = [
    "UNSET",
    "US",
    "EU_433",
    "EU_868",
    "CN",
    "JP",
    "ANZ",
    "KR",
    "TW",
    "RU",
    "IN",
    "NZ_865",
    "TH",
    "LORA_24",
    "UA_433",
    "UA_868",
    "MY_433",
    "MY_919",
    "SG_923",
    "PH_433",
    "PH_868",
    "PH_915",
]

MODEM_VALUES = [
    "LONG_FAST",
    "LONG_SLOW",
    "VERY_LONG_SLOW",
    "MEDIUM_SLOW",
    "MEDIUM_FAST",
    "SHORT_SLOW",
    "SHORT_FAST",
    "SHORT_TURBO",
]

ENUM_VALUES: dict[str, list[str]] = {
    "device.role": ROLE_VALUES,
    "lora.region": REGION_VALUES,
    "lora.modem_preset": MODEM_VALUES,
    "lora.rebroadcast_mode": [
        "ALL",
        "ALL_SKIP_DECODING",
        "LOCAL_ONLY",
        "KNOWN_ONLY",
        "NONE",
        "CORE_PORTNUMS_ONLY",
    ],
    "position.gps_mode": ["DISABLED", "ENABLED", "NOT_PRESENT"],
    "bluetooth.mode": ["RANDOM_PIN", "FIXED_PIN", "NO_PIN"],
    "bluetooth.pairing_mode": ["RANDOM_PIN", "FIXED_PIN", "NO_PIN"],
    "display.units": ["METRIC", "IMPERIAL"],
    "display.oled_type": ["OLED_AUTO", "OLED_SSD1306", "OLED_SH1106", "OLED_SH1107"],
    "network.address_mode": ["DHCP", "STATIC"],
}

TAB_ORDER = ["Gerät", "LoRa", "Position", "Power", "Bluetooth", "Display", "Module", "Sonstiges"]


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


def _canonical(path: tuple[str, ...]) -> str:
    parts = list(path)
    if parts and parts[0] in {"config", "module_config", "moduleConfig"}:
        parts = parts[1:]
    return ".".join(parts)


def _category(path: tuple[str, ...]) -> str:
    key = _canonical(path)
    if key in {"owner", "owner_short", "long_name", "short_name", "longName", "shortName"}:
        return "Gerät"
    first = key.split(".", 1)[0].lower()
    if first == "device":
        return "Gerät"
    if first == "lora":
        return "LoRa"
    if first == "position":
        return "Position"
    if first == "power":
        return "Power"
    if first == "bluetooth":
        return "Bluetooth"
    if first == "display":
        return "Display"
    if path and path[0] in {"module_config", "moduleConfig"}:
        return "Module"
    if first in {
        "mqtt",
        "telemetry",
        "canned_message",
        "canned_message_module",
        "neighbor_info",
        "range_test",
        "serial",
        "store_forward",
        "detection_sensor",
        "audio",
        "remote_hardware",
        "paxcounter",
        "ambient_lighting",
        "traffic_management",
    }:
        return "Module"
    return "Sonstiges"


def _flatten(value: Any, prefix: tuple[str, ...] = ()) -> list[tuple[tuple[str, ...], Any]]:
    result: list[tuple[tuple[str, ...], Any]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            result.extend(_flatten(child, prefix + (str(key),)))
        return result
    if isinstance(value, (str, int, float, bool)) or value is None:
        result.append((prefix, value))
    return result


def _set_nested(root: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    node: dict[str, Any] = root
    for key in path[:-1]:
        child = node.get(key)
        if not isinstance(child, dict):
            child = {}
            node[key] = child
        node = child
    if path:
        node[path[-1]] = value


def _summary_from_data(data: dict[str, Any]) -> ProfileSummary:
    long_name = str(data.get("owner") or data.get("long_name") or data.get("longName") or "").strip()
    short_name = str(data.get("owner_short") or data.get("short_name") or data.get("shortName") or "").strip()
    role = ""
    config = data.get("config")
    if isinstance(config, dict):
        device = config.get("device")
        if isinstance(device, dict):
            role = str(device.get("role") or "").strip()
    if not role:
        device = data.get("device")
        if isinstance(device, dict):
            role = str(device.get("role") or "").strip()
    return ProfileSummary(long_name=long_name, short_name=short_name, role=role)


def _convert(text: str, original: Any) -> Any:
    if isinstance(original, bool):
        return text.strip().lower() in {"ja", "true", "1", "on"}
    if isinstance(original, int) and not isinstance(original, bool):
        return int(text.strip())
    if isinstance(original, float):
        return float(text.strip().replace(",", "."))
    if original is None:
        stripped = text.strip()
        if stripped.lower() in {"none", "null", "~"}:
            return None
        return stripped
    return text


def _archive_copy(path: Path, archive_dir: Path) -> Path | None:
    if not path.exists() or not path.is_file():
        return None
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = archive_dir / f"{path.stem}__{stamp}{path.suffix or '.yaml'}"
    counter = 2
    while candidate.exists():
        candidate = archive_dir / f"{path.stem}__{stamp}-{counter}{path.suffix or '.yaml'}"
        counter += 1
    shutil.copy2(path, candidate)
    return candidate


class ProfileEditor(ctk.CTkToplevel):
    def __init__(self, app: Any, services: Any, source: Path) -> None:
        super().__init__(app)
        self.app = app
        self.services = services
        self.source = Path(source)
        self.original = yaml.safe_load(self.source.read_text(encoding="utf-8", errors="replace")) or {}
        if not isinstance(self.original, dict):
            raise ValueError("Das Profil hat keine gültige YAML-Objektstruktur.")
        self.data = copy.deepcopy(self.original)
        self.fields: dict[tuple[str, ...], tuple[Any, ctk.StringVar]] = {}
        self.dirty_paths: set[tuple[str, ...]] = set()
        self._closing = False

        self.title("JARNSEN MESH · Profil bearbeiten")
        self.geometry("1180x760")
        self.minsize(940, 620)
        self.transient(app)

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=22, pady=(18, 8))
        ctk.CTkLabel(header, text="Profil bearbeiten", font=ctk.CTkFont(size=24, weight="bold")).pack(side="left")
        self.change_var = ctk.StringVar(value="Keine ungespeicherten Änderungen")
        ctk.CTkLabel(header, textvariable=self.change_var, text_color=("gray40", "gray65")).pack(side="left", padx=(14, 0), pady=(6, 0))

        board_values = ["nicht zugeordnet"] + [str(item["label"]) for item in services.BOARD_PROFILES.values()]
        assigned = board_for_profile(self.source)
        selected_board = str(services.BOARD_PROFILES[assigned]["label"]) if assigned in services.BOARD_PROFILES else "nicht zugeordnet"
        self.board_var = ctk.StringVar(value=selected_board)
        ctk.CTkLabel(header, text="Board:").pack(side="right", padx=(12, 6))
        ctk.CTkOptionMenu(header, variable=self.board_var, values=board_values, width=250, command=lambda _v: self._mark_board_dirty()).pack(side="right")

        path_frame = ctk.CTkFrame(self, fg_color="transparent")
        path_frame.pack(fill="x", padx=22, pady=(0, 10))
        self.path_var = ctk.StringVar(value=str(self.source))
        ctk.CTkLabel(path_frame, textvariable=self.path_var, anchor="w", text_color=("gray40", "gray65"), font=ctk.CTkFont(size=11)).pack(fill="x")

        self.tabs = ctk.CTkTabview(self)
        self.tabs.pack(fill="both", expand=True, padx=22, pady=(0, 12))

        flattened = _flatten(self.original)
        grouped: dict[str, list[tuple[tuple[str, ...], Any]]] = {name: [] for name in TAB_ORDER}
        for path, value in flattened:
            if path:
                grouped[_category(path)].append((path, value))

        for tab_name in TAB_ORDER:
            items = grouped[tab_name]
            if not items:
                continue
            tab = self.tabs.add(tab_name)
            scroller = ctk.CTkScrollableFrame(tab, fg_color="transparent")
            scroller.pack(fill="both", expand=True, padx=4, pady=4)
            scroller.grid_columnconfigure(1, weight=1)
            for row, (path, value) in enumerate(items):
                canonical = _canonical(path)
                ctk.CTkLabel(scroller, text=canonical, anchor="w", font=ctk.CTkFont(size=12)).grid(row=row, column=0, sticky="w", padx=(8, 14), pady=5)
                var = ctk.StringVar(value="Ja" if value is True else "Nein" if value is False else "" if value is None else str(value))
                self.fields[path] = (value, var)
                choices = None
                if isinstance(value, bool):
                    choices = ["Ja", "Nein"]
                else:
                    choices = ENUM_VALUES.get(canonical)
                if choices:
                    values = list(dict.fromkeys(([str(value)] if value is not None and str(value) not in choices else []) + list(choices)))
                    widget = ctk.CTkOptionMenu(scroller, variable=var, values=values, width=270, command=lambda _v, p=path: self._field_changed(p))
                    widget.grid(row=row, column=1, sticky="ew", padx=(0, 8), pady=5)
                else:
                    widget = ctk.CTkEntry(scroller, textvariable=var)
                    widget.grid(row=row, column=1, sticky="ew", padx=(0, 8), pady=5)
                    var.trace_add("write", lambda *_args, p=path: self._field_changed(p))

        raw_tab = self.tabs.add("YAML")
        ctk.CTkLabel(
            raw_tab,
            text="Vollständige YAML-Vorschau. Komplexe Listen/Objekte bleiben beim strukturierten Speichern unverändert.",
            anchor="w",
            text_color=("gray40", "gray65"),
        ).pack(fill="x", padx=8, pady=(8, 6))
        self.yaml_box = ctk.CTkTextbox(raw_tab, corner_radius=10)
        self.yaml_box.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.yaml_box.insert("1.0", yaml.safe_dump(self.original, allow_unicode=True, sort_keys=False))
        self.yaml_box.configure(state="disabled")

        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=22, pady=(0, 18))
        ctk.CTkButton(footer, text="Profil prüfen", width=120, fg_color=("gray72", "gray28"), hover_color=("gray65", "gray35"), command=self.validate).pack(side="left")
        ctk.CTkButton(footer, text="Speichern unter …", width=150, fg_color=("gray72", "gray28"), hover_color=("gray65", "gray35"), command=self.save_as).pack(side="left", padx=(10, 0))
        ctk.CTkButton(footer, text="Verwerfen", width=110, fg_color=("gray72", "gray28"), hover_color=("gray65", "gray35"), command=self.close_requested).pack(side="right")
        ctk.CTkButton(footer, text="SPEICHERN", width=150, command=self.save).pack(side="right", padx=(0, 10))

        self.protocol("WM_DELETE_WINDOW", self.close_requested)
        self.after(100, self.focus_force)
        self.grab_set()
        _emit(f"PROFILE EDITOR OPEN source={str(self.source)!r} fields={len(self.fields)}")

    def _mark_board_dirty(self) -> None:
        self.dirty_paths.add(("__board__",))
        self._refresh_dirty()

    def _field_changed(self, path: tuple[str, ...]) -> None:
        original, var = self.fields[path]
        try:
            current = _convert(var.get(), original)
        except Exception:
            current = var.get()
        if current == original:
            self.dirty_paths.discard(path)
        else:
            self.dirty_paths.add(path)
        self._refresh_dirty()

    def _refresh_dirty(self) -> None:
        count = len(self.dirty_paths)
        self.change_var.set("Keine ungespeicherten Änderungen" if count == 0 else f"● {count} ungespeicherte Änderung{'en' if count != 1 else ''}")

    def _collect(self) -> dict[str, Any]:
        data = copy.deepcopy(self.original)
        errors: list[str] = []
        for path, (original, var) in self.fields.items():
            try:
                value = _convert(var.get(), original)
            except Exception as exc:
                errors.append(f"{_canonical(path)}: {exc}")
                continue
            _set_nested(data, path, value)
        if errors:
            raise ValueError("Ungültige Werte:\n" + "\n".join(errors[:12]))
        summary = _summary_from_data(data)
        if summary.short_name and len(summary.short_name) > 4:
            raise ValueError("Short Name darf höchstens 4 Zeichen haben.")
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        return data

    def _selected_board_key(self) -> str | None:
        label = self.board_var.get()
        for key, profile in self.services.BOARD_PROFILES.items():
            if str(profile["label"]) == label:
                return key
        return None

    def validate(self) -> None:
        try:
            data = self._collect()
            summary = _summary_from_data(data)
            messagebox.showinfo(
                "Profil gültig",
                f"YAML ist gültig.\n\n{format_summary(summary)}\n\nBearbeitbare Felder: {len(self.fields)}",
                parent=self,
            )
        except Exception as exc:
            messagebox.showerror("Profil ungültig", str(exc), parent=self)

    def _write(self, requested_target: Path | None = None) -> None:
        data = self._collect()
        summary = _summary_from_data(data)
        profiles = Path(self.services.PATHS.profiles)
        archive_dir = profiles / "archive"
        profiles.mkdir(parents=True, exist_ok=True)
        archive_dir.mkdir(parents=True, exist_ok=True)

        if requested_target is not None:
            target = Path(requested_target)
        else:
            target = profiles / stable_profile_name(summary, self.source.suffix or ".yaml")

        target.parent.mkdir(parents=True, exist_ok=True)
        archived: list[Path] = []
        if self.source.exists():
            archived_source = _archive_copy(self.source, archive_dir)
            if archived_source:
                archived.append(archived_source)
        if target.exists() and target.resolve() != self.source.resolve():
            archived_target = _archive_copy(target, archive_dir)
            if archived_target:
                archived.append(archived_target)

        temp = target.with_suffix(target.suffix + ".tmp")
        temp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        yaml.safe_load(temp.read_text(encoding="utf-8"))
        temp.replace(target)

        try:
            source_resolved = self.source.resolve()
            target_resolved = target.resolve()
        except Exception:
            source_resolved = self.source
            target_resolved = target
        if source_resolved != target_resolved and self.source.exists() and self.source.parent.resolve() == profiles.resolve() and not self.source.name.startswith("."):
            try:
                self.source.unlink()
            except Exception:
                pass

        active = Path(self.services.PATHS.active_profile)
        shutil.copy2(target, active)
        board_key = self._selected_board_key()
        if board_key in self.services.BOARD_PROFILES:
            register_profile(target, board_key, summary, source="profile-editor")
            register_profile(active, board_key, summary, source=f"active-from:{target.name}")

        self.source = target
        self.original = copy.deepcopy(data)
        self.path_var.set(str(target))
        self.dirty_paths.clear()
        self._refresh_dirty()
        for path, (_old, var) in list(self.fields.items()):
            node: Any = data
            for key in path:
                if not isinstance(node, dict):
                    node = None
                    break
                node = node.get(key)
            self.fields[path] = (node, var)

        try:
            self.app.profile_path_var.set(str(target))
            self.app.profile_summary_var.set(format_summary(summary))
            if summary.long_name:
                self.app.long_name_var.set(summary.long_name)
            if summary.short_name:
                self.app.short_name_var.set(summary.short_name)
            self.app._append_log(
                f"PROFIL GESPEICHERT · {target.name} · Board={board_key or 'nicht zugeordnet'} · "
                f"{format_summary(summary)} · Archivkopien={len(archived)}"
            )
        except Exception:
            pass

        self.yaml_box.configure(state="normal")
        self.yaml_box.delete("1.0", "end")
        self.yaml_box.insert("1.0", yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
        self.yaml_box.configure(state="disabled")
        _emit(f"PROFILE EDITOR SAVE target={str(target)!r} board={board_key!r} archived={len(archived)}")
        messagebox.showinfo("Profil gespeichert", f"Profil gespeichert:\n{target}\n\nVorherige Fassung im Archiv: {'ja' if archived else 'nein'}", parent=self)

    def save(self) -> None:
        try:
            self._write()
        except Exception as exc:
            messagebox.showerror("Speichern fehlgeschlagen", str(exc), parent=self)

    def save_as(self) -> None:
        try:
            data = self._collect()
            summary = _summary_from_data(data)
            suggested = stable_profile_name(summary, self.source.suffix or ".yaml")
            selected = filedialog.asksaveasfilename(
                parent=self,
                title="Profil speichern unter",
                initialdir=str(self.services.PATHS.profiles),
                initialfile=suggested,
                defaultextension=".yaml",
                filetypes=[("YAML", "*.yaml *.yml"), ("Alle Dateien", "*.*")],
            )
            if selected:
                self._write(Path(selected))
        except Exception as exc:
            messagebox.showerror("Speichern fehlgeschlagen", str(exc), parent=self)

    def close_requested(self) -> None:
        if self._closing:
            return
        if self.dirty_paths:
            if not messagebox.askyesno("Änderungen verwerfen?", "Es gibt ungespeicherte Änderungen. Wirklich schließen?", parent=self):
                return
        self._closing = True
        self.destroy()


def _resolve_profile_path(app: Any, services: Any) -> Path | None:
    try:
        raw = str(app.profile_path_var.get() or "").strip()
    except Exception:
        raw = ""
    path = Path(raw) if raw and raw != "Kein Profil geladen" else Path(services.PATHS.active_profile)
    if path.exists() and path.is_file():
        return path
    active = Path(services.PATHS.active_profile)
    return active if active.exists() else None


def install(services: Any) -> None:
    """Add a structured, dropdown-aware profile editor to the main profile card."""
    original_root_init = ctk.CTk.__init__

    def root_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_root_init(self, *args, **kwargs)

        def patch_app() -> None:
            if getattr(self, "_jarnsen_profile_editor_installed", False):
                return
            anchor_button = None
            for widget in _walk(self):
                if _button_text(widget) in {"Profil auswählen", "Profil laden"}:
                    anchor_button = widget
                    break
            if anchor_button is None:
                try:
                    self.after(180, patch_app)
                except Exception:
                    pass
                return
            parent = getattr(anchor_button, "master", None)
            if parent is None:
                return

            def open_editor() -> None:
                source = _resolve_profile_path(self, services)
                if source is None:
                    messagebox.showwarning("Kein Profil", "Bitte zuerst ein Profil auswählen oder vom Master einlesen.", parent=self)
                    return
                try:
                    ProfileEditor(self, services, source)
                except Exception as exc:
                    messagebox.showerror("Profil-Editor", f"Profil konnte nicht geöffnet werden.\n\n{exc}", parent=self)

            button = ctk.CTkButton(
                parent,
                text="PROFIL BEARBEITEN",
                width=155,
                fg_color=("gray62", "gray30"),
                hover_color=("gray55", "gray36"),
                command=open_editor,
            )
            button.pack(side="left", padx=(10, 0))
            self.profile_edit_button = button
            self._jarnsen_profile_editor_installed = True
            _emit("PROFILE EDITOR UI installed structured-dropdowns=1 archive-on-save=1")

        try:
            self.after(760, patch_app)
        except Exception:
            pass

    ctk.CTk.__init__ = root_init
    _emit("PROFILE EDITOR layer installed")
