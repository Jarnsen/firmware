from __future__ import annotations

import threading
import types
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


def _decode_timeout_output(exc: Exception) -> str:
    parts: list[str] = []
    for name in ("stdout", "stderr", "output"):
        value = getattr(exc, name, None)
        if not value:
            continue
        if isinstance(value, bytes):
            value = value.decode("utf-8", errors="replace")
        text = str(value)
        if text and text not in parts:
            parts.append(text)
    return "\n".join(parts)


def install(services: Any) -> None:
    """Add a profile-only workflow that never touches firmware or flash memory."""
    import customtkinter as ctk

    original_root_init = ctk.CTk.__init__

    def root_init(self: Any, *args: Any, **kwargs: Any) -> None:
        original_root_init(self, *args, **kwargs)

        def patch_app() -> None:
            required = (
                "_selected_device",
                "_selected_board_key",
                "_set_progress",
                "_append_log",
                "_set_busy",
            )
            if not all(hasattr(self, name) for name in required):
                try:
                    self.after(120, patch_app)
                except Exception:
                    pass
                return
            if getattr(self, "_jarnsen_profile_only_installed", False):
                return

            profile_select_button = None
            for widget in _walk(self):
                text = _button_text(widget)
                if text in {"Profil auswählen", "Profil laden"}:
                    profile_select_button = widget
                    break
            if profile_select_button is None:
                try:
                    self.after(180, patch_app)
                except Exception:
                    pass
                return

            self._jarnsen_profile_only_installed = True
            parent = getattr(profile_select_button, "master", None)
            if parent is None:
                _emit("PROFILE ONLY UI failed: profile button parent missing")
                return

            def start_profile_only() -> None:
                if getattr(self, "busy", False):
                    return

                device = self._selected_device()
                if device is None:
                    messagebox.showwarning(
                        "Kein Gerät",
                        "Bitte zuerst ein Zielgerät per USB auswählen.",
                        parent=self,
                    )
                    return

                board_key = self._selected_board_key()
                if not board_key:
                    messagebox.showwarning(
                        "Board unbekannt",
                        "Bitte das Board automatisch erkennen lassen oder manuell auswählen.",
                        parent=self,
                    )
                    return

                active_profile = Path(services.PATHS.active_profile)
                if not active_profile.exists():
                    messagebox.showwarning(
                        "Kein Profil",
                        "Bitte zuerst ein Profil auswählen oder vom Master einlesen.",
                        parent=self,
                    )
                    return

                if getattr(device, "board_key", None) and device.board_key != board_key:
                    messagebox.showerror(
                        "Board-Widerspruch",
                        f"Geräteerkennung und ausgewähltes Board widersprechen sich.\n\n"
                        f"Gerät: {services.BOARD_PROFILES[device.board_key]['label']}\n"
                        f"Auswahl: {services.BOARD_PROFILES[board_key]['label']}",
                        parent=self,
                    )
                    return

                try:
                    from profile_catalog import board_for_profile
                    assigned_board = board_for_profile(active_profile)
                except Exception:
                    assigned_board = None

                if assigned_board and assigned_board != board_key:
                    messagebox.showerror(
                        "Profil passt nicht zum Board",
                        f"Das aktive Profil ist {services.BOARD_PROFILES[assigned_board]['label']} zugeordnet, "
                        f"angeschlossen ist {services.BOARD_PROFILES[board_key]['label']}.\n\n"
                        "Das Profil wird nicht geschrieben.",
                        parent=self,
                    )
                    return

                long_name = str(self.long_name_var.get()).strip() if hasattr(self, "long_name_var") else ""
                short_name = str(self.short_name_var.get()).strip() if hasattr(self, "short_name_var") else ""
                if bool(long_name) != bool(short_name):
                    messagebox.showwarning(
                        "Gerätename unvollständig",
                        "Long Name und Short Name müssen entweder beide gesetzt oder beide leer sein.",
                        parent=self,
                    )
                    return
                if short_name and not (1 <= len(short_name) <= 4):
                    messagebox.showwarning(
                        "Short Name",
                        "Short Name muss 1 bis 4 Zeichen lang sein.",
                        parent=self,
                    )
                    return

                board_label = services.BOARD_PROFILES[board_key]["label"]
                names_text = (
                    f"{long_name} / {short_name}" if long_name and short_name else "nicht ändern"
                )
                if not messagebox.askyesno(
                    "Nur Profil schreiben",
                    f"Port: {device.port}\n"
                    f"Board: {board_label}\n"
                    f"Profil: {Path(self.profile_path_var.get()).name if hasattr(self, 'profile_path_var') else active_profile.name}\n"
                    f"Name: {names_text}\n\n"
                    "Es werden nur Grundeinstellungen, Kanäle, Module, Name sowie Rolle/Power-Saving geschrieben.\n"
                    "Firmware, Flash-Speicher und vorhandenes Firmware-Image werden NICHT verändert.\n\n"
                    "Profil jetzt schreiben?",
                    parent=self,
                ):
                    return

                self._set_busy(True)
                self._set_progress(0.0, "Nur Profil · Vorbereitung")

                threading.Thread(
                    target=profile_only_worker,
                    args=(device.port, board_key, long_name, short_name),
                    name="jarnsen-profile-only",
                    daemon=True,
                ).start()

            profile_only_button = ctk.CTkButton(
                parent,
                text="NUR PROFIL SCHREIBEN",
                width=170,
                command=start_profile_only,
            )
            profile_only_button.pack(side="left", padx=(10, 0))
            self.profile_only_button = profile_only_button

            original_set_busy = self._set_busy

            def set_busy(app_self: Any, busy: bool) -> None:
                original_set_busy(busy)
                state = "disabled" if busy else "normal"
                try:
                    app_self.after(0, profile_only_button.configure, {"state": state})
                except Exception:
                    pass

            self._set_busy = types.MethodType(set_busy, self)

            def profile_only_worker(port: str, board_key: str, long_name: str, short_name: str) -> None:
                previous_profile_callback = getattr(services, "_jarnsen_profile_progress_callback", None)

                def profile_progress(fraction: float, stage: str, detail: str = "") -> None:
                    fraction = max(0.0, min(1.0, float(fraction)))
                    if "rolle" in stage.lower() or "power" in stage.lower():
                        overall = 0.80 + 0.10 * fraction
                    else:
                        overall = 0.15 + 0.55 * fraction
                    suffix = f" · {detail}" if detail else ""
                    self._set_progress(overall, f"Nur Profil · {stage}{suffix}")

                services._jarnsen_profile_progress_callback = profile_progress
                try:
                    board_label = services.BOARD_PROFILES[board_key]["label"]
                    self._append_log(
                        f"PROFIL-ONLY START · Port={port} · Board={board_label} · "
                        f"Profil={Path(services.PATHS.active_profile).name} · Firmware/Flash=unverändert"
                    )

                    self._set_progress(0.04, "Nur Profil · USB-Port prüfen")
                    from serial.tools import list_ports
                    if not any(str(item.device).upper() == port.upper() for item in list_ports.comports()):
                        raise services.FlasherError(f"{port} ist nicht mehr als serieller USB-Port vorhanden.")

                    self._set_progress(0.08, "Nur Profil · Board prüfen")
                    detected = None
                    try:
                        result = services.meshtastic(port, "--info", timeout=15, check=False)
                        info_text = "\n".join(filter(None, (result.stdout, result.stderr)))
                        detected = services.detect_board_from_text(info_text)
                    except Exception as exc:
                        info_text = _decode_timeout_output(exc)
                        if info_text:
                            detected = services.detect_board_from_text(info_text)
                            self._append_log(
                                f"PROFIL-ONLY BOARD CHECK · Teilantwort nach Timeout ausgewertet · "
                                f"Board={detected or 'unbekannt'}"
                            )

                    if detected and detected != board_key:
                        raise services.FlasherError(
                            f"Boardprüfung fehlgeschlagen: erwartet {board_label}, "
                            f"erkannt {services.BOARD_PROFILES[detected]['label']}."
                        )
                    self._append_log(
                        f"PROFIL-ONLY BOARD CHECK OK · Port={port} · Board={board_label} · "
                        f"Erkennung={detected or 'manuell bestätigt'}"
                    )

                    self._set_progress(0.12, "Nur Profil · Profil/Board-Zuordnung prüfen")
                    try:
                        from profile_catalog import board_for_profile
                        assigned = board_for_profile(Path(services.PATHS.active_profile))
                    except Exception:
                        assigned = None
                    if assigned and assigned != board_key:
                        raise services.FlasherError(
                            f"Profil ist {services.BOARD_PROFILES[assigned]['label']} zugeordnet, "
                            f"Zielgerät ist {board_label}."
                        )

                    self._set_progress(0.15, "Nur Profil · Grundeinstellungen schreiben")
                    services.restore_profile(port)

                    if long_name and short_name:
                        self._set_progress(0.73, "Nur Profil · Long/Short Name schreiben")
                        self._append_log(
                            f"PROFIL-ONLY NAMEN · Long={long_name!r} · Short={short_name!r}"
                        )
                        services.set_names(port, long_name, short_name)
                    else:
                        self._set_progress(0.78, "Nur Profil · Gerätenamen unverändert lassen")
                        self._append_log("PROFIL-ONLY NAMEN · übersprungen")

                    self._set_progress(0.80, "Nur Profil · Rolle/Power-Saving zuletzt aktivieren")
                    services.reboot_node(port)

                    self._set_progress(0.91, "Nur Profil · Auf Node-Neuanmeldung warten")
                    services.wait_for_serial(port, timeout=90)

                    self._set_progress(0.96, "Nur Profil · Endprüfung Board/Rolle/Power-Saving")
                    services.verify_node(port, expected_board=board_key)

                    self._set_progress(1.0, "Nur Profil · Fertig · Konfiguration geprüft")
                    self._append_log(
                        f"PROFIL-ONLY ENDE · ERFOLG · Port={port} · Board={board_label} · "
                        "Firmware/Flash unverändert"
                    )
                    self.after(
                        0,
                        messagebox.showinfo,
                        "Profil erfolgreich geschrieben",
                        f"{board_label} auf {port} wurde ohne Firmware-Flash konfiguriert.\n\n"
                        f"Profil: {Path(self.profile_path_var.get()).name if hasattr(self, 'profile_path_var') else Path(services.PATHS.active_profile).name}\n"
                        f"Name: {long_name + ' / ' + short_name if long_name and short_name else 'unverändert'}\n\n"
                        "Firmware und Flash-Speicher wurden nicht verändert.",
                    )
                except Exception as exc:
                    self._append_log(
                        f"PROFIL-ONLY FEHLER · {type(exc).__name__}: {exc}"
                    )
                    try:
                        self._show_error(exc)
                    except Exception:
                        self.after(0, messagebox.showerror, "Profil schreiben fehlgeschlagen", str(exc))
                finally:
                    services._jarnsen_profile_progress_callback = previous_profile_callback
                    self._set_busy(False)

            _emit("PROFILE ONLY UI installed no-flash=1 staged-restore=1 final-verify=1")

        try:
            self.after(520, patch_app)
        except Exception:
            pass

    ctk.CTk.__init__ = root_init
    _emit("PROFILE ONLY layer installed")
