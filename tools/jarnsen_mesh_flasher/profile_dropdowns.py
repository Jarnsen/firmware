from __future__ import annotations

from typing import Any

import customtkinter as ctk


ROLE_VALUES = [
    "CLIENT",
    "CLIENT_MUTE",
    "CLIENT_BASE",
    "ROUTER",
    "ROUTER_LATE",
    "ROUTER_CLIENT",
    "REPEATER",
    "TRACKER",
    "SENSOR",
    "TAK",
    "TAK_TRACKER",
]

REGION_VALUES = [
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
]

MODEM_VALUES = [
    "LONG_FAST",
    "LONG_SLOW",
    "VERY_LONG_SLOW",
    "MEDIUM_SLOW",
    "MEDIUM_FAST",
    "SHORT_SLOW",
    "SHORT_FAST",
    "SHORT_TURBO",
]

FIELD_CHOICES: dict[str, list[str]] = {
    "device.role": ROLE_VALUES,
    "lora.region": REGION_VALUES,
    "lora.modem_preset": MODEM_VALUES,
    "lora.rebroadcast_mode": [
        "ALL",
        "ALL_SKIP_DECODING",
        "LOCAL_ONLY",
        "KNOWN_ONLY",
        "NONE",
        "CORE_PORTNUMS_ONLY",
    ],
    "position.gps_mode": ["DISABLED", "ENABLED", "NOT_PRESENT"],
    "bluetooth.mode": ["RANDOM_PIN", "FIXED_PIN", "NO_PIN"],
    "bluetooth.pairing_mode": ["RANDOM_PIN", "FIXED_PIN", "NO_PIN"],
    "display.units": ["METRIC", "IMPERIAL"],
    "display.oled_type": ["OLED_AUTO", "OLED_SSD1306", "OLED_SH1106", "OLED_SH1107"],
    "network.address_mode": ["DHCP", "STATIC"],
}


def _emit(message: str) -> None:
    try:
        import diagnostics
        diagnostics._emit(message)
    except Exception:
        pass


def _inside_profile_editor(master: Any) -> bool:
    node = master
    seen: set[int] = set()
    while node is not None and id(node) not in seen:
        seen.add(id(node))
        if isinstance(node, ctk.CTkToplevel):
            try:
                return "Profil bearbeiten" in str(node.title())
            except Exception:
                return False
        node = getattr(node, "master", None)
    return False


def _field_name(master: Any) -> str:
    """The editor creates the field label immediately before its input widget."""
    try:
        children = list(master.winfo_children())
    except Exception:
        return ""
    for child in reversed(children):
        if isinstance(child, ctk.CTkLabel):
            try:
                text = str(child.cget("text") or "").strip()
            except Exception:
                text = ""
            if text and text not in {"Gerät", "LoRa", "Position", "Power", "Bluetooth", "Display", "Netzwerk", "MQTT", "Telemetrie", "Module", "Sonstiges"}:
                return text
    return ""


def install(services: Any) -> None:
    """Upgrade known enum profile fields from free text entries to dropdowns."""
    if getattr(services, "_jarnsen_profile_dropdowns_installed", False):
        return
    services._jarnsen_profile_dropdowns_installed = True

    original_entry = ctk.CTkEntry

    def entry_factory(master: Any, *args: Any, **kwargs: Any):
        if _inside_profile_editor(master):
            field = _field_name(master)
            choices = FIELD_CHOICES.get(field)
            if choices:
                variable = kwargs.pop("textvariable", None)
                current = ""
                try:
                    current = str(variable.get() or "") if variable is not None else ""
                except Exception:
                    current = ""
                values = list(choices)
                if current and current not in values:
                    values.insert(0, current)
                width = kwargs.pop("width", 280)
                kwargs.pop("placeholder_text", None)
                kwargs.pop("show", None)
                widget = ctk.CTkOptionMenu(
                    master,
                    variable=variable,
                    values=values,
                    width=width,
                )
                _emit(f"PROFILE DROPDOWN field={field!r} values={len(values)} current={current!r}")
                return widget
        return original_entry(master, *args, **kwargs)

    ctk.CTkEntry = entry_factory  # type: ignore[assignment]
    _emit(f"PROFILE DROPDOWNS installed fields={len(FIELD_CHOICES)}")
