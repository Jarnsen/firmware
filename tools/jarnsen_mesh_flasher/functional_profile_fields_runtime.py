from __future__ import annotations

from typing import Any


def _walk_messages(messages: Any):
    for message in messages:
        yield message
        nested = getattr(message, "nested_types", ())
        if nested:
            yield from _walk_messages(nested)


def install() -> None:
    """Teach the role-only editor about nested Meshtastic config descriptors.

    Meshtastic 2.7.x stores DeviceConfig/LoRaConfig/etc. as nested protobuf
    descriptors below the top-level Config messages. The original catalog only
    inspected top-level descriptors and therefore saw no editable fields.
    """
    import functional_profile_fields as fields

    if getattr(fields, "_jarnsen_nested_descriptor_catalog", False):
        return

    def protobuf_specs() -> list[Any]:
        modules: list[tuple[str, Any]] = []
        try:
            from meshtastic.protobuf import config_pb2

            modules.append(("config", config_pb2))
        except Exception:
            pass
        try:
            from meshtastic.protobuf import module_config_pb2

            modules.append(("module_config", module_config_pb2))
        except Exception:
            pass

        result: list[Any] = []
        seen: set[tuple[str, str, str]] = set()
        for wrapper, module in modules:
            descriptor = getattr(module, "DESCRIPTOR", None)
            roots = (
                getattr(descriptor, "message_types_by_name", {}).values()
                if descriptor is not None
                else ()
            )
            for message in _walk_messages(roots):
                name = str(getattr(message, "name", "") or "")
                if not name.endswith("Config") or name in {"Config", "ModuleConfig"}:
                    continue
                section = fields._section(name)
                for field in getattr(message, "fields", ()):
                    field_name = str(getattr(field, "name", "") or "")
                    if not field_name:
                        continue
                    visible = f"{section}.{field_name}".casefold()
                    if visible in fields._SENSITIVE:
                        continue
                    kind = fields._field_kind(field)
                    if kind is None:
                        continue
                    key = (wrapper, section, field_name)
                    if key in seen:
                        continue
                    seen.add(key)
                    enum = getattr(field, "enum_type", None)
                    choices = (
                        tuple(
                            str(item.name)
                            for item in getattr(enum, "values", ())
                            if getattr(item, "name", None)
                        )
                        if enum is not None
                        else ()
                    )
                    path = (wrapper, section, field_name)
                    result.append(
                        fields.FieldSpec(
                            path,
                            kind,
                            choices=choices,
                            locked=path == ("config", "device", "role"),
                        )
                    )
        return result

    fields._protobuf_specs = protobuf_specs
    fields._jarnsen_nested_descriptor_catalog = True
