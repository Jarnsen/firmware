from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import yaml
from functional_profile_fields import KEEP_VALUE, _lookup

_MISSING = object()


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _format_value(spec: Any, value: Any) -> str:
    kind = str(getattr(spec, "kind", "") or "")
    if kind == "bool":
        return "Ein" if bool(value) else "Aus"
    if kind == "complex":
        return yaml.safe_dump(
            value,
            allow_unicode=True,
            default_flow_style=True,
        ).strip()
    return "null" if value is None else str(value)


def _protobuf_default_value(spec: Any) -> Any:
    """Return the scalar proto default when export-config omits that field."""
    kind = str(getattr(spec, "kind", "") or "")
    if kind == "bool":
        return False
    if kind == "int":
        return 0
    if kind == "float":
        return 0.0
    if kind == "enum":
        choices = tuple(getattr(spec, "choices", ()) or ())
        return choices[0] if choices else _MISSING
    if kind == "string":
        return ""
    return _MISSING


def _selected_port(root: Any) -> str | None:
    device = None
    try:
        if hasattr(root, "_selected_device"):
            device = root._selected_device()
    except Exception:
        device = None
    port = str(getattr(device, "port", "") or "").strip()
    return port or None


def _read_current_node_config(
    port: str, services: Any
) -> tuple[dict[str, Any], str | None]:
    if not port:
        return {}, None

    work = Path(services.PATHS.root) / "profile-editor-current"
    work.mkdir(parents=True, exist_ok=True)
    safe_port = "".join(ch for ch in port if ch.isalnum() or ch in "-_") or "node"
    target = work / f"{safe_port}-{time.time_ns()}.yaml"

    try:
        services.meshtastic(
            port,
            "--export-config",
            str(target),
            timeout=60,
        )
        data = (
            yaml.safe_load(target.read_text(encoding="utf-8", errors="replace")) or {}
        )
        if not isinstance(data, dict):
            raise ValueError("Node-Export ist kein YAML-Mapping.")
        _emit(
            f"PROFILE EDITOR CURRENT NODE READ port={port} fields-source=export-config"
        )
        return data, port
    except Exception as exc:
        _emit(
            f"PROFILE EDITOR CURRENT NODE READ FAILED port={port} "
            f"type={type(exc).__name__} message={exc}"
        )
        return {}, None
    finally:
        try:
            target.unlink(missing_ok=True)
        except Exception:
            pass


def _current_value_for_spec(
    spec: Any, node_data: dict[str, Any]
) -> tuple[str | None, bool]:
    if bool(getattr(spec, "present", False)) or bool(getattr(spec, "locked", False)):
        return None, False

    found, value = _lookup(node_data, tuple(getattr(spec, "path", ())))
    if found:
        return _format_value(spec, value), True

    # Meshtastic export-config omits many scalar fields when they have their
    # protobuf default. Once a real node export succeeded, displaying that
    # effective default is more useful than showing a generic inheritance token.
    default = _protobuf_default_value(spec)
    if default is not _MISSING:
        return _format_value(spec, default), True
    return None, False


def _looks_like_custom_suggestion(values: list[str]) -> bool:
    """Keep free-form suggestion fields editable; fixed lists become menus."""
    try:
        import profile_editor_choices as choices

        actual = {str(value) for value in values if str(value) != KEEP_VALUE}
        for suggested in choices._SUGGESTED_VALUES.values():
            expected = {str(value) for value in suggested}
            if expected and expected.issubset(actual):
                return True
    except Exception:
        pass
    return False


class _FunctionalCtkProxy:
    """Render fixed/enumerated choices as full-width clickable blue menus."""

    def __init__(self, real_ctk: Any):
        self._real = real_ctk

    @staticmethod
    def _menu_values(kwargs: dict[str, Any]) -> list[str]:
        values = [str(value) for value in kwargs.get("values", ())]
        selectable = [value for value in values if value != KEEP_VALUE]
        return selectable or values

    def CTkOptionMenu(self, master: Any, *args: Any, **kwargs: Any) -> Any:
        kwargs = dict(kwargs)
        kwargs["values"] = self._menu_values(kwargs)
        return self._real.CTkOptionMenu(master, *args, **kwargs)

    def CTkComboBox(self, master: Any, *args: Any, **kwargs: Any) -> Any:
        values = [str(value) for value in kwargs.get("values", ())]
        kwargs = dict(kwargs)
        kwargs["values"] = self._menu_values(kwargs)
        if _looks_like_custom_suggestion(values):
            return self._real.CTkComboBox(master, *args, **kwargs)
        return self._real.CTkOptionMenu(master, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


def _read_with_feedback(
    root: Any, ctk: Any, port: str, services: Any
) -> tuple[dict[str, Any], str | None]:
    """Read the node while keeping an immediately visible responsive dialog."""
    if not hasattr(ctk, "CTkToplevel") or not hasattr(root, "wait_window"):
        return _read_current_node_config(port, services)

    try:
        if hasattr(root, "_set_status"):
            root._set_status(
                f"Profil bearbeiten · aktuelle Werte von {port} werden gelesen …"
            )
    except Exception:
        pass

    dialog = ctk.CTkToplevel(root)
    dialog.title("Profil vorbereiten")
    dialog.geometry("520x175")
    dialog.resizable(False, False)
    dialog.transient(root)
    dialog.protocol("WM_DELETE_WINDOW", lambda: None)

    ctk.CTkLabel(
        dialog,
        text="Aktuelle Node-Werte werden gelesen …",
        font=ctk.CTkFont(size=18, weight="bold"),
    ).pack(padx=24, pady=(26, 8))
    ctk.CTkLabel(
        dialog,
        text=(
            f"{port} wird vollständig ausgelesen. Das kann je nach USB-/Seriell-Verbindung "
            "einige Sekunden dauern."
        ),
        wraplength=455,
        justify="center",
    ).pack(padx=24, pady=(0, 14))
    progress = ctk.CTkProgressBar(dialog, mode="indeterminate", width=420)
    progress.pack(padx=24, pady=(0, 18))
    progress.start()

    result: dict[str, Any] = {"data": {}, "port": None}
    done = threading.Event()

    def worker() -> None:
        data, read_port = _read_current_node_config(port, services)
        result["data"] = data
        result["port"] = read_port
        done.set()

    threading.Thread(
        target=worker,
        name="jarnsen-profile-editor-node-read",
        daemon=True,
    ).start()

    def poll() -> None:
        if done.is_set():
            try:
                progress.stop()
            except Exception:
                pass
            dialog.destroy()
            return
        dialog.after(80, poll)

    dialog.after(80, poll)
    try:
        dialog.grab_set()
    except Exception:
        pass
    root.wait_window(dialog)

    data = result.get("data")
    read_port = result.get("port")
    return (data if isinstance(data, dict) else {}), (
        str(read_port) if read_port else None
    )


def install() -> None:
    """Show current connected-node values for inherited functional-profile fields.

    The editor opens only after an immediately visible read-progress dialog. The
    selected node is exported once, then absent scalar values are completed with
    their protobuf defaults. Unchanged inherited values are translated back to
    KEEP_VALUE on save, so simply viewing the editor never pins the full node
    configuration into the functional profile.
    """
    import functional_profile_editor as editor

    original_open = editor.open_functional_profile_editor
    if getattr(original_open, "_jarnsen_current_node_values", False):
        return

    def open_functional_profile_editor(
        root: Any,
        services: Any,
        source: Path,
        functional: Any,
        *,
        ctk: Any,
    ) -> Path | None:
        display_ctk = _FunctionalCtkProxy(ctk)
        port = _selected_port(root)
        if not port:
            return original_open(
                root,
                services,
                source,
                functional,
                ctk=display_ctk,
            )

        node_data, read_port = _read_with_feedback(root, ctk, port, services)
        if not node_data:
            return original_open(
                root,
                services,
                source,
                functional,
                ctk=display_ctk,
            )

        base_shown_value = editor.shown_value
        base_apply_values = editor.apply_profile_values
        inherited_values: dict[tuple[str, ...], str] = {}

        def shown_value(spec: Any) -> str:
            stored = base_shown_value(spec)
            current, inherited = _current_value_for_spec(spec, node_data)
            if inherited and current is not None:
                inherited_values[tuple(spec.path)] = current
                return current
            return stored

        def apply_profile_values(
            original: dict[str, Any],
            specs: Any,
            raw_values: dict[tuple[str, ...], str],
            functional_profile: Any,
        ) -> dict[str, Any]:
            adjusted = dict(raw_values)
            for spec in specs:
                path = tuple(spec.path)
                inherited = inherited_values.get(path)
                if inherited is None:
                    continue
                if str(adjusted.get(path, "")) == inherited:
                    adjusted[path] = KEEP_VALUE
            return base_apply_values(
                original,
                specs,
                adjusted,
                functional_profile,
            )

        editor.shown_value = shown_value
        editor.apply_profile_values = apply_profile_values
        try:
            if hasattr(root, "_append_log"):
                try:
                    root._append_log(
                        f"Profil bearbeiten · aktuelle Werte von {read_port or port} geladen"
                    )
                except Exception:
                    pass
            try:
                if hasattr(root, "_set_status"):
                    root._set_status(
                        f"Profil bearbeiten · aktuelle Werte von {read_port or port} geladen"
                    )
            except Exception:
                pass
            _emit(
                f"PROFILE EDITOR CURRENT VALUES active port={read_port or port} "
                "display-node-values=1 proto-defaults=1 keep-unmodified-inherited=1 "
                "fixed-dropdowns-full-menu=1"
            )
            return original_open(
                root,
                services,
                source,
                functional,
                ctk=display_ctk,
            )
        finally:
            editor.shown_value = base_shown_value
            editor.apply_profile_values = base_apply_values

    open_functional_profile_editor._jarnsen_current_node_values = True  # type: ignore[attr-defined]
    editor.open_functional_profile_editor = open_functional_profile_editor
    _emit(
        "PROFILE EDITOR CURRENT VALUES installed connected-node-display=1 "
        "profile-values-win=1 inherited-save-safe=1 visible-read-feedback=1 "
        "fixed-dropdowns-full-menu=1"
    )
