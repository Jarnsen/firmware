from __future__ import annotations

from typing import Any

import customtkinter as ctk


BUTTON_HEIGHT = 36
SMALL_BUTTON_HEIGHT = 34
MIN_LOG_HEIGHT = 118


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


def _req_height(widget: Any, fallback: int) -> int:
    if widget is None:
        return fallback
    try:
        widget.update_idletasks()
        return max(fallback, int(widget.winfo_reqheight()) + 8)
    except Exception:
        return fallback


def install(services: Any) -> None:
    """Final geometry guard after all injected dashboard controls exist."""
    original_root_init = ctk.CTk.__init__

    def root_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_root_init(self, *args, **kwargs)

        def patch_app(attempt: int = 0) -> None:
            if getattr(self, "_jarnsen_overlap_guard_installed", False):
                return
            if not hasattr(self, "body") or not hasattr(self, "log_box"):
                if attempt < 30:
                    try:
                        self.after(180, patch_app, attempt + 1)
                    except Exception:
                        pass
                return

            profile_card = _find_card(self, ("2 · GRUNDEINSTELLUNGEN",))
            firmware_card = _find_card(self, ("3 · FIRMWARE",))
            device_card = _find_card(self, ("1 · GERÄT",))
            identity_card = _find_card(self, ("4 · IDENTITÄT", "4 · GERÄTENAME"))
            action_card = _find_card(self, ("5 · AUTOMATISCHER ABLAUF",))
            log_card = _find_card(self, ("PROTOKOLL",))

            required_buttons = {
                "MASTER EINLESEN",
                "PROFIL AUSWÄHLEN",
                "NUR PROFIL SCHREIBEN",
                "PROFIL BEARBEITEN",
                "NEUESTE PRÜFEN",
                "NUR FIRMWARE UPDATEN",
                "DATEI VOM PC",
            }
            visible = {_text(widget) for widget in _walk(self) if isinstance(widget, ctk.CTkButton)}
            if not required_buttons.issubset(visible):
                if attempt < 30:
                    try:
                        self.after(180, patch_app, attempt + 1)
                    except Exception:
                        pass
                return

            self._jarnsen_overlap_guard_installed = True
            try:
                self.update_idletasks()
            except Exception:
                pass

            # Keep all action buttons readable and identical in height. Service and
            # protocol utility buttons are intentionally one small step shorter.
            full_height_labels = {
                "MASTER EINLESEN",
                "PROFIL AUSWÄHLEN",
                "NUR PROFIL SCHREIBEN",
                "PROFIL BEARBEITEN",
                "NEUESTE PRÜFEN",
                "NUR FIRMWARE UPDATEN",
                "DATEI VOM PC",
            }
            small_height_labels = {
                "NODE-LOG USB",
                "INFO LESEN",
                "NEUSTART",
                "Neu suchen",
                "PROTOKOLL GROSS",
                "PROTOKOLL KOMPAKT",
                "KOPIEREN",
                "LOGORDNER",
            }
            for widget in _walk(self):
                if not isinstance(widget, ctk.CTkButton):
                    continue
                label = _text(widget)
                try:
                    if label in full_height_labels:
                        widget.configure(height=BUTTON_HEIGHT, corner_radius=8)
                    elif label in small_height_labels:
                        widget.configure(height=SMALL_BUTTON_HEIGHT, corner_radius=8)
                except Exception:
                    pass

            # Measure the actual cards after ui_action_polish created its 2x2 and
            # 3-column action groups. Grid rows are then sized from the real
            # requested height instead of hard-coded estimates.
            row0 = max(
                _req_height(device_card, 220),
                _req_height(identity_card, 150),
            )
            row1 = _req_height(profile_card, 205)
            row2 = _req_height(firmware_card, 205)
            action_need = _req_height(action_card, 260)
            if row1 + row2 < action_need:
                missing = action_need - (row1 + row2)
                row1 += missing // 2
                row2 += missing - (missing // 2)

            try:
                body_height = max(1, int(self.body.winfo_height()))
            except Exception:
                body_height = 760

            # Protocol is the flexible area. It gives space back first so profile
            # and firmware action rows can never be covered by the following card.
            fixed = row0 + row1 + row2 + 28
            remaining = body_height - fixed
            row3 = max(MIN_LOG_HEIGHT, min(180, remaining))

            try:
                self.body.grid_rowconfigure(0, weight=0, minsize=row0)
                self.body.grid_rowconfigure(1, weight=0, minsize=row1)
                self.body.grid_rowconfigure(2, weight=0, minsize=row2)
                self.body.grid_rowconfigure(3, weight=1, minsize=row3)
                self.log_box.configure(height=max(92, row3 - 58))
            except Exception:
                pass

            # A second idle pass catches Windows DPI/layout recalculation after the
            # maximized window has reached its final logical size.
            def verify() -> None:
                try:
                    self.update_idletasks()
                    profile_actual = int(profile_card.winfo_height()) if profile_card is not None else 0
                    firmware_actual = int(firmware_card.winfo_height()) if firmware_card is not None else 0
                    profile_required = int(profile_card.winfo_reqheight()) if profile_card is not None else 0
                    firmware_required = int(firmware_card.winfo_reqheight()) if firmware_card is not None else 0
                    if profile_required > profile_actual:
                        self.body.grid_rowconfigure(1, minsize=profile_required + 10)
                    if firmware_required > firmware_actual:
                        self.body.grid_rowconfigure(2, minsize=firmware_required + 10)
                    _emit(
                        "UI OVERLAP GUARD VERIFY "
                        f"body={body_height} rows={row0}/{row1}/{row2}/{row3} "
                        f"profile={profile_actual}/{profile_required} "
                        f"firmware={firmware_actual}/{firmware_required}"
                    )
                except Exception as exc:
                    _emit(f"UI OVERLAP GUARD VERIFY ERROR type={type(exc).__name__} message={exc}")

            try:
                self.after_idle(verify)
            except Exception:
                pass

            _emit(
                "UI OVERLAP GUARD installed "
                f"body={body_height} rows={row0}/{row1}/{row2}/{row3} "
                "profile-actions=2x2 firmware-actions=1x3"
            )

        try:
            self.after(1250, patch_app)
        except Exception:
            pass

    ctk.CTk.__init__ = root_init
    _emit("UI OVERLAP GUARD layer installed auto-card-height=1")
