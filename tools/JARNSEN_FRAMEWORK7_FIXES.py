"""Small v3.1 bridge fixes kept separate from the mature feature adapter."""
from __future__ import annotations

from typing import Any

from JARNSEN_FRAMEWORK7_LEGACY_COMPAT import install_legacy_compat
from JARNSEN_FRAMEWORK7_SERIAL_LIVE import install_serial_live
from JARNSEN_FRAMEWORK7_USB_NAME_SELECT import install_usb_name_selection
from JARNSEN_FRAMEWORK7_USB_SELECTION_FIX import install_usb_selection_fix


def install_fixes(LegacyBridge: type) -> None:
    original_profile_action = LegacyBridge.profile_action

    def profile_action(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
        command = str(payload.get("command") or "")
        if command != "capture":
            return original_profile_action(self, payload)

        slot = int(payload.get("slot", -1))
        node_id = str(payload.get("node_id") or "").strip()
        preferred = str(payload.get("transport") or "Automatisch")
        if slot < 0:
            raise RuntimeError("Ungültiger Profil-Slot")
        if not node_id:
            raise RuntimeError("Bitte zuerst eine Ziel-Node auswählen")

        def execute() -> dict[str, Any]:
            transport, target = self._select_profile_target(node_id, preferred)
            self.tool.start_config_profile_capture(slot)
            return {
                "ok": True,
                "message": f"Profil {slot + 1} wird über {transport} von der Node eingelesen",
                "target": target,
            }

        return self.call_ui(execute, timeout=30.0)

    LegacyBridge.profile_action = profile_action

    # Installed first: preserve the mature USB-first service behavior and expose
    # the physical target cache used by the additive wrappers below.
    install_legacy_compat(LegacyBridge)

    # Hardware identity remains the fastest mapping when it is already known.
    install_usb_selection_fix(LegacyBridge)

    # A freshly imported payload is authoritative for the physical COM session.
    # Exact long+short names bind and select the current node even when a historic
    # node-id reused the same human-readable names.
    install_usb_name_selection(LegacyBridge)

    # Live display follows the same transport policy as the rest of the tool:
    # exact USB/serial first, BLE only as fallback.
    install_serial_live(LegacyBridge)
