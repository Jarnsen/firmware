from __future__ import annotations

from pathlib import Path


def configure_runtime() -> None:
    """Apply Windows runtime paths and detailed diagnostics before the GUI imports services."""
    try:
        import services

        log_dir = (
            Path.home()
            / "Downloads"
            / "Meshtastic-Logs"
            / "JARNSEN-MESHFLASHER"
        )
        log_dir.mkdir(parents=True, exist_ok=True)
        services.PATHS.logs = log_dir

        # Install low-level diagnostics before app.py imports the service functions.
        # This makes serial/Meshtastic/esptool/GitHub details land in the same
        # flasher-*.log file that is shown by the GUI.
        from diagnostics import install

        install(services, log_dir)
    except Exception:
        # Diagnostics must never prevent the flasher from starting.
        pass
