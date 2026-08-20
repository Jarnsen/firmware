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


# One build-time patch owns all V3 service changes. Do not duplicate these
# replacements from a PlatformIO pre-script: that previously caused the build
# to patch 60s->180s once in Actions and then fail trying to patch 60s again.
replace_once(
    "#ifndef V3_SERVICE_MAX_MS\n#define V3_SERVICE_MAX_MS (15UL * 60UL * 1000UL)\n#endif\n",
    "#ifndef V3_SERVICE_MAX_MS\n#define V3_SERVICE_MAX_MS (15UL * 60UL * 1000UL)\n#endif\n"
    "#ifndef V3_SERVICE_PACKET_LIMIT\n#define V3_SERVICE_PACKET_LIMIT 20U\n#endif\n",
    "20-packet BLE service budget",
)

replace_once(
    "#define V3_POSITION_FRESH_SECS 60UL",
    "#define V3_POSITION_FRESH_SECS 180UL",
    "phone GPS freshness 180s",
)

replace_once(
    "static char v3ServiceBanner[160];\n",
    "static char v3ServiceBanner[160];\n"
    "static uint32_t v3ServicePacketCount = 0;\n"
    "static uint32_t v3ServiceLastFromNum = 0;\n"
    "static bool v3ServiceHaveFromNum = false;\n"
    "static bool v3FromNumObserverInstalled = false;\n",
    "BLE packet counter state",
)

replace_once(
    """        if (!isFromUs(&mp) || mp.transport_mechanism != meshtastic_MeshPacket_TransportMechanism_TRANSPORT_API)\n            return false;\n\n        // This module is statically constructed before the normal PositionModule\n""",
    """        // Real Meshtastic phone positions are inserted into Router as from=0 +\n        // TRANSPORT_INTERNAL on this firmware. Keep TRANSPORT_API as a compatibility\n        // path for clients/builds that preserve the API transport marker.\n        const bool phoneTransport =\n            mp.transport_mechanism == meshtastic_MeshPacket_TransportMechanism_TRANSPORT_API ||\n            (mp.transport_mechanism == meshtastic_MeshPacket_TransportMechanism_TRANSPORT_INTERNAL && mp.from == 0);\n        const bool phoneSource = isFromUs(&mp) || mp.from == 0;\n        if (!phoneSource || !phoneTransport)\n            return false;\n\n        // This module is statically constructed before the normal PositionModule\n""",
    "accept real phone GPS transport",
)

replace_once(
    """    v3LatestPhoneFixFresh = v3PhoneFixFresh(position);\n    v3LatestPhoneFixAccurate = v3PhoneFixAccurate(position);\n\n    if (!v3PhoneFixHasCoordinates(position) || !v3LatestPhoneFixFresh || !v3LatestPhoneFixAccurate) {\n""",
    """    v3LatestPhoneFixFresh = v3PhoneFixFresh(position);\n    v3LatestPhoneFixAccurate = v3PhoneFixAccurate(position);\n\n    const uint32_t nowEpoch = getValidTime(RTCQualityFromNet);\n    const uint32_t fixAge = (position.time != 0 && nowEpoch != 0)\n                                ? (nowEpoch >= position.time ? nowEpoch - position.time : position.time - nowEpoch)\n                                : UINT32_MAX;\n    LOG_INFO(\"Heltec V3 phone GPS: lat=%d lon=%d acc=%umm age=%us coords=%s fresh=%s accurate=%s\",\n             position.latitude_i, position.longitude_i, (unsigned)position.gps_accuracy,\n             fixAge == UINT32_MAX ? 9999U : (unsigned)fixAge,\n             v3PhoneFixHasCoordinates(position) ? \"yes\" : \"no\",\n             v3LatestPhoneFixFresh ? \"yes\" : \"no\",\n             v3LatestPhoneFixAccurate ? \"yes\" : \"no\");\n\n    if (!v3PhoneFixHasCoordinates(position) || !v3LatestPhoneFixFresh || !v3LatestPhoneFixAccurate) {\n""",
    "GPS acceptance diagnostics",
)

replace_once(
    """        snprintf(v3ServiceBanner, sizeof(v3ServiceBanner), \"V3 SERVICE\\n%s  BAT %u%%\\nSHORT: NEXT\\nBT %us\", role, battery, remaining);\n""",
    """        snprintf(v3ServiceBanner, sizeof(v3ServiceBanner), \"V3 SERVICE\\n%s BAT %u%%\\nBT %us P%u/%u\\nSHORT: NEXT\",\n                 role, battery, remaining, (unsigned)v3ServicePacketCount, (unsigned)V3_SERVICE_PACKET_LIMIT);\n""",
    "show BLE packet budget on service page",
)

replace_once(
    """        v3DisplayVisible = false;\n        v3LastFrameAssertMs = 0;\n        v3ResetAutoConfirmation();\n""",
    """        v3DisplayVisible = false;\n        v3LastFrameAssertMs = 0;\n        v3ServicePacketCount = 0;\n        v3ResetAutoConfirmation();\n""",
    "reset BLE packet budget at service start",
)

replace_once(
    """    LOG_INFO(\"Heltec V3 service: GPIO0 opened display/Bluetooth; idle=%us hard-cap=%us power-save=%s\",\n                 (unsigned)(V3_SERVICE_IDLE_MS / 1000UL), (unsigned)(V3_SERVICE_MAX_MS / 1000UL),\n                 config.power.is_power_saving ? \"on\" : \"off\");\n""",
    """    LOG_INFO(\"Heltec V3 service: GPIO0 opened display/Bluetooth; idle=%us packet-limit=%u power-save=%s; passive BLE does not extend idle\",\n                 (unsigned)(V3_SERVICE_IDLE_MS / 1000UL), (unsigned)V3_SERVICE_PACKET_LIMIT,\n                 config.power.is_power_saving ? \"on\" : \"off\");\n""",
    "service timeout and packet-budget log",
)

replace_once(
    "class V3LightSleepEndObserver : public Observer<esp_sleep_wakeup_cause_t>\n",
    """class V3FromNumObserver : public Observer<uint32_t>\n{\n  protected:\n    int onNotify(uint32_t newValue) override\n    {\n        if (!v3RepeaterRoleEnabled())\n            return 0;\n\n        if (!v3ServiceHaveFromNum) {\n            v3ServiceLastFromNum = newValue;\n            v3ServiceHaveFromNum = true;\n            if (v3ServiceActive)\n                v3ServicePacketCount++;\n        } else {\n            uint32_t delta = newValue - v3ServiceLastFromNum;\n            v3ServiceLastFromNum = newValue;\n            if (v3ServiceActive) {\n                if (delta > V3_SERVICE_PACKET_LIMIT)\n                    delta = V3_SERVICE_PACKET_LIMIT;\n                v3ServicePacketCount += delta;\n            }\n        }\n\n        if (v3ServiceActive && v3ServiceTaskHandle)\n            xTaskNotifyGive(v3ServiceTaskHandle);\n        return 0;\n    }\n};\n\nstatic V3FromNumObserver v3FromNumObserver;\n\nclass V3LightSleepEndObserver : public Observer<esp_sleep_wakeup_cause_t>\n""",
    "observe Meshtastic FromRadio packet counter",
)

replace_once(
    """        if (v3BleConnected())\n            v3ServiceLastActivityMs = now;\n\n        const bool hardCapReached = (uint32_t)(now - v3ServiceStartedMs) >= (uint32_t)V3_SERVICE_MAX_MS;\n""",
    """        // A connected phone, client heartbeat, GPS update, or background packet does\n        // not refresh the service timeout. Only intentional GPIO0 interaction does.\n\n        const bool hardCapReached = (uint32_t)(now - v3ServiceStartedMs) >= (uint32_t)V3_SERVICE_MAX_MS;\n""",
    "BLE passive connection no longer extends service",
)

replace_once(
    """        const bool hardCapReached = (uint32_t)(now - v3ServiceStartedMs) >= (uint32_t)V3_SERVICE_MAX_MS;\n        const bool idleExpired = (uint32_t)(now - v3ServiceLastActivityMs) >= (uint32_t)V3_SERVICE_IDLE_MS;\n        if (hardCapReached || idleExpired) {\n            stopV3ServiceMode();\n            continue;\n        }\n""",
    """        const bool hardCapReached = (uint32_t)(now - v3ServiceStartedMs) >= (uint32_t)V3_SERVICE_MAX_MS;\n        const bool idleExpired = (uint32_t)(now - v3ServiceLastActivityMs) >= (uint32_t)V3_SERVICE_IDLE_MS;\n        const bool packetLimitReached = v3ServicePacketCount >= (uint32_t)V3_SERVICE_PACKET_LIMIT;\n        if (hardCapReached || idleExpired || packetLimitReached) {\n            if (packetLimitReached)\n                LOG_INFO(\"Heltec V3 service: BLE packet budget reached (%u/%u); closing service\",\n                         (unsigned)v3ServicePacketCount, (unsigned)V3_SERVICE_PACKET_LIMIT);\n            stopV3ServiceMode();\n            continue;\n        }\n""",
    "close BLE after 20 new packets or timeout",
)

replace_once(
    """    setupV3ServiceButton();\n\n    LOG_INFO(\"Heltec V3 %s duty:""",
    """    setupV3ServiceButton();\n    if (service && !v3FromNumObserverInstalled) {\n        v3FromNumObserver.observe(&service->fromNumChanged);\n        v3FromNumObserverInstalled = true;\n    }\n\n    LOG_INFO(\"Heltec V3 %s duty:""",
    "install BLE packet-budget observer",
)

PATH.write_text(s)
print("V3 runtime fixes ready: phone GPS + strict 120s BLE idle + 20-packet budget")
