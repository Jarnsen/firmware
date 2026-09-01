from __future__ import annotations

from pathlib import Path


def configure_runtime() -> None:
    """Apply Windows runtime paths before the main app imports PATHS."""
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
    except Exception:
        # Logging must never block the flasher from starting.
        pass
