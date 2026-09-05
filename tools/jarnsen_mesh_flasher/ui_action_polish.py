from __future__ import annotations

from typing import Any

import customtkinter as ctk


BUTTON_HEIGHT = 36
SMALL_BUTTON_HEIGHT = 34
PRIMARY_HEIGHT = 44


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


def _find_card(root: Any, titles: tuple[str, ...]) -> Any | None:
    wanted = {title.casefold() for title in titles}
    for widget in _walk(root):
        if _text(widget).casefold() in wanted:
            return getattr(widget, "master", None)
    return None


def _find_button(root: Any, text: str) -> Any | None:
    wanted = text.casefold()
    for widget in _walk(root):
        if isinstance(widget, ctk.CTkButton) and _text(widget).casefold() == wanted:
            command = getattr(widget, "_command", None)
            if callable(command):
                return widget
    return None


def _forget(widget: Any) -> None:
    for method_name in ("pack_forget", "grid_forget", "place_forget"):
        try:
            getattr(widget, method_name)()
        except Exception:
            pass


def _style_button(button: Any, *, primary: bool = False, neutral: bool = False) -> None:
    kwargs: dict[str, Any] = {
        "height": BUTTON_HEIGHT,
        "corner_radius": 8,
        "font": ctk.CTkFont(size=11, weight="bold"),
    }
    if primary:
        kwargs.update(
            fg_color="#2376B7",
            hover_color="#1C659E",
            text_color="white",
        )
    elif neutral:
        kwargs.update(
            fg_color=("gray74", "gray28"),
            hover_color=("gray66", "gray34"),
        )
    try:
        button.configure(**kwargs)
    except Exception:
        pass


def _button_command(button: Any):
    command = getattr(button, "_command", None)
    return command if callable(command) else None


def _clone_button(parent: Any, source: Any, text: str, *, primary: bool = False, neutral: bool = False) -> Any | None:
    command = _button_command(source)
    if not callable(command):
        return None
    button = ctk.CTkButton(parent, text=text, command=command)
    _style_button(button, primary=primary, neutral=neutral)
    return button


def _compact_parent_if_empty(parent: Any, hidden: set[Any]) -> None:
    try:
        children = [child for child in parent.winfo_children() if child not in hidden]
    except Exception:
        return
    # If a runtime layer created a row containing only a button that we replaced,
    # remove the now-empty row so it cannot consume vertical space.
    if not children:
        _forget(parent)


def install(services: Any) -> None:
    """Final dashboard pass: uniform actions, readable spacing and strong firmware state."""
    original_root_init = ctk.CTk.__init__

    def root_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_root_init(self, *args, **kwargs)

        def patch_app() -> None:
            if getattr(self, "_jarnsen_action_polish_installed", False):
                return
            required = (
                "body",
                "_set_busy",
                "_append_log",
            )
            if not all(hasattr(self, name) for name in required):
                try:
                    self.after(220, patch_app)
                except Exception:
                    pass
                return

            profile_card = _find_card(self, ("2 · GRUNDEINSTELLUNGEN",))
            firmware_card = _find_card(self, ("3 · FIRMWARE",))
            device_card = _find_card(self, ("1 · GERÄT",))
            action_card = _find_card(self, ("5 · AUTOMATISCHER ABLAUF",))
            if not all((profile_card, firmware_card, device_card, action_card)):
                try:
                    self.after(260, patch_app)
                except Exception:
                    pass
                return

            # Wait for the late runtime layers (profile editor, local firmware,
            # firmware-only, service bar and firmware comparison) to finish.
            expected = (
                _find_button(profile_card, "PROFIL BEARBEITEN"),
                _find_button(profile_card, "NUR PROFIL SCHREIBEN"),
                _find_button(firmware_card, "NUR FIRMWARE UPDATEN"),
                _find_button(firmware_card, "Datei vom PC auswählen"),
            )
            if not all(expected):
                try:
                    self.after(260, patch_app)
                except Exception:
                    pass
                return

            self._jarnsen_action_polish_installed = True
            managed_busy_buttons: list[Any] = []

            # Give the left cards enough natural height for two clean action rows,
            # while keeping the protocol compact enough for a Full-HD desktop.
            try:
                self.body.grid_rowconfigure(0, minsize=188)
                self.body.grid_rowconfigure(1, minsize=182)
                self.body.grid_rowconfigure(2, minsize=178)
                self.body.grid_rowconfigure(3, minsize=150)
            except Exception:
                pass

            # ------------------------------------------------------------------
            # Profile actions: one 2x2 block with equal button sizes.
            # ------------------------------------------------------------------
            profile_specs = (
                ("Vom Master einlesen", "MASTER EINLESEN", False),
                ("Profil auswählen", "PROFIL AUSWÄHLEN", False),
                ("NUR PROFIL SCHREIBEN", "NUR PROFIL SCHREIBEN", True),
                ("PROFIL BEARBEITEN", "PROFIL BEARBEITEN", False),
            )
            original_profile_buttons: list[Any] = []
            profile_commands: list[tuple[str, Any, bool]] = []
            for old_text, new_text, primary in profile_specs:
                button = _find_button(profile_card, old_text)
                if button is not None:
                    original_profile_buttons.append(button)
                    command = _button_command(button)
                    if callable(command):
                        profile_commands.append((new_text, command, primary))

            profile_anchor = getattr(original_profile_buttons[0], "master", None) if original_profile_buttons else None
            for button in original_profile_buttons:
                _forget(button)

            profile_actions = ctk.CTkFrame(profile_card, fg_color="transparent")
            profile_actions.grid_columnconfigure(0, weight=1, uniform="profile-actions")
            profile_actions.grid_columnconfigure(1, weight=1, uniform="profile-actions")
            try:
                if profile_anchor is not None:
                    profile_actions.pack(fill="x", padx=18, pady=(0, 12), before=profile_anchor)
                else:
                    profile_actions.pack(fill="x", padx=18, pady=(0, 12))
            except Exception:
                profile_actions.pack(fill="x", padx=18, pady=(0, 12))

            for index, (label, command, primary) in enumerate(profile_commands):
                button = ctk.CTkButton(profile_actions, text=label, command=command)
                _style_button(button, primary=primary, neutral=not primary)
                button.grid(
                    row=index // 2,
                    column=index % 2,
                    sticky="ew",
                    padx=(0, 6) if index % 2 == 0 else (6, 0),
                    pady=(0, 7) if index < 2 else (0, 0),
                )
                managed_busy_buttons.append(button)
            if profile_anchor is not None:
                _compact_parent_if_empty(profile_anchor, set(original_profile_buttons))

            # ------------------------------------------------------------------
            # Firmware actions: three equal buttons in one row. Flash baud remains
            # as a separate, clearly readable setting underneath.
            # ------------------------------------------------------------------
            firmware_specs = (
                ("Neueste Firmware prüfen", "NEUESTE PRÜFEN", False),
                ("NUR FIRMWARE UPDATEN", "NUR FIRMWARE UPDATEN", True),
                ("Datei vom PC auswählen", "DATEI VOM PC", False),
            )
            original_firmware_buttons: list[Any] = []
            firmware_commands: list[tuple[str, Any, bool]] = []
            for old_text, new_text, primary in firmware_specs:
                button = _find_button(firmware_card, old_text)
                if button is not None:
                    original_firmware_buttons.append(button)
                    command = _button_command(button)
                    if callable(command):
                        firmware_commands.append((new_text, command, primary))

            check_button = _find_button(firmware_card, "Neueste Firmware prüfen")
            check_anchor = check_button
            parents = {getattr(button, "master", None) for button in original_firmware_buttons}
            for button in original_firmware_buttons:
                _forget(button)

            firmware_actions = ctk.CTkFrame(firmware_card, fg_color="transparent")
            for column in range(3):
                firmware_actions.grid_columnconfigure(column, weight=1, uniform="firmware-actions")
            try:
                if check_anchor is not None:
                    firmware_actions.pack(fill="x", padx=18, pady=(0, 9), before=check_anchor)
                else:
                    firmware_actions.pack(fill="x", padx=18, pady=(0, 9))
            except Exception:
                firmware_actions.pack(fill="x", padx=18, pady=(0, 9))

            firmware_update_button = None
            for index, (label, command, primary) in enumerate(firmware_commands):
                button = ctk.CTkButton(firmware_actions, text=label, command=command)
                _style_button(button, primary=primary, neutral=not primary)
                button.grid(
                    row=0,
                    column=index,
                    sticky="ew",
                    padx=(0, 5) if index == 0 else ((5, 5) if index == 1 else (5, 0)),
                )
                managed_busy_buttons.append(button)
                if label == "NUR FIRMWARE UPDATEN":
                    firmware_update_button = button
                    self.firmware_only_button_polished = button

            # Remove empty one-button rows left behind by runtime injectors. Keep
            # the local firmware row because it also contains Flash-Baud controls.
            for parent in parents:
                if parent is None or parent is firmware_card:
                    continue
                try:
                    visible_other = [
                        child for child in parent.winfo_children()
                        if child not in set(original_firmware_buttons)
                    ]
                except Exception:
                    visible_other = []
                if not visible_other:
                    _forget(parent)

            # Make the baud selector readable and aligned with the action group.
            for widget in _walk(firmware_card):
                text = _text(widget)
                if text == "Flash-Baud:":
                    try:
                        widget.configure(
                            text="Flash-Geschwindigkeit",
                            font=ctk.CTkFont(size=11, weight="bold"),
                        )
                    except Exception:
                        pass
                if isinstance(widget, ctk.CTkOptionMenu):
                    try:
                        widget.configure(height=BUTTON_HEIGHT, width=145)
                    except Exception:
                        pass

            # ------------------------------------------------------------------
            # Service bar: same height, equal visual weight, no tiny controls.
            # ------------------------------------------------------------------
            service_buttons = [
                _find_button(device_card, "NODE-LOG USB"),
                _find_button(device_card, "INFO LESEN"),
                _find_button(device_card, "NEUSTART"),
            ]
            service_buttons = [button for button in service_buttons if button is not None]
            if service_buttons:
                service_parent = getattr(service_buttons[0], "master", None)
                if service_parent is not None and all(getattr(button, "master", None) is service_parent for button in service_buttons):
                    service_label = next((child for child in service_parent.winfo_children() if _text(child) == "SERVICE"), None)
                    if service_label is not None:
                        _forget(service_label)
                    for button in service_buttons:
                        _forget(button)
                    try:
                        service_parent.grid_columnconfigure(0, weight=0, minsize=64)
                        for column in (1, 2, 3):
                            service_parent.grid_columnconfigure(column, weight=1, uniform="service-actions")
                        if service_label is not None:
                            service_label.grid(row=0, column=0, sticky="w", padx=(0, 10))
                        for index, button in enumerate(service_buttons, start=1):
                            _style_button(button, primary=index == 1, neutral=index != 1)
                            button.configure(height=SMALL_BUTTON_HEIGHT)
                            button.grid(row=0, column=index, sticky="ew", padx=(0, 6) if index < 3 else (0, 0))
                            managed_busy_buttons.append(button)
                    except Exception:
                        pass

            # General control sizes that were visually inconsistent in Build 99.
            for widget in _walk(self):
                if isinstance(widget, ctk.CTkButton):
                    label = _text(widget)
                    if label in {"Neu suchen", "PROTOKOLL GROSS", "PROTOKOLL KOMPAKT", "KOPIEREN", "LOGORDNER"}:
                        try:
                            widget.configure(height=SMALL_BUTTON_HEIGHT, corner_radius=8)
                        except Exception:
                            pass
                elif isinstance(widget, ctk.CTkSegmentedButton):
                    try:
                        widget.configure(height=SMALL_BUTTON_HEIGHT)
                    except Exception:
                        pass

            try:
                self.flash_button.configure(height=PRIMARY_HEIGHT, corner_radius=10)
            except Exception:
                pass
            try:
                self.series_button.configure(height=BUTTON_HEIGHT, corner_radius=8)
                self.series_stop_button.configure(height=BUTTON_HEIGHT, corner_radius=8)
            except Exception:
                pass

            # ------------------------------------------------------------------
            # Firmware state banner: deliberately prominent. The existing firmware
            # status layer already does the hard detection/comparison; this layer
            # only turns its result into an unmistakable visual state.
            # ------------------------------------------------------------------
            compare_var = getattr(self, "firmware_compare_var", None)
            status_frame = None
            if compare_var is not None:
                for widget in _walk(device_card):
                    if not isinstance(widget, ctk.CTkLabel):
                        continue
                    try:
                        variable_name = str(widget.cget("textvariable") or "")
                    except Exception:
                        variable_name = ""
                    try:
                        compare_name = str(compare_var)
                    except Exception:
                        compare_name = ""
                    if variable_name and compare_name and variable_name == compare_name:
                        status_frame = getattr(widget, "master", None)
                        break

            if status_frame is None:
                # Fallback: firmware status frame is the parent that contains the
                # static labels Firmware + GitHub.
                for frame in _walk(device_card):
                    if not isinstance(frame, ctk.CTkFrame):
                        continue
                    labels = {_text(child) for child in frame.winfo_children()}
                    if "Firmware" in labels and "GitHub" in labels:
                        status_frame = frame
                        break

            badge = None
            if status_frame is not None and compare_var is not None:
                try:
                    status_frame.configure(border_width=2, border_color="#4B5563")
                except Exception:
                    pass
                badge = ctk.CTkLabel(
                    status_frame,
                    text="FIRMWARESTATUS WIRD GEPRÜFT",
                    height=34,
                    corner_radius=7,
                    fg_color="#374151",
                    text_color="white",
                    font=ctk.CTkFont(size=12, weight="bold"),
                    anchor="w",
                )
                try:
                    badge.grid(row=3, column=0, columnspan=2, sticky="ew", padx=8, pady=(5, 8))
                except Exception:
                    badge = None

            def refresh_firmware_badge(*_args: Any) -> None:
                if badge is None or compare_var is None:
                    return
                try:
                    raw = str(compare_var.get() or "").strip()
                except Exception:
                    raw = ""
                upper = raw.upper()
                if upper.startswith("AKTUELL"):
                    bg, border = "#166534", "#22C55E"
                    headline = "NODE-FIRMWARE AKTUELL"
                    button_bg = "#166534"
                    button_hover = "#14532D"
                elif upper.startswith("UPDATE VERFÜGBAR"):
                    bg, border = "#B45309", "#F59E0B"
                    headline = "UPDATE VERFÜGBAR"
                    button_bg = "#D97706"
                    button_hover = "#B45309"
                elif upper.startswith("ANDERE FIRMWARE") or upper.startswith("JARNSEN-MESH VERFÜGBAR"):
                    bg, border = "#9A3412", "#FB923C"
                    headline = "JARNSEN-MESH UPDATE EMPFOHLEN"
                    button_bg = "#D97706"
                    button_hover = "#B45309"
                elif upper.startswith("NEUER ALS GITHUB"):
                    bg, border = "#1E4E79", "#60A5FA"
                    headline = "NODE IST NEUER ALS GITHUB"
                    button_bg = "#2376B7"
                    button_hover = "#1C659E"
                elif raw:
                    bg, border = "#374151", "#6B7280"
                    headline = "FIRMWARESTATUS"
                    button_bg = "#2376B7"
                    button_hover = "#1C659E"
                else:
                    bg, border = "#374151", "#6B7280"
                    headline = "FIRMWARESTATUS WIRD GEPRÜFT"
                    button_bg = "#2376B7"
                    button_hover = "#1C659E"

                detail = raw
                if " · " in raw:
                    _kind, detail = raw.split(" · ", 1)
                shown = headline if not detail or detail == raw and not raw else f"{headline}  ·  {detail}"
                if len(shown) > 150:
                    shown = shown[:147] + "..."
                try:
                    badge.configure(text=shown, fg_color=bg)
                    if status_frame is not None:
                        status_frame.configure(border_color=border)
                    if firmware_update_button is not None:
                        firmware_update_button.configure(fg_color=button_bg, hover_color=button_hover)
                except Exception:
                    pass
                _emit(f"UI FIRMWARE BADGE state={headline!r} raw={raw!r}")

            if compare_var is not None and badge is not None:
                try:
                    compare_var.trace_add("write", refresh_firmware_badge)
                except Exception:
                    pass
                refresh_firmware_badge()

            # Busy-state integration for all replacement buttons. Existing hidden
            # controls keep their original wrappers; these visible controls mirror it.
            previous_set_busy = self._set_busy

            def polished_set_busy(busy: bool) -> None:
                previous_set_busy(busy)
                state = "disabled" if busy else "normal"
                for button in managed_busy_buttons:
                    try:
                        self.after(0, button.configure, {"state": state})
                    except Exception:
                        pass

            self._set_busy = polished_set_busy
            self._jarnsen_polished_buttons = managed_busy_buttons
            self._append_log(
                "UI · Aktionen neu gruppiert · einheitliche Button-Höhen · Firmwarestatus farbig hervorgehoben"
            )
            _emit(
                "UI ACTION POLISH installed profile=2x2 firmware=3col service=equal-height "
                "firmware-badge=colored fullhd-spacing=1"
            )

        try:
            self.after(1450, patch_app)
        except Exception:
            pass

    ctk.CTk.__init__ = root_init
    _emit("UI ACTION POLISH layer installed")
