from pathlib import Path

PATH = Path("src/infrastructure/HeltecV3RepeaterPolicy.cpp")
s = PATH.read_text()


def replace_once(old: str, new: str, label: str) -> None:
    global s
    if new in s:
        print(f"{label}: already applied")
        return
    if old not in s:
        raise SystemExit(f"{label}: anchor not found")
    s = s.replace(old, new, 1)
    print(f"{label}: applied")


replace_once(
    "#define V3_POSITION_FRESH_SECS 60UL",
    "#define V3_POSITION_FRESH_SECS 180UL",
    "phone GPS freshness 180s",
)

replace_once(
    """        if (!isFromUs(&mp) || mp.transport_mechanism != meshtastic_MeshPacket_TransportMechanism_TRANSPORT_API)\n            return false;\n\n        // This module is statically constructed before the normal PositionModule\n""",
    """        // Phone-originated packets are inserted into Router with from==0 and\n        // TRANSPORT_INTERNAL. TRANSPORT_API is not preserved at this point in the\n        // RX chain (confirmed by field logs), so requiring TRANSPORT_API caused\n        // every real Meshtastic phone GPS packet to be silently rejected.\n        const bool fromPhone =\n            mp.from == 0 &&\n            mp.transport_mechanism == meshtastic_MeshPacket_TransportMechanism_TRANSPORT_INTERNAL;\n        if (!fromPhone)\n            return false;\n\n        // This module is statically constructed before the normal PositionModule\n""",
    "accept real phone GPS transport",
)

replace_once(
    """    v3LatestPhoneFixFresh = v3PhoneFixFresh(position);\n    v3LatestPhoneFixAccurate = v3PhoneFixAccurate(position);\n\n    if (!v3PhoneFixHasCoordinates(position) || !v3LatestPhoneFixFresh || !v3LatestPhoneFixAccurate) {\n""",
    """    v3LatestPhoneFixFresh = v3PhoneFixFresh(position);\n    v3LatestPhoneFixAccurate = v3PhoneFixAccurate(position);\n\n    const uint32_t nowEpoch = getValidTime(RTCQualityFromNet);\n    const uint32_t fixAge = (position.time != 0 && nowEpoch != 0)\n                                ? (nowEpoch >= position.time ? nowEpoch - position.time : position.time - nowEpoch)\n                                : UINT32_MAX;\n    LOG_INFO(\"Heltec V3 phone GPS: lat=%d lon=%d acc=%umm age=%us coords=%s fresh=%s accurate=%s\",\n             position.latitude_i, position.longitude_i, (unsigned)position.gps_accuracy,\n             fixAge == UINT32_MAX ? 9999U : (unsigned)fixAge,\n             v3PhoneFixHasCoordinates(position) ? \"yes\" : \"no\",\n             v3LatestPhoneFixFresh ? \"yes\" : \"no\",\n             v3LatestPhoneFixAccurate ? \"yes\" : \"no\");\n\n    if (!v3PhoneFixHasCoordinates(position) || !v3LatestPhoneFixFresh || !v3LatestPhoneFixAccurate) {\n""",
    "GPS acceptance diagnostics",
)

replace_once(
    """        if (v3BleConnected())\n            v3ServiceLastActivityMs = now;\n\n        const bool hardCapReached = (uint32_t)(now - v3ServiceStartedMs) >= (uint32_t)V3_SERVICE_MAX_MS;\n""",
    """        // A BLE connection alone is NOT service activity. Meshtastic clients\n        // keep sending heartbeats, node-info/config traffic and background phone\n        // positions even when the app is not being actively used. Refreshing the\n        // timer from isConnected() therefore kept BLE alive until the 15 minute\n        // hard cap. Only intentional GPIO0 interaction refreshes the 120 s idle\n        // timer; background BLE traffic cannot extend it.\n\n        const bool hardCapReached = (uint32_t)(now - v3ServiceStartedMs) >= (uint32_t)V3_SERVICE_MAX_MS;\n""",
    "BLE passive connection no longer extends service",
)

replace_once(
    """    LOG_INFO(\"Heltec V3 service: GPIO0 opened display/Bluetooth; idle=%us hard-cap=%us power-save=%s\",\n                 (unsigned)(V3_SERVICE_IDLE_MS / 1000UL), (unsigned)(V3_SERVICE_MAX_MS / 1000UL),\n                 config.power.is_power_saving ? \"on\" : \"off\");\n""",
    """    LOG_INFO(\"Heltec V3 service: GPIO0 opened display/Bluetooth; idle=%us hard-cap=%us power-save=%s; passive BLE does not extend idle\",\n                 (unsigned)(V3_SERVICE_IDLE_MS / 1000UL), (unsigned)(V3_SERVICE_MAX_MS / 1000UL),\n                 config.power.is_power_saving ? \"on\" : \"off\");\n""",
    "service timeout log",
)

PATH.write_text(s)
print("V3 phone GPS + BLE idle runtime fixes ready")
