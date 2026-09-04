from __future__ import annotations

from typing import Any

import customtkinter as ctk


BUTTON_HEIGHT = 36


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


def install(services: Any) -> None:
    """Apply the user-approved Full-HD dashboard arrangement."""
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
                and getattr(self, "_jarnsen_final_layout_installed", False)
                and getattr(self, "_jarnsen_dashboard_cleanup_installed", False)
            ):
                if attempt < 45:
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
                if attempt < 45:
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
            if not all(source_buttons) or not all(profile_buttons):
                if attempt < 45:
                    self.after(150, patch_app, attempt + 1)
                return

            self._jarnsen_target_layout_installed = True
            _rename(identity, ("4 · IDENTITÄT", "4 · GERÄTENAME", "3 · IDENTITÄT"), "3 · IDENTITÄT")
            _rename(firmware, ("3 · FIRMWARE", "4 · FIRMWARE"), "4 · FIRMWARE")

            # SERVICE becomes its own left-column card; commands stay unchanged.
            service_commands = [_command(button) for button in source_buttons]
            _forget(source_service)
            service = ctk.CTkFrame(self.body, corner_radius=14)
            ctk.CTkLabel(
                service,
                text="SERVICE",
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=("gray35", "gray70"),
            ).pack(anchor="w", padx=18, pady=(14, 7))
            service_row = ctk.CTkFrame(service, fg_color="transparent")
            service_row.pack(fill="x", padx=18, pady=(0, 14))
            for column in range(3):
                service_row.grid_columnconfigure(column, weight=1, uniform="service-target")
            for index, (label, command) in enumerate(zip(("NODE-LOG USB", "INFO LESEN", "NEUSTART"), service_commands)):
                if not callable(command):
                    continue
                primary = index == 0
                button = ctk.CTkButton(
                    service_row,
                    text=label,
                    command=command,
                    height=BUTTON_HEIGHT,
                    corner_radius=8,
                    fg_color="#2376B7" if primary else ("gray72", "gray28"),
                    hover_color="#1C659E" if primary else ("gray65", "gray35"),
                )
                button.grid(row=0, column=index, sticky="ew", padx=(0, 5) if index == 0 else ((3, 3) if index == 1 else (5, 0)))
                if index == 0:
                    self.usb_log_button = button

            # Profile actions use the 2x2 layout shown in the approved screenshot.
            profile_parent = getattr(profile_buttons[0], "master", None)
            if profile_parent is not None:
                for button in profile_buttons:
                    _forget(button)
                for column in (0, 1):
                    profile_parent.grid_columnconfigure(column, weight=1, uniform="profile-target", minsize=0)
                for column in (2, 3):
                    profile_parent.grid_columnconfigure(column, weight=0, uniform="", minsize=0)
                for index, button in enumerate(profile_buttons):
                    row, column = divmod(index, 2)
                    button.configure(height=BUTTON_HEIGHT, corner_radius=8, font=ctk.CTkFont(size=11, weight="bold"))
                    button.grid(
                        row=row,
                        column=column,
                        sticky="ew",
                        padx=(0, 5) if column == 0 else (5, 0),
                        pady=(0, 5) if row == 0 else (5, 0),
                    )

            # Keep AUTOMATISCH FLASHEN compact and right aligned in single mode.
            flash_button = self.flash_button
            try:
                flash_button.configure(width=220, height=38, corner_radius=8, font=ctk.CTkFont(size=12, weight="bold"))
            except Exception:
                pass

            def compact_flash() -> None:
                mode = getattr(self, "operation_mode", None)
                try:
                    if mode is not None and str(mode.get()) != "Einzelgerät":
                        return
                except Exception:
                    pass
                _forget(flash_button)
                try:
                    flash_button.pack(anchor="e", padx=18, pady=(0, 12), after=self.progress)
                except Exception:
                    flash_button.pack(anchor="e", padx=18, pady=(0, 12))

            compact_flash()
            mode_var = getattr(self, "operation_mode", None)
            if mode_var is not None:
                def mode_changed(*_args: Any) -> None:
                    try:
                        if str(mode_var.get()) == "Einzelgerät":
                            self.after_idle(compact_flash)
                    except Exception:
                        pass
                try:
                    mode_var.trace_add("write", mode_changed)
                except Exception:
                    pass

            # Exact requested columns: full-width device; profile/identity; service
            # spanning the left side while firmware + automatic flow stack right.
            self.body.grid_columnconfigure(0, weight=1, uniform="target-dashboard")
            self.body.grid_columnconfigure(1, weight=1, uniform="target-dashboard")
            device.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=5, pady=(0, 8))
            profile.grid(row=1, column=0, sticky="nsew", padx=(5, 4), pady=(0, 8))
            identity.grid(row=1, column=1, sticky="nsew", padx=(4, 5), pady=(0, 8))
            service.grid(row=2, column=0, rowspan=2, sticky="nsew", padx=(5, 4), pady=(0, 8))
            firmware.grid(row=2, column=1, sticky="nsew", padx=(4, 5), pady=(0, 8))
            automatic.grid(row=3, column=1, sticky="nsew", padx=(4, 5), pady=(0, 8))
            protocol.grid(row=4, column=0, columnspan=2, sticky="nsew", padx=5, pady=(0, 8))

            # Give the protocol the remaining space; it now lives in row 4.
            self.body.grid_rowconfigure(0, weight=0, minsize=160)
            self.body.grid_rowconfigure(1, weight=0, minsize=145)
            self.body.grid_rowconfigure(2, weight=0, minsize=120)
            self.body.grid_rowconfigure(3, weight=0, minsize=145)
            self.body.grid_rowconfigure(4, weight=1, minsize=190)
            try:
                self.log_box.configure(height=170)
            except Exception:
                pass

            log_toggle = _button(protocol, "PROTOKOLL GROSS") or _button(protocol, "PROTOKOLL KOMPAKT")
            if log_toggle is not None:
                expanded = {"value": False}

                def toggle_log() -> None:
                    expanded["value"] = not expanded["value"]
                    try:
                        if expanded["value"]:
                            self.body.grid_rowconfigure(4, weight=2, minsize=320)
                            self.log_box.configure(height=285)
                            log_toggle.configure(text="PROTOKOLL KOMPAKT")
                        else:
                            self.body.grid_rowconfigure(4, weight=1, minsize=190)
                            self.log_box.configure(height=170)
                            log_toggle.configure(text="PROTOKOLL GROSS")
                    except Exception:
                        pass

                try:
                    log_toggle.configure(command=toggle_log)
                except Exception:
                    pass

            try:
                self._append_log("UI · Ziel-Layout aktiv · Service links · Firmware/Automatik rechts · Protokoll vollbreit")
            except Exception:
                pass
            _emit("UI TARGET LAYOUT installed service-left-span auto-right auto-button=220 protocol-row=4")

        try:
            self.after(2250, patch_app)
        except Exception:
            pass

    ctk.CTk.__init__ = root_init
    _emit("UI TARGET LAYOUT layer installed")
