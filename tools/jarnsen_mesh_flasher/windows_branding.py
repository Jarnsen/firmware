from __future__ import annotations

import ctypes
import sys
from pathlib import Path

APP_USER_MODEL_ID = "Jarnsen.MeshFlasher"
ICON_NAME = "jarnsen_mesh_flasher_icon.ico"


def _asset_path() -> Path:
    if getattr(sys, "frozen", False):
        root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        root = Path(__file__).resolve().parent
    return root / "assets" / ICON_NAME


def _set_app_user_model_id() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass


def configure_windows_branding() -> None:
    """Keep the branded icon consistent for the EXE, window and Windows taskbar."""
    if sys.platform != "win32":
        return

    _set_app_user_model_id()

    try:
        import customtkinter as ctk
    except Exception:
        return

    if getattr(ctk.CTk, "_jarnsen_branding_installed", False):
        return

    original_init = ctk.CTk.__init__

    def branded_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)

        def apply_icon() -> None:
            icon_path = _asset_path()
            if not icon_path.exists():
                return
            try:
                self.iconbitmap(default=str(icon_path))
            except Exception:
                pass

        # CustomTkinter may apply its own icon shortly after window creation.
        # Apply ours immediately and again after that delayed initialization.
        apply_icon()
        try:
            self.after(300, apply_icon)
            self.after(1200, apply_icon)
        except Exception:
            pass

    ctk.CTk.__init__ = branded_init
    ctk.CTk._jarnsen_branding_installed = True
