from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import yaml
from functional_profile_fields import KEEP_VALUE, _lookup


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


def _read_current_node_config(root: Any, services: Any) -> tuple[dict[str, Any], str | None]:
    device = None
    try:
        if hasattr(root, "_selected_device"):
            device = root._selected_device()
    except Exception:
        device = None

    port = str(getattr(device, "port", "") or "").strip()
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
        data = yaml.safe_load(target.read_text(encoding="utf-8", errors="replace")) or {}
        if not isinstance(data, dict):
            raise ValueError("Node-Export ist kein YAML-Mapping.")
        _emit(f"PROFILE EDITOR CURRENT NODE READ port={port} fields-source=export-config")
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


def _current_value_for_spec(spec: Any, node_data: dict[str, Any]) -> tuple[str | None, bool]:
    if bool(getattr(spec, "present", False)) or bool(getattr(spec, "locked", False)):
        return None, False
    found, value = _lookup(node_data, tuple(getattr(spec, "path", ())))
    if not found:
        return None, False
    return _format_value(spec, value), True


def install() -> None:
    """Show current connected-node values for inherited functional-profile fields.

    The UI may display an actual node value even when the functional profile does
    not pin that field. Unchanged inherited values are translated back to
    KEEP_VALUE on save, so merely opening the editor never converts the whole
    node configuration into hard-coded profile values.
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
        node_data, port = _read_current_node_config(root, services)
        if not node_data:
            return original_open(root, services, source, functional, ctk=ctk)

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
                        f"Profil bearbeiten · aktuelle nicht gespeicherte Werte werden von {port} angezeigt"
                    )
                except Exception:
                    pass
            _emit(
                f"PROFILE EDITOR CURRENT VALUES active port={port} "
                "display-node-values=1 keep-unmodified-inherited=1"
            )
            return original_open(root, services, source, functional, ctk=ctk)
        finally:
            editor.shown_value = base_shown_value
            editor.apply_profile_values = base_apply_values

    open_functional_profile_editor._jarnsen_current_node_values = True  # type: ignore[attr-defined]
    editor.open_functional_profile_editor = open_functional_profile_editor
    _emit(
        "PROFILE EDITOR CURRENT VALUES installed connected-node-display=1 "
        "profile-values-win=1 inherited-save-safe=1"
    )
