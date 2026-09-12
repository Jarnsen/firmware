from __future__ import annotations

import importlib
import pkgutil
import re
from typing import Any

import customtkinter as ctk

GREEN_TEXT = "#86EFAC"
ACTIVE_TEXT = "#60A5FA"
PENDING_TEXT = "#8999A9"
CONTROL = "#15273A"
CONTROL_HOVER = "#1D354D"
BORDER = "#344A5F"
FONT = "Segoe UI"

_PROTO_MODULES = (
    "config_pb2",
    "module_config_pb2",
    "channel_pb2",
    "localonly_pb2",
    "deviceonly_pb2",
    "mesh_pb2",
    "admin_pb2",
    "telemetry_pb2",
)

# Fallbacks are only used if the installed Meshtastic protobuf package cannot
# provide the enum descriptor. The normal path always uses the package's own
# enum definitions, so future Meshtastic additions appear automatically.
_FALLBACK_ENUMS: dict[str, tuple[str, ...]] = {
    "device.role": (
        "CLIENT",
        "CLIENT_MUTE",
        "CLIENT_HIDDEN",
        "CLIENT_BASE",
        "ROUTER",
        "ROUTER_LATE",
        "ROUTER_CLIENT",
        "REPEATER",
        "TRACKER",
        "SENSOR",
        "TAK",
        "LOST_AND_FOUND",
        "TAK_TRACKER",
    ),
    "device.rebroadcastmode": (
        "ALL",
        "ALL_SKIP_DECODING",
        "LOCAL_ONLY",
        "KNOWN_ONLY",
        "NONE",
        "CORE_PORTNUMS_ONLY",
    ),
    "lora.region": (
        "UNSET",
        "US",
        "EU_433",
        "EU_868",
        "CN",
        "JP",
        "ANZ",
        "KR",
        "TW",
        "RU",
        "IN",
        "NZ_865",
        "TH",
        "LORA_24",
        "UA_433",
        "UA_868",
        "MY_433",
        "MY_919",
        "SG_923",
        "PH_433",
        "PH_868",
        "PH_915",
        "ANZ_433",
        "KZ_433",
        "KZ_863",
        "NP_865",
        "BR_902",
        "ITU1_2M",
        "ITU2_2M",
        "EU_866",
        "EU_874",
        "EU_917",
        "EU_N_868",
        "ITU3_2M",
        "ITU1_70CM",
        "ITU2_70CM",
        "ITU3_70CM",
        "ITU2_125CM",
    ),
    "lora.modempreset": (
        "LONG_FAST",
        "LONG_SLOW",
        "VERY_LONG_SLOW",
        "MEDIUM_SLOW",
        "MEDIUM_FAST",
        "SHORT_SLOW",
        "SHORT_FAST",
        "LONG_MODERATE",
        "SHORT_TURBO",
        "LONG_TURBO",
        "LITE_FAST",
        "LITE_SLOW",
        "NARROW_FAST",
        "NARROW_SLOW",
        "TINY_FAST",
        "TINY_SLOW",
        "MEDIUM_TURBO",
    ),
    "position.gpsmode": ("DISABLED", "ENABLED", "NOT_PRESENT"),
    "network.addressmode": ("DHCP", "STATIC"),
    "display.units": ("METRIC", "IMPERIAL"),
    "display.oled": (
        "OLED_AUTO",
        "OLED_SSD1306",
        "OLED_SH1106",
        "OLED_SH1107",
        "OLED_SH1107_128_128",
        "OLED_SH1107_ROTATED",
    ),
    "display.displaymode": ("DEFAULT", "TWOCOLOR", "INVERTED", "COLOR"),
    "display.compassorientation": (
        "DEGREES_0",
        "DEGREES_90",
        "DEGREES_180",
        "DEGREES_270",
        "DEGREES_0_INVERTED",
        "DEGREES_90_INVERTED",
        "DEGREES_180_INVERTED",
        "DEGREES_270_INVERTED",
    ),
    "device.buzzermode": (
        "ALL_ENABLED",
        "DISABLED",
        "NOTIFICATIONS_ONLY",
        "SYSTEM_ONLY",
        "DIRECT_MSG_ONLY",
    ),
}

# Only genuinely bounded numeric profile fields belong here. Values that are
# board-, region- or use-case-dependent intentionally remain editable text.
_FIXED_VALUES: dict[str, tuple[str, ...]] = {
    # Standard is capped to 7 by radio_profiles; Jarnsen 1/2 support 1..20.
    "lora.hoplimit": tuple(str(value) for value in range(1, 21)),
}

# These are useful presets, not limits. The editor renders them as editable
# combo boxes so board- or deployment-specific values remain possible.
_SUGGESTED_VALUES: dict[str, tuple[str, ...]] = {
    "lora.overridefrequency": ("0.0", "915.625", "917.375"),
    "lora.txpower": tuple(str(value) for value in range(0, 31)),
    "device.nodeinfobroadcastsecs": ("0", "300", "600", "900", "1800", "3600"),
    "position.positionbroadcastsecs": ("0", "60", "300", "900", "1800", "3600"),
    "position.gpsupdateinterval": ("0", "30", "60", "300", "900", "1800", "3600"),
    "position.broadcastsmartminimumdistance": (
        "0",
        "25",
        "50",
        "75",
        "100",
        "250",
        "500",
    ),
    "position.broadcastsmartminimumintervalsecs": (
        "0",
        "30",
        "60",
        "120",
        "300",
        "900",
        "3600",
    ),
    "display.screenonsecs": ("0", "15", "30", "60", "120", "300", "600"),
}

_ENUM_CACHE: list[tuple[str, str, tuple[str, ...]]] | None = None


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _walk_messages(messages: Any, sink: list[tuple[str, str, tuple[str, ...]]]) -> None:
    for message in messages:
        message_name = _norm(getattr(message, "name", ""))
        for field in getattr(message, "fields", ()):
            enum_type = getattr(field, "enum_type", None)
            if enum_type is None:
                continue
            values = tuple(
                str(item.name)
                for item in getattr(enum_type, "values", ())
                if getattr(item, "name", None)
            )
            if values:
                sink.append((message_name, _norm(getattr(field, "name", "")), values))
        nested = getattr(message, "nested_types", ())
        if nested:
            _walk_messages(nested, sink)


def _protobuf_modules() -> tuple[str, ...]:
    """Return known modules plus every protobuf module shipped by Meshtastic."""
    names = list(_PROTO_MODULES)
    try:
        package = importlib.import_module("meshtastic.protobuf")
        for record in pkgutil.iter_modules(getattr(package, "__path__", ())):
            name = str(record.name)
            if name.endswith("_pb2") and name not in names:
                names.append(name)
    except Exception:
        pass
    return tuple(names)


def _enum_catalog() -> list[tuple[str, str, tuple[str, ...]]]:
    global _ENUM_CACHE
    if _ENUM_CACHE is not None:
        return _ENUM_CACHE

    records: list[tuple[str, str, tuple[str, ...]]] = []
    module_names = _protobuf_modules()
    loaded_modules = 0
    for module_name in module_names:
        try:
            module = importlib.import_module(f"meshtastic.protobuf.{module_name}")
            descriptor = getattr(module, "DESCRIPTOR", None)
            if descriptor is None:
                continue
            _walk_messages(
                getattr(descriptor, "message_types_by_name", {}).values(), records
            )
            loaded_modules += 1
        except Exception:
            continue

    _ENUM_CACHE = records
    _emit(
        f"PROFILE EDITOR ENUM catalog fields={len(records)} "
        f"modules={loaded_modules}/{len(module_names)}"
    )
    return records


def enum_values_for_label(label: str, current: Any) -> list[str]:
    """Return valid enum names for one visible profile field, if it is an enum."""
    text = str(label or "").strip()
    parts = [part for part in text.split(".") if part]
    if len(parts) < 2:
        return []

    parent = _norm(parts[-2])
    leaf = _norm(parts[-1])
    current_text = str(current if current is not None else "").strip()
    candidates: list[tuple[int, tuple[str, ...]]] = []

    matching_fields = [
        (message_name, values)
        for message_name, field_name, values in _enum_catalog()
        if field_name == leaf
    ]
    for message_name, values in matching_fields:
        score = 0
        if parent and (parent in message_name or message_name in parent):
            score += 12
        if current_text in values:
            score += 6
        score -= max(0, len(values) - 25) // 10
        candidates.append((score, values))

    if candidates:
        candidates.sort(key=lambda item: item[0], reverse=True)
        best_score, best_values = candidates[0]
        if best_score > 0 or len(matching_fields) == 1:
            values = list(best_values)
            if current_text and current_text not in values:
                values.insert(0, current_text)
            return values

    fallback = _FALLBACK_ENUMS.get(f"{parent}.{leaf}")
    if fallback:
        values = list(fallback)
        if current_text and current_text not in values:
            values.insert(0, current_text)
        return values
    return []


def field_values_for_label(label: str, current: Any) -> list[str]:
    """Return every safe dropdown value while preserving an older current value."""
    enum_values = enum_values_for_label(label, current)
    if enum_values:
        return enum_values
    key = ".".join(_norm(part) for part in str(label or "").split(".")[-2:])
    fixed = list(_FIXED_VALUES.get(key, ()) or _SUGGESTED_VALUES.get(key, ()))
    current_text = str(current if current is not None else "").strip()
    if fixed and current_text and current_text not in fixed:
        fixed.insert(0, current_text)
    return fixed


def field_allows_custom_value(label: str) -> bool:
    key = ".".join(_norm(part) for part in str(label or "").split(".")[-2:])
    return key in _SUGGESTED_VALUES


def _looks_like_field_label(text: Any) -> bool:
    value = str(text or "").strip()
    return bool(
        re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+", value)
    )


class _EditorCtkProxy:
    """Replace only enum CTkEntry fields with CTkOptionMenu controls."""

    def __init__(self, real_ctk: Any, state: dict[str, Any]):
        self._real = real_ctk
        self._state = state

    def CTkLabel(self, master: Any, *args: Any, **kwargs: Any) -> Any:
        text = kwargs.get("text")
        if _looks_like_field_label(text):
            self._state["field"] = str(text).strip()
        return self._real.CTkLabel(master, *args, **kwargs)

    def CTkEntry(self, master: Any, *args: Any, **kwargs: Any) -> Any:
        field = str(self._state.pop("field", "") or "")
        variable = kwargs.get("textvariable")
        current = ""
        try:
            current = str(variable.get()) if variable is not None else ""
        except Exception:
            pass

        values = field_values_for_label(field, current) if field else []
        if values and variable is not None:
            self._state["count"] = int(self._state.get("count", 0)) + 1
            _emit(
                f"PROFILE EDITOR DROPDOWN field={field!r} current={current!r} choices={len(values)}"
            )
            widget_type = (
                self._real.CTkComboBox
                if field_allows_custom_value(field)
                else self._real.CTkOptionMenu
            )
            return widget_type(
                master,
                variable=variable,
                values=values,
                height=30,
                corner_radius=6,
                fg_color=CONTROL,
                button_color=CONTROL_HOVER,
                button_hover_color="#29445E",
                font=ctk.CTkFont(family=FONT, size=11),
                dropdown_font=ctk.CTkFont(family=FONT, size=11),
            )
        return self._real.CTkEntry(master, *args, **kwargs)

    def CTkSwitch(self, master: Any, *args: Any, **kwargs: Any) -> Any:
        # A boolean row consumes the preceding field label as well. Clear the
        # context so the next text entry cannot inherit the boolean field name.
        self._state.pop("field", None)
        return self._real.CTkSwitch(master, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


def _install_profile_editor_dropdowns() -> None:
    import profile_editor

    original_open = profile_editor.open_profile_editor
    if getattr(original_open, "_jarnsen_enum_dropdown_wrapper", False):
        return

    if bool(getattr(profile_editor, "PROFILE_EDITOR_NATIVE_CHOICES", False)):

        def open_native_profile_editor(root: Any, services: Any, source: Any) -> Any:
            try:
                return original_open(root, services, source)
            finally:
                try:
                    root._jarnsen_profile_dropdowns_ready = True
                except Exception:
                    pass
                _emit("PROFILE EDITOR DROPDOWNS rendered=native")

        open_native_profile_editor._jarnsen_enum_dropdown_wrapper = True  # type: ignore[attr-defined]
        profile_editor.open_profile_editor = open_native_profile_editor
        return

    def open_profile_editor(root: Any, services: Any, source: Any) -> Any:
        real_ctk = profile_editor.ctk
        state: dict[str, Any] = {"field": "", "count": 0}
        profile_editor.ctk = _EditorCtkProxy(real_ctk, state)
        try:
            return original_open(root, services, source)
        finally:
            profile_editor.ctk = real_ctk
            try:
                root._jarnsen_profile_dropdown_count = int(state.get("count", 0))
                root._jarnsen_profile_dropdowns_ready = True
            except Exception:
                pass
            _emit(f"PROFILE EDITOR DROPDOWNS rendered={int(state.get('count', 0))}")

    open_profile_editor._jarnsen_enum_dropdown_wrapper = True  # type: ignore[attr-defined]
    profile_editor.open_profile_editor = open_profile_editor


def _walk(widget: Any):
    yield widget
    try:
        children = widget.winfo_children()
    except Exception:
        children = []
    for child in children:
        yield from _walk(child)


def _stage_index_for_text(text: str) -> int | None:
    exact = str(text or "").strip()
    lookup = {
        "Backup": 0,
        "Firmware": 1,
        "Grundeinst.": 2,
        "Profil": 2,
        "Namen": 3,
        "Neustart": 4,
        "Prüfung": 5,
    }
    return lookup.get(exact)


def _active_stage(fraction: float) -> int:
    if fraction < 0.35:
        return 0
    if fraction < 0.79:
        return 1
    if fraction < 0.88:
        return 2
    if fraction < 0.94:
        return 3
    if fraction < 0.98:
        return 4
    return 5


def _install_completed_stage_style(app: Any) -> None:
    labels: dict[int, Any] = {}
    for widget in _walk(getattr(app, "body", app)):
        if not isinstance(widget, ctk.CTkLabel):
            continue
        try:
            idx = _stage_index_for_text(str(widget.cget("text") or ""))
        except Exception:
            idx = None
        if idx is not None and idx not in labels:
            labels[idx] = widget

    if len(labels) != 6:
        raise RuntimeError(
            f"Automatik-Fortschrittslabels nicht vollständig gefunden: {sorted(labels)}"
        )

    completed_font = ctk.CTkFont(family=FONT, size=7, weight="bold")
    active_font = ctk.CTkFont(family=FONT, size=7, weight="bold")
    pending_font = ctk.CTkFont(family=FONT, size=7, weight="normal")
    base_set_progress = app._set_progress

    def set_progress(value: float, text: str) -> None:
        base_set_progress(value, text)
        fraction = max(0.0, min(1.0, float(value)))
        active = _active_stage(fraction)
        all_complete = fraction >= 0.999

        def apply_style() -> None:
            for idx in range(6):
                label = labels[idx]
                if all_complete or idx < active:
                    label.configure(text_color=GREEN_TEXT, font=completed_font)
                elif idx == active:
                    label.configure(text_color=ACTIVE_TEXT, font=active_font)
                else:
                    label.configure(text_color=PENDING_TEXT, font=pending_font)

        # reference_dashboard schedules its own color update with after(0).
        # Queue ours afterwards so the final visible state is green + bold.
        app.after(0, apply_style)

    app._set_progress = set_progress
    app._jarnsen_progress_stage_labels = labels
    app._jarnsen_completed_stage_style_ready = True
    _emit(
        "AUTOMATIC TIMELINE completed-style=green-bold active=blue-bold final-all-green=1"
    )


def install(services: Any) -> None:
    if getattr(services, "_jarnsen_profile_editor_choices_installed", False):
        return
    services._jarnsen_profile_editor_choices_installed = True

    # Fail early in CI if the key dropdown behaviour is unavailable.
    if "TAK" not in enum_values_for_label("device.role", "TAK"):
        raise RuntimeError(
            "Profil-Editor Rollen-Dropdown konnte nicht aufgebaut werden"
        )
    if "LOCAL_ONLY" not in enum_values_for_label(
        "device.rebroadcastMode", "LOCAL_ONLY"
    ):
        raise RuntimeError(
            "Profil-Editor Rebroadcast-Dropdown konnte nicht aufgebaut werden"
        )
    if field_values_for_label("lora.hop_limit", "3") != [
        str(value) for value in range(1, 21)
    ]:
        raise RuntimeError(
            "Profil-Editor Hop-Limit-Dropdown konnte nicht aufgebaut werden"
        )
    legacy_values = field_values_for_label("device.role", "LEGACY_CUSTOM_ROLE")
    if (
        not legacy_values
        or legacy_values[0] != "LEGACY_CUSTOM_ROLE"
        or "CLIENT" not in legacy_values
    ):
        raise RuntimeError(
            "Profil-Editor kann bestehende unbekannte Werte nicht sicher übernehmen"
        )

    _install_profile_editor_dropdowns()

    import reference_dashboard

    original_build = reference_dashboard._build_dashboard
    if not getattr(original_build, "_jarnsen_completed_stage_style_wrapper", False):

        def build_dashboard(app: Any, runtime_services: Any) -> None:
            original_build(app, runtime_services)
            _install_completed_stage_style(app)

        build_dashboard._jarnsen_completed_stage_style_wrapper = True  # type: ignore[attr-defined]
        reference_dashboard._build_dashboard = build_dashboard

    _emit(
        "PROFILE EDITOR CHOICES installed all-protobuf-enums=1 fallback-enums=1 "
        "legacy-value-preservation=1 jarnsen-hop-max=20 editable-presets=1 "
        "progress-complete-green-bold=1"
    )
