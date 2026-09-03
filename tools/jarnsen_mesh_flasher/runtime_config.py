from __future__ import annotations

import shutil
import sys
from pathlib import Path


def configure_runtime() -> None:
    """Apply Windows runtime paths, board/profile guards and diagnostics before GUI imports."""
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
        if getattr(sys, "frozen", False):
            bundle_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))

            def bundled_helper_command() -> list[str]:
                helper = bundle_root / "_JarnsenMeshHelper.exe"
                if not helper.exists():
                    raise services.FlasherError(f"Eingebetteter Helper fehlt: {helper}")
                return [str(helper)]

            services.helper_command = bundled_helper_command

        # Detailed diagnostics first, so all following runtime layers can log.
        from diagnostics import install

        install(services, log_dir)

        # Replace the old first-token board guess with structured hwModel/model
        # parsing plus confidence scoring. Ambiguous evidence returns None.
        from board_detection import install as install_board_detection

        install_board_detection(services)

        # Active 5-second USB/serial discovery. It calls services.detect_board...
        # dynamically, therefore it uses the stronger detector installed above.
        from serial_probe import install as install_serial_probe

        install_serial_probe(services)

        from profile_catalog import (
            board_for_profile,
            copy_profile_assignment,
            register_profile,
        )
        from profile_utils import (
            rename_profile_archive,
            summary_from_info_text,
            summary_from_profile_file,
        )

        # Save human-readable profile archives and persist which board each
        # profile belongs to. active-profile.yaml remains the internal restore
        # copy but receives the same board assignment in profile-catalog.json.
        original_export_profile = services.export_profile

        def descriptive_export_profile(port: str) -> Path:
            path = original_export_profile(port)
            summary = summary_from_profile_file(path)
            info_text = ""
            board_key = None
            try:
                result = services.meshtastic(port, "--info", timeout=45, check=False)
                info_text = "\n".join(filter(None, (result.stdout, result.stderr)))
                summary = summary.with_fallback(summary_from_info_text(info_text))
                board_key = services.detect_board_from_text(info_text)
            except Exception:
                pass

            named_path = rename_profile_archive(path, summary)
            shutil.copy2(named_path, services.PATHS.active_profile)

            if board_key in services.BOARD_PROFILES:
                register_profile(named_path, board_key, summary, source=f"master:{port}")
                register_profile(
                    services.PATHS.active_profile,
                    board_key,
                    summary,
                    source=f"active-from:{named_path.name}",
                )

            try:
                import diagnostics

                diagnostics._emit(
                    "PROFILE ARCHIVE SAVED "
                    f"file={named_path.name!r} board={board_key!r} role={summary.role!r} "
                    f"long={summary.long_name!r} short={summary.short_name!r}"
                )
            except Exception:
                pass
            return named_path

        services.export_profile = descriptive_export_profile

        # Preserve board assignment when the user selects a stored profile.
        original_import_profile = services.import_profile_file

        def catalog_import_profile(source: Path) -> Path:
            source = Path(source)
            selected = original_import_profile(source)
            assigned = board_for_profile(source)
            if assigned:
                copy_profile_assignment(source, services.PATHS.active_profile)
            try:
                import diagnostics

                diagnostics._emit(
                    "PROFILE IMPORT "
                    f"source={source.name!r} board={assigned!r} active={services.PATHS.active_profile.name!r}"
                )
            except Exception:
                pass
            return selected

        services.import_profile_file = catalog_import_profile

        # The profile chooser always starts in the application's profile folder.
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

        # Keep the UI wording aligned with the action.
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

        # During series flashing this layer compares the newly detected board
        # with active-profile.yaml. On a board switch (Tracker <-> V3) it opens
        # a profile selection dialog before the existing flash worker can erase
        # anything. Wrong-board profiles are rejected.
        from series_profile_guard import install as install_series_profile_guard

        install_series_profile_guard(services)

    except Exception:
        # Runtime setup/diagnostics must never prevent the flasher from starting.
        pass
