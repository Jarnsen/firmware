from __future__ import annotations

from typing import Any

import customtkinter as ctk

from _build_version import APP_VERSION


BG = "#07111E"
CARD = "#0B1725"
CARD_BORDER = "#223247"
CONTROL = "#142438"
CONTROL_HOVER = "#1C334B"
INPUT_BG = "#0B1624"
BLUE = "#0B72E7"
BLUE_HOVER = "#0862C6"
ORANGE = "#D97706"
ORANGE_HOVER = "#B45309"
GREEN = "#15803D"
TEXT_MUTED = "#93A4B7"


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


def _forget(widget: Any) -> None:
    if widget is None:
        return
    for method in ("pack_forget", "grid_forget", "place_forget"):
        try:
            getattr(widget, method)()
        except Exception:
            pass


def _find_header(root: Any, body: Any) -> Any | None:
    for child in root.winfo_children():
        if child is body or not isinstance(child, ctk.CTkFrame):
            continue
        if any(_text(widget) == "JARNSEN MESH Flasher" for widget in _walk(child)):
            return child
    return None


def _find_footer(root: Any) -> Any | None:
    for child in root.winfo_children():
        if not isinstance(child, ctk.CTkFrame):
            continue
        if any(_text(widget).startswith("© 2026 JARNSEN") for widget in _walk(child)):
            return child
    return None


def _title_label(card: Any) -> Any | None:
    for child in card.winfo_children():
        if isinstance(child, ctk.CTkLabel):
            text = _text(child)
            if any(
                token in text
                for token in (
                    "GERÄT",
                    "GRUNDEINSTELLUNGEN",
                    "IDENTITÄT",
                    "FIRMWARE",
                    "SERVICE",
                    "AUTOMATISCHER ABLAUF",
                    "Hinweise",
                    "PROTOKOLL",
                )
            ):
                return child
    return None


def _style_controls(root: Any) -> None:
    for widget in _walk(root):
        try:
            if isinstance(widget, ctk.CTkButton):
                text = _text(widget).upper()
                common = dict(
                    height=34,
                    corner_radius=7,
                    border_width=1,
                    border_color="#2B4055",
                    font=ctk.CTkFont(size=10, weight="bold"),
                )
                if "NUR FIRMWARE UPDATEN" in text:
                    widget.configure(
                        **common,
                        fg_color=ORANGE,
                        hover_color=ORANGE_HOVER,
                        border_color="#F59E0B",
                        text_color="white",
                    )
                elif (
                    "NEU SUCHEN" in text
                    or "PROFIL" in text and "AUSWÄHLEN" in text
                    or "NODE-LOG USB" in text
                    or "AUTOMATISCH FLASHEN" in text
                ):
                    widget.configure(
                        **common,
                        fg_color=BLUE,
                        hover_color=BLUE_HOVER,
                        border_color="#1683F5",
                        text_color="white",
                    )
                else:
                    widget.configure(
                        **common,
                        fg_color=CONTROL,
                        hover_color=CONTROL_HOVER,
                        text_color="white",
                    )
            elif isinstance(widget, ctk.CTkSegmentedButton):
                widget.configure(
                    height=30,
                    corner_radius=6,
                    selected_color=BLUE,
                    selected_hover_color=BLUE_HOVER,
                    unselected_color=CONTROL,
                    unselected_hover_color=CONTROL_HOVER,
                )
            elif isinstance(widget, ctk.CTkEntry):
                widget.configure(
                    height=32,
                    corner_radius=6,
                    fg_color=INPUT_BG,
                    border_color="#344A5F",
                    border_width=1,
                )
            elif isinstance(widget, ctk.CTkComboBox):
                widget.configure(
                    height=32,
                    corner_radius=6,
                    fg_color=INPUT_BG,
                    border_color="#344A5F",
                    button_color=CONTROL,
                    button_hover_color=CONTROL_HOVER,
                )
            elif isinstance(widget, ctk.CTkOptionMenu):
                widget.configure(
                    height=32,
                    corner_radius=6,
                    fg_color=CONTROL,
                    button_color=CONTROL_HOVER,
                    button_hover_color="#29445E",
                )
            elif isinstance(widget, ctk.CTkProgressBar):
                widget.configure(height=7, corner_radius=4, progress_color=BLUE, fg_color="#294055")
        except Exception:
            pass


def install(services: Any) -> None:
    """Pixel-proportional final pass matching the approved 1920x1080 reference."""
    original_root_init = ctk.CTk.__init__

    def root_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_root_init(self, *args, **kwargs)

        def apply_reference(attempt: int = 0) -> None:
            if getattr(self, "_jarnsen_reference_exact_installed", False):
                return
            if not (
                hasattr(self, "body")
                and hasattr(self, "log_box")
                and getattr(self, "_jarnsen_1080_fit_installed", False)
            ):
                if attempt < 90:
                    try:
                        self.after(120, apply_reference, attempt + 1)
                    except Exception:
                        pass
                return

            device = _card(self, "1 · GERÄT", "▣  1. GERÄT")
            profile = _card(self, "2 · GRUNDEINSTELLUNGEN", "⚙  2. GRUNDEINSTELLUNGEN")
            identity = _card(self, "3 · IDENTITÄT", "●  3. IDENTITÄT")
            firmware = _card(self, "4 · FIRMWARE", "▦  4. FIRMWARE", "▣  4. FIRMWARE")
            service = _card(self, "SERVICE", "🔧  SERVICE", "⌕  SERVICE")
            automatic = _card(self, "5 · AUTOMATISCHER ABLAUF", "◷  5. AUTOMATISCHER ABLAUF")
            hints = _card(self, "Hinweise", "💡  Hinweise")
            protocol = _card(self, "PROTOKOLL", "☷  PROTOKOLL")

            if not all((device, profile, identity, firmware, service, automatic, hints, protocol)):
                if attempt < 90:
                    try:
                        self.after(120, apply_reference, attempt + 1)
                    except Exception:
                        pass
                return

            self._jarnsen_reference_exact_installed = True

            try:
                self.configure(fg_color=BG)
                self.body.configure(fg_color="transparent", corner_radius=0)
            except Exception:
                pass

            header = _find_header(self, self.body)
            if header is not None:
                for child in list(header.winfo_children()):
                    _forget(child)
                try:
                    header.configure(fg_color="transparent", height=48)
                    header.pack_configure(fill="x", padx=24, pady=(7, 5))
                except Exception:
                    pass

                logo = ctk.CTkLabel(
                    header,
                    text="J",
                    width=38,
                    height=38,
                    corner_radius=8,
                    fg_color=BLUE,
                    text_color="white",
                    font=ctk.CTkFont(size=22, weight="bold"),
                )
                logo.pack(side="left", padx=(0, 12))

                ctk.CTkLabel(
                    header,
                    text="JARNSEN MESH Flasher",
                    font=ctk.CTkFont(size=25, weight="bold"),
                ).pack(side="left")

                ctk.CTkLabel(
                    header,
                    text=f"  {APP_VERSION}",
                    font=ctk.CTkFont(size=10),
                    text_color=TEXT_MUTED,
                ).pack(side="left", padx=(7, 0), pady=(7, 0))

                right = ctk.CTkFrame(header, fg_color="transparent")
                right.pack(side="right")

                device_count = ctk.StringVar(value="⌕  0 Gerät(e) gefunden")
                board_count = ctk.StringVar(value="▣  0 Board(s) erkannt")
                ctk.CTkLabel(
                    right,
                    textvariable=device_count,
                    font=ctk.CTkFont(size=10, weight="bold"),
                ).pack(side="left", padx=(0, 28))
                ctk.CTkLabel(
                    right,
                    textvariable=board_count,
                    font=ctk.CTkFont(size=10, weight="bold"),
                ).pack(side="left", padx=(0, 28))
                ctk.CTkLabel(
                    right,
                    text="●",
                    text_color="#22C55E",
                    font=ctk.CTkFont(size=14, weight="bold"),
                ).pack(side="left", padx=(0, 6))
                ctk.CTkLabel(
                    right,
                    textvariable=self.status_var,
                    font=ctk.CTkFont(size=10, weight="bold"),
                ).pack(side="left")

                def refresh_header_counts() -> None:
                    try:
                        devices = list(getattr(self, "devices", []) or [])
                        boards = sum(1 for item in devices if getattr(item, "board_key", None))
                        device_count.set(f"⌕  {len(devices)} Gerät(e) gefunden")
                        board_count.set(f"▣  {boards} Board(s) erkannt")
                        self.after(700, refresh_header_counts)
                    except Exception:
                        pass

                refresh_header_counts()

            try:
                self.body.pack_forget()
                footer = _find_footer(self)
                if footer is not None:
                    footer.pack_forget()
                self.body.pack(fill="both", expand=True, padx=24, pady=(0, 4))
                if footer is not None:
                    footer.configure(fg_color="transparent", height=24)
                    footer.pack(side="bottom", fill="x", padx=24, pady=(0, 5))
            except Exception:
                pass

            title_map = (
                (device, "▣  1. GERÄT"),
                (profile, "⚙  2. GRUNDEINSTELLUNGEN"),
                (identity, "●  3. IDENTITÄT"),
                (firmware, "▦  4. FIRMWARE"),
                (service, "⌕  SERVICE"),
                (automatic, "◷  5. AUTOMATISCHER ABLAUF"),
                (hints, "◉  Hinweise"),
                (protocol, "☷  PROTOKOLL"),
            )
            for card_widget, title_text in title_map:
                try:
                    card_widget.configure(
                        fg_color=CARD,
                        corner_radius=10,
                        border_width=1,
                        border_color=CARD_BORDER,
                    )
                except Exception:
                    pass
                title = _title_label(card_widget)
                if title is not None:
                    try:
                        title.configure(
                            text=title_text,
                            font=ctk.CTkFont(size=11, weight="bold"),
                            text_color="#E6EEF7",
                        )
                        title.pack_configure(padx=14, pady=(9, 4))
                    except Exception:
                        pass

            for widget in (device, profile, identity, service, firmware, automatic, hints, protocol):
                _forget(widget)

            left_w = 0.496
            right_x = 0.504
            device.place(relx=0.0, rely=0.0, relwidth=1.0, relheight=0.1825)
            profile.place(relx=0.0, rely=0.1933, relwidth=left_w, relheight=0.1793)
            identity.place(relx=right_x, rely=0.1933, relwidth=left_w, relheight=0.1793)
            service.place(relx=0.0, rely=0.3834, relwidth=left_w, relheight=0.1113)
            firmware.place(relx=right_x, rely=0.3834, relwidth=left_w, relheight=0.1113)
            automatic.place(relx=0.0, rely=0.5055, relwidth=left_w, relheight=0.2427)
            hints.place(relx=right_x, rely=0.5055, relwidth=left_w, relheight=0.2427)
            protocol.place(relx=0.0, rely=0.7574, relwidth=1.0, relheight=0.2426)

            for widget in (device, profile, identity, service, firmware, automatic, hints, protocol):
                try:
                    widget.pack_propagate(True)
                    widget.grid_propagate(True)
                except Exception:
                    pass

            _style_controls(self)

            for card_widget in (profile, identity, service, firmware, automatic, hints):
                for child in card_widget.winfo_children():
                    try:
                        info = child.pack_info()
                    except Exception:
                        continue
                    try:
                        pady = info.get("pady", 0)
                        if isinstance(pady, tuple):
                            top, bottom = pady
                            child.pack_configure(pady=(min(int(top), 5), min(int(bottom), 6)))
                    except Exception:
                        pass

            try:
                self.log_box.configure(
                    height=150,
                    corner_radius=7,
                    fg_color="#06111D",
                    border_width=0,
                    font=ctk.CTkFont(family="Consolas", size=10),
                )
                self.log_box.pack_configure(fill="both", expand=True, padx=14, pady=(0, 8))
            except Exception:
                pass

            for widget in _walk(protocol):
                if not isinstance(widget, ctk.CTkButton):
                    continue
                text = _text(widget).upper()
                if any(token in text for token in ("PROTOKOLL GROSS", "PROTOKOLL KOMPAKT", "KOPIEREN", "LOGORDNER", "PROTOKOLL LEEREN")):
                    try:
                        widget.configure(height=28, font=ctk.CTkFont(size=9, weight="bold"))
                    except Exception:
                        pass

            def report() -> None:
                try:
                    _emit(
                        "UI REFERENCE EXACT "
                        f"screen={self.winfo_screenwidth()}x{self.winfo_screenheight()} "
                        f"window={self.winfo_width()}x{self.winfo_height()} "
                        f"body={self.body.winfo_width()}x{self.body.winfo_height()} "
                        f"profile={profile.winfo_height()} service={service.winfo_height()} "
                        f"auto={automatic.winfo_height()} protocol={protocol.winfo_height()}"
                    )
                except Exception:
                    pass

            try:
                self.after(350, report)
                self.after(1200, report)
                self._append_log(
                    "UI · Referenz 1:1 aktiv · proportionsbasiert für 1920x1080 · "
                    "keine DPI-bedingten Leerhöhen"
                )
            except Exception:
                pass
            _emit("UI REFERENCE EXACT installed layout=1to1 place-proportions=1")

        try:
            self.after(3450, apply_reference)
        except Exception:
            pass

    ctk.CTk.__init__ = root_init
    _emit("UI REFERENCE EXACT layer installed")
