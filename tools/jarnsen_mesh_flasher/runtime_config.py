from __future__ import annotations

import re
import sys
import traceback
from pathlib import Path


def configure_runtime() -> None:
    """Configure the packaged flasher without allowing one feature to disable the rest."""
    try:
        import services
    except Exception:
        return

    log_dir = Path.home() / "Downloads" / "Meshtastic-Logs" / "JARNSEN-MESHFLASHER"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        services.PATHS.logs = log_dir
    except Exception:
        pass

    try:
        services.AppPaths.active_profile = property(
            lambda self: self.profiles / ".active-profile.yaml"
        )
    except Exception:
        pass

    try:
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
    except Exception:
        pass

    if getattr(sys, "frozen", False):
        try:
            bundle_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))

            def bundled_helper_command() -> list[str]:
                helper = bundle_root / "_JarnsenMeshHelper.exe"
                if not helper.exists():
                    raise services.FlasherError(f"Eingebetteter Helper fehlt: {helper}")
                return [str(helper)]

            services.helper_command = bundled_helper_command
        except Exception:
            pass

    diagnostics = None
    try:
        import diagnostics as _diagnostics

        diagnostics = _diagnostics
        diagnostics.install(services, log_dir)
    except Exception:
        diagnostics = None

    def emit(message: str) -> None:
        if diagnostics is None:
            return
        try:
            diagnostics._emit(message)
        except Exception:
            pass

    def install_layer(name: str, callback) -> bool:
        emit(f"RUNTIME LAYER START name={name}")
        try:
            callback()
            emit(f"RUNTIME LAYER OK name={name}")
            return True
        except Exception as exc:
            emit(
                f"RUNTIME LAYER FAILED name={name} type={type(exc).__name__} message={exc}"
            )
            try:
                diagnostics._emit_block(
                    f"RUNTIME LAYER TRACEBACK {name}", traceback.format_exc(), max_chars=30000
                )
            except Exception:
                pass
            return False

    def install_ui() -> None:
        from ui_tuning import install
        install(services)

    def install_board() -> None:
        from board_detection import install
        install(services)

    def install_wio() -> None:
        from wio_support import install
        install(services)

    def install_serial() -> None:
        from serial_probe import install
        install(services)

    def install_serial_autowatch() -> None:
        from serial_autowatch import install
        install(services)

    def install_firmware_artifacts() -> None:
        from firmware_artifact_compat import install
        install(services)

    install_layer("ui_tuning", install_ui)
    install_layer("board_detection", install_board)
    install_layer("wio_support", install_wio)
    install_layer("serial_probe", install_serial)
    install_layer("serial_autowatch", install_serial_autowatch)
    install_layer("firmware_artifact_compat", install_firmware_artifacts)

    def install_profiles() -> None:
        from profile_catalog import board_for_profile, copy_profile_assignment
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
            except Exception as exc:
                stdout = getattr(exc, "stdout", b"") or b""
                stderr = getattr(exc, "stderr", b"") or b""
                if isinstance(stdout, bytes):
                    stdout = stdout.decode("utf-8", errors="replace")
                if isinstance(stderr, bytes):
                    stderr = stderr.decode("utf-8", errors="replace")
                info_text = "\n".join(filter(None, (str(stdout), str(stderr))))
                if info_text:
                    summary = summary.with_fallback(summary_from_info_text(info_text))
                    board_key = services.detect_board_from_text(info_text)

            return store_exported_profile(
                raw_path,
                summary,
                board_key,
                services,
                source=f"master:{port}",
            )

        services.export_profile = descriptive_export_profile

        original_import_profile = services.import_profile_file

        def catalog_import_profile(source: Path) -> Path:
            source = Path(source)
            original_import_profile(source)
            assigned = board_for_profile(source)
            if assigned:
                copy_profile_assignment(source, services.PATHS.active_profile)
            emit(
                "PROFILE IMPORT "
                f"source={source.name!r} board={assigned!r} active={services.PATHS.active_profile.name!r}"
            )
            return source

        services.import_profile_file = catalog_import_profile

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

        import customtkinter as ctk

        previous_button_init = ctk.CTkButton.__init__

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
            previous_button_init(self, *args, **kwargs)

        ctk.CTkButton.__init__ = button_init

    install_layer("profiles", install_profiles)

    def install_series_guard() -> None:
        from series_profile_guard import install
        install(services)

    def install_wio_series() -> None:
        from wio_series import install
        install(services)

    install_layer("series_profile_guard", install_series_guard)
    install_layer("wio_series", install_wio_series)
    emit("RUNTIME CONFIG COMPLETE")
