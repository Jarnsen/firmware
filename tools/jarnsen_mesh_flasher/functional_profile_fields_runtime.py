from __future__ import annotations

from typing import Any


def _root_message(module: Any, wanted: str) -> Any | None:
    descriptor = getattr(module, "DESCRIPTOR", None)
    messages = (
        getattr(descriptor, "message_types_by_name", {})
        if descriptor is not None
        else {}
    )
    direct = messages.get(wanted)
    if direct is not None:
        return direct
    return next(
        (
            message
            for message in messages.values()
            if str(getattr(message, "name", "") or "").casefold()
            == wanted.casefold()
        ),
        None,
    )


def install() -> None:
    """Expose absent Meshtastic settings from nested protobuf descriptors.

    Meshtastic keeps DeviceConfig, LoRaConfig, PowerConfig and the module
    equivalents below top-level Config/ModuleConfig messages. Walking the root
    field graph also preserves deeper YAML paths such as network.ipv4_config.*.
    """
    import functional_profile_fields as fields

    if getattr(fields, "_jarnsen_nested_descriptor_catalog", False):
        return

    def append_message_fields(
        result: list[Any],
        seen: set[tuple[str, ...]],
        wrapper: str,
        prefix: tuple[str, ...],
        message: Any,
    ) -> None:
        for field in getattr(message, "fields", ()):
            field_name = str(getattr(field, "name", "") or "")
            if not field_name:
                continue
            repeated = bool(getattr(field, "is_repeated", False)) or int(
                getattr(field, "label", 0) or 0
            ) == int(getattr(field, "LABEL_REPEATED", 3))
            message_type = getattr(field, "message_type", None)
            if message_type is not None:
                if not repeated:
                    append_message_fields(
                        result,
                        seen,
                        wrapper,
                        (*prefix, field_name),
                        message_type,
                    )
                continue

            path = (wrapper, *prefix, field_name)
            visible = ".".join((*prefix, field_name)).casefold()
            if visible in fields._SENSITIVE:
                continue
            kind = fields._field_kind(field)
            if kind is None or path in seen:
                continue
            seen.add(path)
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
            result.append(
                fields.FieldSpec(
                    path,
                    kind,
                    choices=choices,
                    locked=path == ("config", "device", "role"),
                )
            )

    def protobuf_specs() -> list[Any]:
        modules: list[tuple[str, Any, str]] = []
        try:
            from meshtastic.protobuf import config_pb2

            modules.append(("config", config_pb2, "Config"))
        except Exception:
            pass
        try:
            from meshtastic.protobuf import module_config_pb2

            modules.append(("module_config", module_config_pb2, "ModuleConfig"))
        except Exception:
            pass

        result: list[Any] = []
        seen: set[tuple[str, ...]] = set()
        for wrapper, module, root_name in modules:
            root = _root_message(module, root_name)
            if root is None:
                continue
            for field in getattr(root, "fields", ()):
                field_name = str(getattr(field, "name", "") or "")
                message_type = getattr(field, "message_type", None)
                if not field_name or message_type is None:
                    continue
                repeated = bool(getattr(field, "is_repeated", False)) or int(
                    getattr(field, "label", 0) or 0
                ) == int(getattr(field, "LABEL_REPEATED", 3))
                if repeated:
                    continue
                append_message_fields(
                    result,
                    seen,
                    wrapper,
                    (field_name,),
                    message_type,
                )
        return result

    fields._protobuf_specs = protobuf_specs
    fields._jarnsen_nested_descriptor_catalog = True
