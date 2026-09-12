from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import customtkinter as ctk
from profile_utils import (
    ProfileSummary,
    summary_from_info_text,
    summary_from_profile_file,
)

_INSTALLED = False
_ROLE_OVERRIDE_BY_PORT: dict[str, str] = {}


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _append_log(app: Any, message: str) -> None:
    try:
        app._append_log(message)
    except Exception:
        _emit(message)


def _norm(value: str) -> str:
    return str(value or "").strip().casefold()


def _decode(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


@dataclass(frozen=True)
class WriteChoices:
    long_name: str
    short_name: str
    role: str


def _two_choice(
    parent: Any,
    *,
    title: str,
    heading: str,
    details: str,
    left_text: str,
    right_text: str,
) -> str | None:
    """Show a mandatory two-choice popup.

    Returning None means that the user closed the dialog or pressed Escape.
    There is deliberately no implicit/default choice.
    """
    result: dict[str, str | None] = {"value": None}

    dialog = ctk.CTkToplevel(parent)
    dialog.title(title)
    dialog.geometry("600x330")
    dialog.minsize(560, 300)
    dialog.resizable(False, False)
    try:
        dialog.transient(parent)
    except Exception:
        pass

    shell = ctk.CTkFrame(dialog, corner_radius=16)
    shell.pack(fill="both", expand=True, padx=18, pady=18)

    ctk.CTkLabel(
        shell,
        text=heading,
        font=ctk.CTkFont(size=19, weight="bold"),
        anchor="w",
        justify="left",
    ).pack(fill="x", padx=20, pady=(20, 10))

    ctk.CTkLabel(
        shell,
        text=details,
        font=ctk.CTkFont(size=13),
        anchor="w",
        justify="left",
        wraplength=520,
    ).pack(fill="both", expand=True, padx=20, pady=(0, 18))

    buttons = ctk.CTkFrame(shell, fg_color="transparent")
    buttons.pack(fill="x", padx=20, pady=(0, 20))
    buttons.grid_columnconfigure(0, weight=1, uniform="write-choice")
    buttons.grid_columnconfigure(1, weight=1, uniform="write-choice")

    def finish(value: str | None) -> None:
        result["value"] = value
        try:
            dialog.grab_release()
        except Exception:
            pass
        try:
            dialog.destroy()
        except Exception:
            pass

    ctk.CTkButton(
        buttons,
        text=left_text,
        height=46,
        corner_radius=10,
        command=lambda: finish("left"),
    ).grid(row=0, column=0, sticky="ew", padx=(0, 6))

    ctk.CTkButton(
        buttons,
        text=right_text,
        height=46,
        corner_radius=10,
        command=lambda: finish("right"),
    ).grid(row=0, column=1, sticky="ew", padx=(6, 0))

    dialog.protocol("WM_DELETE_WINDOW", lambda: finish(None))
    dialog.bind("<Escape>", lambda _event: finish(None))
    try:
        dialog.grab_set()
        dialog.focus_force()
    except Exception:
        pass
    parent.wait_window(dialog)
    return result["value"]


def _read_current_summary(services: Any, device: Any) -> ProfileSummary:
    fresh_text = ""
    try:
        result = services.meshtastic(
            device.port,
            "--info",
            timeout=25,
            check=False,
        )
        fresh_text = "\n".join(
            part for part in (_decode(result.stdout), _decode(result.stderr)) if part
        )
    except Exception as exc:
        fresh_text = "\n".join(
            part
            for part in (
                _decode(getattr(exc, "stdout", "")),
                _decode(getattr(exc, "stderr", "")),
                _decode(getattr(exc, "output", "")),
            )
            if part
        )

    current = summary_from_info_text(fresh_text)
    fallback = summary_from_info_text(str(getattr(device, "model_text", "") or ""))
    current = current.with_fallback(fallback)

    _emit(
        "WRITE CHOICE READ "
        f"port={device.port} fresh_chars={len(fresh_text)} "
        f"long={current.long_name!r} short={current.short_name!r} role={current.role!r}"
    )
    return current


def _prepare_choices(
    app: Any, services: Any, *, action_name: str
) -> WriteChoices | None:
    device = app._selected_device()
    if device is None:
        return None

    key = str(device.port).upper()
    # A previous confirmation can have been cancelled by a later legacy/final
    # confirmation. Never let such a pending choice leak into the next action.
    _ROLE_OVERRIDE_BY_PORT.pop(key, None)

    profile_path = Path(services.PATHS.active_profile)
    if not profile_path.exists():
        return None

    target_long = str(app.long_name_var.get() or "").strip()
    target_short = str(app.short_name_var.get() or "").strip()
    try:
        target_profile = summary_from_profile_file(profile_path)
    except Exception as exc:
        from tkinter import messagebox

        messagebox.showerror(
            "Profil konnte nicht geprüft werden",
            f"Die Rolle des aktiven Profils konnte nicht gelesen werden.\n\n{exc}",
            parent=app,
        )
        return None

    try:
        app._set_status(f"{action_name} · aktuelle Rolle und Namen prüfen …")
    except Exception:
        pass
    current = _read_current_summary(services, device)

    selected_role = target_profile.role.strip()
    functional_role_locked = False
    try:
        from functional_profiles import active_profile as active_functional_profile

        functional = active_functional_profile(services)
        if functional is not None:
            functional_role_locked = True
            selected_role = functional.meshtastic_role
            _append_log(
                app,
                f"WRITE CHOICE FUNKTION · Port={device.port} · "
                f"{functional.label} erzwingt Rolle {selected_role}",
            )
    except Exception:
        # The ordinary profile flow remains fully available when the optional
        # functional-profile layer is not active.
        functional_role_locked = False

    if selected_role and not functional_role_locked:
        if not current.role.strip():
            from tkinter import messagebox

            messagebox.showerror(
                "Rolle nicht lesbar",
                "Die aktuelle Rolle des angeschlossenen Nodes konnte nicht sicher "
                "gelesen werden.\n\nDer Schreibvorgang wird nicht gestartet.",
                parent=app,
            )
            _append_log(
                app,
                f"WRITE CHOICE ABBRUCH · Port={device.port} · aktuelle Rolle nicht lesbar",
            )
            return None

        if _norm(current.role) != _norm(selected_role):
            role_choice = _two_choice(
                app,
                title="Rolle auswählen",
                heading="Welche Rolle soll geschrieben werden?",
                details=(
                    "Die aktuelle Node-Rolle weicht von der Rolle im Profil ab.\n\n"
                    f"Aktuelle Rolle:  {current.role}\n"
                    f"Profil-Rolle:    {selected_role}\n\n"
                    "Wähle die Rolle, die nach dem Schreiben auf dem Node aktiv sein soll."
                ),
                left_text=current.role,
                right_text=selected_role,
            )
            if role_choice is None:
                _append_log(
                    app,
                    f"WRITE CHOICE ABBRUCH · Port={device.port} · Rollenauswahl geschlossen",
                )
                return None
            selected_role = current.role if role_choice == "left" else selected_role
            _append_log(
                app,
                f"WRITE CHOICE ROLLE · Port={device.port} · "
                f"aktuell={current.role!r} · profil={target_profile.role!r} · "
                f"gewählt={selected_role!r}",
            )

    names_differ = _norm(current.long_name) != _norm(target_long) or _norm(
        current.short_name
    ) != _norm(target_short)
    selected_long = target_long
    selected_short = target_short

    if names_differ:
        names_choice = _two_choice(
            app,
            title="Gerätenamen auswählen",
            heading="Welche Namen sollen geschrieben werden?",
            details=(
                "Long Name und Short Name werden gemeinsam behandelt.\n\n"
                "Aktuell auf dem Node:\n"
                f"Long Name:  {current.long_name or '-'}\n"
                f"Short Name: {current.short_name or '-'}\n\n"
                "Neu / vorgesehen:\n"
                f"Long Name:  {target_long or '-'}\n"
                f"Short Name: {target_short or '-'}"
            ),
            left_text="Alte Namen behalten",
            right_text="Neue Namen übernehmen",
        )
        if names_choice is None:
            _append_log(
                app,
                f"WRITE CHOICE ABBRUCH · Port={device.port} · Namensauswahl geschlossen",
            )
            return None

        if names_choice == "left":
            selected_long = current.long_name.strip()
            selected_short = current.short_name.strip()
            if not selected_long or not (1 <= len(selected_short) <= 4):
                from tkinter import messagebox

                messagebox.showerror(
                    "Alte Namen nicht verwendbar",
                    "Die bisherigen Long-/Short-Namen konnten nicht vollständig "
                    "gelesen werden. Sie können deshalb nicht sicher beibehalten werden.",
                    parent=app,
                )
                return None

        _append_log(
            app,
            f"WRITE CHOICE NAMEN · Port={device.port} · "
            f"alt={current.long_name!r}/{current.short_name!r} · "
            f"neu={target_long!r}/{target_short!r} · "
            f"gewählt={selected_long!r}/{selected_short!r}",
        )

    app.long_name_var.set(selected_long)
    app.short_name_var.set(selected_short)

    # Only a mismatch requires an override. If profile/current are equal, the
    # normal staged profile restore already writes the right role.
    if (
        not functional_role_locked
        and target_profile.role.strip()
        and current.role.strip()
        and _norm(current.role) != _norm(target_profile.role)
    ):
        _ROLE_OVERRIDE_BY_PORT[key] = selected_role

    return WriteChoices(
        long_name=selected_long,
        short_name=selected_short,
        role=selected_role,
    )


def _profile_with_role(services: Any, source: Path, port: str, role: str) -> Path:
    try:
        import yaml

        data = (
            yaml.safe_load(source.read_text(encoding="utf-8", errors="replace")) or {}
        )
    except Exception as exc:
        raise services.FlasherError(
            f"Profil-Rolle konnte für die Auswahl nicht vorbereitet werden: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise services.FlasherError("Aktives Profil hat kein gültiges YAML-Objekt.")

    root = data.get("config")
    if not isinstance(root, dict):
        root = data

    device = root.get("device")
    if not isinstance(device, dict):
        device = {}
        root["device"] = device
    device["role"] = role

    work_dir = services.PATHS.root / "write-choice"
    work_dir.mkdir(parents=True, exist_ok=True)
    safe_port = "".join(ch for ch in str(port) if ch.isalnum()) or "port"
    path = work_dir / f"{safe_port}-{int(time.time() * 1000)}-role.yaml"
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def _install_restore_override(services: Any) -> None:
    base_restore_profile = services.restore_profile

    def guarded_restore_profile(port: str, profile: Path | None = None) -> None:
        key = str(port).upper()
        role = _ROLE_OVERRIDE_BY_PORT.pop(key, None)
        if not role:
            return base_restore_profile(port, profile)

        source = Path(profile or services.PATHS.active_profile)
        override_profile = _profile_with_role(services, source, port, role)
        _emit(
            f"WRITE CHOICE ROLE APPLY port={port} role={role!r} "
            f"source={source.name!r} temp={override_profile.name!r}"
        )
        try:
            return base_restore_profile(port, override_profile)
        finally:
            try:
                override_profile.unlink(missing_ok=True)
            except Exception:
                pass

    services.restore_profile = guarded_restore_profile


def _command_of(button: Any) -> Callable[[], Any] | None:
    command = getattr(button, "_command", None)
    if callable(command):
        return command
    try:
        command = button.cget("command")
    except Exception:
        command = None
    return command if callable(command) else None


def _wrap_button(app: Any, services: Any, button: Any, *, action_name: str) -> bool:
    if button is None:
        return False
    if getattr(button, "_jarnsen_write_choice_guard", False):
        return True

    original_command = _command_of(button)
    if not callable(original_command):
        return False

    def guarded_command() -> Any:
        if getattr(app, "busy", False):
            return None

        # Let the original workflow show its existing prerequisite warnings.
        device = app._selected_device()
        if device is None or not Path(services.PATHS.active_profile).exists():
            return original_command()

        choices = _prepare_choices(app, services, action_name=action_name)
        if choices is None:
            try:
                app._set_status(f"{action_name} · abgebrochen")
            except Exception:
                pass
            return None

        port_key = str(device.port).upper()
        result = original_command()

        # The original workflows set busy=True synchronously only after their
        # final confirmation. If that final confirmation was cancelled, discard
        # the one-shot role choice immediately.
        if not getattr(app, "busy", False):
            _ROLE_OVERRIDE_BY_PORT.pop(port_key, None)
        return result

    button.configure(command=guarded_command)
    button._jarnsen_write_choice_guard = True
    _emit(f"WRITE CHOICE BUTTON wrapped action={action_name!r}")
    return True


def install(services: Any) -> None:
    """Confirm role and Long/Short name changes before profile writes/full flashes."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    _install_restore_override(services)

    original_root_init = ctk.CTk.__init__

    def root_init(app: Any, *args: Any, **kwargs: Any) -> None:
        original_root_init(app, *args, **kwargs)

        def patch_app(attempt: int = 0) -> None:
            flash_ready = _wrap_button(
                app,
                services,
                getattr(app, "flash_button", None),
                action_name="Flash",
            )
            profile_ready = _wrap_button(
                app,
                services,
                getattr(app, "profile_only_button", None),
                action_name="Profil schreiben",
            )
            if flash_ready and profile_ready:
                app._jarnsen_write_choice_guard_installed = True
                _emit("WRITE CHOICE GUARD UI ready flash=1 profile_only=1")
                return
            if attempt < 80:
                try:
                    app.after(150, patch_app, attempt + 1)
                except Exception:
                    pass
            else:
                _emit(
                    "WRITE CHOICE GUARD UI incomplete "
                    f"flash={int(flash_ready)} profile_only={int(profile_ready)}"
                )

        try:
            app.after(650, patch_app)
        except Exception:
            pass

    ctk.CTk.__init__ = root_init
    _emit("WRITE CHOICE GUARD installed role=1 combined_names=1 close_aborts=1")
