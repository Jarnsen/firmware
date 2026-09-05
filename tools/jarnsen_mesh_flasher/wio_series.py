from __future__ import annotations

from typing import Any


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def install(services: Any) -> None:
    """Extend series/manual board handling to every Unified-Core board."""
    # This layer is intentionally last in runtime_config, so finalize the board
    # catalog only after the Wio/artifact/flash layers have installed their base
    # behavior. app.py imports the resulting service functions immediately after
    # configure_runtime() returns.
    from unified_board_support import install as install_unified_board_support

    install_unified_board_support(services)

    import series_profile_guard as guard
    from tkinter import simpledialog

    def manual_board(root: Any, services_arg: Any, info_text: str) -> str | None:
        upper = (info_text or "").upper()
        evidence = any(
            token in upper
            for token in (
                "OWNER",
                "METADATA",
                "FIRMWARE",
                "MESHTASTIC",
                "NODE",
                "PIOENV",
                "HWMODEL",
                "HARDWARE",
            )
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
                "3 = Seeed Wio Tracker L1\n"
                "4 = Heltec V4\n"
                "5 = LILYGO T-Beam\n"
                "6 = LILYGO T-Beam Supreme\n\n"
                "Bitte 1 bis 6 eingeben. Abbrechen stoppt die Serie.",
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
            "heltec tracker": "tracker",
            "2": "repeater",
            "v3": "repeater",
            "heltec v3": "repeater",
            "repeater": "repeater",
            "3": "wio",
            "wio": "wio",
            "wio tracker": "wio",
            "4": "heltec_v4",
            "v4": "heltec_v4",
            "heltec v4": "heltec_v4",
            "5": "tbeam",
            "t-beam": "tbeam",
            "tbeam": "tbeam",
            "lilygo t-beam": "tbeam",
            "6": "tbeam_supreme",
            "supreme": "tbeam_supreme",
            "t-beam supreme": "tbeam_supreme",
            "tbeam supreme": "tbeam_supreme",
            "lilygo t-beam supreme": "tbeam_supreme",
        }
        board_key = mapping.get(value)
        if board_key not in services_arg.BOARD_PROFILES:
            _emit(f"SERIES BOARD MANUAL invalid={answer!r}")
            return None
        _emit(f"SERIES BOARD MANUAL confirmed={board_key!r}")
        return board_key

    guard._manual_board = manual_board
    _emit(
        "UNIFIED SERIES SUPPORT installed: 6-board manual confirmation "
        "Tracker/V3/Wio/V4/T-Beam/T-Beam-Supreme"
    )
