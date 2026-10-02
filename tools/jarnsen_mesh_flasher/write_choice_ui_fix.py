from __future__ import annotations

from typing import Any

import customtkinter as ctk

_INSTALLED = False


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _center_on_parent(dialog: Any, parent: Any, width: int, height: int) -> None:
    try:
        parent.update_idletasks()
    except Exception:
        pass
    try:
        dialog.update_idletasks()
    except Exception:
        pass

    try:
        px = int(parent.winfo_rootx())
        py = int(parent.winfo_rooty())
        pw = int(parent.winfo_width())
        ph = int(parent.winfo_height())
    except Exception:
        px = py = 0
        pw = ph = 0

    if pw < 300 or ph < 250:
        try:
            pw = int(dialog.winfo_screenwidth())
            ph = int(dialog.winfo_screenheight())
        except Exception:
            pw, ph = 1280, 720
        px = py = 0

    width = min(width, max(560, pw - 80))
    height = min(height, max(320, ph - 80))
    x = px + max(0, (pw - width) // 2)
    y = py + max(0, (ph - height) // 2)
    dialog.geometry(f"{width}x{height}+{x}+{y}")


def _two_choice_centered(
    parent: Any,
    *,
    title: str,
    heading: str,
    details: str,
    left_text: str,
    right_text: str,
) -> str | None:
    result: dict[str, str | None] = {"value": None}
    is_names = "name" in title.casefold() or "name" in heading.casefold()
    width = 780 if is_names else 720
    height = 430 if is_names else 370

    dialog = ctk.CTkToplevel(parent)
    dialog.withdraw()
    dialog.title(title)
    dialog.resizable(False, False)
    try:
        dialog.transient(parent)
    except Exception:
        pass

    shell = ctk.CTkFrame(dialog, corner_radius=16)
    shell.pack(fill="both", expand=True, padx=20, pady=20)

    ctk.CTkLabel(
        shell,
        text=heading,
        font=ctk.CTkFont(size=20, weight="bold"),
        anchor="w",
        justify="left",
    ).pack(fill="x", padx=24, pady=(22, 12))

    detail_wrap = ctk.CTkFrame(shell, corner_radius=10, fg_color=("#F3F6F9", "#111E2C"))
    detail_wrap.pack(fill="both", expand=True, padx=24, pady=(0, 18))
    ctk.CTkLabel(
        detail_wrap,
        text=details,
        font=ctk.CTkFont(size=14),
        anchor="nw",
        justify="left",
        wraplength=680 if is_names else 620,
    ).pack(fill="both", expand=True, padx=18, pady=16)

    buttons = ctk.CTkFrame(shell, fg_color="transparent")
    buttons.pack(fill="x", padx=24, pady=(0, 22))
    buttons.grid_columnconfigure(0, weight=1, uniform="write-choice")
    buttons.grid_columnconfigure(1, weight=1, uniform="write-choice")

    def finish(value: str | None) -> None:
        result["value"] = value
        try:
            dialog.grab_release()
        except Exception:
            pass
        try:
            dialog.destroy()
        except Exception:
            pass

    ctk.CTkButton(
        buttons,
        text=left_text,
        height=50,
        corner_radius=10,
        font=ctk.CTkFont(size=14, weight="bold"),
        command=lambda: finish("left"),
    ).grid(row=0, column=0, sticky="ew", padx=(0, 7))

    ctk.CTkButton(
        buttons,
        text=right_text,
        height=50,
        corner_radius=10,
        font=ctk.CTkFont(size=14, weight="bold"),
        command=lambda: finish("right"),
    ).grid(row=0, column=1, sticky="ew", padx=(7, 0))

    dialog.protocol("WM_DELETE_WINDOW", lambda: finish(None))
    dialog.bind("<Escape>", lambda _event: finish(None))

    _center_on_parent(dialog, parent, width, height)
    dialog.deiconify()
    try:
        dialog.lift()
        dialog.grab_set()
        dialog.focus_force()
    except Exception:
        pass

    parent.wait_window(dialog)
    return result["value"]


_two_choice_centered._jarnsen_centered = True  # type: ignore[attr-defined]
_two_choice_centered._jarnsen_full_name_layout = True  # type: ignore[attr-defined]


def _install_profile_only_button_bridge() -> None:
    """Expose the reference-dashboard profile-only button on the app object.

    write_choice_guard intentionally binds to app.profile_only_button so the same
    role/name resolver protects both full flashes and profile-only writes.  The
    reference dashboard created the button but did not publish that attribute,
    leaving profile-only writes unguarded.  Capture only that exact button while
    it is constructed; all other CTkButton instances remain untouched.
    """
    original_init = ctk.CTkButton.__init__
    if getattr(original_init, "_jarnsen_profile_only_bridge", False):
        return

    def button_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_init(self, *args, **kwargs)
        try:
            text = str(self.cget("text") or "").replace("\n", " ").strip().casefold()
            if text != "nur profil schreiben":
                return
            root = self.winfo_toplevel()
            root.profile_only_button = self
            _emit("WRITE CHOICE PROFILE BUTTON bridge attached=1")
        except Exception as exc:
            _emit(
                f"WRITE CHOICE PROFILE BUTTON bridge skipped {type(exc).__name__}:{exc}"
            )

    button_init._jarnsen_profile_only_bridge = True  # type: ignore[attr-defined]
    ctk.CTkButton.__init__ = button_init
    _emit("WRITE CHOICE PROFILE BUTTON bridge installed=1")


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    import write_choice_guard

    _install_profile_only_button_bridge()
    write_choice_guard._two_choice = _two_choice_centered
    _emit(
        "WRITE CHOICE UI FIX installed centered-on-app=1 role-size=720x370 "
        "names-size=780x430 full-name-wrap=1 profile-only-bridge=1"
    )
