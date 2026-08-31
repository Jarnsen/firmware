"""Small v3.1 bridge fixes kept separate from the mature feature adapter."""
from __future__ import annotations

from typing import Any

from JARNSEN_FRAMEWORK7_LEGACY_COMPAT import install_legacy_compat


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

    # Installed last on purpose: it preserves the managed-node path above, but
    # restores the stable tool's unique physical USB fallback for virgin or
    # serial-only nodes and exposes USB connection state to Framework7.
    install_legacy_compat(LegacyBridge)
