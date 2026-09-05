from __future__ import annotations

import threading
from pathlib import Path
from tkinter import messagebox
from typing import Any


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _safe_start_firmware_only(app: Any, services: Any) -> None:
    """Run firmware-only update without opening a Tk modal from a worker thread."""
    from flash_runtime import _stream_esptool

    if getattr(app, "busy", False):
        return

    device = app._selected_device()
    if device is None:
        messagebox.showwarning(
            "Kein Gerät",
            "Bitte zuerst ein USB-Gerät auswählen.",
            parent=app,
        )
        return

    board_key = app._selected_board_key()
    if board_key not in {"tracker", "repeater"}:
        messagebox.showinfo(
            "Firmware-Update",
            "Der reine Firmware-Updatepfad ist aktuell für Tracker V1.1 und Heltec V3 freigegeben.\n\n"
            "Die übrigen Unified-Core-Boards können über AUTOMATISCH FLASHEN vollständig geflasht werden.",
            parent=app,
        )
        return

    board_label = str(services.BOARD_PROFILES[board_key]["label"])
    cached = getattr(app, "bundle", None)
    if cached is not None and getattr(cached, "board_key", None) == board_key:
        firmware_text = str(cached.display_name)
    else:
        cached = None
        firmware_text = "Neueste erfolgreiche JARNSEN-MESH Firmware von GitHub"

    # IMPORTANT: this modal must run directly on the Tk main thread.  The old
    # implementation created it from a background worker via app.after() and
    # then blocked that worker on an Event.  In the frozen borderless Windows
    # build this was the exact transition where the process could disappear.
    approved = messagebox.askyesno(
        "Nur Firmware updaten",
        f"Port: {device.port}\n"
        f"Board: {board_label}\n"
        f"Firmware: {firmware_text}\n\n"
        "Nur die App-Firmware-Slots werden aktualisiert. Profil, Namen, NVS und Logs bleiben erhalten.\n\n"
        "Firmware jetzt aktualisieren?",
        parent=app,
    )
    if not approved:
        app._append_log(
            f"FIRMWARE-ONLY ABBRUCH · Port={device.port} · Board={board_label} · vor Flash"
        )
        app._set_progress(0.0, "Firmware-Update abgebrochen")
        return

    app._append_log(
        f"FIRMWARE-ONLY FREIGABE · Port={device.port} · Board={board_label} · "
        f"Quelle={'Cache' if cached is not None else 'GitHub'}"
    )
    _emit(
        f"FIRMWARE-ONLY MAIN-THREAD CONFIRM OK port={device.port!r} board={board_key!r}"
    )
    app._set_busy(True)

    def worker() -> None:
        previous = getattr(services, "_jarnsen_flash_progress_callback", None)
        try:
            app._set_progress(0.03, "Firmware-Update · Firmware auflösen")
            app._append_log(
                f"FIRMWARE-ONLY RESOLVE START · Port={device.port} · Board={board_label}"
            )

            bundle = cached
            if bundle is None:
                bundle = services.GitHubFirmwareClient().resolve_latest(board_key)
                app.bundle = bundle
                app.after(0, app.firmware_var.set, bundle.display_name)

            update_image = Path(bundle.update)
            if not update_image.exists():
                raise services.FlasherError(f"Update-Image fehlt: {update_image}")

            app._append_log(
                f"FIRMWARE-ONLY RESOLVE ENDE · {bundle.display_name} · "
                f"Datei={update_image.name} · Bytes={update_image.stat().st_size}"
            )

            baud = str(getattr(services, "_jarnsen_flash_baud", "921600"))
            if baud not in {"115200", "230400", "460800", "921600"}:
                baud = "921600"

            def flash_progress(fraction: float, stage: str, detail: str) -> None:
                suffix = f" · {detail}" if detail else ""
                app._set_progress(
                    fraction,
                    f"Firmware-Update · {stage}{suffix}",
                )

            services._jarnsen_flash_progress_callback = flash_progress
            common = [
                "--baud",
                baud,
                "write-flash",
                "--flash-mode",
                "dio",
                "--flash-freq",
                "80m",
                "--flash-size",
                "keep",
            ]

            app._append_log(
                f"FIRMWARE-ONLY FLASH START · Port={device.port} · Board={board_label} · "
                f"Baud={baud} · Datei={update_image.name}"
            )
            _stream_esptool(
                services,
                device.port,
                [*common, "0x10000", str(update_image)],
                timeout=600,
                stage="App-Slot A schreiben",
                phase_start=0.08,
                phase_end=0.48,
                log=app._append_log,
            )
            _stream_esptool(
                services,
                device.port,
                [*common, "0x340000", str(update_image)],
                timeout=600,
                stage="App-Slot B schreiben",
                phase_start=0.48,
                phase_end=0.88,
                log=app._append_log,
            )
            _stream_esptool(
                services,
                device.port,
                ["run"],
                timeout=30,
                stage="Node starten",
                phase_start=0.88,
                phase_end=0.91,
                log=app._append_log,
                check=False,
            )

            app._set_progress(0.93, "Firmware-Update · Auf USB warten")
            services.wait_for_serial(device.port, timeout=90)
            app._set_progress(0.97, "Firmware-Update · Board prüfen")
            services.verify_node(device.port, expected_board=board_key)
            app._append_log(
                f"FIRMWARE-ONLY FLASH ENDE · Port={device.port} · Board={board_label} · "
                f"Firmware={bundle.display_name} · verifiziert=1"
            )
            app._set_progress(1.0, "Firmware-Update fertig · Board verifiziert")
        except Exception as exc:
            app._append_log(
                f"FIRMWARE-ONLY FEHLER · {type(exc).__name__}: {exc}"
            )
            app._show_error(exc)
        finally:
            services._jarnsen_flash_progress_callback = previous
            app._set_busy(False)

    threading.Thread(
        target=worker,
        name="jarnsen-firmware-only-native-safe",
        daemon=True,
    ).start()


def install(services: Any) -> None:
    """Replace the firmware-only action in every already-imported dashboard binding."""
    import native_actions

    native_actions.start_firmware_only = _safe_start_firmware_only

    patched = ["native_actions"]
    try:
        import reference_dashboard

        reference_dashboard.start_firmware_only = _safe_start_firmware_only
        patched.append("reference_dashboard")
    except Exception as exc:
        _emit(
            "FIRMWARE-ONLY STABILITY reference binding skipped "
            f"type={type(exc).__name__} message={exc}"
        )

    _emit(
        "FIRMWARE-ONLY STABILITY installed main-thread-confirm=1 worker-modal=0 "
        f"bindings={patched!r}"
    )
