from __future__ import annotations

import shutil
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
        # asynchronous Windows PnP snapshot has any useful result. Replace it
        # with an active 5-second wired/USB discovery pass that also consumes
        # Windows PnP information synchronously.
        from serial_probe import install as install_serial_probe

        install_serial_probe(services)

        # Save human-readable profile archives. active-profile.yaml remains only
        # the internal working copy used for restore/series flashing.
        from profile_utils import (
            rename_profile_archive,
            summary_from_info_text,
            summary_from_profile_file,
        )

        original_export_profile = services.export_profile

        def descriptive_export_profile(port: str) -> Path:
            path = original_export_profile(port)
            summary = summary_from_profile_file(path)
            if not (summary.long_name and summary.short_name and summary.role):
                try:
                    result = services.meshtastic(port, "--info", timeout=45, check=False)
                    info_text = "\n".join(filter(None, (result.stdout, result.stderr)))
                    summary = summary.with_fallback(summary_from_info_text(info_text))
                except Exception:
                    pass

            named_path = rename_profile_archive(path, summary)
            # Keep the internal active profile synchronized with the renamed
            # archive. The user-facing archive keeps ROLE/LONG/SHORT in its name.
            shutil.copy2(named_path, services.PATHS.active_profile)
            try:
                import diagnostics

                diagnostics._emit(
                    "PROFILE ARCHIVE SAVED "
                    f"file={named_path.name!r} role={summary.role!r} "
                    f"long={summary.long_name!r} short={summary.short_name!r}"
                )
            except Exception:
                pass
            return named_path

        services.export_profile = descriptive_export_profile

        # The profile chooser should always open directly in the app's profile
        # directory instead of the last arbitrary Explorer location.
        try:
            from tkinter import filedialog

            original_askopenfilename = filedialog.askopenfilename

            def profile_askopenfilename(*args, **kwargs):
                kwargs.setdefault("initialdir", str(services.PATHS.profiles))
                if kwargs.get("title") == "Meshtastic Profil laden":
                    kwargs["title"] = "Meshtastic Profil auswählen"
                return original_askopenfilename(*args, **kwargs)

            filedialog.askopenfilename = profile_askopenfilename
        except Exception:
            pass

        # Keep the UI wording aligned with the action without touching any other
        # buttons. customtkinter is already imported before _build_version loads
        # this runtime configuration.
        try:
            import customtkinter as ctk

            original_button_init = ctk.CTkButton.__init__

            def button_init(self, *args, **kwargs):
                if kwargs.get("text") == "Profil laden":
                    kwargs["text"] = "Profil auswählen"
                original_button_init(self, *args, **kwargs)

            ctk.CTkButton.__init__ = button_init
        except Exception:
            pass
    except Exception:
        # Runtime setup/diagnostics must never prevent the flasher from starting.
        pass
