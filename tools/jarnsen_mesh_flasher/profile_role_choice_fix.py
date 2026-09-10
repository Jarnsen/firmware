from __future__ import annotations

import tempfile
import time
from pathlib import Path
from typing import Any

import yaml


_INSTALLED = False


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _key(port: str) -> str:
    return str(port or "").strip().upper()


def _norm(value: Any) -> str:
    return str(value or "").strip().casefold()


def _external_work_dir(name: str) -> Path:
    root = Path(tempfile.gettempdir()) / "JarnsenMeshFlasher" / name
    root.mkdir(parents=True, exist_ok=True)
    return root


def _prepare_choices(app: Any, services: Any, *, action_name: str):
    """Role/name preflight where functional profiles no longer suppress role choice."""
    import write_choice_guard as guard

    device = app._selected_device()
    if device is None:
        return None

    key = _key(device.port)
    guard._ROLE_OVERRIDE_BY_PORT.pop(key, None)

    profile_path = Path(services.PATHS.active_profile)
    if not profile_path.exists():
        return None

    target_long = str(app.long_name_var.get() or "").strip()
    target_short = str(app.short_name_var.get() or "").strip()
    try:
        target_profile = guard.summary_from_profile_file(profile_path)
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
    current = guard._read_current_summary(services, device)

    target_role = str(target_profile.role or "").strip()
    functional_label = ""
    try:
        import functional_profiles

        functional = functional_profiles.active_profile(services)
        if functional is not None:
            functional_label = str(functional.label or "").strip()
            target_role = str(functional.meshtastic_role or "").strip()
            guard._append_log(
                app,
                f"WRITE CHOICE FUNKTION · Port={device.port} · "
                f"{functional_label} · Profilrolle={target_role} · "
                "Rollenauswahl bei Abweichung=aktiv",
            )
    except Exception:
        pass

    selected_role = target_role
    if target_role:
        if not str(current.role or "").strip():
            from tkinter import messagebox

            messagebox.showerror(
                "Rolle nicht lesbar",
                "Die aktuelle Rolle des angeschlossenen Nodes konnte nicht sicher "
                "gelesen werden.\n\nDer Schreibvorgang wird nicht gestartet.",
                parent=app,
            )
            guard._append_log(
                app,
                f"WRITE CHOICE ABBRUCH · Port={device.port} · aktuelle Rolle nicht lesbar",
            )
            return None

        if _norm(current.role) != _norm(target_role):
            role_choice = guard._two_choice(
                app,
                title="Rolle auswählen",
                heading="Welche Rolle soll geschrieben werden?",
                details=(
                    "Die aktuelle Node-Rolle weicht von der Rolle im Profil ab.\n\n"
                    f"Aktuelle Rolle:  {current.role}\n"
                    f"Profil-Rolle:    {target_role}\n\n"
                    "Wähle die Rolle, die nach dem Schreiben auf dem Node aktiv sein soll."
                ),
                left_text=str(current.role),
                right_text=target_role,
            )
            if role_choice is None:
                guard._append_log(
                    app,
                    f"WRITE CHOICE ABBRUCH · Port={device.port} · Rollenauswahl geschlossen",
                )
                return None
            selected_role = str(current.role).strip() if role_choice == "left" else target_role
            guard._append_log(
                app,
                f"WRITE CHOICE ROLLE · Port={device.port} · "
                f"aktuell={current.role!r} · profil={target_role!r} · "
                f"gewählt={selected_role!r}",
            )

    names_differ = (
        _norm(current.long_name) != _norm(target_long)
        or _norm(current.short_name) != _norm(target_short)
    )
    selected_long = target_long
    selected_short = target_short

    if names_differ:
        names_choice = guard._two_choice(
            app,
            title="Gerätenamen auswählen",
            heading="Welche Namen sollen geschrieben werden?",
            details=(
                "Long Name und Short Name werden gemeinsam behandelt.\n\n"
                "Aktuell auf dem Node:\n"
                f"Long Name:  {current.long_name or '–'}\n"
                f"Short Name: {current.short_name or '–'}\n\n"
                "Neu / vorgesehen:\n"
                f"Long Name:  {target_long or '–'}\n"
                f"Short Name: {target_short or '–'}"
            ),
            left_text="Alte Namen behalten",
            right_text="Neue Namen übernehmen",
        )
        if names_choice is None:
            guard._append_log(
                app,
                f"WRITE CHOICE ABBRUCH · Port={device.port} · Namensauswahl geschlossen",
            )
            return None

        if names_choice == "left":
            selected_long = str(current.long_name or "").strip()
            selected_short = str(current.short_name or "").strip()
            if not selected_long or not (1 <= len(selected_short) <= 4):
                from tkinter import messagebox

                messagebox.showerror(
                    "Alte Namen nicht verwendbar",
                    "Die bisherigen Long-/Short-Namen konnten nicht vollständig "
                    "gelesen werden. Sie können deshalb nicht sicher beibehalten werden.",
                    parent=app,
                )
                return None

        guard._append_log(
            app,
            f"WRITE CHOICE NAMEN · Port={device.port} · "
            f"alt={current.long_name!r}/{current.short_name!r} · "
            f"neu={target_long!r}/{target_short!r} · "
            f"gewählt={selected_long!r}/{selected_short!r}",
        )

    app.long_name_var.set(selected_long)
    app.short_name_var.set(selected_short)

    # Keep the operator's explicit decision alive until the delta writer/final
    # transaction has consumed it. This is also required for functional profiles.
    if (
        target_role
        and str(current.role or "").strip()
        and _norm(current.role) != _norm(target_role)
    ):
        guard._ROLE_OVERRIDE_BY_PORT[key] = selected_role

    return guard.WriteChoices(
        long_name=selected_long,
        short_name=selected_short,
        role=selected_role,
    )


def _profile_with_role(services: Any, source: Path, port: str, role: str) -> Path:
    """Build a role override outside PATHS.root so functional enforcement cannot undo it."""
    try:
        data = yaml.safe_load(source.read_text(encoding="utf-8", errors="replace")) or {}
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
    device["role"] = str(role or "").strip()

    work_dir = _external_work_dir("write-choice")
    safe_port = "".join(ch for ch in str(port) if ch.isalnum()) or "port"
    path = work_dir / f"{safe_port}-{time.time_ns()}-role.yaml"
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def _write_delta_profile(_work_dir: Path, port: str, delta: dict[str, Any]) -> Path:
    """Keep the already-computed delta out of functional_profiles' runtime-work renormalizer."""
    work_dir = _external_work_dir("restore-work")
    path = work_dir / f"{_key(port).replace(':', '-')}-{time.time_ns()}-delta.yaml"
    path.write_text(
        yaml.safe_dump(delta, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def install(services: Any) -> None:
    global _INSTALLED
    if _INSTALLED or getattr(services, "_jarnsen_profile_role_choice_fix", False):
        return
    _INSTALLED = True

    import profile_runtime_efficiency
    import write_choice_guard

    # Late binding is intentional: button guards and restore wrappers resolve
    # these module globals at call time, so this fixes already-installed layers.
    write_choice_guard._prepare_choices = _prepare_choices
    write_choice_guard._profile_with_role = _profile_with_role
    profile_runtime_efficiency._write_delta_profile = _write_delta_profile

    services._jarnsen_profile_role_choice_fix = True
    _emit(
        "PROFILE ROLE CHOICE FIX installed functional-mismatch-prompt=1 "
        "selected-role-authoritative=1 external-role-override=1 "
        "external-delta=1 functional-renormalize-bypass=1"
    )
