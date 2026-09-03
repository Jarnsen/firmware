from __future__ import annotations

from typing import Any


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def install(services: Any) -> None:
    """Extend the series fallback selector to Tracker, V3 and Wio."""
    import series_profile_guard as guard
    from tkinter import simpledialog

    def manual_board(root: Any, services_arg: Any, info_text: str) -> str | None:
        upper = (info_text or "").upper()
        evidence = any(
            token in upper
            for token in ("OWNER", "METADATA", "FIRMWARE", "MESHTASTIC", "NODE", "PIOENV", "HWMODEL")
        )
        if not evidence:
            return None

        answer = guard._ui_call(
            root,
            lambda: simpledialog.askstring(
                "Serienflash · Board bestätigen",
                "Board konnte nicht eindeutig erkannt werden.\n\n"
                "1 = Heltec Wireless Tracker V1.1\n"
                "2 = Heltec V3\n"
                "3 = Seeed Wio Tracker L1\n\n"
                "Bitte 1, 2 oder 3 eingeben. Abbrechen stoppt die Serie.",
                parent=root,
            ),
        )
        if answer is None:
            _emit("SERIES BOARD MANUAL cancelled")
            return None
        value = str(answer).strip().lower()
        mapping = {
            "1": "tracker",
            "tracker": "tracker",
            "2": "repeater",
            "v3": "repeater",
            "repeater": "repeater",
            "3": "wio",
            "wio": "wio",
            "wio tracker": "wio",
        }
        board_key = mapping.get(value)
        if board_key not in services_arg.BOARD_PROFILES:
            _emit(f"SERIES BOARD MANUAL invalid={answer!r}")
            return None
        _emit(f"SERIES BOARD MANUAL confirmed={board_key!r}")
        return board_key

    guard._manual_board = manual_board
    _emit("WIO SERIES SUPPORT installed: 3-board manual confirmation")
