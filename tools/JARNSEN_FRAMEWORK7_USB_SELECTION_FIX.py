"""Resolve a unique USB serial target to the already-known managed node.

Heltec ESP32-S3 USB CDC exposes the radio MAC as the Windows serial number. The
BLE identity table stores the same value as ``addr:aa:bb:cc:dd:ee:ff``. Reusing
that exact hardware identity gives Framework7 an immediate node mapping before a
new diagnostic payload has had a chance to persist the USB identity.
"""
from __future__ import annotations

import contextlib
import re
from typing import Any


_MAC_RE = re.compile(r"(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}", re.IGNORECASE)


def _mac_identity(target: dict[str, Any]) -> str:
    for key in ("serial_number", "hwid", "description"):
        text = str(target.get(key) or "").strip()
        match = _MAC_RE.search(text)
        if match:
            return "addr:" + match.group(0).lower().replace("-", ":")
    return ""


def install_usb_selection_fix(LegacyBridge: type) -> None:
    if getattr(LegacyBridge, "_jarnsen_usb_selection_fix", False):
        return
    LegacyBridge._jarnsen_usb_selection_fix = True

    original_state = LegacyBridge.state

    def state(self: Any) -> dict[str, Any]:
        data = original_state(self)
        connections = data.get("connections")
        if not isinstance(connections, dict):
            return data
        targets = connections.get("usb")
        if not isinstance(targets, list):
            return data

        repository = getattr(self.tool, "repository", None)
        ble_lookup = getattr(repository, "ble_mapping_v2132", None)
        mapped_unique = ""

        for target in targets:
            if not isinstance(target, dict):
                continue
            node_id = str(target.get("mapped_node_id") or "").strip()
            if not node_id and callable(ble_lookup):
                identity = _mac_identity(target)
                if identity:
                    with contextlib.suppress(Exception):
                        mapping = ble_lookup(identity)
                        if mapping:
                            node_id = str(dict(mapping).get("node_id") or "").strip()
            if not node_id:
                continue

            target["mapped_node_id"] = node_id
            if len(targets) == 1:
                mapped_unique = node_id

            # Keep the bridge cache in sync so _current_usb_port(node_id) and
            # subsequent service actions use the same exact mapping immediately.
            device = str(target.get("device") or "").strip().lower()
            for cached in self.__dict__.get("_framework7_usb_cache", []):
                if not isinstance(cached, dict):
                    continue
                if str(cached.get("device") or "").strip().lower() == device:
                    cached["mapped_node_id"] = node_id

        if len(targets) == 1:
            connections["unique_usb"] = targets[0]

        by_node = {
            str(target.get("mapped_node_id") or "").strip().lower(): target
            for target in targets
            if isinstance(target, dict) and str(target.get("mapped_node_id") or "").strip()
        }
        for node in data.get("nodes", []):
            if not isinstance(node, dict):
                continue
            usb = by_node.get(str(node.get("node_id") or "").strip().lower())
            if not usb:
                continue
            node["usb_reachable"] = True
            node["usb"] = usb
            node["transport"] = "USB"

        if mapped_unique:
            # Align the proven legacy service core with the Framework7 target.
            # The browser still owns navigation/inspector state; this only keeps
            # backend actions pointed at the same unique attached node.
            with contextlib.suppress(Exception):
                self.tool.selected_node_id = mapped_unique

        # The base bridge historically exposed worker_running, but the serial
        # downloader uses self.tool.worker. Publish the actual worker state so
        # the USB popup gets a reliable running -> finished transition and can
        # stop its progress bar/close even when no new captured_at is available.
        worker = getattr(self.tool, "worker", None)
        worker_busy = False
        if worker is not None:
            with contextlib.suppress(Exception):
                worker_busy = bool(worker.is_alive())
        data["busy"] = worker_busy
        connections["usb_worker_busy"] = worker_busy

        return data

    LegacyBridge.state = state
