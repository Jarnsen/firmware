from __future__ import annotations

from typing import Any

_MODEM_PRESET_FALLBACK = (
    "LONG_FAST",
    "LONG_SLOW",
    "VERY_LONG_SLOW",
    "MEDIUM_SLOW",
    "MEDIUM_FAST",
    "SHORT_SLOW",
    "SHORT_FAST",
    "SHORT_TURBO",
)


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
            if str(getattr(message, "name", "") or "").casefold() == wanted.casefold()
        ),
        None,
    )


def _modem_preset_choices() -> tuple[str, ...]:
    """Return the runtime Meshtastic modem presets, with a safe legacy fallback."""
    try:
        from profile_editor_choices import field_values_for_label

        values = tuple(field_values_for_label("lora.modem_preset", ""))
        if values:
            return values
    except Exception:
        pass
    return _MODEM_PRESET_FALLBACK


def install() -> None:
    """Expose absent Meshtastic settings from nested protobuf descriptors.

    Meshtastic keeps DeviceConfig, LoRaConfig, PowerConfig and the module
    equivalents below top-level Config/ModuleConfig messages. Walking the root
    field graph also preserves deeper YAML paths such as network.ipv4_config.*.
    """
    from profile_editor_current_values import install as install_current_values

    # Install this before functional_profile_editor.install(). The later editor
    # wrapper resolves open_functional_profile_editor dynamically, so the source
    # UI automatically gains connected-node current-value display without
    # changing the persisted inheritance semantics.
    install_current_values()

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

        # The functional profiles start as role-only files, so modem_preset must
        # still exist as an editable virtual field. Prefer the exact enum from the
        # installed Meshtastic package. If that descriptor is missing/incomplete,
        # fall back to the stable Long/Medium/Short preset family instead of
        # degrading the field to free text or hiding it entirely.
        modem_path = ("config", "lora", "modem_preset")
        modem_choices = _modem_preset_choices()
        for index, spec in enumerate(result):
            if getattr(spec, "path", None) != modem_path:
                continue
            if not getattr(spec, "choices", ()) and modem_choices:
                result[index] = fields.FieldSpec(
                    spec.path,
                    "enum",
                    current=spec.current,
                    present=spec.present,
                    choices=modem_choices,
                    locked=spec.locked,
                )
            break
        else:
            if modem_choices:
                result.append(
                    fields.FieldSpec(modem_path, "enum", choices=modem_choices)
                )

        return result

    fields._protobuf_specs = protobuf_specs
    fields._jarnsen_nested_descriptor_catalog = True
