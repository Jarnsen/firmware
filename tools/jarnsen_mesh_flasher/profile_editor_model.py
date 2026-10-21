from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FieldMeta:
    title: str
    help: str


@dataclass(frozen=True)
class ProfileChange:
    path: str
    before: Any
    after: Any


_FIELDS: dict[str, FieldMeta] = {
    "device.role": FieldMeta(
        "Geräterolle", "Bestimmt das Verhalten des Nodes im Mesh."
    ),
    "device.rebroadcastmode": FieldMeta(
        "Weiterleitung", "Legt fest, welche Pakete der Node erneut sendet."
    ),
    "device.nodeinfobroadcastsecs": FieldMeta(
        "Node-Info-Intervall",
        "Sekunden zwischen automatischen Node-Info-Meldungen; 0 nutzt den Firmware-Standard.",
    ),
    "lora.region": FieldMeta(
        "Funkregion", "Muss zur gesetzlichen Funkregion des Einsatzorts passen."
    ),
    "lora.modempreset": FieldMeta(
        "Modemprofil", "Steuert Reichweite, Geschwindigkeit und Airtime."
    ),
    "lora.hoplimit": FieldMeta(
        "Hop-Limit",
        "Maximale Anzahl der Mesh-Weiterleitungen: Standard bis 7, Jarnsen 1/2 bis 20.",
    ),
    "lora.txpower": FieldMeta(
        "Sendeleistung",
        "Sendeleistung in dBm; 0 lässt die Firmware automatisch wählen.",
    ),
    "lora.overridefrequency": FieldMeta(
        "Frequenz überschreiben",
        "0 nutzt die Regionseinstellung; Jarnsen 1/2 verwenden ihre festen Frequenzen.",
    ),
    "lora.overridedutycycle": FieldMeta(
        "Duty-Cycle überschreiben",
        "Nur verwenden, wenn die Funkregeln der gewählten Region dies erlauben.",
    ),
    "lora.usepreset": FieldMeta(
        "Modemprofil verwenden", "Aktiviert das ausgewählte Meshtastic-Modemprofil."
    ),
    "position.gpsmode": FieldMeta(
        "GPS-Modus", "Aktiviert, deaktiviert oder kennzeichnet nicht vorhandenes GPS."
    ),
    "position.positionbroadcastsecs": FieldMeta(
        "Positionsintervall",
        "Sekunden zwischen Positionsmeldungen; 0 nutzt die Firmware-Automatik.",
    ),
    "position.gpsupdateinterval": FieldMeta(
        "GPS-Abfrageintervall", "Sekunden zwischen neuen GPS-Messungen."
    ),
    "position.broadcastsmartminimumdistance": FieldMeta(
        "Smart-Minimaldistanz", "Mindestbewegung in Metern vor einer Smart-Position."
    ),
    "position.broadcastsmartminimumintervalsecs": FieldMeta(
        "Smart-Minimalintervall", "Kürzester Abstand zwischen Smart-Positionsmeldungen."
    ),
    "power.ispowersaving": FieldMeta(
        "Energiesparmodus",
        "Reduziert den Stromverbrauch und kann USB-/Funkreaktionen verzögern.",
    ),
    "display.screenonsecs": FieldMeta(
        "Display-Einschaltdauer", "Sekunden bis das Display wieder ausgeschaltet wird."
    ),
    "display.units": FieldMeta(
        "Einheiten", "Metrische oder imperiale Anzeigeeinheiten."
    ),
    "network.addressmode": FieldMeta(
        "Netzwerkadressierung",
        "DHCP bezieht die Adresse automatisch; STATIC nutzt feste Werte.",
    ),
    "mqtt.enabled": FieldMeta(
        "MQTT aktiv",
        "Verbindet den Node mit einem MQTT-Broker, sofern Netzwerk verfügbar ist.",
    ),
}

_SECRET_PARTS = (
    "password",
    "passwd",
    "psk",
    "privatekey",
    "private_key",
    "fixedpin",
    "fixed_pin",
)
_GERMAN_WORDS = {
    "address": "Adresse",
    "airtime": "Sendezeit",
    "bluetooth": "Bluetooth",
    "broadcast": "Aussendung",
    "brightness": "Helligkeit",
    "channel": "Kanal",
    "compass": "Kompass",
    "display": "Anzeige",
    "distance": "Entfernung",
    "enabled": "aktiv",
    "ethernet": "Ethernet",
    "fixed": "fest",
    "frequency": "Frequenz",
    "gps": "GPS",
    "interval": "Intervall",
    "minimum": "Mindestwert",
    "mode": "Modus",
    "name": "Name",
    "network": "Netzwerk",
    "orientation": "Ausrichtung",
    "position": "Position",
    "power": "Leistung",
    "screen": "Anzeige",
    "seconds": "Sekunden",
    "secs": "Sekunden",
    "smart": "Smart",
    "telemetry": "Telemetrie",
    "timeout": "Zeitlimit",
    "units": "Einheiten",
    "update": "Aktualisierung",
    "wifi": "WLAN",
}


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def visible_path(path: tuple[str, ...] | str) -> str:
    parts = str(path).split(".") if isinstance(path, str) else list(path)
    return ".".join(part for part in parts if part not in {"config", "module_config"})


def field_meta(path: tuple[str, ...] | str) -> FieldMeta:
    visible = visible_path(path)
    parts = visible.split(".")
    key = ".".join(_norm(part) for part in parts[-2:])
    known = _FIELDS.get(key)
    if known:
        return known
    leaf = parts[-1] if parts else visible
    separated = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", leaf)
    words = [word for word in re.split(r"[_\s-]+", separated) if word]
    translated = [_GERMAN_WORDS.get(word.casefold(), word.title()) for word in words]
    title = " ".join(translated) or "Einstellung"
    area = parts[-2].replace("_", " ").title() if len(parts) > 1 else "Profil"
    return FieldMeta(
        title, f"Einstellung im Bereich {area}. Technisches Feld: {visible}"
    )


def _flatten(value: Any, prefix: tuple[str, ...] = ()) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {".".join(prefix): value}
    result: dict[str, Any] = {}
    for key, child in value.items():
        path = (*prefix, str(key))
        if isinstance(child, dict):
            result.update(_flatten(child, path))
        else:
            result[".".join(path)] = child
    return result


def profile_changes(
    before: dict[str, Any], after: dict[str, Any]
) -> list[ProfileChange]:
    old = _flatten(before)
    new = _flatten(after)
    return [
        ProfileChange(path, old.get(path, "<fehlt>"), new.get(path, "<entfernt>"))
        for path in sorted(set(old) | set(new))
        if old.get(path, "<fehlt>") != new.get(path, "<entfernt>")
    ]


def _safe_value(path: str, value: Any) -> str:
    normalized = _norm(path)
    if any(_norm(part) in normalized for part in _SECRET_PARTS):
        return "••••••"
    if isinstance(value, bool):
        return "Ein" if value else "Aus"
    if value is None:
        return "leer"
    text = str(value)
    return text if len(text) <= 52 else text[:49] + "…"


def format_change_preview(changes: list[ProfileChange], *, limit: int = 24) -> str:
    lines = []
    for change in changes[:limit]:
        title = field_meta(change.path).title
        lines.append(
            f"• {title}: {_safe_value(change.path, change.before)} → {_safe_value(change.path, change.after)}"
        )
    if len(changes) > limit:
        lines.append(f"• … und {len(changes) - limit} weitere Änderung(en)")
    return "\n".join(lines)


def _value(data: dict[str, Any], *paths: tuple[str, ...]) -> Any:
    for path in paths:
        node: Any = data
        for part in path:
            if not isinstance(node, dict):
                break
            match = next((key for key in node if _norm(key) == _norm(part)), None)
            if match is None:
                break
            node = node[match]
        else:
            return node
    return None


def compatibility_notes(
    data: dict[str, Any],
    *,
    assigned_board: str | None,
    selected_board: str | None,
    board_profiles: dict[str, Any],
    radio_settings: dict[str, Any] | None = None,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if assigned_board and selected_board and assigned_board != selected_board:
        assigned = board_profiles.get(assigned_board, {}).get("label", assigned_board)
        selected = board_profiles.get(selected_board, {}).get("label", selected_board)
        errors.append(
            f"Das Profil ist {assigned} zugeordnet, ausgewählt ist aber {selected}."
        )

    role = str(
        _value(data, ("config", "device", "role"), ("device", "role"), ("role",)) or ""
    ).upper()
    rebroadcast = str(
        _value(
            data,
            ("config", "device", "rebroadcast_mode"),
            ("config", "device", "rebroadcastMode"),
            ("device", "rebroadcast_mode"),
        )
        or ""
    ).upper()
    if (
        role in {"ROUTER", "ROUTER_LATE", "ROUTER_CLIENT", "REPEATER"}
        and rebroadcast == "NONE"
    ):
        warnings.append(
            "Die gewählte Router-/Repeater-Rolle leitet mit Weiterleitung NONE keine Mesh-Pakete weiter."
        )
    if role and role != "REPEATER" and rebroadcast == "ALL_SKIP_DECODING":
        warnings.append(
            "ALL_SKIP_DECODING ist für eine reine Repeater-Rolle gedacht; die gewählte Rolle kann dadurch Funktionen verlieren."
        )

    selected_radio = str((radio_settings or {}).get("selected") or "standard").lower()
    region = str(
        _value(data, ("config", "lora", "region"), ("lora", "region")) or ""
    ).upper()
    hop_limit = _value(
        data,
        ("config", "lora", "hop_limit"),
        ("config", "lora", "hopLimit"),
        ("lora", "hop_limit"),
    )
    try:
        hops = int(hop_limit)
    except (TypeError, ValueError):
        hops = None
    if selected_radio == "standard" and hops is not None and hops > 7:
        warnings.append(
            "Standard begrenzt das Hop-Limit beim Schreiben auf 7; Jarnsen 1/2 erlauben bis 20."
        )
    if selected_radio in {"jarnsen1", "jarnsen2"} and region and region != "US":
        warnings.append(
            "Jarnsen 1/2 verwenden für ihren Funk-Slot automatisch US; die Standard-Region bleibt erhalten."
        )
    return errors, warnings
