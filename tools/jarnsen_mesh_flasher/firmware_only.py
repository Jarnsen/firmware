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


def _walk(widget: Any):
    yield widget
    try:
        children = widget.winfo_children()
    except Exception:
        children = []
    for child in children:
        yield from _walk(child)


def _button_text(widget: Any) -> str:
    try:
        return str(widget.cget("text") or "")
    except Exception:
        return ""


def install(services: Any) -> None:
    """Add an app-partition-only firmware update path for ESP32 boards."""
    import customtkinter as ctk
    from flash_runtime import _stream_esptool

    original_root_init = ctk.CTk.__init__

    def root_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_root_init(self, *args, **kwargs)

        def patch_app() -> None:
            if getattr(self, "_jarnsen_firmware_only_installed", False):
                return
            required = (
                "_selected_device",
                "_selected_board_key",
                "_set_busy",
                "_set_progress",
                "_append_log",
            )
            if not all(hasattr(self, name) for name in required):
                try:
                    self.after(150, patch_app)
                except Exception:
                    pass
                return

            check_button = None
            for widget in _walk(self):
                if _button_text(widget) == "Neueste Firmware prüfen":
                    check_button = widget
                    break
            if check_button is None:
                try:
                    self.after(180, patch_app)
                except Exception:
                    pass
                return

            parent = getattr(check_button, "master", None)
            if parent is None:
                return
            self._jarnsen_firmware_only_installed = True

            def start_firmware_only() -> None:
                if getattr(self, "busy", False):
                    return
                device = self._selected_device()
                if device is None:
                    messagebox.showwarning(
                        "Kein Gerät",
                        "Bitte zuerst ein USB-Gerät auswählen.",
                        parent=self,
                    )
                    return
                board_key = self._selected_board_key()
                if board_key not in {"tracker", "repeater"}:
                    messagebox.showinfo(
                        "Firmware-Update",
                        "Der reine Firmware-Updatepfad ist aktuell für Heltec Tracker V1.1 und Heltec V3 freigegeben.",
                        parent=self,
                    )
                    return
                if getattr(device, "board_key", None) and device.board_key != board_key:
                    messagebox.showerror(
                        "Board-Widerspruch",
                        "Automatische Geräteerkennung und Board-Auswahl widersprechen sich.\n\n"
                        "Das Firmware-Update wurde nicht gestartet.",
                        parent=self,
                    )
                    return

                self._set_busy(True)
                threading.Thread(
                    target=firmware_only_worker,
                    args=(device.port, board_key),
                    name="jarnsen-firmware-only",
                    daemon=True,
                ).start()

            update_button = ctk.CTkButton(
                parent,
                text="NUR FIRMWARE UPDATEN",
                width=190,
                command=start_firmware_only,
            )
            try:
                update_button.pack(anchor="w", padx=18, pady=(0, 10), after=check_button)
            except Exception:
                update_button.pack(anchor="w", padx=18, pady=(0, 10))
            self.firmware_only_button = update_button

            original_set_busy = self._set_busy

            def wrapped_set_busy(busy: bool) -> None:
                original_set_busy(busy)
                try:
                    self.after(
                        0,
                        update_button.configure,
                        {"state": "disabled" if busy else "normal"},
                    )
                except Exception:
                    pass

            self._set_busy = wrapped_set_busy

            def firmware_only_worker(port: str, board_key: str) -> None:
                previous_flash_callback = getattr(services, "_jarnsen_flash_progress_callback", None)
                try:
                    board_label = services.BOARD_PROFILES[board_key]["label"]
                    self._set_progress(0.03, "Firmware-Update · Firmware auflösen")
                    self._append_log(
                        f"FIRMWARE-ONLY START · Port={port} · Board={board_label} · "
                        "Erase=NEIN · Profil=NEIN · Name=NEIN · NVS/Logs=behalten"
                    )

                    bundle = getattr(self, "bundle", None)
                    if not (
                        bundle is not None
                        and getattr(bundle, "board_key", None) == board_key
                        and bool(getattr(bundle, "local_source", ""))
                    ):
                        bundle = services.GitHubFirmwareClient().resolve_latest(board_key)
                        self.bundle = bundle
                        try:
                            self.after(0, self.firmware_var.set, bundle.display_name)
                        except Exception:
                            pass

                    update_image = Path(bundle.update)
                    if not update_image.exists():
                        raise services.FlasherError(
                            f"Update-Image fehlt: {update_image}"
                        )

                    decision: list[bool] = []
                    ready = threading.Event()

                    def ask() -> None:
                        try:
                            decision.append(
                                messagebox.askyesno(
                                    "Nur Firmware updaten",
                                    f"Port: {port}\n"
                                    f"Board: {board_label}\n"
                                    f"Firmware: {bundle.display_name}\n\n"
                                    "Es werden NUR die beiden App-Firmware-Slots aktualisiert.\n"
                                    "KEIN Flash-Erase, KEIN Profil, KEINE Namen und KEINE Grundeinstellungen.\n"
                                    "NVS, Gerätekonfiguration und Diagnose-Logs bleiben erhalten.\n\n"
                                    "Firmware jetzt aktualisieren?",
                                    parent=self,
                                )
                            )
                        finally:
                            ready.set()

                    self.after(0, ask)
                    ready.wait()
                    if not decision or not decision[0]:
                        self._append_log("FIRMWARE-ONLY · vom Benutzer abgebrochen")
                        self._set_progress(0.0, "Firmware-Update abgebrochen")
                        return

                    baud = str(getattr(services, "_jarnsen_flash_baud", "921600"))
                    if baud not in {"115200", "230400", "460800", "921600"}:
                        baud = "921600"

                    def flash_progress(fraction: float, stage: str, detail: str) -> None:
                        suffix = f" · {detail}" if detail else ""
                        self._set_progress(fraction, f"Firmware-Update · {stage}{suffix}")

                    services._jarnsen_flash_progress_callback = flash_progress
                    self._append_log(
                        f"FIRMWARE-ONLY IMAGE · {update_image.name} · {update_image.stat().st_size} Bytes · Baud={baud}"
                    )
                    self._append_log(
                        "FIRMWARE-ONLY PLAN · 0x10000 App-Slot A → 0x340000 App-Slot B → Start · kein erase_flash"
                    )
                    _emit(
                        f"FIRMWARE ONLY PLAN port={port} board={board_key} baud={baud} "
                        f"image={update_image.name!r} slot0=0x10000 slot1=0x340000 erase=0"
                    )

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
                    _stream_esptool(
                        services,
                        port,
                        [*common, "0x10000", str(update_image)],
                        timeout=600,
                        stage="App-Slot A schreiben",
                        phase_start=0.08,
                        phase_end=0.48,
                        log=self._append_log,
                    )
                    _stream_esptool(
                        services,
                        port,
                        [*common, "0x340000", str(update_image)],
                        timeout=600,
                        stage="App-Slot B schreiben",
                        phase_start=0.48,
                        phase_end=0.88,
                        log=self._append_log,
                    )
                    _stream_esptool(
                        services,
                        port,
                        ["run"],
                        timeout=30,
                        stage="Node starten",
                        phase_start=0.88,
                        phase_end=0.91,
                        log=self._append_log,
                        check=False,
                    )

                    self._set_progress(0.93, "Firmware-Update · Auf USB-Neuanmeldung warten")
                    services.wait_for_serial(port, timeout=90)
                    self._set_progress(0.97, "Firmware-Update · Board prüfen")
                    services.verify_node(port, expected_board=board_key)
                    self._set_progress(1.0, "Firmware-Update fertig")
                    self._append_log(
                        f"FIRMWARE-ONLY ENDE · ERFOLG · {bundle.display_name} · "
                        "Profil/Namen/NVS/Logs unverändert"
                    )
                    self.after(
                        0,
                        messagebox.showinfo,
                        "Firmware aktualisiert",
                        f"{bundle.display_name}\n\n"
                        "Nur die Firmware-App-Slots wurden aktualisiert.\n"
                        "Profil, Namen, NVS und Diagnose-Logs wurden nicht verändert.",
                    )
                except Exception as exc:
                    self._append_log(
                        f"FIRMWARE-ONLY FEHLER · {type(exc).__name__}: {exc}"
                    )
                    try:
                        self._show_error(exc)
                    except Exception:
                        self.after(
                            0,
                            messagebox.showerror,
                            "Firmware-Update fehlgeschlagen",
                            str(exc),
                        )
                finally:
                    services._jarnsen_flash_progress_callback = previous_flash_callback
                    self._set_busy(False)

            _emit("FIRMWARE ONLY UI installed app-slots=0x10000,0x340000 erase=0 profile=0 names=0")

        try:
            self.after(620, patch_app)
        except Exception:
            pass

    ctk.CTk.__init__ = root_init
    _emit("FIRMWARE ONLY layer installed tracker=1 repeater=1 preserve-nvs=1")
