from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any, Iterable

import yaml

KEEP_VALUE = "Firmware/Node-Wert beibehalten"
CATEGORY_ORDER = (
    "Gerät",
    "LoRa",
    "Position",
    "Power",
    "Bluetooth",
    "Display",
    "Netzwerk",
    "Sicherheit",
    "MQTT",
    "Telemetrie",
    "Module",
    "Sonstiges",
)
_SECTION_CATEGORY = {
    "device": "Gerät",
    "lora": "LoRa",
    "position": "Position",
    "power": "Power",
    "bluetooth": "Bluetooth",
    "display": "Display",
    "network": "Netzwerk",
    "ethernet": "Netzwerk",
    "wifi": "Netzwerk",
    "security": "Sicherheit",
    "sessionkey": "Sicherheit",
    "session_key": "Sicherheit",
    "mqtt": "MQTT",
    "telemetry": "Telemetrie",
}
_SECTION_OVERRIDES = {"lo_ra": "lora", "wi_fi": "wifi", "ble": "bluetooth"}
_SENSITIVE = {
    "security.private_key",
    "security.public_key",
    "security.session_pass_key",
    "security.privatekey",
    "security.publickey",
    "security.sessionpasskey",
}


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _snake(value: str) -> str:
    value = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", value)
    return value.strip("_").casefold()


def _section(message_name: str) -> str:
    stem = message_name[:-6] if message_name.endswith("Config") else message_name
    value = _snake(stem)
    return _SECTION_OVERRIDES.get(value, value)


def _visible(path: Iterable[str]) -> str:
    return ".".join(part for part in path if part not in {"config", "module_config"})


def _category(path: tuple[str, ...]) -> str:
    visible = [part for part in path if part not in {"config", "module_config"}]
    if not visible:
        return "Sonstiges"
    section = _snake(visible[0])
    if path[0] == "module_config":
        return _SECTION_CATEGORY.get(section, "Module")
    return _SECTION_CATEGORY.get(section, "Sonstiges")


def _flatten(
    value: Any, prefix: tuple[str, ...] = ()
) -> list[tuple[tuple[str, ...], Any]]:
    if not isinstance(value, dict):
        return [(prefix, value)]
    result: list[tuple[tuple[str, ...], Any]] = []
    for key, child in value.items():
        result.extend(_flatten(child, (*prefix, str(key))))
    return result


def _lookup(root: dict[str, Any], path: tuple[str, ...]) -> tuple[bool, Any]:
    node: Any = root
    for part in path:
        if not isinstance(node, dict):
            return False, None
        actual = next((key for key in node if _norm(key) == _norm(part)), None)
        if actual is None:
            return False, None
        node = node[actual]
    return True, node


def _set(root: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    node = root
    for part in path[:-1]:
        actual = next((key for key in node if _norm(key) == _norm(part)), part)
        if not isinstance(node.get(actual), dict):
            node[actual] = {}
        node = node[actual]
    leaf = next((key for key in node if _norm(key) == _norm(path[-1])), path[-1])
    node[leaf] = copy.deepcopy(value)


def _delete(root: dict[str, Any], path: tuple[str, ...]) -> None:
    chain: list[tuple[dict[str, Any], str]] = []
    node: Any = root
    for part in path:
        if not isinstance(node, dict):
            return
        actual = next((key for key in node if _norm(key) == _norm(part)), None)
        if actual is None:
            return
        chain.append((node, actual))
        node = node[actual]
    chain[-1][0].pop(chain[-1][1], None)
    for parent, key in reversed(chain[:-1]):
        child = parent.get(key)
        if isinstance(child, dict) and not child:
            parent.pop(key, None)
        else:
            break


@dataclass(frozen=True)
class FieldSpec:
    path: tuple[str, ...]
    kind: str
    current: Any = None
    present: bool = False
    choices: tuple[str, ...] = ()
    locked: bool = False

    @property
    def label(self) -> str:
        return _visible(self.path)

    @property
    def category(self) -> str:
        return _category(self.path)


def _field_kind(field: Any) -> str | None:
    if getattr(field, "message_type", None) is not None:
        return None
    repeated = bool(getattr(field, "is_repeated", False)) or int(
        getattr(field, "label", 0) or 0
    ) == int(getattr(field, "LABEL_REPEATED", 3))
    if repeated:
        return None
    if getattr(field, "enum_type", None) is not None:
        return "enum"
    field_type = int(getattr(field, "type", 0) or 0)
    if field_type == int(getattr(field, "TYPE_BOOL", 8)):
        return "bool"
    if field_type in {
        int(getattr(field, "TYPE_DOUBLE", 1)),
        int(getattr(field, "TYPE_FLOAT", 2)),
    }:
        return "float"
    ints = (3, 4, 5, 6, 7, 13, 15, 16, 17, 18)
    if field_type in {
        int(getattr(field, name, fallback))
        for name, fallback in zip(
            (
                "TYPE_INT64",
                "TYPE_UINT64",
                "TYPE_INT32",
                "TYPE_FIXED64",
                "TYPE_FIXED32",
                "TYPE_UINT32",
                "TYPE_SFIXED32",
                "TYPE_SFIXED64",
                "TYPE_SINT32",
                "TYPE_SINT64",
            ),
            ints,
            strict=True,
        )
    }:
        return "int"
    if field_type == int(getattr(field, "TYPE_BYTES", 12)):
        return None
    return "string"


def _protobuf_specs() -> list[FieldSpec]:
    modules: list[tuple[str, Any]] = []
    for wrapper, module_name in (
        ("config", "config_pb2"),
        ("module_config", "module_config_pb2"),
    ):
        try:
            module = __import__(
                f"meshtastic.protobuf.{module_name}", fromlist=[module_name]
            )
            modules.append((wrapper, module))
        except Exception:
            pass
    result: list[FieldSpec] = []
    for wrapper, module in modules:
        descriptor = getattr(module, "DESCRIPTOR", None)
        messages = (
            getattr(descriptor, "message_types_by_name", {}) if descriptor else {}
        )
        for message in messages.values():
            name = str(getattr(message, "name", "") or "")
            if not name.endswith("Config") or name == "Config":
                continue
            section = _section(name)
            for field in getattr(message, "fields", ()):
                field_name = str(getattr(field, "name", "") or "")
                if not field_name or f"{section}.{field_name}".casefold() in _SENSITIVE:
                    continue
                kind = _field_kind(field)
                if kind is None:
                    continue
                enum = getattr(field, "enum_type", None)
                choices = (
                    tuple(
                        str(item.name)
                        for item in getattr(enum, "values", ())
                        if getattr(item, "name", None)
                    )
                    if enum
                    else ()
                )
                path = (wrapper, section, field_name)
                result.append(
                    FieldSpec(
                        path,
                        kind,
                        choices=choices,
                        locked=path == ("config", "device", "role"),
                    )
                )
    return result


def _value_kind(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, (dict, list)):
        return "complex"
    return "string"


def build_field_specs(data: dict[str, Any], functional: Any) -> list[FieldSpec]:
    by_key = {
        ".".join(_norm(part) for part in spec.path): spec for spec in _protobuf_specs()
    }
    for path, value in _flatten(data):
        if not path:
            continue
        key = ".".join(_norm(part) for part in path)
        known = by_key.get(key)
        by_key[key] = FieldSpec(
            path,
            known.kind if known else _value_kind(value),
            value,
            True,
            known.choices if known else (),
            known.locked if known else False,
        )
    role_path = ("config", "device", "role")
    role_key = ".".join(_norm(part) for part in role_path)
    known_role = by_key.get(role_key)
    role = str(getattr(functional, "meshtastic_role", "") or "")
    by_key[role_key] = FieldSpec(
        known_role.path if known_role and known_role.present else role_path,
        "enum",
        role,
        True,
        tuple(dict.fromkeys((role, *(known_role.choices if known_role else ())))),
        True,
    )
    result: list[FieldSpec] = []
    for spec in by_key.values():
        present, value = _lookup(data, spec.path)
        result.append(
            FieldSpec(
                spec.path,
                spec.kind,
                value if present and not spec.locked else spec.current,
                present or spec.locked,
                spec.choices,
                spec.locked,
            )
        )
    order = {name: index for index, name in enumerate(CATEGORY_ORDER)}
    return sorted(
        result, key=lambda spec: (order.get(spec.category, 99), spec.label.casefold())
    )


def shown_value(spec: FieldSpec) -> str:
    if not spec.present:
        return KEEP_VALUE
    if spec.kind == "bool":
        return "Ein" if bool(spec.current) else "Aus"
    if spec.kind == "complex":
        return yaml.safe_dump(
            spec.current, allow_unicode=True, default_flow_style=True
        ).strip()
    return "null" if spec.current is None else str(spec.current)


def _parse(spec: FieldSpec, raw: str) -> Any:
    text = str(raw or "").strip()
    if spec.kind == "bool":
        if text.casefold() in {"ein", "true", "1", "yes", "on"}:
            return True
        if text.casefold() in {"aus", "false", "0", "no", "off"}:
            return False
        raise ValueError("Bitte Ein oder Aus auswählen.")
    if spec.kind == "int":
        return int(text, 0)
    if spec.kind == "float":
        return float(text.replace(",", "."))
    if spec.kind == "complex":
        value = yaml.safe_load(text)
        if not isinstance(value, type(spec.current)):
            raise ValueError(f"Erwartet {type(spec.current).__name__}.")
        return value
    if spec.kind == "enum" and spec.choices and text not in spec.choices:
        raise ValueError("Bitte einen vollständigen Wert aus der Auswahlliste wählen.")
    return None if text == "null" else text


def apply_profile_values(
    original: dict[str, Any],
    specs: Iterable[FieldSpec],
    raw_values: dict[tuple[str, ...], str],
    functional: Any,
) -> dict[str, Any]:
    result = copy.deepcopy(original)
    for spec in specs:
        if spec.locked:
            continue
        raw = str(raw_values.get(spec.path, shown_value(spec)))
        if raw == KEEP_VALUE:
            if spec.present:
                _delete(result, spec.path)
            continue
        try:
            _set(result, spec.path, _parse(spec, raw))
        except Exception as exc:
            raise ValueError(f"{spec.label}: {exc}") from exc
    _set(
        result, ("config", "device", "role"), getattr(functional, "meshtastic_role", "")
    )
    return result
