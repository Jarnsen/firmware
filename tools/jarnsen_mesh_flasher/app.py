from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog

import customtkinter as ctk

from _build_version import APP_VERSION
from profile_utils import (
    ProfileSummary,
    format_summary,
    summary_from_info_text,
    summary_from_profile_file,
)
from services import (
    BOARD_PROFILES,
    PATHS,
    DeviceInfo,
    FirmwareBundle,
    FlasherError,
    GitHubFirmwareClient,
    backup_flash,
    detect_board_from_text,
    export_profile,
    flash_bundle,
    helper_command,
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
        self.geometry("860x960")
        self.minsize(780, 820)

        self.devices: list[DeviceInfo] = []
        self.bundle: FirmwareBundle | None = None
        self.busy = False
        self.log_path = make_log_file()

        self.series_active = False
        self.series_count = 0
        self.series_last_identity = ""
        self.series_last_port = ""
        self.series_last_board = ""

        initial_summary = ProfileSummary()
        if PATHS.active_profile.exists():
            try:
                initial_summary = summary_from_profile_file(PATHS.active_profile)
            except Exception:
                pass

        self.status_var = ctk.StringVar(value="Bereit")
        self.device_var = ctk.StringVar(value="Kein Gerät erkannt")
        self.board_var = ctk.StringVar(value="Automatisch")
        self.firmware_var = ctk.StringVar(value="Noch nicht geprüft")
        self.profile_path_var = ctk.StringVar(
            value=str(PATHS.active_profile) if PATHS.active_profile.exists() else "Kein Profil geladen"
        )
        self.profile_summary_var = ctk.StringVar(
            value=format_summary(initial_summary) if PATHS.active_profile.exists() else "Noch kein Profil eingelesen"
        )
        self.long_name_var = ctk.StringVar(value=initial_summary.long_name)
        self.short_name_var = ctk.StringVar(value=initial_summary.short_name)
        self.series_status_var = ctk.StringVar(value="Serienmodus inaktiv")

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
            textvariable=self.profile_summary_var,
            anchor="w",
            justify="left",
            wraplength=740,
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(fill="x", padx=18, pady=(0, 5))
        ctk.CTkLabel(
            profile,
            textvariable=self.profile_path_var,
            anchor="w",
            justify="left",
            wraplength=740,
            font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray65"),
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
            wraplength=740,
        ).pack(fill="x", padx=18, pady=(0, 10))
        ctk.CTkButton(
            firmware,
            text="Neueste Firmware prüfen",
            command=self.check_firmware,
        ).pack(anchor="w", padx=18, pady=(0, 14))

        names = self._card(self.body, "4 · GERÄTENAME")
        name_labels = ctk.CTkFrame(names, fg_color="transparent")
        name_labels.pack(fill="x", padx=18, pady=(0, 4))
        ctk.CTkLabel(
            name_labels,
            text="Long Name",
            font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray65"),
        ).pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(
            name_labels,
            text="Short Name",
            width=190,
            anchor="w",
            font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray65"),
        ).pack(side="left", padx=(10, 0))

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
        self.flash_button.pack(fill="x", padx=18, pady=(0, 10))

        series_separator = ctk.CTkFrame(action, height=1, fg_color=("gray78", "gray28"))
        series_separator.pack(fill="x", padx=18, pady=(4, 12))
        ctk.CTkLabel(
            action,
            text="SERIENFLASH",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("gray35", "gray70"),
        ).pack(anchor="w", padx=18, pady=(0, 4))
        ctk.CTkLabel(
            action,
            text="Pro Gerät: COM neu suchen → Board verifizieren → neueste JARNSEN-MESH Firmware → Flash → Endprüfung",
            anchor="w",
            justify="left",
            wraplength=740,
            font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray65"),
        ).pack(fill="x", padx=18, pady=(0, 8))
        ctk.CTkLabel(
            action,
            textvariable=self.series_status_var,
            anchor="w",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(fill="x", padx=18, pady=(0, 8))

        series_buttons = ctk.CTkFrame(action, fg_color="transparent")
        series_buttons.pack(fill="x", padx=18, pady=(0, 16))
        self.series_button = ctk.CTkButton(
            series_buttons,
            text="SERIENMODUS STARTEN",
            height=42,
            corner_radius=12,
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.start_series,
        )
        self.series_button.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.series_stop_button = ctk.CTkButton(
            series_buttons,
            text="Serie beenden",
            width=130,
            height=42,
            fg_color=("gray72", "gray28"),
            hover_color=("gray65", "gray35"),
            state="disabled",
            command=self.stop_series,
        )
        self.series_stop_button.pack(side="left")

        log = self._card(self.body, "PROTOKOLL")
        self.log_box = ctk.CTkTextbox(log, height=180, corner_radius=12)
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
        self.after(0, self.series_button.configure, {"state": state})
        stop_state = "normal" if self.series_active and not busy else "disabled"
        self.after(0, self.series_stop_button.configure, {"state": stop_state})

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

    @staticmethod
    def _device_identity(info_text: str) -> str:
        text = info_text or ""
        patterns = (
            r"(?im)\b(?:node\s*id|id)\s*[:=]\s*(![0-9a-f]{8})\b",
            r"(?im)\bnum\s*[:=]\s*(\d{5,})\b",
            r"(?im)\bmac(?:\s*address)?\s*[:=]\s*([0-9a-f]{2}(?::[0-9a-f]{2}){5})\b",
        )
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).lower()
        return ""

    def _apply_names(self, summary: ProfileSummary, *, log_source: str | None = None) -> None:
        def update() -> None:
            if summary.long_name:
                self.long_name_var.set(summary.long_name)
            if summary.short_name:
                self.short_name_var.set(summary.short_name)

        self.after(0, update)
        if log_source and (summary.long_name or summary.short_name or summary.role):
            self._append_log(
                f"{log_source}: Long Name={summary.long_name or '–'} · "
                f"Short={summary.short_name or '–'} · Rolle={summary.role or '–'}"
            )

    def _apply_profile_summary(self, summary: ProfileSummary, path: Path, source: str) -> None:
        self.after(0, self.profile_path_var.set, str(path))
        self.after(0, self.profile_summary_var.set, format_summary(summary))
        self._apply_names(summary, log_source=source)

    def _device_changed(self, _value: str | None = None) -> None:
        self._invalidate_bundle()
        device = self._selected_device()
        if not device:
            return

        if device.board_key:
            self._append_log(f"Erkannt: {BOARD_PROFILES[device.board_key]['label']} auf {device.port}")

        summary = summary_from_info_text(device.model_text)
        self._apply_names(summary, log_source=f"Gerät {device.port}")

    def _invalidate_bundle(self) -> None:
        self.bundle = None
        self.firmware_var.set("Noch nicht geprüft")

    def _update_device_list(self, devices: list[DeviceInfo], selected: DeviceInfo | None = None) -> None:
        self.devices = devices
        labels = [item.label for item in devices] or ["Kein Gerät erkannt"]
        self.device_combo.configure(values=labels)
        selected_label = selected.label if selected else labels[0]
        if selected_label not in labels:
            selected_label = labels[0]
        self.device_var.set(selected_label)
        self._device_changed(selected_label)

    def refresh_devices(self) -> None:
        if self.busy:
            return
        self._set_busy(True)
        self._set_status("Suche serielle Geräte …")

        def worker() -> None:
            try:
                devices = scan_devices()
                self.after(0, self._update_device_list, devices, None)
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
                summary = summary_from_profile_file(path).with_fallback(
                    summary_from_info_text(device.model_text)
                )
                self._apply_profile_summary(
                    summary,
                    PATHS.active_profile,
                    source=f"Master {device.port}",
                )
                self._set_status(
                    f"Profil gespeichert · {summary.long_name or path.name} · "
                    f"Rolle {summary.role or 'unbekannt'}"
                )
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
            summary = summary_from_profile_file(path)
            self._apply_profile_summary(summary, path, source="Profil")
            self._set_status(
                f"Profil geladen · {summary.long_name or Path(filename).name} · "
                f"Rolle {summary.role or 'unbekannt'}"
            )
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
            f"Long Name: {long_name}\nShort Name: {short_name}\n\n"
            "Jetzt starten?",
        ):
            return

        self._set_busy(True)
        threading.Thread(
            target=self._flash_worker,
            args=(device.port, board_key, long_name, short_name),
            daemon=True,
        ).start()

    def _perform_flash(
        self,
        port: str,
        board_key: str,
        long_name: str,
        short_name: str,
        *,
        series_index: int | None = None,
        strict_preflight: bool = False,
    ) -> tuple[FirmwareBundle, Path, str]:
        prefix = f"Serie #{series_index} · " if series_index is not None else ""

        self._set_progress(0.03, f"{prefix}Seriellen Port und Board prüfen")
        preflight_identity = ""
        if strict_preflight:
            info = verify_node(port)
            detected = detect_board_from_text(info)
            if not detected:
                raise FlasherError(
                    f"{port}: Board konnte unmittelbar vor dem Flash nicht eindeutig erkannt werden."
                )
            if detected != board_key:
                raise FlasherError(
                    f"{port}: Board hat sich geändert. Erwartet {BOARD_PROFILES[board_key]['label']}, "
                    f"erkannt {BOARD_PROFILES[detected]['label']}."
                )
            preflight_identity = self._device_identity(info)
            if self.series_last_identity and preflight_identity == self.series_last_identity:
                raise FlasherError(
                    f"{port}: Das zuletzt geflashte Gerät ist noch angeschlossen. "
                    "Bitte abziehen und das nächste Gerät verbinden."
                )
            self._append_log(
                f"{prefix}Preflight OK · Port={port} · Board={BOARD_PROFILES[board_key]['label']} · "
                f"Identität={preflight_identity or 'nicht auslesbar'}"
            )

        self._set_progress(0.07, f"{prefix}Gerät und Profil prüfen")
        if not PATHS.active_profile.exists():
            raise FlasherError("Aktives Profil ist verschwunden.")

        self._set_progress(0.14, f"{prefix}Neueste JARNSEN-MESH Firmware von GitHub ermitteln")
        bundle = GitHubFirmwareClient().resolve_latest(board_key)
        self.bundle = bundle
        self.after(0, self.firmware_var.set, bundle.display_name)
        self._append_log(f"{prefix}Firmware neu aufgelöst: {bundle.display_name}")

        self._set_progress(0.27, f"{prefix}Vollständiges Sicherheitsbackup erstellen")
        backup = backup_flash(port, board_key)
        self._append_log(f"{prefix}Backup: {backup}")

        self._set_progress(0.42, f"{prefix}Factory/OTA flashen")
        flash_bundle(port, bundle, log=lambda text: self._append_log(prefix + text))

        self._set_progress(0.70, f"{prefix}Auf Neustart des Nodes warten")
        wait_for_serial(port, timeout=120)

        self._set_progress(0.79, f"{prefix}Grundeinstellungen wiederherstellen")
        restore_profile(port)

        self._set_progress(0.88, f"{prefix}Long Name und Short Name setzen")
        set_names(port, long_name, short_name)

        self._set_progress(0.94, f"{prefix}Node neu starten")
        reboot_node(port)
        wait_for_serial(port, timeout=90)

        self._set_progress(0.98, f"{prefix}Installation und Board verifizieren")
        final_info = verify_node(port, expected_board=board_key)
        final_detected = detect_board_from_text(final_info)
        if strict_preflight and final_detected != board_key:
            raise FlasherError(
                f"{port}: Endprüfung konnte {BOARD_PROFILES[board_key]['label']} nicht bestätigen."
            )
        final_identity = self._device_identity(final_info) or preflight_identity

        self._set_progress(1.0, f"{prefix}Fertig · Firmware, Port, Board und Konfiguration geprüft")
        return bundle, backup, final_identity

    def _flash_worker(self, port: str, board_key: str, long_name: str, short_name: str) -> None:
        try:
            bundle, backup, _identity = self._perform_flash(
                port,
                board_key,
                long_name,
                short_name,
            )
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

    def start_series(self) -> None:
        if self.busy:
            return
        if not PATHS.active_profile.exists():
            messagebox.showwarning(
                "Kein Profil",
                "Bitte zuerst die Grundeinstellungen vom Master einlesen oder ein Profil laden.",
            )
            return

        if not self.series_active:
            self.series_active = True
            self.series_count = 0
            self.series_last_identity = ""
            self.series_last_port = ""
            self.series_last_board = ""
            self.series_status_var.set("Serie aktiv · 0 Geräte erfolgreich")
            self.series_button.configure(text="GERÄT 1 PRÜFEN & FLASHEN")
            self.series_stop_button.configure(state="normal")
            self._append_log("SERIENMODUS START · Zähler=0")

        index = self.series_count + 1
        self._set_busy(True)
        self._set_status(f"Serie #{index} · neuen seriellen Port suchen und Board prüfen …")

        threading.Thread(
            target=self._series_prepare_worker,
            args=(index,),
            daemon=True,
        ).start()

    def stop_series(self) -> None:
        if self.busy:
            return
        if not self.series_active:
            return
        count = self.series_count
        self.series_active = False
        self.series_status_var.set(f"Serie beendet · {count} Gerät(e) erfolgreich")
        self.series_button.configure(text="SERIENMODUS STARTEN")
        self.series_stop_button.configure(state="disabled")
        self._append_log(f"SERIENMODUS ENDE · erfolgreich={count}")
        self._set_status(f"Serienmodus beendet · {count} Gerät(e) erfolgreich")

    def _series_prepare_worker(self, index: int) -> None:
        try:
            devices = scan_devices()
            if not devices:
                raise FlasherError(
                    "Serienflash: Kein kabelgebundenes serielles Zielgerät gefunden. "
                    "Bitte genau ein neues Gerät per USB anschließen."
                )
            if len(devices) != 1:
                ports = ", ".join(item.port for item in devices)
                raise FlasherError(
                    f"Serienflash: {len(devices)} serielle Zielgeräte gefunden ({ports}). "
                    "Bitte nur das Gerät anschließen, das jetzt geflasht werden soll."
                )

            device = devices[0]
            self._append_log(
                f"Serie #{index} · Scan-Kandidat Port={device.port} · "
                f"vorläufiges Board={device.board_key or 'unbekannt'}"
            )

            # Independent second read: the serial port and board must be confirmed
            # immediately before the user is allowed to continue.
            info = verify_node(device.port)
            board_key = detect_board_from_text(info)
            if not board_key:
                raise FlasherError(
                    f"Serie #{index}: {device.port} antwortet seriell, aber das Board konnte nicht eindeutig erkannt werden. "
                    "Der Serienflash stoppt vor dem Löschen."
                )
            if device.board_key and device.board_key != board_key:
                raise FlasherError(
                    f"Serie #{index}: widersprüchliche Board-Erkennung auf {device.port}. "
                    f"Scan={BOARD_PROFILES[device.board_key]['label']}, Prüfung={BOARD_PROFILES[board_key]['label']}."
                )

            identity = self._device_identity(info)
            if self.series_last_identity and identity and identity == self.series_last_identity:
                raise FlasherError(
                    f"Serie #{index}: Auf {device.port} ist noch das zuletzt geflashte Gerät angeschlossen. "
                    "Bitte dieses Gerät abziehen und das nächste verbinden."
                )

            device.board_key = board_key
            device.model_text = info
            self._append_log(
                f"Serie #{index} · PORT/BOARD CHECK OK · Port={device.port} · "
                f"Board={BOARD_PROFILES[board_key]['label']} · Identität={identity or 'nicht auslesbar'}"
            )
            self.after(0, self._series_device_ready, index, device)
        except Exception as exc:
            self._show_error(exc)
            self._set_busy(False)

    def _series_device_ready(self, index: int, device: DeviceInfo) -> None:
        if not self.series_active:
            self._set_busy(False)
            return

        self._update_device_list([device], device)
        board_key = device.board_key
        if not board_key:
            self._show_error(FlasherError("Serienflash: Board ging nach der Prüfung verloren."))
            self._set_busy(False)
            return

        current_long = self.long_name_var.get().strip()
        current_short = self.short_name_var.get().strip()
        change_names = messagebox.askyesno(
            f"Serie #{index} · Gerätename",
            f"{device.port} · {BOARD_PROFILES[board_key]['label']} wurde geprüft.\n\n"
            "Soll für dieses Gerät ein neuer Long-/Short-Name eingetragen werden?\n\n"
            f"Aktuell: {current_long or '–'} / {current_short or '–'}\n\n"
            "Nein = die aktuell eingetragenen Namen übernehmen.",
            parent=self,
        )

        if change_names:
            long_name = simpledialog.askstring(
                f"Serie #{index} · Long Name",
                "Long Name für dieses Gerät:",
                initialvalue=current_long,
                parent=self,
            )
            if long_name is None:
                self._set_status(f"Serie #{index} · Namenseingabe abgebrochen")
                self._set_busy(False)
                return
            short_name = simpledialog.askstring(
                f"Serie #{index} · Short Name",
                "Short Name (1–4 Zeichen):",
                initialvalue=current_short,
                parent=self,
            )
            if short_name is None:
                self._set_status(f"Serie #{index} · Namenseingabe abgebrochen")
                self._set_busy(False)
                return
            long_name = long_name.strip()
            short_name = short_name.strip()
            self.long_name_var.set(long_name)
            self.short_name_var.set(short_name)
        else:
            long_name = current_long
            short_name = current_short

        if not long_name:
            messagebox.showwarning("Name fehlt", "Bitte einen Long Name vergeben.", parent=self)
            self._set_busy(False)
            return
        if not (1 <= len(short_name) <= 4):
            messagebox.showwarning("Short Name", "Short Name muss 1 bis 4 Zeichen lang sein.", parent=self)
            self._set_busy(False)
            return

        if not messagebox.askyesno(
            f"Serie #{index} · Flash freigeben",
            f"Sicherheitsprüfung erfolgreich:\n\n"
            f"Port: {device.port}\n"
            f"Board: {BOARD_PROFILES[board_key]['label']}\n"
            f"Long Name: {long_name}\n"
            f"Short Name: {short_name}\n\n"
            "Die neueste JARNSEN-MESH 2.0.0 Firmware wird unmittelbar vor dem Flash erneut von GitHub aufgelöst.\n\n"
            "Dieses Gerät jetzt flashen?",
            parent=self,
        ):
            self._set_status(f"Serie #{index} · Flash vom Benutzer nicht freigegeben")
            self._set_busy(False)
            return

        self._append_log(
            f"Serie #{index} · FREIGABE · Port={device.port} · Board={BOARD_PROFILES[board_key]['label']} · "
            f"Long={long_name!r} · Short={short_name!r}"
        )
        threading.Thread(
            target=self._series_flash_worker,
            args=(index, device.port, board_key, long_name, short_name),
            daemon=True,
        ).start()

    def _series_flash_worker(
        self,
        index: int,
        port: str,
        board_key: str,
        long_name: str,
        short_name: str,
    ) -> None:
        try:
            bundle, backup, final_identity = self._perform_flash(
                port,
                board_key,
                long_name,
                short_name,
                series_index=index,
                strict_preflight=True,
            )
            self.series_count = index
            self.series_last_identity = final_identity
            self.series_last_port = port
            self.series_last_board = board_key
            self.after(
                0,
                self._series_success,
                index,
                port,
                board_key,
                long_name,
                short_name,
                bundle,
                backup,
            )
        except Exception as exc:
            self._show_error(exc)
            self._set_busy(False)

    def _series_success(
        self,
        index: int,
        port: str,
        board_key: str,
        long_name: str,
        short_name: str,
        bundle: FirmwareBundle,
        backup: Path,
    ) -> None:
        self.series_status_var.set(f"Serie aktiv · {index} Gerät(e) erfolgreich")
        self.series_button.configure(text=f"NÄCHSTES GERÄT ({index + 1}) PRÜFEN & FLASHEN")
        self._append_log(
            f"Serie #{index} · ERFOLG · Port={port} · Board={BOARD_PROFILES[board_key]['label']} · "
            f"Firmware={bundle.display_name} · Backup={backup.name} · Long={long_name!r} · Short={short_name!r}"
        )
        self._set_status(
            f"Serie #{index} erfolgreich · Gerät abziehen, nächstes Gerät anschließen und erneut prüfen"
        )
        self._set_busy(False)
        messagebox.showinfo(
            f"Serie #{index} erfolgreich",
            f"Gerät #{index} ist vollständig geprüft und fertig.\n\n"
            f"Port: {port}\n"
            f"Board: {BOARD_PROFILES[board_key]['label']}\n"
            f"Firmware: {bundle.display_name}\n"
            f"Long Name: {long_name}\nShort Name: {short_name}\n\n"
            "Jetzt dieses Gerät abziehen und das nächste per USB anschließen.\n"
            f"Danach „NÄCHSTES GERÄT ({index + 1}) PRÜFEN & FLASHEN“ drücken.",
            parent=self,
        )

    def _show_error(self, exc: Exception) -> None:
        text = str(exc) or exc.__class__.__name__
        self._set_status(f"FEHLER · {text}")
        self.after(0, messagebox.showerror, "JARNSEN MESH Flasher", text)


def _self_test_helper() -> int:
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    for tool in ("meshtastic", "esptool"):
        cmd = helper_command() + [tool, "--help"]
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                creationflags=flags,
            )
        except Exception:
            return 10
        if proc.returncode != 0:
            return 11
    return 0


def main() -> int:
    if "--self-test-helper" in sys.argv:
        return _self_test_helper()
    if "--version" in sys.argv:
        return 0
    app = FlasherApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
