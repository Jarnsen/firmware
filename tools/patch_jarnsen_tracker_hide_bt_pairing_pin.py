"""Hide the Bluetooth pairing passkey on Heltec Tracker V1.1 only.

The JARNSEN fixed Bluetooth PIN, bonding, encryption and MITM policy remain
unchanged. This transform only prevents the Tracker V1.1 local display from
being taken over by the pairing passkey screen. Other boards keep the stock
Meshtastic pairing display behavior.
"""

from pathlib import Path

TARGET = Path("src/nimble/NimbleBluetooth.cpp")
MARKER = "JARNSEN_TRACKER_HIDE_BT_PAIRING_PIN"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, got {count}")
    return text.replace(old, new, 1)


text = TARGET.read_text(encoding="utf-8")

if MARKER not in text:
    pairing_state_anchor = '''#if defined(HELTEC_TRACKER_V1_1)\n        trackerCommonSetPairingDisplay(true);\n#endif\n        powerFSM.trigger(EVENT_BLUETOOTH_PAIR);\n'''
    pairing_state_replacement = '''#if defined(HELTEC_TRACKER_V1_1)\n        // JARNSEN_TRACKER_HIDE_BT_PAIRING_PIN: the fixed Bluetooth PIN remains\n        // active, but pairing must not take ownership of the Tracker display.\n#endif\n        powerFSM.trigger(EVENT_BLUETOOTH_PAIR);\n'''
    text = replace_once(text, pairing_state_anchor, pairing_state_replacement, "Tracker pairing display ownership")

    alert_anchor = '''        bluetoothStatus->updateStatus(&newStatus);\n#if HAS_SCREEN\n        if (screen) {\n'''
    alert_replacement = '''        bluetoothStatus->updateStatus(&newStatus);\n#if HAS_SCREEN && !defined(HELTEC_TRACKER_V1_1)\n        if (screen) {\n'''
    text = replace_once(text, alert_anchor, alert_replacement, "Tracker pairing alert suppression")

    showing_anchor = '''#endif\n        passkeyShowing = true;\n    }\n    void onAuthenticationComplete(ble_gap_conn_desc *desc) override\n'''
    showing_replacement = '''#endif\n#if defined(HELTEC_TRACKER_V1_1)\n        passkeyShowing = false;\n#else\n        passkeyShowing = true;\n#endif\n    }\n    void onAuthenticationComplete(ble_gap_conn_desc *desc) override\n'''
    text = replace_once(text, showing_anchor, showing_replacement, "Tracker pairing display state")

for marker in (
    MARKER,
    "#if HAS_SCREEN && !defined(HELTEC_TRACKER_V1_1)",
    "passkeyShowing = false;",
):
    if marker not in text:
        raise SystemExit(f"Bluetooth pairing display validation failed: {marker}")

TARGET.write_text(text, encoding="utf-8")
