from __future__ import annotations

from pathlib import Path
from typing import Any

import customtkinter as ctk


DEVICE_H = 150
PROFILE_H = 132
SERVICE_H = 112
AUTO_H = 168
PROTOCOL_MIN = 190
CONTROL_H = 36


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


def _button(root: Any, *texts: str) -> Any | None:
    wanted = {text.casefold() for text in texts}
    for widget in _walk(root):
        if isinstance(widget, ctk.CTkButton) and _text(widget).casefold() in wanted:
            return widget
    return None


def _command(widget: Any):
    command = getattr(widget, "_command", None)
    return command if callable(command) else None


def _forget(widget: Any) -> None:
    if widget is None:
        return
    for method in ("pack_forget", "grid_forget", "place_forget"):
        try:
            getattr(widget, method)()
        except Exception:
            pass


def _title_widget(card: Any) -> Any | None:
    for child in card.winfo_children():
        if isinstance(child, ctk.CTkLabel) and any(token in _text(child) for token in ("GERÄT", "GRUNDEINSTELLUNGEN", "IDENTITÄT", "FIRMWARE", "SERVICE", "AUTOMATISCHER ABLAUF", "Hinweise", "PROTOKOLL")):
            return child
    return None


def _status_frame(device: Any) -> Any | None:
    for frame in _walk(device):
        if not isinstance(frame, ctk.CTkFrame):
            continue
        texts = {_text(child) for child in frame.winfo_children()}
        if "Installierte Firmware:" in texts and "Verfügbare Firmware:" in texts:
            return frame
    return None


def _footer_frame(root: Any) -> Any | None:
    for child in root.winfo_children():
        if not isinstance(child, ctk.CTkFrame):
            continue
        if any(_text(widget).startswith("© 2026 JARNSEN") for widget in _walk(child)):
            return child
    return None


def install(services: Any) -> None:
    """Final 1920x1080 fit pass for the approved reference dashboard."""
    original_root_init = ctk.CTk.__init__

    def root_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_root_init(self, *args, **kwargs)

        def patch(attempt: int = 0) -> None:
            if getattr(self, "_jarnsen_1080_fit_installed", False):
                return
            if not getattr(self, "_jarnsen_target_layout_installed", False) or not hasattr(self, "body"):
                if attempt < 70:
                    self.after(150, patch, attempt + 1)
                return

            device = _card(self, "1 · GERÄT", "▣  1. GERÄT")
            profile = _card(self, "2 · GRUNDEINSTELLUNGEN", "⚙  2. GRUNDEINSTELLUNGEN")
            identity = _card(self, "3 · IDENTITÄT", "●  3. IDENTITÄT")
            firmware = _card(self, "4 · FIRMWARE", "▣  4. FIRMWARE")
            service = _card(self, "SERVICE", "🔧  SERVICE")
            automatic = _card(self, "5 · AUTOMATISCHER ABLAUF", "◷  5. AUTOMATISCHER ABLAUF")
            hints = _card(self, "Hinweise", "💡  Hinweise")
            protocol = _card(self, "PROTOKOLL", "☷  PROTOKOLL")
            if not all((device, profile, identity, firmware, service, automatic, hints, protocol)):
                if attempt < 70:
                    self.after(150, patch, attempt + 1)
                return

            self._jarnsen_1080_fit_installed = True

            header = None
            for child in self.winfo_children():
                if child is self.body or not isinstance(child, ctk.CTkFrame):
                    continue
                if any(_text(widget) == "JARNSEN MESH Flasher" for widget in _walk(child)):
                    header = child
                    break
            if header is not None:
                try:
                    header.pack_configure(fill="x", padx=24, pady=(8, 4))
                except Exception:
                    pass
                for widget in _walk(header):
                    if isinstance(widget, ctk.CTkLabel) and _text(widget) == "JARNSEN MESH Flasher":
                        try:
                            widget.configure(font=ctk.CTkFont(size=24, weight="bold"))
                        except Exception:
                            pass

            footer = _footer_frame(self)
            if footer is not None:
                try:
                    footer.pack_forget()
                    footer.pack(side="bottom", fill="x", padx=24, pady=(0, 3))
                    self.body.pack_forget()
                    self.body.pack(fill="both", expand=True, padx=18, pady=(0, 2))
                except Exception:
                    pass

            status = _status_frame(device)
            old_combo = getattr(self, "device_combo", None)
            board_menu = next((w for w in _walk(device) if isinstance(w, ctk.CTkOptionMenu)), None)
            old_device_parent = getattr(old_combo, "master", None) if old_combo is not None else None
            old_board_parent = getattr(board_menu, "master", None) if board_menu is not None else None
            _forget(old_device_parent)
            if old_board_parent is not old_device_parent:
                _forget(old_board_parent)

            top = ctk.CTkFrame(device, fg_color="transparent")
            top.grid_columnconfigure(0, weight=6, uniform="device1080")
            top.grid_columnconfigure(1, weight=0)
            top.grid_columnconfigure(2, weight=5, uniform="device1080")
            try:
                if status is not None:
                    top.pack(fill="x", padx=16, pady=(0, 6), before=status)
                else:
                    top.pack(fill="x", padx=16, pady=(0, 6))
            except Exception:
                top.pack(fill="x", padx=16, pady=(0, 6))

            combo_wrap = ctk.CTkFrame(top, fg_color="transparent")
            combo_wrap.grid(row=0, column=0, sticky="ew", padx=(0, 10))
            ctk.CTkLabel(combo_wrap, text="COM / Gerät", font=ctk.CTkFont(size=9), text_color=("gray40", "gray65")).pack(anchor="w", pady=(0, 2))
            try:
                values = list(old_combo.cget("values")) if old_combo is not None else [self.device_var.get()]
            except Exception:
                values = [self.device_var.get()]
            new_combo = ctk.CTkComboBox(combo_wrap, variable=self.device_var, values=values or ["Kein Gerät erkannt"], command=self._device_changed, state="readonly", height=CONTROL_H)
            new_combo.pack(fill="x")
            self.device_combo = new_combo

            ctk.CTkButton(top, text="⌕  Neu suchen", width=132, height=CONTROL_H, corner_radius=8, command=self.refresh_devices).grid(row=0, column=1, sticky="s", padx=(0, 12))

            board_wrap = ctk.CTkFrame(top, fg_color="transparent")
            board_wrap.grid(row=0, column=2, sticky="ew")
            ctk.CTkLabel(board_wrap, text="Board", font=ctk.CTkFont(size=9), text_color=("gray40", "gray65")).pack(anchor="w", pady=(0, 2))
            ctk.CTkOptionMenu(
                board_wrap,
                variable=self.board_var,
                values=["Automatisch", services.BOARD_PROFILES["tracker"]["label"], services.BOARD_PROFILES["repeater"]["label"]],
                command=lambda _value: self._invalidate_bundle(),
                height=CONTROL_H,
            ).pack(fill="x")

            profile_commands = []
            for labels in (("MASTER EINLESEN", "Vom Master einlesen", "⇩  MASTER\nEINLESEN"), ("PROFIL AUSWÄHLEN", "Profil auswählen", "Profil laden", "▣  PROFIL\nAUSWÄHLEN"), ("NUR PROFIL SCHREIBEN", "⇧  NUR PROFIL\nSCHREIBEN"), ("PROFIL BEARBEITEN", "✎  PROFIL\nBEARBEITEN")):
                button = _button(profile, *labels)
                profile_commands.append(_command(button))
            if all(callable(command) for command in profile_commands):
                for widget in list(_walk(profile)):
                    if isinstance(widget, ctk.CTkButton):
                        _forget(widget)
                row = ctk.CTkFrame(profile, fg_color="transparent")
                row.pack(fill="x", padx=16, pady=(0, 8))
                for column in range(4):
                    row.grid_columnconfigure(column, weight=1, uniform="profile1080")
                texts = ("⇩  MASTER\nEINLESEN", "▣  PROFIL\nAUSWÄHLEN", "⇧  NUR PROFIL\nSCHREIBEN", "✎  PROFIL\nBEARBEITEN")
                for index, (text, command) in enumerate(zip(texts, profile_commands)):
                    primary = index == 1
                    button = ctk.CTkButton(
                        row,
                        text=text,
                        command=command,
                        height=48,
                        corner_radius=8,
                        font=ctk.CTkFont(size=10, weight="bold"),
                        fg_color="#0B72E7" if primary else ("gray72", "gray28"),
                        hover_color="#0862C6" if primary else ("gray65", "gray35"),
                    )
                    button.grid(row=0, column=index, sticky="ew", padx=(0, 4) if index == 0 else ((4, 4) if index < 3 else (4, 0)))

            firmware_commands = []
            for labels in (("NEUESTE PRÜFEN", "☁  NEUESTE PRÜFEN", "Neueste Firmware prüfen"), ("NUR FIRMWARE UPDATEN", "⇧  NUR FIRMWARE UPDATEN"), ("DATEI VOM PC", "▧  DATEI VOM PC", "Datei vom PC auswählen")):
                button = _button(firmware, *labels)
                firmware_commands.append(_command(button))
            footer_frame = None
            for frame in firmware.winfo_children():
                if not isinstance(frame, ctk.CTkFrame):
                    continue
                if any(_text(widget).startswith("Aktuell:") for widget in _walk(frame)):
                    footer_frame = frame
                    break
            title = _title_widget(firmware)
            if all(callable(command) for command in firmware_commands):
                for child in list(firmware.winfo_children()):
                    if child is title or child is footer_frame:
                        continue
                    _forget(child)
                controls = ctk.CTkFrame(firmware, fg_color="transparent")
                try:
                    if footer_frame is not None:
                        controls.pack(fill="x", padx=16, pady=(0, 4), before=footer_frame)
                    else:
                        controls.pack(fill="x", padx=16, pady=(0, 4))
                except Exception:
                    controls.pack(fill="x", padx=16, pady=(0, 4))
                controls.grid_columnconfigure(0, weight=0)
                for column in (1, 2, 3):
                    controls.grid_columnconfigure(column, weight=1, uniform="firmware1080")
                baud = ctk.CTkFrame(controls, fg_color="transparent")
                baud.grid(row=0, column=0, sticky="w", padx=(0, 9))
                ctk.CTkLabel(baud, text="Baud", font=ctk.CTkFont(size=9), text_color=("gray40", "gray65")).pack(anchor="w", pady=(0, 2))
                current_baud = str(getattr(services, "_jarnsen_flash_baud", "921600"))
                baud_var = ctk.StringVar(value=current_baud if current_baud in {"115200", "230400", "460800", "921600"} else "921600")
                ctk.CTkOptionMenu(baud, variable=baud_var, values=["115200", "230400", "460800", "921600"], command=lambda value: setattr(services, "_jarnsen_flash_baud", str(value)), width=130, height=CONTROL_H).pack()
                texts = ("☁  NEUESTE PRÜFEN", "⇧  NUR FIRMWARE UPDATEN", "▧  DATEI VOM PC")
                for index, (text, command) in enumerate(zip(texts, firmware_commands), start=1):
                    button = ctk.CTkButton(
                        controls,
                        text=text,
                        command=command,
                        height=CONTROL_H,
                        corner_radius=8,
                        font=ctk.CTkFont(size=10, weight="bold"),
                        fg_color="#D97706" if index == 2 else ("gray72", "gray28"),
                        hover_color="#B45309" if index == 2 else ("gray65", "gray35"),
                    )
                    button.grid(row=0, column=index, sticky="sew", padx=(0, 4) if index == 1 else ((4, 4) if index == 2 else (4, 0)), pady=(13, 0))

            fixed = ((device, DEVICE_H), (profile, PROFILE_H), (identity, PROFILE_H), (service, SERVICE_H), (firmware, SERVICE_H), (automatic, AUTO_H), (hints, AUTO_H))
            for card_widget, height in fixed:
                try:
                    card_widget.configure(height=height)
                    card_widget.grid_propagate(False)
                except Exception:
                    pass

            self.body.grid_rowconfigure(0, weight=0, minsize=DEVICE_H)
            self.body.grid_rowconfigure(1, weight=0, minsize=PROFILE_H)
            self.body.grid_rowconfigure(2, weight=0, minsize=SERVICE_H)
            self.body.grid_rowconfigure(3, weight=0, minsize=AUTO_H)
            self.body.grid_rowconfigure(4, weight=1, minsize=PROTOCOL_MIN)
            try:
                self.log_box.configure(height=180)
            except Exception:
                pass

            def report_fit() -> None:
                try:
                    _emit(
                        "UI 1080 FIT "
                        f"screen={self.winfo_screenwidth()}x{self.winfo_screenheight()} "
                        f"window={self.winfo_width()}x{self.winfo_height()} "
                        f"body={self.body.winfo_width()}x{self.body.winfo_height()} "
                        f"protocol={protocol.winfo_height()}"
                    )
                except Exception:
                    pass

            self.after(500, report_fit)
            self.after(1600, report_fit)
            try:
                self._append_log("UI · 1920x1080 Fit aktiv · Gerät+Board einzeilig · Profil 1x4 · Firmware kompakt · Protokoll sichtbar")
            except Exception:
                pass
            _emit("UI 1080 FIT installed final-pass=1")

        try:
            self.after(2850, patch)
        except Exception:
            pass

    ctk.CTk.__init__ = root_init
    _emit("UI 1080 FIT layer installed")
