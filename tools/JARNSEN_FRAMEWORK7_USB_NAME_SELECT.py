"""Bind a freshly identified serial node to its physical USB target by names.

The diagnostic payload is authoritative for the device currently attached to the
single COM target.  Historical rows may legitimately have the same long/short
name after a node-id change; they must not keep the physical USB identity or block
Framework7 from selecting the freshly imported node.
"""
from __future__ import annotations

import contextlib
import re
from typing import Any


_HEADER_RE = re.compile(rb"(?m)^# ([a-z_]+)=([^\r\n]+)")


def _headers(payload: bytes) -> dict[str, str]:
    result: dict[str, str] = {}
    for match in _HEADER_RE.finditer(bytes(payload or b"")):
        result[match.group(1).decode("ascii", "ignore")] = match.group(2).decode("utf-8", "replace").strip()
    return result


def _norm_node(value: object) -> str:
    raw = str(value or "").strip().lower().lstrip("!")
    return f"!{raw}" if raw else ""


def _norm_name(value: object) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def install_usb_name_selection(LegacyBridge: type) -> None:
    if getattr(LegacyBridge, "_jarnsen_usb_name_selection", False):
        return
    LegacyBridge._jarnsen_usb_name_selection = True

    original_state = LegacyBridge.state

    def state(self: Any) -> dict[str, Any]:
        data = original_state(self)
        connections = data.get("connections")
        targets = connections.get("usb") if isinstance(connections, dict) else None
        if not isinstance(targets, list) or len(targets) != 1:
            return data

        payload = getattr(self.tool, "last_payload", None)
        if not isinstance(payload, (bytes, bytearray)) or not payload:
            return data
        headers = _headers(bytes(payload))
        long_name = str(headers.get("long_name") or "").strip()
        short_name = str(headers.get("short_name") or "").strip()
        payload_node_id = _norm_node(headers.get("node_id"))
        device_name = str(headers.get("device") or "").strip()
        if not long_name or not short_name or not payload_node_id:
            return data

        # Long + short name is the human identity requested by the Service Tool.
        # If historical node IDs reused the same pair, the node_id carried by the
        # payload received from this exact COM session is the tie-breaker.
        name_matches: list[dict[str, Any]] = []
        for node in data.get("nodes", []):
            if not isinstance(node, dict):
                continue
            if _norm_name(node.get("long_name")) != _norm_name(long_name):
                continue
            if _norm_name(node.get("short_name")) != _norm_name(short_name):
                continue
            name_matches.append(node)
        if not name_matches:
            return data

        selected = next(
            (node for node in name_matches if _norm_node(node.get("node_id")) == payload_node_id),
            None,
        )
        if selected is None and len(name_matches) == 1:
            selected = name_matches[0]
        if selected is None:
            # Multiple historical rows share the pair and the current payload row
            # is not indexed yet. Do not guess until the repository refresh lands.
            return data

        node_id = _norm_node(selected.get("node_id"))
        target = targets[0]
        identity = str(target.get("identity") or "").strip().lower()
        port = str(target.get("device") or "").strip()
        if not node_id or not port:
            return data

        repository = getattr(self.tool, "repository", None)
        if identity and hasattr(repository, "_connect"):
            with contextlib.suppress(Exception):
                import contextlib as _contextlib
                with _contextlib.closing(repository._connect()) as connection, connection:
                    connection.execute(
                        "UPDATE managed_nodes SET usb_identity='',last_port='' WHERE usb_identity=? AND node_id<>?",
                        (identity, node_id),
                    )

        updater = getattr(repository, "upsert_managed_node", None)
        if callable(updater):
            with contextlib.suppress(Exception):
                updater(
                    node_id=node_id,
                    long_name=long_name,
                    short_name=short_name,
                    hardware=device_name,
                    usb_identity=identity,
                    last_port=port,
                    status="USB verbunden",
                )

        target["mapped_node_id"] = node_id
        for cached in self.__dict__.get("_framework7_usb_cache", []):
            if not isinstance(cached, dict):
                continue
            if str(cached.get("device") or "").strip().lower() == port.lower():
                cached["mapped_node_id"] = node_id

        self.tool.selected_node_id = node_id
        self.__dict__["_framework7_usb_identity_conflict"] = None
        data["selected_node_id"] = node_id
        connections["selected_usb_node_id"] = node_id
        connections["unique_usb"] = target

        selected["usb_reachable"] = True
        selected["usb"] = target
        selected["transport"] = "USB"
        return data

    LegacyBridge.state = state
