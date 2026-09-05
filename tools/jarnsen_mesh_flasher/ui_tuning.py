from __future__ import annotations

from typing import Any

import customtkinter as ctk


_INSTALLED = False
REFERENCE_WIDGET_SCALE = 1.00
REFERENCE_FONT_SCALE = 1.28
CONTENT_BASE_FONT_SIZE = 13
STAGE_BASE_FONT_SIZE = 9
FIRMWARE_STATUS_BASE_FONT_SIZE = 15
FIRMWARE_STATUS_ICON_SIZE = 21
PROFILE_ACTION_ICON_SIZE = 18
MODE_BUTTON_HEIGHT = 30
PROGRESS_BAR_HEIGHT = 18


def install(services: Any) -> None:
    """Keep startup geometry/DPI handling lightweight; reference UI owns final chrome."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    ctk.set_widget_scaling(REFERENCE_WIDGET_SCALE)

    original_font_init = ctk.CTkFont.__init__

    def font_init(self: Any, *args: Any, **kwargs: Any) -> None:
        args_list = list(args)
        if "size" in kwargs and kwargs["size"] is not None:
            try:
                kwargs["size"] = max(1, int(round(float(kwargs["size"]) * REFERENCE_FONT_SCALE)))
            except Exception:
                pass
        elif len(args_list) >= 2 and args_list[1] is not None:
            try:
                args_list[1] = max(1, int(round(float(args_list[1]) * REFERENCE_FONT_SCALE)))
            except Exception:
                pass
        original_font_init(self, *args_list, **kwargs)

    ctk.CTkFont.__init__ = font_init

    try:
        import ui_icons

        original_icon = ui_icons.icon

        def tuned_icon(name: str, size: int, color: str, *args: Any, **kwargs: Any):
            if name == "chip" and int(size) == 13 and str(color).upper() == "#93A6BA":
                size = FIRMWARE_STATUS_ICON_SIZE
            return original_icon(name, size, color, *args, **kwargs)

        ui_icons.icon = tuned_icon
    except Exception:
        pass

    original_label_init = ctk.CTkLabel.__init__
    original_label_configure = ctk.CTkLabel.configure
    stage_names = {"Backup", "Firmware", "Grundeinst.", "Grundeinstellungen", "Profil", "Namen", "Neustart", "Prüfung"}
    firmware_status_labels = {"Installierte Firmware:", "Verfügbare Firmware:"}

    def normalize_stage_text(text: str) -> str:
        if "Grundeinstellungen" in text:
            return text.replace("Grundeinstellungen", "Profil")
        if "Grundeinst." in text:
            return text.replace("Grundeinst.", "Profil")
        return text

    def label_init(self: Any, master: Any, *args: Any, **kwargs: Any) -> None:
        text = kwargs.get("text")
        if isinstance(text, str) and text.startswith("• Vor dem Flashen"):
            kwargs["font"] = ctk.CTkFont(size=CONTENT_BASE_FONT_SIZE)
        elif isinstance(text, str) and text in firmware_status_labels:
            kwargs["font"] = ctk.CTkFont(size=FIRMWARE_STATUS_BASE_FONT_SIZE)
        elif isinstance(text, str):
            stage_text = text.replace("●", "").replace("○", "").strip()
            if stage_text in stage_names:
                kwargs["text"] = normalize_stage_text(text)
                kwargs["font"] = ctk.CTkFont(size=STAGE_BASE_FONT_SIZE)
        original_label_init(self, master, *args, **kwargs)

    def label_configure(self: Any, *args: Any, **kwargs: Any):
        text = kwargs.get("text")
        if isinstance(text, str):
            stage_text = text.replace("●", "").replace("○", "").strip()
            if stage_text in stage_names:
                kwargs["text"] = normalize_stage_text(text)
        return original_label_configure(self, *args, **kwargs)

    ctk.CTkLabel.__init__ = label_init
    ctk.CTkLabel.configure = label_configure

    original_textbox_init = ctk.CTkTextbox.__init__

    def textbox_init(self: Any, master: Any, *args: Any, **kwargs: Any) -> None:
        font = kwargs.get("font")
        family = ""
        try:
            family = str(font.cget("family")) if font is not None else ""
        except Exception:
            family = ""
        if family.lower() == "consolas":
            kwargs["font"] = ctk.CTkFont(family="Consolas", size=CONTENT_BASE_FONT_SIZE)
        original_textbox_init(self, master, *args, **kwargs)

    ctk.CTkTextbox.__init__ = textbox_init

    # Only the four action buttons in the Grundeinstellungen card get larger icons.
    # Button height and text remain unchanged.
    original_button_init = ctk.CTkButton.__init__
    profile_action_icons = {
        "MASTER\nEINLESEN": "download",
        "PROFIL\nAUSWÄHLEN": "folder",
        "NUR PROFIL\nSCHREIBEN": "upload",
        "PROFIL\nBEARBEITEN": "edit",
    }

    def button_init(self: Any, master: Any, *args: Any, **kwargs: Any) -> None:
        text = kwargs.get("text")
        icon_name = profile_action_icons.get(text) if isinstance(text, str) else None
        if icon_name:
            try:
                import ui_icons
                kwargs["image"] = ui_icons.icon(icon_name, PROFILE_ACTION_ICON_SIZE, "#F8FAFC")
                kwargs["compound"] = "left"
            except Exception:
                pass
        original_button_init(self, master, *args, **kwargs)

    ctk.CTkButton.__init__ = button_init

    # The automatic-flow progress bar is authored with height=5. Increase that
    # specific compact bar only, leaving all other progress bars untouched.
    original_progress_init = ctk.CTkProgressBar.__init__

    def progress_init(self: Any, master: Any, *args: Any, **kwargs: Any) -> None:
        if kwargs.get("height") == 5:
            kwargs["height"] = PROGRESS_BAR_HEIGHT
            if kwargs.get("corner_radius") == 3:
                kwargs["corner_radius"] = 7
        original_progress_init(self, master, *args, **kwargs)

    ctk.CTkProgressBar.__init__ = progress_init

    original_segmented_button = ctk.CTkSegmentedButton

    class ServiceModeSwitch(ctk.CTkFrame):
        def __init__(self, master: Any, *args: Any, values: Any = None, variable: Any = None, command: Any = None, height: int = MODE_BUTTON_HEIGHT, **kwargs: Any) -> None:
            super().__init__(master, fg_color="transparent", corner_radius=0, height=MODE_BUTTON_HEIGHT)
            self._values = list(values or ["Einzelgerät", "Serie"])
            self._variable = variable or ctk.StringVar(value=self._values[0])
            self._command = command
            self._buttons: list[Any] = []
            for idx, value in enumerate(self._values):
                btn = ctk.CTkButton(self, text=value, height=MODE_BUTTON_HEIGHT, corner_radius=6, border_width=1, font=ctk.CTkFont(size=10, weight="bold"), command=lambda selected=value: self._select(selected))
                btn.pack(side="left", fill="x", expand=True, padx=(0, 4) if idx == 0 else (4, 0))
                self._buttons.append(btn)
            try:
                self._variable.trace_add("write", lambda *_: self._refresh())
            except Exception:
                pass
            self._refresh()

        def _select(self, value: str) -> None:
            self._variable.set(value)
            self._refresh()
            if callable(self._command):
                self._command(value)

        def _refresh(self) -> None:
            selected = str(self._variable.get())
            for value, btn in zip(self._values, self._buttons):
                active = value == selected
                btn.configure(fg_color="#0B72E7" if active else "#15263A", hover_color="#0862C6" if active else "#1D344C", border_color="#1683F5" if active else "#2A4057")

        def configure(self, *args: Any, **kwargs: Any):
            if "command" in kwargs:
                self._command = kwargs.pop("command")
            if "state" in kwargs:
                state = kwargs.pop("state")
                for btn in self._buttons:
                    btn.configure(state=state)
            if kwargs or args:
                return super().configure(*args, **kwargs)
            return None

        config = configure

        def get(self) -> str:
            return str(self._variable.get())

        def set(self, value: str) -> None:
            self._variable.set(value)
            self._refresh()

    def segmented_button_factory(master: Any, *args: Any, **kwargs: Any):
        values = kwargs.get("values")
        if values == ["Einzelgerät", "Serie"] or values == ("Einzelgerät", "Serie"):
            return ServiceModeSwitch(master, *args, **kwargs)
        return original_segmented_button(master, *args, **kwargs)

    ctk.CTkSegmentedButton = segmented_button_factory  # type: ignore[assignment]

    # Final reference chrome owns the first visible window state. Do not schedule
    # a second maximize transition from the tuning layer; that used to make the
    # application appear to build/open multiple times.
    original_root_init = ctk.CTk.__init__

    def root_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_root_init(self, *args, **kwargs)
        self._jarnsen_ui_tuning_root_initialized = True

    ctk.CTk.__init__ = root_init

    # Keep the root fully withdrawn while the dashboard, brand, proportional card
    # geometry and custom titlebar are assembled. reference_dashboard still asks for
    # a legacy 'zoomed' state during construction; suppress that request until the
    # final single reveal. This is the main fix for the visible three-stage redraw.
    original_state = ctk.CTk.state

    def state(self: Any, newstate: str | None = None):
        startup_hidden = bool(getattr(self, "_jarnsen_startup_hidden", False))
        startup_revealed = bool(getattr(self, "_jarnsen_startup_revealed", False))
        if newstate == "zoomed" and startup_hidden and not startup_revealed:
            try:
                import diagnostics
                diagnostics._emit("STARTUP PAINT suppressed legacy zoomed transition while hidden")
            except Exception:
                pass
            return original_state(self)
        if newstate is None:
            return original_state(self)
        return original_state(self, newstate)

    ctk.CTk.state = state

    # A forced update_idletasks() during hidden startup flushes all pending geometry
    # work and costs a noticeable fraction of startup time. Nothing needs painting
    # while withdrawn, so defer that flush until after the root has been revealed.
    original_update_idletasks = ctk.CTk.update_idletasks

    def update_idletasks(self: Any):
        startup_hidden = bool(getattr(self, "_jarnsen_startup_hidden", False))
        startup_revealed = bool(getattr(self, "_jarnsen_startup_revealed", False))
        if startup_hidden and not startup_revealed:
            return None
        return original_update_idletasks(self)

    ctk.CTk.update_idletasks = update_idletasks

    original_geometry = ctk.CTk.geometry
    def geometry(self: Any, geometry_string: str | None = None):
        if geometry_string and geometry_string.strip().startswith("860x960"):
            try:
                sw = int(self.winfo_screenwidth()); sh = int(self.winfo_screenheight())
                geometry_string = f"{max(1280, sw - 24)}x{max(720, sh - 48)}"
            except Exception:
                geometry_string = "1600x900"
        return original_geometry(self, geometry_string)
    ctk.CTk.geometry = geometry

    original_minsize = ctk.CTk.minsize
    def minsize(self: Any, width: int | None = None, height: int | None = None):
        if width == 780 and height == 820:
            width, height = 1180, 720
        return original_minsize(self, width, height)
    ctk.CTk.minsize = minsize

    try:
        import diagnostics
        diagnostics._emit(
            "UI TUNING installed lightweight=1 native-dashboard=1 automatic-stage-profile=1 "
            f"firmware-status-font={FIRMWARE_STATUS_BASE_FONT_SIZE} firmware-status-icon={FIRMWARE_STATUS_ICON_SIZE} "
            f"profile-action-icon={PROFILE_ACTION_ICON_SIZE} mode-height={MODE_BUTTON_HEIGHT} "
            f"progress-height={PROGRESS_BAR_HEIGHT} reference=1920x1080@125% single-paint=1 hidden-idle-flush=0"
        )
    except Exception:
        pass
