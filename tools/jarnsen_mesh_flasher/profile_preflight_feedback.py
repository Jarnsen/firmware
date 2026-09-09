from __future__ import annotations

import time
from typing import Any


_INSTALLED = False


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _app_root() -> Any | None:
    try:
        import tkinter as tk

        return getattr(tk, "_default_root", None)
    except Exception:
        return None


def _paint(app: Any | None, value: float, text: str, ready_text: str) -> None:
    """Paint feedback synchronously before a blocking Meshtastic CLI read starts."""
    if app is None:
        return
    try:
        progress = getattr(app, "progress", None)
        if progress is not None:
            progress.set(max(0.0, min(1.0, float(value))))
    except Exception:
        pass
    try:
        status_var = getattr(app, "status_var", None)
        if status_var is not None:
            status_var.set(text)
    except Exception:
        pass
    try:
        native_ready = getattr(app, "native_ready_var", None)
        if native_ready is not None:
            native_ready.set(ready_text)
    except Exception:
        pass
    try:
        app.update_idletasks()
    except Exception:
        pass


def install(services: Any) -> None:
    """Make the synchronous role/name preflight visibly responsive on every board."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    import write_choice_guard

    base_read = write_choice_guard._read_current_summary

    def read_current_summary(runtime_services: Any, device: Any):
        app = _app_root()
        started = time.monotonic()
        _paint(
            app,
            0.02,
            "Profil schreiben · aktuelle Rolle und Namen lesen …",
            "Node-Daten lesen …",
        )
        _emit(
            f"PROFILE PREFLIGHT FEEDBACK START port={getattr(device, 'port', '')} "
            "visible-before-blocking-info=1 all-boards=1"
        )
        try:
            return base_read(runtime_services, device)
        finally:
            elapsed = time.monotonic() - started
            _paint(
                app,
                0.04,
                f"Profil schreiben · Node-Daten gelesen · {elapsed:.1f}s",
                "Auswahl prüfen …",
            )
            _emit(
                f"PROFILE PREFLIGHT FEEDBACK END port={getattr(device, 'port', '')} "
                f"elapsed={elapsed:.2f}s all-boards=1"
            )

    write_choice_guard._read_current_summary = read_current_summary
    services._jarnsen_profile_preflight_feedback = True
    _emit(
        "PROFILE PREFLIGHT FEEDBACK installed all-boards=1 synchronous-paint=1 "
        "role-name-read-visible=1"
    )
