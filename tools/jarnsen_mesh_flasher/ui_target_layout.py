from __future__ import annotations

from pathlib import Path
from tkinter import messagebox
from typing import Any

import customtkinter as ctk

from _build_version import APP_VERSION


BUTTON_HEIGHT = 38
CARD_RADIUS = 12


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


def _text(widget: Any) -> str:
    try:
        return str(widget.cget("text") or "")
    except Exception:
        return ""


def _card(root: Any, *titles: str) -> Any | None:
    wanted = {title.casefold() for title in titles}
    for widget in _walk(root):
        if _text(widget).casefold() in wanted:
            return getattr(widget, "master", None)
    return None


def _button(root: Any, text: str) -> Any | None:
    if root is None:
        return None
    wanted = text.casefold()
    for widget in _walk(root):
        if isinstance(widget, ctk.CTkButton) and _text(widget).casefold() == wanted:
            return widget
    return None


def _label_starts(root: Any, prefix: str) -> Any | None:
    wanted = prefix.casefold()
    for widget in _walk(root):
        if isinstance(widget, ctk.CTkLabel) and _text(widget).casefold().startswith(wanted):
            return widget
    return None


def _forget(widget: Any) -> None:
    if widget is None:
        return
    for method in ("pack_forget", "grid_forget", "place_forget"):
        try:
            getattr(widget, method)()
        except Exception:
            pass


def _command(widget: Any):
    command = getattr(widget, "_command", None)
    return command if callable(command) else None


def _rename(card: Any, old_titles: tuple[str, ...], new_title: str) -> None:
    for widget in _walk(card):
        if _text(widget) in old_titles:
            try:
                widget.configure(text=new_title)
            except Exception:
                pass
            return


def _service_bar(device_card: Any) -> Any | None:
    required = {"SERVICE", "NODE-LOG USB", "INFO LESEN", "NEUSTART"}
    try:
        children = device_card.winfo_children()
    except Exception:
        return None
    for child in children:
        if required.issubset({_text(widget) for widget in _walk(child)}):
            return child
    return None


def _status_frame(device_card: Any, compare_var: Any) -> Any | None:
    compare_name = str(compare_var) if compare_var is not None else ""
    if compare_name:
        for widget in _walk(device_card):
            if not isinstance(widget, ctk.CTkLabel):
                continue
            try:
                variable_name = str(widget.cget("textvariable") or "")
            except Exception:
                variable_name = ""
            if variable_name == compare_name:
                return getattr(widget, "master", None)
    for frame in _walk(device_card):
        if not isinstance(frame, ctk.CTkFrame):
            continue
        labels = {_text(child) for child in frame.winfo_children()}
        if "Firmware" in labels and "GitHub" in labels:
            return frame
    return None


def _strip_prefix(value: str, *prefixes: str) -> str:
    text = str(value or "").strip()
    lowered = text.casefold()
    for prefix in prefixes:
        if lowered.startswith(prefix.casefold()):
            return text[len(prefix):].strip()
    return text


def install(services: Any) -> None:
    """Apply the approved JARNSEN MESH Flasher dashboard from the visual reference."""
    original_root_init = ctk.CTk.__init__

    def root_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_root_init(self, *args, **kwargs)

        def patch_app(attempt: int = 0) -> None:
            if getattr(self, "_jarnsen_target_layout_installed", False):
                return
            if not (
                hasattr(self, "body")
                and hasattr(self, "log_box")
                and hasattr(self, "flash_button")
                and hasattr(self, "progress")
                and getattr(self, "_jarnsen_final_layout_installed", False)
                and getattr(self, "_jarnsen_dashboard_cleanup_installed", False)
            ):
                if attempt < 50:
                    self.after(150, patch_app, attempt + 1)
                return

            device = _card(self, "1 · GERÄT")
            profile = _card(self, "2 · GRUNDEINSTELLUNGEN")
            firmware = _card(self, "3 · FIRMWARE", "4 · FIRMWARE")
            identity = _card(self, "4 · IDENTITÄT", "4 · GERÄTENAME", "3 · IDENTITÄT")
            automatic = _card(self, "5 · AUTOMATISCHER ABLAUF")
            protocol = _card(self, "PROTOKOLL")
            source_service = _service_bar(device) if device else None

            if not all((device, profile, firmware, identity, automatic, protocol, source_service)):
                if attempt < 50:
                    self.after(150, patch_app, attempt + 1)
                return

            source_buttons = [
                _button(source_service, "NODE-LOG USB"),
                _button(source_service, "INFO LESEN"),
                _button(source_service, "NEUSTART"),
            ]
            profile_buttons = [
                _button(profile, "MASTER EINLESEN"),
                _button(profile, "PROFIL AUSWÄHLEN"),
                _button(profile, "NUR PROFIL SCHREIBEN"),
                _button(profile, "PROFIL BEARBEITEN"),
            ]
            firmware_buttons = [
                _button(firmware, "NEUESTE PRÜFEN"),
                _button(firmware, "NUR FIRMWARE UPDATEN"),
                _button(firmware, "DATEI VOM PC"),
            ]
            if not all(source_buttons) or not all(profile_buttons) or not all(firmware_buttons):
                if attempt < 50:
                    self.after(150, patch_app, attempt + 1)
                return

            self._jarnsen_target_layout_installed = True

            # Titles and compact card styling follow the approved reference.
            _rename(identity, ("4 · IDENTITÄT", "4 · GERÄTENAME", "3 · IDENTITÄT"), "3 · IDENTITÄT")
            _rename(firmware, ("3 · FIRMWARE", "4 · FIRMWARE"), "4 · FIRMWARE")
            for card in (device, profile, identity, firmware, automatic, protocol):
                try:
                    card.configure(corner_radius=CARD_RADIUS)
                except Exception:
                    pass

            # ------------------------------------------------------------------
            # Top firmware line: one compact status row with a real Details popup.
            # ------------------------------------------------------------------
            installed_var = getattr(self, "installed_firmware_var", None)
            available_var = getattr(self, "available_firmware_var", None)
            compare_var = getattr(self, "firmware_compare_var", None)
            status = _status_frame(device, compare_var)
            compact_installed = ctk.StringVar(value="")
            compact_available = ctk.StringVar(value="")
            badge_var = ctk.StringVar(value="WIRD GEPRÜFT")

            if status is not None:
                for child in list(status.winfo_children()):
                    _forget(child)
                try:
                    status.configure(
                        corner_radius=9,
                        border_width=1,
                        border_color="#4B5563",
                        fg_color=("gray91", "gray18"),
                    )
                except Exception:
                    pass
                for column in range(7):
                    status.grid_columnconfigure(column, weight=0)
                status.grid_columnconfigure(1, weight=1)
                status.grid_columnconfigure(4, weight=1)

                ctk.CTkLabel(
                    status,
                    text="Installierte Firmware:",
                    font=ctk.CTkFont(size=11),
                    text_color=("gray40", "gray72"),
                ).grid(row=0, column=0, sticky="w", padx=(14, 8), pady=9)
                ctk.CTkLabel(
                    status,
                    textvariable=compact_installed,
                    font=ctk.CTkFont(size=11, weight="bold"),
                    anchor="w",
                ).grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=9)
                ctk.CTkLabel(
                    status,
                    text="|",
                    text_color=("gray55", "gray55"),
                ).grid(row=0, column=2, padx=(0, 10), pady=9)
                ctk.CTkLabel(
                    status,
                    text="Verfügbare Firmware:",
                    font=ctk.CTkFont(size=11),
                    text_color=("gray40", "gray72"),
                ).grid(row=0, column=3, sticky="e", padx=(0, 8), pady=9)
                ctk.CTkLabel(
                    status,
                    textvariable=compact_available,
                    font=ctk.CTkFont(size=11, weight="bold"),
                    anchor="w",
                ).grid(row=0, column=4, sticky="w", padx=(0, 10), pady=9)

                firmware_badge = ctk.CTkLabel(
                    status,
                    textvariable=badge_var,
                    width=136,
                    height=30,
                    corner_radius=7,
                    fg_color="#374151",
                    text_color="white",
                    font=ctk.CTkFont(size=10, weight="bold"),
                )
                firmware_badge.grid(row=0, column=5, padx=(4, 12), pady=7)

                def show_details() -> None:
                    installed = str(installed_var.get() if installed_var is not None else "unbekannt")
                    available = str(available_var.get() if available_var is not None else "unbekannt")
                    comparison = str(compare_var.get() if compare_var is not None else "")
                    messagebox.showinfo(
                        "Firmwaredetails",
                        f"{installed}\n\n{available}\n\nStatus: {comparison or 'noch nicht geprüft'}",
                        parent=self,
                    )

                ctk.CTkButton(
                    status,
                    text="Details  ▾",
                    width=92,
                    height=30,
                    corner_radius=7,
                    fg_color=("gray72", "gray28"),
                    hover_color=("gray65", "gray35"),
                    command=show_details,
                ).grid(row=0, column=6, padx=(0, 10), pady=7)

                def refresh_status(*_args: Any) -> None:
                    raw_installed = str(installed_var.get() if installed_var is not None else "")
                    raw_available = str(available_var.get() if available_var is not None else "")
                    raw_compare = str(compare_var.get() if compare_var is not None else "").strip()
                    compact_installed.set(
                        _strip_prefix(raw_installed, "Installiert:", "Firmware:")
                        or "wird gelesen"
                    )
                    compact_available.set(
                        _strip_prefix(raw_available, "Verfügbar:", "GitHub:")
                        or "noch nicht geprüft"
                    )
                    upper = raw_compare.upper()
                    if upper.startswith("AKTUELL"):
                        badge_var.set("AKTUELL")
                        bg, border = "#166534", "#22C55E"
                    elif (
                        upper.startswith("UPDATE VERFÜGBAR")
                        or upper.startswith("ANDERE FIRMWARE")
                        or upper.startswith("JARNSEN-MESH VERFÜGBAR")
                    ):
                        badge_var.set("UPDATE EMPFOHLEN")
                        bg, border = "#D97706", "#F59E0B"
                    elif upper.startswith("NEUER ALS GITHUB"):
                        badge_var.set("NODE NEUER")
                        bg, border = "#1E4E79", "#60A5FA"
                    else:
                        badge_var.set("WIRD GEPRÜFT")
                        bg, border = "#374151", "#6B7280"
                    try:
                        firmware_badge.configure(fg_color=bg)
                        status.configure(border_color=border)
                    except Exception:
                        pass

                for variable in (installed_var, available_var, compare_var):
                    if variable is not None:
                        try:
                            variable.trace_add("write", refresh_status)
                        except Exception:
                            pass
                refresh_status()

            # ------------------------------------------------------------------
            # Profile card: four equal actions in one row, exactly as in reference.
            # ------------------------------------------------------------------
            profile_parent = getattr(profile_buttons[0], "master", None)
            if profile_parent is not None:
                for button in profile_buttons:
                    _forget(button)
                for column in range(4):
                    profile_parent.grid_columnconfigure(
                        column,
                        weight=1,
                        uniform="profile-reference",
                        minsize=0,
                    )
                profile_texts = (
                    "⇩  MASTER\nEINLESEN",
                    "▣  PROFIL\nAUSWÄHLEN",
                    "⇧  NUR PROFIL\nSCHREIBEN",
                    "✎  PROFIL\nBEARBEITEN",
                )
                for index, (button, text) in enumerate(zip(profile_buttons, profile_texts)):
                    button.configure(
                        text=text,
                        height=52,
                        corner_radius=8,
                        font=ctk.CTkFont(size=10, weight="bold"),
                    )
                    button.grid(
                        row=0,
                        column=index,
                        sticky="ew",
                        padx=(0, 5) if index == 0 else ((4, 4) if index < 3 else (5, 0)),
                        pady=0,
                    )

            # One compact summary line: Long/Short/Role plus active profile filename.
            summary_var = getattr(self, "profile_summary_var", None)
            path_var = getattr(self, "profile_path_var", None)
            profile_compact_var = ctk.StringVar(value="")

            summary_widget = None
            path_widget = None
            summary_name = str(summary_var) if summary_var is not None else ""
            path_name = str(path_var) if path_var is not None else ""
            for widget in _walk(profile):
                if not isinstance(widget, ctk.CTkLabel):
                    continue
                try:
                    variable_name = str(widget.cget("textvariable") or "")
                except Exception:
                    variable_name = ""
                if summary_name and variable_name == summary_name:
                    summary_widget = widget
                elif path_name and variable_name == path_name:
                    path_widget = widget
            _forget(summary_widget)
            _forget(path_widget)

            def refresh_profile_compact(*_args: Any) -> None:
                summary = str(summary_var.get() if summary_var is not None else "").strip()
                raw_path = str(path_var.get() if path_var is not None else "").strip()
                filename = Path(raw_path).name if raw_path and raw_path != "Kein Profil geladen" else "–"
                if summary:
                    profile_compact_var.set(f"{summary}   ·   Profil: {filename}")
                else:
                    profile_compact_var.set(f"Profil: {filename}")

            compact_profile_label = ctk.CTkLabel(
                profile,
                textvariable=profile_compact_var,
                anchor="w",
                justify="left",
                font=ctk.CTkFont(size=10, weight="bold"),
            )
            try:
                if profile_parent is not None:
                    compact_profile_label.pack(fill="x", padx=18, pady=(0, 8), before=profile_parent)
                else:
                    compact_profile_label.pack(fill="x", padx=18, pady=(0, 8))
            except Exception:
                compact_profile_label.pack(fill="x", padx=18, pady=(0, 8))

            for variable in (summary_var, path_var):
                if variable is not None:
                    try:
                        variable.trace_add("write", refresh_profile_compact)
                    except Exception:
                        pass
            refresh_profile_compact()

            # ------------------------------------------------------------------
            # Identity: compact inputs plus green state line from the reference.
            # ------------------------------------------------------------------
            identity_state = ctk.StringVar(value="✓  Node aktuell   |   Wird beim nächsten Flash übernommen")
            identity_bar = ctk.CTkFrame(
                identity,
                corner_radius=7,
                fg_color=("#DCFCE7", "#143B2C"),
                border_width=1,
                border_color=("#86EFAC", "#1F6A48"),
            )
            identity_bar.pack(fill="x", padx=18, pady=(0, 10))
            ctk.CTkLabel(
                identity_bar,
                textvariable=identity_state,
                anchor="w",
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color=("#166534", "#86EFAC"),
            ).pack(side="left", fill="x", expand=True, padx=10, pady=5)
            ctk.CTkLabel(
                identity_bar,
                text="ⓘ",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=("#166534", "#86EFAC"),
            ).pack(side="right", padx=(5, 10), pady=5)

            baseline = {
                "long": str(getattr(self, "long_name_var").get() or ""),
                "short": str(getattr(self, "short_name_var").get() or ""),
            }

            def refresh_identity(*_args: Any) -> None:
                current_long = str(self.long_name_var.get() or "")
                current_short = str(self.short_name_var.get() or "")
                if current_long == baseline["long"] and current_short == baseline["short"]:
                    identity_state.set("✓  Node aktuell   |   Wird beim nächsten Flash übernommen")
                else:
                    identity_state.set("●  Änderung vorgemerkt   |   Wird beim nächsten Flash übernommen")

            try:
                self.long_name_var.trace_add("write", refresh_identity)
                self.short_name_var.trace_add("write", refresh_identity)
            except Exception:
                pass

            # ------------------------------------------------------------------
            # SERVICE: own compact left card, three equal buttons.
            # ------------------------------------------------------------------
            service_commands = [_command(button) for button in source_buttons]
            _forget(source_service)
            service = ctk.CTkFrame(self.body, corner_radius=CARD_RADIUS)
            ctk.CTkLabel(
                service,
                text="🔧  SERVICE",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=("gray35", "gray75"),
            ).pack(anchor="w", padx=18, pady=(11, 6))
            service_row = ctk.CTkFrame(service, fg_color="transparent")
            service_row.pack(fill="x", padx=18, pady=(0, 10))
            for column in range(3):
                service_row.grid_columnconfigure(column, weight=1, uniform="service-reference")
            service_labels = ("▧  NODE-LOG USB", "ⓘ  INFO LESEN", "⟳  NEUSTART")
            replacement_service_buttons: list[Any] = []
            for index, (label, command) in enumerate(zip(service_labels, service_commands)):
                if not callable(command):
                    continue
                primary = index == 0
                button = ctk.CTkButton(
                    service_row,
                    text=label,
                    command=command,
                    height=BUTTON_HEIGHT,
                    corner_radius=8,
                    font=ctk.CTkFont(size=10, weight="bold"),
                    fg_color="#0B72E7" if primary else ("gray72", "gray28"),
                    hover_color="#0862C6" if primary else ("gray65", "gray35"),
                )
                button.grid(
                    row=0,
                    column=index,
                    sticky="ew",
                    padx=(0, 5) if index == 0 else ((4, 4) if index == 1 else (5, 0)),
                )
                replacement_service_buttons.append(button)
                if index == 0:
                    self.usb_log_button = button

            managed_buttons = getattr(self, "_jarnsen_polished_buttons", None)
            if isinstance(managed_buttons, list):
                managed_buttons.extend(replacement_service_buttons)

            # ------------------------------------------------------------------
            # Firmware: compact baud + three actions, plus the lower status line.
            # ------------------------------------------------------------------
            firmware_texts = ("☁  NEUESTE PRÜFEN", "⇧  NUR FIRMWARE UPDATEN", "▧  DATEI VOM PC")
            for index, (button, text) in enumerate(zip(firmware_buttons, firmware_texts)):
                button.configure(
                    text=text,
                    height=BUTTON_HEIGHT,
                    corner_radius=8,
                    font=ctk.CTkFont(size=10, weight="bold"),
                )
                if index == 1:
                    try:
                        button.configure(fg_color="#D97706", hover_color="#B45309")
                    except Exception:
                        pass

            firmware_var = getattr(self, "firmware_var", None)
            if firmware_var is not None:
                variable_name = str(firmware_var)
                for widget in _walk(firmware):
                    if not isinstance(widget, ctk.CTkLabel):
                        continue
                    try:
                        if str(widget.cget("textvariable") or "") == variable_name:
                            _forget(widget)
                    except Exception:
                        pass

            fw_line = ctk.CTkFrame(firmware, fg_color="transparent")
            fw_line.pack(fill="x", padx=18, pady=(0, 9))
            fw_line.grid_columnconfigure(0, weight=1)
            fw_line.grid_columnconfigure(1, weight=0)

            fw_summary = ctk.StringVar(value="Aktuell: wird gelesen   |   Neueste: noch nicht geprüft")
            ctk.CTkLabel(
                fw_line,
                textvariable=fw_summary,
                anchor="w",
                font=ctk.CTkFont(size=10),
            ).grid(row=0, column=0, sticky="ew")
            fw_badge = ctk.CTkLabel(
                fw_line,
                text="Wird geprüft",
                width=125,
                height=27,
                corner_radius=7,
                fg_color="#374151",
                text_color="white",
                font=ctk.CTkFont(size=10, weight="bold"),
            )
            fw_badge.grid(row=0, column=1, padx=(8, 0))

            def refresh_firmware_footer(*_args: Any) -> None:
                raw_installed = str(installed_var.get() if installed_var is not None else "")
                raw_available = str(available_var.get() if available_var is not None else "")
                raw_compare = str(compare_var.get() if compare_var is not None else "").strip()
                current = _strip_prefix(raw_installed, "Installiert:", "Firmware:") or "wird gelesen"
                latest = _strip_prefix(raw_available, "Verfügbar:", "GitHub:") or "noch nicht geprüft"
                fw_summary.set(f"Aktuell: {current}   |   Neueste: {latest}")
                upper = raw_compare.upper()
                if upper.startswith("AKTUELL"):
                    text, bg = "Aktuell", "#166534"
                elif (
                    upper.startswith("UPDATE VERFÜGBAR")
                    or upper.startswith("ANDERE FIRMWARE")
                    or upper.startswith("JARNSEN-MESH VERFÜGBAR")
                ):
                    text, bg = "⚠  Update verfügbar", "#9A4D00"
                elif upper.startswith("NEUER ALS GITHUB"):
                    text, bg = "Node neuer", "#1E4E79"
                else:
                    text, bg = "Wird geprüft", "#374151"
                try:
                    fw_badge.configure(text=text, fg_color=bg)
                except Exception:
                    pass

            for variable in (installed_var, available_var, compare_var):
                if variable is not None:
                    try:
                        variable.trace_add("write", refresh_firmware_footer)
                    except Exception:
                        pass
            refresh_firmware_footer()

            # ------------------------------------------------------------------
            # Automatic flow: left lower card, stage line and full-width action.
            # ------------------------------------------------------------------
            old_description = _label_starts(automatic, "Backup →")
            if old_description is not None:
                _forget(old_description)

            mode_switch = next(
                (widget for widget in _walk(automatic) if isinstance(widget, ctk.CTkSegmentedButton)),
                None,
            )
            timeline = ctk.CTkFrame(automatic, fg_color="transparent")
            stage_names = ("Backup", "Firmware", "Grundeinst.", "Namen", "Neustart", "Prüfung")
            stage_labels: list[Any] = []
            for column in range(len(stage_names)):
                timeline.grid_columnconfigure(column, weight=1, uniform="flash-stages")
            for index, stage in enumerate(stage_names):
                label = ctk.CTkLabel(
                    timeline,
                    text=("●  " if index == 0 else "○  ") + stage,
                    font=ctk.CTkFont(size=9),
                    text_color="#3B9CFF" if index == 0 else ("gray45", "gray60"),
                )
                label.grid(row=0, column=index, sticky="w", padx=(0, 4))
                stage_labels.append(label)

            try:
                if mode_switch is not None:
                    timeline.pack(fill="x", padx=18, pady=(2, 6), after=mode_switch)
                else:
                    timeline.pack(fill="x", padx=18, pady=(2, 6))
            except Exception:
                timeline.pack(fill="x", padx=18, pady=(2, 6))

            flash_button = self.flash_button
            try:
                flash_button.configure(
                    text="▶  AUTOMATISCH FLASHEN",
                    height=40,
                    corner_radius=8,
                    font=ctk.CTkFont(size=12, weight="bold"),
                )
            except Exception:
                pass

            def show_single_reference() -> None:
                mode = getattr(self, "operation_mode", None)
                try:
                    if mode is not None and str(mode.get()) != "Einzelgerät":
                        _forget(timeline)
                        return
                except Exception:
                    pass
                if old_description is not None:
                    _forget(old_description)
                _forget(timeline)
                try:
                    if mode_switch is not None:
                        timeline.pack(fill="x", padx=18, pady=(2, 6), after=mode_switch)
                    else:
                        timeline.pack(fill="x", padx=18, pady=(2, 6))
                except Exception:
                    timeline.pack(fill="x", padx=18, pady=(2, 6))
                _forget(flash_button)
                try:
                    flash_button.pack(fill="x", padx=18, pady=(0, 10), after=self.progress)
                except Exception:
                    flash_button.pack(fill="x", padx=18, pady=(0, 10))

            show_single_reference()
            mode_var = getattr(self, "operation_mode", None)
            if mode_var is not None:
                def mode_changed(*_args: Any) -> None:
                    try:
                        if str(mode_var.get()) == "Einzelgerät":
                            self.after_idle(show_single_reference)
                        else:
                            _forget(timeline)
                    except Exception:
                        pass
                try:
                    mode_var.trace_add("write", mode_changed)
                except Exception:
                    pass

            previous_set_progress = self._set_progress

            def target_set_progress(value: float, text: str) -> None:
                previous_set_progress(value, text)
                fraction = max(0.0, min(1.0, float(value)))
                if fraction < 0.35:
                    active = 0
                elif fraction < 0.79:
                    active = 1
                elif fraction < 0.88:
                    active = 2
                elif fraction < 0.94:
                    active = 3
                elif fraction < 0.98:
                    active = 4
                else:
                    active = 5

                def update_stage() -> None:
                    for index, label in enumerate(stage_labels):
                        if index < active:
                            label.configure(
                                text="●  " + stage_names[index],
                                text_color="#22C55E",
                            )
                        elif index == active:
                            label.configure(
                                text="●  " + stage_names[index],
                                text_color="#3B9CFF",
                            )
                        else:
                            label.configure(
                                text="○  " + stage_names[index],
                                text_color=("gray45", "gray60"),
                            )

                try:
                    self.after(0, update_stage)
                except Exception:
                    pass

            self._set_progress = target_set_progress

            # ------------------------------------------------------------------
            # Hints: dedicated right lower card from the approved reference.
            # ------------------------------------------------------------------
            hints = ctk.CTkFrame(self.body, corner_radius=CARD_RADIUS)
            ctk.CTkLabel(
                hints,
                text="💡  Hinweise",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=("gray35", "gray78"),
            ).pack(anchor="w", padx=18, pady=(11, 5))
            hint_text = (
                "• Vor dem Flashen wird automatisch ein Backup der aktuellen Konfiguration erstellt.\n"
                "• Alte Profilversionen werden beim Speichern automatisch archiviert.\n"
                "• Über „Node-Log USB“ kann der Log direkt vom Gerät geladen werden.\n"
                "• Für erste OTA-Installation ggf. serielle Verbindung verwenden.\n"
                "• Weitere Optionen im Profil-Editor (inkl. YAML-Ansicht)."
            )
            ctk.CTkLabel(
                hints,
                text=hint_text,
                anchor="w",
                justify="left",
                font=ctk.CTkFont(size=10),
                wraplength=700,
            ).pack(fill="x", padx=18, pady=(0, 10))

            # ------------------------------------------------------------------
            # Protocol: full width, toolbar on top, no redundant path line.
            # ------------------------------------------------------------------
            for widget in _walk(protocol):
                if isinstance(widget, ctk.CTkLabel) and _text(widget).startswith("Log: "):
                    _forget(widget)

            log_toggle = _button(protocol, "PROTOKOLL GROSS") or _button(protocol, "PROTOKOLL KOMPAKT")
            if log_toggle is not None:
                try:
                    log_toggle.configure(height=30, corner_radius=7)
                except Exception:
                    pass
            for label in ("KOPIEREN", "LOGORDNER", "PROTOKOLL LEEREN"):
                button = _button(protocol, label)
                if button is not None:
                    try:
                        button.configure(height=30, corner_radius=7)
                    except Exception:
                        pass

            # ------------------------------------------------------------------
            # Final grid = exact requested visual arrangement:
            # full device
            # profile | identity
            # service | firmware
            # automatic | hints
            # protocol across both columns
            # ------------------------------------------------------------------
            self.body.grid_columnconfigure(0, weight=1, uniform="target-reference")
            self.body.grid_columnconfigure(1, weight=1, uniform="target-reference")

            device.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=5, pady=(0, 7))
            profile.grid(row=1, column=0, sticky="nsew", padx=(5, 4), pady=(0, 7))
            identity.grid(row=1, column=1, sticky="nsew", padx=(4, 5), pady=(0, 7))
            service.grid(row=2, column=0, sticky="nsew", padx=(5, 4), pady=(0, 7))
            firmware.grid(row=2, column=1, sticky="nsew", padx=(4, 5), pady=(0, 7))
            automatic.grid(row=3, column=0, sticky="nsew", padx=(5, 4), pady=(0, 7))
            hints.grid(row=3, column=1, sticky="nsew", padx=(4, 5), pady=(0, 7))
            protocol.grid(row=4, column=0, columnspan=2, sticky="nsew", padx=5, pady=(0, 6))

            self.body.grid_rowconfigure(0, weight=0, minsize=148)
            self.body.grid_rowconfigure(1, weight=0, minsize=132)
            self.body.grid_rowconfigure(2, weight=0, minsize=102)
            self.body.grid_rowconfigure(3, weight=0, minsize=178)
            self.body.grid_rowconfigure(4, weight=1, minsize=180)
            try:
                self.log_box.configure(height=175, corner_radius=8)
            except Exception:
                pass

            if log_toggle is not None:
                expanded = {"value": False}

                def toggle_log() -> None:
                    expanded["value"] = not expanded["value"]
                    try:
                        if expanded["value"]:
                            self.body.grid_rowconfigure(4, weight=3, minsize=330)
                            self.log_box.configure(height=300)
                            log_toggle.configure(text="PROTOKOLL KOMPAKT")
                        else:
                            self.body.grid_rowconfigure(4, weight=1, minsize=180)
                            self.log_box.configure(height=175)
                            log_toggle.configure(text="PROTOKOLL GROSS")
                    except Exception:
                        pass

                try:
                    log_toggle.configure(command=toggle_log)
                except Exception:
                    pass

            # Footer from the visual reference. It consumes only one compact line.
            if not getattr(self, "_jarnsen_reference_footer", False):
                self._jarnsen_reference_footer = True
                footer = ctk.CTkFrame(self, fg_color="transparent", height=22)
                footer.pack(side="bottom", fill="x", padx=24, pady=(0, 5))
                ctk.CTkLabel(
                    footer,
                    text=f"JARNSEN MESH Flasher   ·   {APP_VERSION}",
                    font=ctk.CTkFont(size=9),
                    text_color=("gray40", "gray60"),
                ).pack(side="left")
                ctk.CTkLabel(
                    footer,
                    text="© 2026 JARNSEN   |",
                    font=ctk.CTkFont(size=9),
                    text_color=("gray40", "gray60"),
                ).pack(side="right", padx=(0, 8))
                ctk.CTkLabel(
                    footer,
                    textvariable=self.status_var,
                    font=ctk.CTkFont(size=9, weight="bold"),
                ).pack(side="right", padx=(0, 10))

            try:
                self._append_log(
                    "UI · Referenz-Layout aktiv · Gerät vollbreit · Profil/Identität · "
                    "Service/Firmware · Automatik/Hinweise · Protokoll vollbreit"
                )
            except Exception:
                pass
            _emit(
                "UI TARGET LAYOUT installed reference=approved "
                "rows=device,profile-identity,service-firmware,auto-hints,protocol "
                "profile=1x4 firmware=baud+3 timeline=6 footer=1"
            )

        try:
            self.after(2350, patch_app)
        except Exception:
            pass

    ctk.CTk.__init__ = root_init
    _emit("UI TARGET LAYOUT layer installed reference=approved")
