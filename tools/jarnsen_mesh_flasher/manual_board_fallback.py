from __future__ import annotations

from typing import Any

import customtkinter as ctk


_INSTALLED = False
_PREFERRED_ORDER = (
    "tracker",
    "repeater",
    "wio",
    "heltec_v4",
    "tbeam",
    "tbeam_supreme",
)


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _board_values(services: Any) -> list[str]:
    values = ["Automatisch"]
    seen: set[str] = set()
    for key in _PREFERRED_ORDER:
        profile = services.BOARD_PROFILES.get(key)
        if not profile:
            continue
        label = str(profile.get("label") or key).strip()
        if label and label not in seen:
            values.append(label)
            seen.add(label)
    for key, profile in services.BOARD_PROFILES.items():
        label = str(profile.get("label") or key).strip()
        if label and label not in seen:
            values.append(label)
            seen.add(label)
    return values


def _manual_board_key(app: Any, services: Any) -> str | None:
    try:
        manual = str(app.board_var.get() or "").strip()
    except Exception:
        manual = ""
    if manual and manual != "Automatisch":
        for key, profile in services.BOARD_PROFILES.items():
            if manual == str(profile.get("label") or "").strip():
                return key
    return None


def install(services: Any) -> None:
    """Expose every supported board as a safe manual fallback.

    Original Meshtastic firmware can expose a serial port before `meshtastic --info`
    gives us a unique physical board identity. Auto detection remains preferred, but
    the operator must still be able to select T-Beam/T-Beam Supreme explicitly and
    continue with the normal full-flash safety path.
    """

    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    available_values = _board_values(services)
    label_to_key = {
        str(profile.get("label") or "").strip(): key
        for key, profile in services.BOARD_PROFILES.items()
        if str(profile.get("label") or "").strip()
    }

    original_root_init = ctk.CTk.__init__

    def root_init(app: Any, *args: Any, **kwargs: Any) -> None:
        original_root_init(app, *args, **kwargs)

        # FlasherApp is already a complete Python class when the CTk base
        # constructor runs. Replace only this application's instance resolver;
        # unrelated CTk windows remain untouched.
        original_resolver = getattr(app, "_selected_board_key", None)
        if not callable(original_resolver):
            return

        def selected_board_key() -> str | None:
            manual = _manual_board_key(app, services)
            if manual:
                return manual
            return original_resolver()

        app._selected_board_key = selected_board_key
        app._jarnsen_manual_board_fallback = True
        app._jarnsen_manual_board_values = tuple(available_values)

    ctk.CTk.__init__ = root_init

    original_option_init = ctk.CTkOptionMenu.__init__

    def option_init(self: Any, master: Any, *args: Any, **kwargs: Any) -> None:
        values = list(kwargs.get("values") or [])
        variable = kwargs.get("variable")
        current = ""
        try:
            current = str(variable.get() or "") if variable is not None else ""
        except Exception:
            current = ""

        looks_like_board_menu = (
            current == "Automatisch"
            and "Automatisch" in values
            and any(label in values for label in label_to_key)
        )
        if looks_like_board_menu:
            kwargs["values"] = list(available_values)
            original_command = kwargs.get("command")

            def board_changed(value: str) -> None:
                # Preserve the original invalidation/UI callback. The instance
                # resolver above reads board_var directly, so no device object
                # needs to be mutated merely to honor a manual fallback.
                if callable(original_command):
                    original_command(value)
                try:
                    app = master.winfo_toplevel()
                    app._jarnsen_manual_board_values = tuple(available_values)
                    key = label_to_key.get(str(value or "").strip())
                    if key:
                        app._append_log(
                            f"BOARD MANUELL · {services.BOARD_PROFILES[key]['label']} ausgewählt · "
                            "Auto-Erkennung wird für diesen Flash übersteuert"
                        )
                except Exception:
                    pass

            kwargs["command"] = board_changed

        original_option_init(self, master, *args, **kwargs)

    ctk.CTkOptionMenu.__init__ = option_init
    _emit(
        "MANUAL BOARD FALLBACK installed values="
        + ", ".join(available_values)
    )
