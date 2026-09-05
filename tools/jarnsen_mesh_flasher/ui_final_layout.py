from __future__ import annotations

from typing import Any

import customtkinter as ctk


BUTTON_HEIGHT = 36
BAUD_VALUES = ("115200", "230400", "460800", "921600")


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
            return widget
    return None


def _button_command(button: Any):
    command = getattr(button, "_command", None)
    return command if callable(command) else None


def _forget(widget: Any) -> None:
    if widget is None:
        return
    for method_name in ("pack_forget", "grid_forget", "place_forget"):
        try:
            getattr(widget, method_name)()
        except Exception:
            pass


def _req_height(widget: Any, fallback: int) -> int:
    if widget is None:
        return fallback
    try:
        widget.update_idletasks()
        return max(fallback, int(widget.winfo_reqheight()) + 8)
    except Exception:
        return fallback


def install(services: Any) -> None:
    """Apply the final Full-HD dashboard arrangement after all late UI layers."""
    original_root_init = ctk.CTk.__init__

    def root_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_root_init(self, *args, **kwargs)

        def patch_app(attempt: int = 0) -> None:
            if getattr(self, "_jarnsen_final_layout_installed", False):
                return

            ready = (
                hasattr(self, "body")
                and hasattr(self, "log_box")
                and getattr(self, "_jarnsen_action_polish_installed", False)
                and getattr(self, "_jarnsen_overlap_guard_installed", False)
            )
            if not ready:
                if attempt < 35:
                    try:
                        self.after(200, patch_app, attempt + 1)
                    except Exception:
                        pass
                return

            device_card = _find_card(self, ("1 · GERÄT",))
            profile_card = _find_card(self, ("2 · GRUNDEINSTELLUNGEN",))
            firmware_card = _find_card(self, ("3 · FIRMWARE",))
            identity_card = _find_card(self, ("4 · IDENTITÄT", "4 · GERÄTENAME"))
            action_card = _find_card(self, ("5 · AUTOMATISCHER ABLAUF",))
            log_card = _find_card(self, ("PROTOKOLL",))

            profile_labels = (
                "MASTER EINLESEN",
                "PROFIL AUSWÄHLEN",
                "NUR PROFIL SCHREIBEN",
                "PROFIL BEARBEITEN",
            )
            firmware_labels = (
                "NEUESTE PRÜFEN",
                "NUR FIRMWARE UPDATEN",
                "DATEI VOM PC",
            )
            profile_buttons = [_find_button(profile_card, label) for label in profile_labels] if profile_card else []
            firmware_buttons = [_find_button(firmware_card, label) for label in firmware_labels] if firmware_card else []

            if not all((device_card, profile_card, firmware_card, identity_card, action_card, log_card)) or not all(profile_buttons) or not all(firmware_buttons):
                if attempt < 35:
                    try:
                        self.after(200, patch_app, attempt + 1)
                    except Exception:
                        pass
                return

            self._jarnsen_final_layout_installed = True

            # Final card positions requested for the Full-HD dashboard:
            # device | identity
            # firmware | profile
            #          | automatic flow
            # protocol across the full width
            try:
                self.body.grid_columnconfigure(0, weight=9, uniform="")
                self.body.grid_columnconfigure(1, weight=10, uniform="")
                device_card.grid(row=0, column=0, rowspan=1, columnspan=1, sticky="nsew", padx=5, pady=(0, 8))
                identity_card.grid(row=0, column=1, rowspan=1, columnspan=1, sticky="nsew", padx=5, pady=(0, 8))
                firmware_card.grid(row=1, column=0, rowspan=1, columnspan=1, sticky="nsew", padx=5, pady=(0, 8))
                profile_card.grid(row=1, column=1, rowspan=1, columnspan=1, sticky="nsew", padx=5, pady=(0, 8))
                action_card.grid(row=2, column=1, rowspan=1, columnspan=1, sticky="nsew", padx=5, pady=(0, 8))
                log_card.grid(row=3, column=0, rowspan=1, columnspan=2, sticky="nsew", padx=5, pady=(0, 8))
            except Exception as exc:
                _emit(f"UI FINAL LAYOUT card-grid error type={type(exc).__name__} message={exc}")

            # Put the four profile actions into one horizontal row instead of 2x2.
            profile_parent = getattr(profile_buttons[0], "master", None)
            if profile_parent is not None and all(getattr(button, "master", None) is profile_parent for button in profile_buttons):
                for button in profile_buttons:
                    _forget(button)
                try:
                    for column in range(4):
                        profile_parent.grid_columnconfigure(column, weight=1, uniform="profile-actions-final", minsize=0)
                    for index, button in enumerate(profile_buttons):
                        button.configure(
                            height=BUTTON_HEIGHT,
                            corner_radius=8,
                            font=ctk.CTkFont(size=10, weight="bold"),
                        )
                        button.grid(
                            row=0,
                            column=index,
                            sticky="ew",
                            padx=(0, 4) if index == 0 else ((4, 4) if index < 3 else (4, 0)),
                            pady=0,
                        )
                except Exception as exc:
                    _emit(f"UI FINAL LAYOUT profile-row error type={type(exc).__name__} message={exc}")

            # Replace the separate baud/action rows with one compact row:
            # BAUD [selector] [check] [firmware update] [file from PC].
            firmware_parent = getattr(firmware_buttons[0], "master", None)
            firmware_commands = [(label, _button_command(button)) for label, button in zip(firmware_labels, firmware_buttons)]
            baud_label = next(
                (
                    widget
                    for widget in _walk(firmware_card)
                    if _text(widget) in {"Flash-Geschwindigkeit", "Flash-Baud:", "Flash-Baud"}
                ),
                None,
            )
            baud_option = next((widget for widget in _walk(firmware_card) if isinstance(widget, ctk.CTkOptionMenu)), None)
            baud_parent = getattr(baud_option, "master", None) if baud_option is not None else None

            if firmware_parent is not None:
                _forget(firmware_parent)

            if baud_option is not None:
                if baud_parent is not None and baud_parent is not firmware_card and baud_parent is not firmware_parent:
                    try:
                        children = list(baud_parent.winfo_children())
                    except Exception:
                        children = []
                    allowed = {"Flash-Geschwindigkeit", "Flash-Baud:", "Flash-Baud", ""}
                    if children and all(child is baud_option or _text(child) in allowed for child in children):
                        _forget(baud_parent)
                    else:
                        _forget(baud_option)
                        _forget(baud_label)
                else:
                    _forget(baud_option)
                    _forget(baud_label)

            combined = ctk.CTkFrame(firmware_card, fg_color="transparent")
            combined.pack(fill="x", padx=18, pady=(0, 10))
            combined.grid_columnconfigure(0, weight=0, minsize=42)
            combined.grid_columnconfigure(1, weight=0, minsize=128)
            for column in (2, 3, 4):
                combined.grid_columnconfigure(column, weight=1, uniform="firmware-actions-final")

            ctk.CTkLabel(
                combined,
                text="BAUD",
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color=("gray40", "gray65"),
            ).grid(row=0, column=0, sticky="w", padx=(0, 6))

            current_baud = str(getattr(services, "_jarnsen_flash_baud", "921600"))
            if current_baud not in BAUD_VALUES:
                current_baud = "921600"
            baud_var = ctk.StringVar(value=current_baud)

            def set_baud(value: str) -> None:
                chosen = str(value)
                if chosen not in BAUD_VALUES:
                    return
                services._jarnsen_flash_baud = chosen
                try:
                    self._append_log(f"FLASH-BAUD · {chosen}")
                except Exception:
                    pass
                _emit(f"UI FINAL LAYOUT baud={chosen}")

            baud_menu = ctk.CTkOptionMenu(
                combined,
                variable=baud_var,
                values=list(BAUD_VALUES),
                command=set_baud,
                width=124,
                height=BUTTON_HEIGHT,
            )
            baud_menu.grid(row=0, column=1, sticky="w", padx=(0, 8))
            self.final_baud_var = baud_var
            self.final_baud_menu = baud_menu

            new_firmware_buttons: list[Any] = []
            update_button = None
            for index, (label, command) in enumerate(firmware_commands, start=2):
                if not callable(command):
                    continue
                primary = label == "NUR FIRMWARE UPDATEN"
                button = ctk.CTkButton(
                    combined,
                    text=label,
                    command=command,
                    height=BUTTON_HEIGHT,
                    corner_radius=8,
                    font=ctk.CTkFont(size=10, weight="bold"),
                    fg_color="#2376B7" if primary else ("gray74", "gray28"),
                    hover_color="#1C659E" if primary else ("gray66", "gray34"),
                )
                button.grid(
                    row=0,
                    column=index,
                    sticky="ew",
                    padx=(0, 4) if index == 2 else ((4, 4) if index == 3 else (4, 0)),
                )
                new_firmware_buttons.append(button)
                if primary:
                    update_button = button

            # The existing busy wrapper owns this list; appending the replacement
            # controls makes them follow the same disabled/enabled state.
            managed = getattr(self, "_jarnsen_polished_buttons", None)
            if isinstance(managed, list):
                managed.extend(new_firmware_buttons)

            compare_var = getattr(self, "firmware_compare_var", None)

            def refresh_update_color(*_args: Any) -> None:
                if update_button is None:
                    return
                try:
                    raw = str(compare_var.get() or "") if compare_var is not None else ""
                except Exception:
                    raw = ""
                upper = raw.upper()
                if upper.startswith("AKTUELL"):
                    fg, hover = "#166534", "#14532D"
                elif (
                    upper.startswith("UPDATE VERFÜGBAR")
                    or upper.startswith("ANDERE FIRMWARE")
                    or upper.startswith("JARNSEN-MESH VERFÜGBAR")
                ):
                    fg, hover = "#D97706", "#B45309"
                else:
                    fg, hover = "#2376B7", "#1C659E"
                try:
                    update_button.configure(fg_color=fg, hover_color=hover)
                except Exception:
                    pass

            if compare_var is not None and update_button is not None:
                try:
                    compare_var.trace_add("write", refresh_update_color)
                except Exception:
                    pass
            refresh_update_color()

            # Recalculate row heights from the compacted cards. Spare space is
            # intentionally given to the protocol, not to empty dashboard rows.
            def reflow() -> None:
                try:
                    self.update_idletasks()
                except Exception:
                    pass
                row0 = max(_req_height(device_card, 185), _req_height(identity_card, 145))
                row1 = max(_req_height(firmware_card, 150), _req_height(profile_card, 150))
                row2 = _req_height(action_card, 175)
                try:
                    body_height = max(1, int(self.body.winfo_height()))
                except Exception:
                    body_height = 760
                if body_height < 300:
                    body_height = 760
                fixed = row0 + row1 + row2 + 28
                remaining = body_height - fixed
                row3 = max(150, min(360, remaining if remaining > 0 else 150))
                try:
                    self.body.grid_rowconfigure(0, weight=0, minsize=row0)
                    self.body.grid_rowconfigure(1, weight=0, minsize=row1)
                    self.body.grid_rowconfigure(2, weight=0, minsize=row2)
                    self.body.grid_rowconfigure(3, weight=1, minsize=row3)
                    self.log_box.configure(height=max(105, row3 - 58))
                except Exception:
                    pass
                _emit(
                    "UI FINAL LAYOUT REFLOW "
                    f"body={body_height} rows={row0}/{row1}/{row2}/{row3}"
                )

            self._jarnsen_final_layout_reflow = reflow
            reflow()
            try:
                self.after(350, reflow)
                self.after(1100, reflow)
            except Exception:
                pass

            # Errors should automatically give the protocol more room, as specified
            # for the service workflow. The user can still return to compact mode.
            original_show_error = getattr(self, "_show_error", None)
            if callable(original_show_error):
                def show_error(exc: Any) -> Any:
                    try:
                        self.body.grid_rowconfigure(3, weight=2, minsize=300)
                        self.log_box.configure(height=245)
                    except Exception:
                        pass
                    return original_show_error(exc)

                self._show_error = show_error

            try:
                self._append_log(
                    "UI · Finales Layout aktiv · Profilaktionen 1x4 · Firmware Baud+3 · Protokoll vergrößert"
                )
            except Exception:
                pass
            _emit(
                "UI FINAL LAYOUT installed profile-actions=1x4 firmware-row=baud+3 "
                "cards=device/identity,firmware/profile,action-right protocol-flex=1 error-expand=1"
            )

        try:
            self.after(1850, patch_app)
        except Exception:
            pass

    ctk.CTk.__init__ = root_init
    _emit("UI FINAL LAYOUT layer installed")
