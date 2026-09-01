from __future__ import annotations

import threading
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox

import customtkinter as ctk
from serial.tools import list_ports


ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


@dataclass
class DeviceInfo:
    port: str
    description: str
    vid: int | None = None
    pid: int | None = None


class FlasherApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("JARNSEN MESH Flasher")
        self.geometry("760x620")
        self.minsize(700, 560)

        self.device_var = tk.StringVar(value="Kein Gerät erkannt")
        self.firmware_var = tk.StringVar(value="Noch nicht geprüft")
        self.profile_var = tk.StringVar(value="Kein Profil geladen")
        self.status_var = tk.StringVar(value="Bereit")
        self.long_name_var = tk.StringVar()
        self.short_name_var = tk.StringVar()

        self._build_ui()
        self.after(250, self.refresh_devices)

    def _card(self, title: str) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self, corner_radius=16)
        frame.pack(fill="x", padx=24, pady=(0, 14))
        ctk.CTkLabel(frame, text=title, font=ctk.CTkFont(size=13, weight="bold")).pack(
            anchor="w", padx=18, pady=(14, 4)
        )
        return frame

    def _build_ui(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=24, pady=(22, 16))
        ctk.CTkLabel(
            header,
            text="JARNSEN MESH Flasher",
            font=ctk.CTkFont(size=26, weight="bold"),
        ).pack(side="left")
        ctk.CTkLabel(header, textvariable=self.status_var).pack(side="right")

        device = self._card("GERÄT")
        ctk.CTkLabel(device, textvariable=self.device_var, font=ctk.CTkFont(size=17, weight="bold")).pack(
            anchor="w", padx=18, pady=(4, 14)
        )

        firmware = self._card("FIRMWARE")
        ctk.CTkLabel(firmware, textvariable=self.firmware_var).pack(anchor="w", padx=18, pady=(4, 14))

        profile = self._card("PROFIL")
        ctk.CTkLabel(profile, textvariable=self.profile_var).pack(anchor="w", padx=18, pady=(4, 8))
        ctk.CTkButton(profile, text="Grundeinstellungen einlesen", command=self.read_master_profile).pack(
            anchor="w", padx=18, pady=(0, 14)
        )

        names = self._card("GERÄTENAME")
        row = ctk.CTkFrame(names, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=(4, 14))
        ctk.CTkEntry(row, textvariable=self.long_name_var, placeholder_text="Long Name").pack(
            side="left", fill="x", expand=True, padx=(0, 10)
        )
        ctk.CTkEntry(row, textvariable=self.short_name_var, placeholder_text="Short Name", width=160).pack(side="left")

        self.progress = ctk.CTkProgressBar(self)
        self.progress.pack(fill="x", padx=24, pady=(2, 10))
        self.progress.set(0)

        self.flash_button = ctk.CTkButton(
            self,
            text="AUTOMATISCH FLASHEN",
            height=48,
            corner_radius=14,
            font=ctk.CTkFont(size=15, weight="bold"),
            command=self.start_flash,
        )
        self.flash_button.pack(fill="x", padx=24, pady=(0, 12))

        ctk.CTkButton(self, text="Geräte neu suchen", fg_color="transparent", command=self.refresh_devices).pack()

    def refresh_devices(self) -> None:
        ports = list(list_ports.comports())
        if not ports:
            self.device_var.set("Kein Gerät erkannt")
            self.flash_button.configure(state="disabled")
            return

        preferred = sorted(
            ports,
            key=lambda p: (
                0 if any(token in (p.description or "").lower() for token in ("cp210", "usb", "uart", "serial")) else 1,
                p.device,
            ),
        )[0]
        self.device_var.set(f"{preferred.device} · {preferred.description or 'Serielles Gerät'}")
        self.flash_button.configure(state="normal")

    def read_master_profile(self) -> None:
        self.profile_var.set("Profil-Lesen wird als nächster Schritt an die Meshtastic Serial API angebunden")

    def start_flash(self) -> None:
        if not self.long_name_var.get().strip() or not self.short_name_var.get().strip():
            messagebox.showwarning("Name fehlt", "Bitte Long Name und Short Name vergeben.")
            return
        self.flash_button.configure(state="disabled")
        threading.Thread(target=self._flash_worker, daemon=True).start()

    def _flash_worker(self) -> None:
        # The orchestration hooks are intentionally present already; the concrete
        # GitHub artifact resolver, backup, esptool flash and Meshtastic restore
        # services are wired in incrementally so each destructive step can be
        # validated independently on real hardware.
        steps = [
            (0.10, "Gerät prüfen"),
            (0.25, "Firmware ermitteln"),
            (0.40, "Sicherheitsbackup"),
            (0.68, "Factory/OTA flashen"),
            (0.82, "Grundeinstellungen wiederherstellen"),
            (0.93, "Namen setzen"),
            (1.00, "Neustart & Prüfung"),
        ]
        for value, label in steps:
            self.after(0, self.progress.set, value)
            self.after(0, self.status_var.set, label)
            self.event_generate("<<Noop>>", when="tail")
            threading.Event().wait(0.15)
        self.after(0, self.status_var.set, "Grundgerüst bereit – Hardware-Schritte noch gesperrt")
        self.after(0, self.flash_button.configure, {"state": "normal"})


def main() -> None:
    app = FlasherApp()
    app.mainloop()


if __name__ == "__main__":
    main()
