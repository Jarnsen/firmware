from __future__ import annotations

import re
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

        # The selected profile is a visible, named file. The restore working
        # copy is intentionally internal and never shown in the profile manager.
        services.AppPaths.active_profile = property(
            lambda self: self.profiles / ".active-profile.yaml"
        )

        # Firmware display must use the build carried by the JARNSEN-MESH
        # artifact name itself, not merely a generic GitHub Actions run label.
        def firmware_build_number(bundle) -> int:
            match = re.search(r"-Build-(\d+)$", str(bundle.artifact_name), re.IGNORECASE)
            if match:
                return int(match.group(1))
            return int(bundle.run_number)

        def firmware_display_name(bundle) -> str:
            build = firmware_build_number(bundle)
            return (
                f"{bundle.product} v{bundle.version} · Build {build} · "
                f"{services.BOARD_PROFILES[bundle.board_key]['label']}"
            )

        services.FirmwareBundle.build_number = property(firmware_build_number)
        services.FirmwareBundle.display_name = property(firmware_display_name)

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

        # Compact the main app for a 1920x1080 desktop before app.py creates
        # any CustomTkinter widgets. Dialogs remain independently sized.
        from ui_tuning import install as install_ui_tuning

        install_ui_tuning(services)

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
        from profile_manager import (
            choose_profile_for_app,
            migrate_internal_active_profile,
            migrate_legacy_master_profiles,
            read_master_profile_for_app,
            select_profile_dialog,
            store_exported_profile,
        )
        from profile_utils import summary_from_info_text, summary_from_profile_file

        services.PATHS.profiles.mkdir(parents=True, exist_ok=True)
        (services.PATHS.profiles / "archive").mkdir(parents=True, exist_ok=True)
        migrate_internal_active_profile(services)
        migrate_legacy_master_profiles(services)

        # Save one stable visible profile per ROLE/LONG/SHORT. Re-reading the
        # same profile archives the previous revision with a timestamp.
        original_export_profile = services.export_profile

        def descriptive_export_profile(port: str) -> Path:
            raw_path = original_export_profile(port)
            summary = summary_from_profile_file(raw_path)
            info_text = ""
            board_key = None
            try:
                result = services.meshtastic(port, "--info", timeout=45, check=False)
                info_text = "\n".join(filter(None, (result.stdout, result.stderr)))
                summary = summary.with_fallback(summary_from_info_text(info_text))
                board_key = services.detect_board_from_text(info_text)
            except Exception:
                pass

            named_path = store_exported_profile(
                raw_path,
                summary,
                board_key,
                services,
                source=f"master:{port}",
            )
            return named_path

        services.export_profile = descriptive_export_profile

        # Selecting a visible profile updates the internal restore copy, while
        # returning the visible source path so the UI never displays .active-profile.
        original_import_profile = services.import_profile_file

        def catalog_import_profile(source: Path) -> Path:
            source = Path(source)
            original_import_profile(source)
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
            return source

        services.import_profile_file = catalog_import_profile

        # Replace the native file picker with the built-in profile manager for
        # all profile selections, including board-specific series selection.
        # If a native dialog ever has to be used as a fallback, it is still
        # forced to open in the JarnsenMeshFlasher\profiles directory.
        try:
            import tkinter as tk
            from tkinter import filedialog

            original_askopenfilename = filedialog.askopenfilename

            def profile_askopenfilename(*args, **kwargs):
                title = str(kwargs.get("title") or "")
                if "Profil" not in title:
                    return original_askopenfilename(*args, **kwargs)

                kwargs.setdefault("initialdir", str(services.PATHS.profiles))
                root = kwargs.get("parent") or getattr(tk, "_default_root", None)
                if root is None:
                    return original_askopenfilename(*args, **kwargs)

                board_key = None
                for key, profile in services.BOARD_PROFILES.items():
                    if str(profile["label"]) in title:
                        board_key = key
                        break

                selected = select_profile_dialog(
                    root,
                    services,
                    board_key=board_key,
                    title=title if title else "JARNSEN MESH · Profil auswählen",
                )
                return str(selected) if selected else ""

            filedialog.askopenfilename = profile_askopenfilename
        except Exception:
            pass

        # Replace the two profile button actions without duplicating the large
        # app module: master read uses the named path, profile select opens the
        # in-app manager and directly updates Role/Long/Short in the main UI.
        try:
            import customtkinter as ctk

            original_button_init = ctk.CTkButton.__init__

            def button_init(self, *args, **kwargs):
                text = kwargs.get("text")
                command = kwargs.get("command")
                app = getattr(command, "__self__", None)

                if text == "Profil laden":
                    kwargs["text"] = "Profil auswählen"
                    if app is not None:
                        kwargs["command"] = lambda app=app: choose_profile_for_app(app, services)
                elif text == "Vom Master einlesen" and app is not None:
                    kwargs["command"] = lambda app=app: read_master_profile_for_app(app, services)

                original_button_init(self, *args, **kwargs)

            ctk.CTkButton.__init__ = button_init
        except Exception:
            pass

        # During series flashing this layer compares the newly detected board
        # with the internal active profile. Its file chooser is now transparently
        # backed by the same in-app profile manager above.
        from series_profile_guard import install as install_series_profile_guard

        install_series_profile_guard(services)

    except Exception:
        # Runtime setup/diagnostics must never prevent the flasher from starting.
        pass
