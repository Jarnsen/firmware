from __future__ import annotations

import sys
from pathlib import Path


def configure_runtime() -> None:
    """Apply Windows runtime paths, bundled helper lookup and diagnostics before GUI imports."""
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

        # Release builds contain _JarnsenMeshHelper.exe inside the one-file app.
        # PyInstaller extracts it into sys._MEIPASS at runtime, so the user only
        # needs a single visible flasher EXE.
        if getattr(sys, "frozen", False):
            bundle_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))

            def bundled_helper_command() -> list[str]:
                helper = bundle_root / "_JarnsenMeshHelper.exe"
                if not helper.exists():
                    raise services.FlasherError(f"Eingebetteter Helper fehlt: {helper}")
                return [str(helper)]

            services.helper_command = bundled_helper_command

        # Install low-level diagnostics before app.py imports the service functions.
        # This makes serial/Meshtastic/esptool/GitHub details land in the same
        # flasher-*.log file that is shown by the GUI.
        from diagnostics import install

        install(services, log_dir)

        # Build 21 showed that a one-shot pyserial scan can finish before the
        # asynchronous Windows PnP snapshot has any useful result.  Replace it
        # with an active 5-second wired/USB discovery pass that also consumes
        # Windows PnP information synchronously.
        from serial_probe import install as install_serial_probe

        install_serial_probe(services)
    except Exception:
        # Runtime setup/diagnostics must never prevent the flasher from starting.
        pass
