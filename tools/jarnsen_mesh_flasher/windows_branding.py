from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Any

APP_USER_MODEL_ID = "Jarnsen.MeshFlasher"
ICON_NAME = "jarnsen_mesh_flasher_icon.ico"

GWL_EXSTYLE = -20
GWLP_HWNDPARENT = -8
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_NOACTIVATE = 0x08000000

SW_HIDE = 0
SW_SHOW = 5
SW_RESTORE = 9

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020

HWND_TOPMOST = -1
HWND_NOTOPMOST = -2


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


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _user32():
    user32 = ctypes.windll.user32
    hwnd_t = wintypes.HWND
    user32.GetParent.argtypes = [hwnd_t]
    user32.GetParent.restype = hwnd_t
    user32.IsWindow.argtypes = [hwnd_t]
    user32.IsWindow.restype = wintypes.BOOL
    user32.GetWindowLongW.argtypes = [hwnd_t, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW.argtypes = [hwnd_t, ctypes.c_int, ctypes.c_long]
    user32.SetWindowLongW.restype = ctypes.c_long
    user32.ShowWindow.argtypes = [hwnd_t, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.BringWindowToTop.argtypes = [hwnd_t]
    user32.BringWindowToTop.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [hwnd_t]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [
        hwnd_t,
        hwnd_t,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL
    return user32


def _window_hwnd(window: Any) -> int | None:
    if sys.platform != "win32":
        return None
    try:
        user32 = _user32()
        try:
            window.update_idletasks()
        except Exception:
            pass
        widget_hwnd = int(window.winfo_id())
        parent = user32.GetParent(wintypes.HWND(widget_hwnd))
        parent_hwnd = int(parent or 0)
        for hwnd in (parent_hwnd, widget_hwnd):
            if hwnd and bool(user32.IsWindow(wintypes.HWND(hwnd))):
                return hwnd
    except Exception:
        pass
    return None


def _clear_owner(user32: Any, hwnd: int) -> None:
    try:
        set_long_ptr = getattr(user32, "SetWindowLongPtrW", None)
        if set_long_ptr is not None:
            set_long_ptr.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
            set_long_ptr.restype = ctypes.c_void_p
            set_long_ptr(wintypes.HWND(hwnd), GWLP_HWNDPARENT, None)
        else:
            user32.SetWindowLongW(wintypes.HWND(hwnd), GWLP_HWNDPARENT, 0)
    except Exception:
        pass


def ensure_taskbar_window(
    window: Any,
    *,
    activate: bool = False,
    refresh_taskbar: bool = False,
) -> bool:
    """Give a borderless Tk root a normal Windows taskbar identity and activation."""
    if sys.platform != "win32":
        return False

    _set_app_user_model_id()
    hwnd = _window_hwnd(window)
    if not hwnd:
        return False

    try:
        user32 = _user32()
        handle = wintypes.HWND(hwnd)
        ex_style = int(user32.GetWindowLongW(handle, GWL_EXSTYLE))
        wanted = (ex_style & ~WS_EX_TOOLWINDOW & ~WS_EX_NOACTIVATE) | WS_EX_APPWINDOW
        if wanted != ex_style:
            user32.SetWindowLongW(handle, GWL_EXSTYLE, wanted)

        # A Tk override-redirect root can acquire an owner window, which makes
        # Windows treat it like a tool/dialog and omit it from the taskbar.
        _clear_owner(user32, hwnd)

        user32.SetWindowPos(
            handle,
            wintypes.HWND(0),
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )

        if refresh_taskbar:
            # During the single-paint startup the root is still alpha=0 here,
            # so this hidden/show cycle refreshes the taskbar without a visible
            # second window paint.
            user32.ShowWindow(handle, SW_HIDE)
            user32.ShowWindow(handle, SW_SHOW)

        if activate:
            user32.ShowWindow(handle, SW_RESTORE)
            try:
                user32.AllowSetForegroundWindow(-1)
            except Exception:
                pass
            user32.BringWindowToTop(handle)

            # A short topmost/not-topmost pulse reliably places the just-launched
            # app above existing windows without leaving it permanently topmost.
            user32.SetWindowPos(
                handle,
                wintypes.HWND(HWND_TOPMOST),
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE,
            )
            user32.SetWindowPos(
                handle,
                wintypes.HWND(HWND_NOTOPMOST),
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE,
            )
            user32.SetForegroundWindow(handle)
            window._jarnsen_taskbar_activated = True

        window._jarnsen_windows_hwnd = hwnd
        _emit(
            "WINDOW IDENTITY "
            f"hwnd={hwnd} taskbar=1 activate={int(bool(activate))} "
            f"refresh={int(bool(refresh_taskbar))}"
        )
        return True
    except Exception as exc:
        _emit(
            f"WINDOW IDENTITY failed type={type(exc).__name__} message={exc}"
        )
        return False


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
    original_deiconify = ctk.CTk.deiconify
    original_overrideredirect = ctk.CTk.overrideredirect

    def branded_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)

        def apply_icon() -> None:
            icon_path = _asset_path()
            if icon_path.exists():
                try:
                    self.iconbitmap(default=str(icon_path))
                except Exception:
                    pass
            ensure_taskbar_window(self, activate=False, refresh_taskbar=False)

        def foreground_fallback() -> None:
            if bool(getattr(self, "_jarnsen_taskbar_activated", False)):
                return
            ensure_taskbar_window(self, activate=True, refresh_taskbar=False)

        # CustomTkinter and the custom borderless chrome both touch window
        # styles shortly after construction. Reassert the app identity after
        # those transitions as a fallback.
        apply_icon()
        try:
            self.after(300, apply_icon)
            self.after(1200, apply_icon)
            self.after(1800, foreground_fallback)
        except Exception:
            pass

    def branded_deiconify(self):
        result = original_deiconify(self)
        transparent_startup = bool(
            getattr(self, "_jarnsen_startup_alpha_hidden", False)
        )
        ensure_taskbar_window(
            self,
            activate=False,
            refresh_taskbar=transparent_startup,
        )

        def activate_after_reveal() -> None:
            ensure_taskbar_window(self, activate=True, refresh_taskbar=False)

        try:
            self.after_idle(activate_after_reveal)
        except Exception:
            activate_after_reveal()
        return result

    def branded_overrideredirect(self, boolean=None):
        if boolean is None:
            return original_overrideredirect(self)
        result = original_overrideredirect(self, boolean)
        try:
            self.after_idle(
                lambda: ensure_taskbar_window(
                    self,
                    activate=False,
                    refresh_taskbar=False,
                )
            )
        except Exception:
            pass
        return result

    ctk.CTk.__init__ = branded_init
    ctk.CTk.deiconify = branded_deiconify
    ctk.CTk.overrideredirect = branded_overrideredirect
    ctk.CTk._jarnsen_branding_installed = True
    _emit("WINDOW BRANDING installed taskbar=1 foreground-on-reveal=1")
