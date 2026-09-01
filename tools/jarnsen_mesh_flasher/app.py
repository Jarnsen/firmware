from __future__ import annotations

import sys
import threading
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from _build_version import APP_VERSION
from services import (
    BOARD_PROFILES,
    PATHS,
    DeviceInfo,
    FirmwareBundle,
    FlasherError,
    GitHubFirmwareClient,
    backup_flash,
    export_profile,
    flash_bundle,
    import_profile_file,
    make_log_file,
    reboot_node,
    restore_profile,
    scan_devices,
    set_names,
    verify_node,
    wait_for_serial,
)


ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


class FlasherApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"JARNSEN MESH Flasher · {APP_VERSION}")
        self.geometry("840x860")
        self.minsize(760, 760)

        self.devices: list[DeviceInfo] = []
        self.bundle: FirmwareBundle | None = None
        self.busy = False
        self.log_path = make_log_file()

        self.status_var = ctk.StringVar(value="Bereit")
        self.device_var = ctk.StringVar(value="Kein Gerät erkannt")
        self.board_var = ctk.StringVar(value="Automatisch")
        self.firmware_var = ctk.StringVar(value="Noch nicht geprüft")
        self.profile_var = ctk.StringVar(
            value=str(PATHS.active_profile) if PATHS.active_profile.exists() else "Kein Profil geladen"
        )
        self.long_name_var = ctk.StringVar()
        self.short_name_var = ctk.StringVar()

        self._build_ui()
        self.after(300, self.refresh_devices)

    def _card(self, parent: ctk.CTkFrame, title: str) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(parent, corner_radius=18)
        frame.pack(fill="x", padx=4, pady=(0, 14))
        ctk.CTkLabel(
            frame,
            text=title,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("gray35", "gray70"),
        ).pack(anchor="w", padx=18, pady=(14, 6))
        return frame

    def _build_ui(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=26, pady=(22, 12))
        ctk.CTkLabel(
            header,
            text="JARNSEN MESH Flasher",
            font=ctk.CTkFont(size=28, weight="bold"),
        ).pack(side="left")
        ctk.CTkLabel(
            header,
            text=f"v{APP_VERSION}",
            font=ctk.CTkFont(size=12),
            text_color=("gray40", "gray65"),
        ).pack(side="left", padx=(10, 0), pady=(8, 0))
        self.status_label = ctk.CTkLabel(
            header,
            textvariable=self.status_var,
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.status_label.pack(side="right")

        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=22, pady=(0, 12))

        device = self._card(self.body, "1 · GERÄT")
        device_row = ctk.CTkFrame(device, fg_color="transparent")
        device_row.pack(fill="x", padx=18, pady=(0, 10))
        self.device_combo = ctk.CTkComboBox(
            device_row,
            variable=self.device_var,
            values=["Kein Gerät erkannt"],
            command=self._device_changed,
            state="readonly",
        )
        self.device_combo.pack(side="left", fill="x", expand=True, padx=(0, 10))
        ctk.CTkButton(
            device_row,
            text="Neu suchen",
            width=120,
            command=self.refresh_devices,
        ).pack(side="left")

        board_row = ctk.CTkFrame(device, fg_color="transparent")
        board_row.pack(fill="x", padx=18, pady=(0, 14))
        ctk.CTkLabel(board_row, text="Board").pack(side="left")
        ctk.CTkOptionMenu(
            board_row,
            variable=self.board_var,
            values=[
                "Automatisch",
                BOARD_PROFILES["tracker"]["label"],
                BOARD_PROFILES["repeater"]["label"],
            ],
            command=lambda _value: self._invalidate_bundle(),
            width=280,
        ).pack(side="right")

        profile = self._card(self.body, "2 · GRUNDEINSTELLUNGEN")
        ctk.CTkLabel(
            profile,
            textvariable=self.profile_var,
            anchor="w",
            justify="left",
            wraplength=720,
        ).pack(fill="x", padx=18, pady=(0, 10))
        profile_buttons = ctk.CTkFrame(profile, fg_color="transparent")
        profile_buttons.pack(fill="x", padx=18, pady=(0, 14))
        ctk.CTkButton(
            profile_buttons,
            text="Vom Master einlesen",
            command=self.read_master_profile,
        ).pack(side="left", padx=(0, 10))
        ctk.CTkButton(
            profile_buttons,
            text="Profil laden",
            fg_color=("gray72", "gray28"),
            hover_color=("gray65", "gray35"),
            command=self.load_profile,
        ).pack(side="left")

        firmware = self._card(self.body, "3 · FIRMWARE")
        ctk.CTkLabel(
            firmware,
            textvariable=self.firmware_var,
            anchor="w",
            justify="left",
            wraplength=720,
        ).pack(fill="x", padx=18, pady=(0, 10))
        ctk.CTkButton(
            firmware,
            text="Neueste Firmware prüfen",
            command=self.check_firmware,
        ).pack(anchor="w", padx=18, pady=(0, 14))

        names = self._card(self.body, "4 · GERÄTENAME")
        names_row = ctk.CTkFrame(names, fg_color="transparent")
        names_row.pack(fill="x", padx=18, pady=(0, 14))
        ctk.CTkEntry(
            names_row,
            textvariable=self.long_name_var,
            placeholder_text="Long Name",
        ).pack(side="left", fill="x", expand=True, padx=(0, 10))
        ctk.CTkEntry(
            names_row,
            textvariable=self.short_name_var,
            placeholder_text="Short Name (max. 4)",
            width=190,
        ).pack(side="left")

        action = self._card(self.body, "5 · AUTOMATISCHER ABLAUF")
        ctk.CTkLabel(
            action,
            text="Backup → neueste Firmware → Grundeinstellungen → Namen → Neustart → Prüfung",
            anchor="w",
            justify="left",
        ).pack(fill="x", padx=18, pady=(0, 10))
        self.progress = ctk.CTkProgressBar(action)
        self.progress.pack(fill="x", padx=18, pady=(0, 12))
        self.progress.set(0)
        self.flash_button = ctk.CTkButton(
            action,
            text="AUTOMATISCH FLASHEN",
            height=50,
            corner_radius=14,
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self.start_flash,
        )
        self.flash_button.pack(fill="x", padx=18, pady=(0, 16))

        log = self._card(self.body, "PROTOKOLL")
        self.log_box = ctk.CTkTextbox(log, height=170, corner_radius=12)
        self.log_box.pack(fill="both", expand=True, padx=18, pady=(0, 10))
        self.log_box.configure(state="disabled")
        ctk.CTkLabel(
            log,
            text=f"Log: {self.log_path}",
            font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray65"),
        ).pack(anchor="w", padx=18, pady=(0, 14))

    def _append_log(self, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{stamp}] {text}"
        try:
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except Exception:
            pass

        def update() -> None:
            self.log_box.configure(state="normal")
            self.log_box.insert("end", line + "\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")

        self.after(0, update)

    def _set_status(self, text: str) -> None:
        self.after(0, self.status_var.set, text)
        self._append_log(text)

    def _set_progress(self, value: float, text: str) -> None:
        self.after(0, self.progress.set, value)
        self._set_status(text)

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.after(0, self.flash_button.configure, {"state": state})

    def _selected_device(self) -> DeviceInfo | None:
        selected = self.device_var.get()
        return next((item for item in self.devices if item.label == selected), None)

    def _selected_board_key(self) -> str | None:
        manual = self.board_var.get()
        if manual == BOARD_PROFILES["tracker"]["label"]:
            return "tracker"
        if manual == BOARD_PROFILES["repeater"]["label"]:
            return "repeater"
        device = self._selected_device()
        return device.board_key if device else None

    def _device_changed(self, _value: str | None = None) -> None:
        self._invalidate_bundle()
        device = self._selected_device()
        if device and device.board_key:
            self._append_log(f"Erkannt: {BOARD_PROFILES[device.board_key]['label']} auf {device.port}")

    def _invalidate_bundle(self) -> None:
        self.bundle = None
        self.firmware_var.set("Noch nicht geprüft")

    def refresh_devices(self) -> None:
        if self.busy:
            return
        self._set_busy(True)
        self._set_status("Suche serielle Geräte …")

        def worker() -> None:
            try:
                devices = scan_devices()
                self.devices = devices
                labels = [item.label for item in devices] or ["Kein Gerät erkannt"]

                def update() -> None:
                    self.device_combo.configure(values=labels)
                    self.device_var.set(labels[0])
                    self._device_changed(labels[0])

                self.after(0, update)
                if devices:
                    detected = sum(1 for item in devices if item.board_key)
                    self._set_status(f"{len(devices)} Gerät(e) gefunden · {detected} Board(s) erkannt")
                else:
                    self._set_status("Kein serielles Gerät gefunden")
            except Exception as exc:
                self._show_error(exc)
            finally:
                self._set_busy(False)

        threading.Thread(target=worker, daemon=True).start()

    def read_master_profile(self) -> None:
        device = self._selected_device()
        if not device:
            messagebox.showwarning("Kein Gerät", "Bitte zuerst einen Master-Node verbinden.")
            return
        if self.busy:
            return
        self._set_busy(True)

        def worker() -> None:
            try:
                self._set_status(f"Grundeinstellungen von {device.port} einlesen …")
                path = export_profile(device.port)
                self.after(0, self.profile_var.set, str(PATHS.active_profile))
                self._set_status(f"Profil gespeichert · {path.name}")
            except Exception as exc:
                self._show_error(exc)
            finally:
                self._set_busy(False)

        threading.Thread(target=worker, daemon=True).start()

    def load_profile(self) -> None:
        filename = filedialog.askopenfilename(
            title="Meshtastic Profil laden",
            filetypes=[
                ("Meshtastic Profil", "*.yaml *.yml *.cfg"),
                ("Alle Dateien", "*.*"),
            ],
        )
        if not filename:
            return
        try:
            path = import_profile_file(Path(filename))
            self.profile_var.set(str(path))
            self._set_status("Profil geladen")
        except Exception as exc:
            self._show_error(exc)

    def check_firmware(self) -> None:
        board_key = self._selected_board_key()
        if not board_key:
            messagebox.showwarning(
                "Board unbekannt",
                "Board konnte nicht automatisch erkannt werden. Bitte Tracker V1.1 oder Heltec V3 auswählen.",
            )
            return
        if self.busy:
            return
        self._set_busy(True)

        def worker() -> None:
            try:
                self._set_status("Neueste erfolgreiche GitHub-Firmware suchen …")
                bundle = GitHubFirmwareClient().resolve_latest(board_key)
                self.bundle = bundle
                self.after(0, self.firmware_var.set, bundle.display_name)
                self._set_status(f"Firmware bereit · Run #{bundle.run_number}")
            except Exception as exc:
                self._show_error(exc)
            finally:
                self._set_busy(False)

        threading.Thread(target=worker, daemon=True).start()

    def start_flash(self) -> None:
        device = self._selected_device()
        board_key = self._selected_board_key()
        long_name = self.long_name_var.get().strip()
        short_name = self.short_name_var.get().strip()

        if not device:
            messagebox.showwarning("Kein Gerät", "Bitte ein Zielgerät auswählen.")
            return
        if not board_key:
            messagebox.showwarning("Board unbekannt", "Bitte das Board manuell auswählen.")
            return
        if not PATHS.active_profile.exists():
            messagebox.showwarning(
                "Kein Profil",
                "Bitte zuerst die Grundeinstellungen vom Master einlesen oder ein Profil laden.",
            )
            return
        if not long_name:
            messagebox.showwarning("Name fehlt", "Bitte einen Long Name vergeben.")
            return
        if not (1 <= len(short_name) <= 4):
            messagebox.showwarning("Short Name", "Short Name muss 1 bis 4 Zeichen lang sein.")
            return
        if self.busy:
            return

        board_label = BOARD_PROFILES[board_key]["label"]
        if not messagebox.askyesno(
            "Flash bestätigen",
            f"{device.port} · {board_label}\n\n"
            "Es wird zuerst ein vollständiges Sicherheitsbackup angelegt und danach der Flash gelöscht.\n"
            "Anschließend werden Firmware, Grundeinstellungen und Gerätenamen automatisch gesetzt.\n\n"
            "Jetzt starten?",
        ):
            return

        self._set_busy(True)
        threading.Thread(
            target=self._flash_worker,
            args=(device.port, board_key, long_name, short_name),
            daemon=True,
        ).start()

    def _flash_worker(self, port: str, board_key: str, long_name: str, short_name: str) -> None:
        try:
            self._set_progress(0.05, "Gerät und Profil prüfen")
            if not PATHS.active_profile.exists():
                raise FlasherError("Aktives Profil ist verschwunden.")

            self._set_progress(0.14, "Neueste Firmware von GitHub ermitteln")
            bundle = GitHubFirmwareClient().resolve_latest(board_key)
            self.bundle = bundle
            self.after(0, self.firmware_var.set, bundle.display_name)
            self._append_log(f"Firmware: {bundle.display_name}")

            self._set_progress(0.27, "Vollständiges Sicherheitsbackup erstellen")
            backup = backup_flash(port, board_key)
            self._append_log(f"Backup: {backup}")

            self._set_progress(0.42, "Factory/OTA/LittleFS flashen")
            flash_bundle(port, bundle, log=self._append_log)

            self._set_progress(0.70, "Auf Neustart des Nodes warten")
            wait_for_serial(port, timeout=120)

            self._set_progress(0.79, "Grundeinstellungen wiederherstellen")
            restore_profile(port)

            self._set_progress(0.88, "Long Name und Short Name setzen")
            set_names(port, long_name, short_name)

            self._set_progress(0.94, "Node neu starten")
            reboot_node(port)
            wait_for_serial(port, timeout=90)

            self._set_progress(0.98, "Installation verifizieren")
            verify_node(port, expected_board=board_key)

            self._set_progress(1.0, "Fertig · Firmware und Konfiguration geprüft")
            self.after(
                0,
                messagebox.showinfo,
                "Flash erfolgreich",
                f"{BOARD_PROFILES[board_key]['label']} wurde erfolgreich eingerichtet.\n\n"
                f"Firmware: Run #{bundle.run_number}\n"
                f"Backup: {backup.name}\n"
                f"Long Name: {long_name}\nShort Name: {short_name}",
            )
        except Exception as exc:
            self._show_error(exc)
        finally:
            self._set_busy(False)

    def _show_error(self, exc: Exception) -> None:
        text = str(exc) or exc.__class__.__name__
        self._set_status(f"FEHLER · {text}")
        self.after(0, messagebox.showerror, "JARNSEN MESH Flasher", text)


def main() -> int:
    if "--version" in sys.argv:
        print(APP_VERSION)
        return 0
    app = FlasherApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
