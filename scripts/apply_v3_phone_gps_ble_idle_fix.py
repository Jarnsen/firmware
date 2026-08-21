from pathlib import Path

POLICY_PATH = Path("src/infrastructure/HeltecV3RepeaterPolicy.cpp")
NIMBLE_H_PATH = Path("src/nimble/NimbleBluetooth.h")
NIMBLE_CPP_PATH = Path("src/nimble/NimbleBluetooth.cpp")

policy = POLICY_PATH.read_text()
nimble_h = NIMBLE_H_PATH.read_text()
nimble_cpp = NIMBLE_CPP_PATH.read_text()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"{label}: already applied")
        return text
    if old not in text:
        raise SystemExit(f"{label}: anchor not found")
    print(f"{label}: applied")
    return text.replace(old, new, 1)


# Keep all V3 build-time edits in this one script. There is deliberately no
# PlatformIO pre-patcher anymore; CI runs this once before compiling.
policy = replace_once(
    policy,
    "#ifndef V3_SERVICE_MAX_MS\n#define V3_SERVICE_MAX_MS (15UL * 60UL * 1000UL)\n#endif\n",
    "#ifndef V3_SERVICE_MAX_MS\n#define V3_SERVICE_MAX_MS (15UL * 60UL * 1000UL)\n#endif\n"
    "#ifndef V3_SERVICE_CONNECT_GRACE_MS\n#define V3_SERVICE_CONNECT_GRACE_MS (30UL * 1000UL)\n#endif\n"
    "#ifndef V3_SERVICE_ACTIVITY_WINDOW_MS\n#define V3_SERVICE_ACTIVITY_WINDOW_MS (10UL * 1000UL)\n#endif\n"
    "#ifndef V3_SERVICE_ACTIVITY_THRESHOLD\n#define V3_SERVICE_ACTIVITY_THRESHOLD 3U\n#endif\n",
    "BLE activity burst constants",
)

policy = replace_once(
    policy,
    "#define V3_POSITION_FRESH_SECS 60UL",
    "#define V3_POSITION_FRESH_SECS 180UL",
    "phone GPS freshness 180s",
)

policy = replace_once(
    policy,
    "static char v3ServiceBanner[160];\n",
    "static char v3ServiceBanner[160];\n"
    "static bool v3ServiceEverConnected = false;\n"
    "static uint32_t v3BleTrafficLast = 0;\n"
    "static uint32_t v3BleActivityWindowStartedMs = 0;\n"
    "static uint8_t v3BleActivityWindowCount = 0;\n",
    "BLE burst detector state",
)

policy = replace_once(
    policy,
    """static bool v3BleConnected()\n{\n#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH\n    return nimbleBluetooth && nimbleBluetooth->isConnected();\n#else\n    return false;\n#endif\n}\n""",
    """static bool v3BleConnected()\n{\n#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH\n    return nimbleBluetooth && nimbleBluetooth->isConnected();\n#else\n    return false;\n#endif\n}\n\nstatic uint32_t v3BleMeaningfulTrafficCount()\n{\n#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH\n    return nimbleBluetooth ? nimbleBluetooth->getMeaningfulTrafficCount() : 0U;\n#else\n    return 0U;\n#endif\n}\n""",
    "BLE meaningful traffic accessor",
)

policy = replace_once(
    policy,
    """        if (!isFromUs(&mp) || mp.transport_mechanism != meshtastic_MeshPacket_TransportMechanism_TRANSPORT_API)\n            return false;\n\n        // This module is statically constructed before the normal PositionModule\n""",
    """        // Real Meshtastic phone positions are inserted into Router as from=0 +\n        // TRANSPORT_INTERNAL on this firmware. Keep TRANSPORT_API as a compatibility\n        // path for clients/builds that preserve the API transport marker.\n        const bool phoneTransport =\n            mp.transport_mechanism == meshtastic_MeshPacket_TransportMechanism_TRANSPORT_API ||\n            (mp.transport_mechanism == meshtastic_MeshPacket_TransportMechanism_TRANSPORT_INTERNAL && mp.from == 0);\n        const bool phoneSource = isFromUs(&mp) || mp.from == 0;\n        if (!phoneSource || !phoneTransport)\n            return false;\n\n        // This module is statically constructed before the normal PositionModule\n""",
    "accept real phone GPS transport",
)

policy = replace_once(
    policy,
    """    v3LatestPhoneFixFresh = v3PhoneFixFresh(position);\n    v3LatestPhoneFixAccurate = v3PhoneFixAccurate(position);\n\n    if (!v3PhoneFixHasCoordinates(position) || !v3LatestPhoneFixFresh || !v3LatestPhoneFixAccurate) {\n""",
    """    v3LatestPhoneFixFresh = v3PhoneFixFresh(position);\n    v3LatestPhoneFixAccurate = v3PhoneFixAccurate(position);\n\n    const uint32_t nowEpoch = getValidTime(RTCQualityFromNet);\n    const uint32_t fixAge = (position.time != 0 && nowEpoch != 0)\n                                ? (nowEpoch >= position.time ? nowEpoch - position.time : position.time - nowEpoch)\n                                : UINT32_MAX;\n    LOG_INFO(\"Heltec V3 phone GPS: lat=%d lon=%d acc=%umm age=%us coords=%s fresh=%s accurate=%s\",\n             position.latitude_i, position.longitude_i, (unsigned)position.gps_accuracy,\n             fixAge == UINT32_MAX ? 9999U : (unsigned)fixAge,\n             v3PhoneFixHasCoordinates(position) ? \"yes\" : \"no\",\n             v3LatestPhoneFixFresh ? \"yes\" : \"no\",\n             v3LatestPhoneFixAccurate ? \"yes\" : \"no\");\n\n    if (!v3PhoneFixHasCoordinates(position) || !v3LatestPhoneFixFresh || !v3LatestPhoneFixAccurate) {\n""",
    "GPS acceptance diagnostics",
)

policy = replace_once(
    policy,
    """        snprintf(v3ServiceBanner, sizeof(v3ServiceBanner), \"V3 SERVICE\\n%s  BAT %u%%\\nSHORT: NEXT\\nBT %us\", role, battery, remaining);\n""",
    """        snprintf(v3ServiceBanner, sizeof(v3ServiceBanner), \"V3 SERVICE\\n%s BAT %u%%\\nBT %us A%u/%u\\nSHORT: NEXT\",\n                 role, battery, remaining, (unsigned)v3BleActivityWindowCount,\n                 (unsigned)V3_SERVICE_ACTIVITY_THRESHOLD);\n""",
    "show BLE burst detector on service page",
)

policy = replace_once(
    policy,
    """        v3DisplayVisible = false;\n        v3LastFrameAssertMs = 0;\n        v3ResetAutoConfirmation();\n\n        config.power.is_power_saving = true;\n        config.bluetooth.enabled = true;\n        v3BluetoothOnNow();\n        LOG_INFO(\"Heltec V3 service: GPIO0 opened display/Bluetooth; idle=%us hard-cap=%us power-save=%s\",\n                 (unsigned)(V3_SERVICE_IDLE_MS / 1000UL), (unsigned)(V3_SERVICE_MAX_MS / 1000UL),\n                 config.power.is_power_saving ? \"on\" : \"off\");\n""",
    """        v3DisplayVisible = false;\n        v3LastFrameAssertMs = 0;\n        v3ServiceEverConnected = false;\n        v3BleActivityWindowStartedMs = 0;\n        v3BleActivityWindowCount = 0;\n        v3ResetAutoConfirmation();\n\n        config.power.is_power_saving = true;\n        config.bluetooth.enabled = true;\n        v3BluetoothOnNow();\n        v3BleTrafficLast = v3BleMeaningfulTrafficCount();\n        LOG_INFO(\"Heltec V3 service: GPIO0 opened display/Bluetooth; idle=%us connect-grace=%us activity=%u/%us hard-cap=%us power-save=%s\",\n                 (unsigned)(V3_SERVICE_IDLE_MS / 1000UL),\n                 (unsigned)(V3_SERVICE_CONNECT_GRACE_MS / 1000UL),\n                 (unsigned)V3_SERVICE_ACTIVITY_THRESHOLD,\n                 (unsigned)(V3_SERVICE_ACTIVITY_WINDOW_MS / 1000UL),\n                 (unsigned)(V3_SERVICE_MAX_MS / 1000UL),\n                 config.power.is_power_saving ? \"on\" : \"off\");\n""",
    "initialize BLE burst activity service",
)

# Replace the old "connected BLE == activity" behavior with a real traffic-rate
# detector. Only meaningful GATT payload transactions count: accepted phone
# writes and non-empty reads sent back to the phone. Empty polling reads are not
# counted. Three transactions inside ten seconds indicate active use and reset
# the 120s inactivity timer. A lone heartbeat/GPS packet does not.
policy = replace_once(
    policy,
    """        if (v3BleConnected())\n            v3ServiceLastActivityMs = now;\n\n        const bool hardCapReached = (uint32_t)(now - v3ServiceStartedMs) >= (uint32_t)V3_SERVICE_MAX_MS;\n        const bool idleExpired = (uint32_t)(now - v3ServiceLastActivityMs) >= (uint32_t)V3_SERVICE_IDLE_MS;\n        if (hardCapReached || idleExpired) {\n            stopV3ServiceMode();\n            continue;\n        }\n""",
    """        const bool bleConnected = v3BleConnected();\n        if (bleConnected && !v3ServiceEverConnected) {\n            v3ServiceEverConnected = true;\n            LOG_INFO(\"Heltec V3 service: BLE connected; activity burst detector armed (%u transactions/%us)\",\n                     (unsigned)V3_SERVICE_ACTIVITY_THRESHOLD,\n                     (unsigned)(V3_SERVICE_ACTIVITY_WINDOW_MS / 1000UL));\n        }\n\n        const uint32_t trafficNow = v3BleMeaningfulTrafficCount();\n        if (trafficNow < v3BleTrafficLast) {\n            // NimBLE resets its per-session counter on disconnect/reconnect.\n            v3BleTrafficLast = trafficNow;\n            v3BleActivityWindowStartedMs = 0;\n            v3BleActivityWindowCount = 0;\n        } else if (trafficNow > v3BleTrafficLast) {\n            uint32_t delta = trafficNow - v3BleTrafficLast;\n            v3BleTrafficLast = trafficNow;\n\n            if (v3BleActivityWindowStartedMs == 0 ||\n                (uint32_t)(now - v3BleActivityWindowStartedMs) > (uint32_t)V3_SERVICE_ACTIVITY_WINDOW_MS) {\n                v3BleActivityWindowStartedMs = now ? now : 1;\n                v3BleActivityWindowCount = 0;\n            }\n\n            if (delta > (uint32_t)V3_SERVICE_ACTIVITY_THRESHOLD)\n                delta = (uint32_t)V3_SERVICE_ACTIVITY_THRESHOLD;\n            uint32_t activityCount = (uint32_t)v3BleActivityWindowCount + delta;\n            v3BleActivityWindowCount = activityCount > (uint32_t)V3_SERVICE_ACTIVITY_THRESHOLD\n                                           ? (uint8_t)V3_SERVICE_ACTIVITY_THRESHOLD\n                                           : (uint8_t)activityCount;\n\n            if (v3BleActivityWindowCount >= (uint8_t)V3_SERVICE_ACTIVITY_THRESHOLD) {\n                v3ServiceLastActivityMs = now;\n                LOG_DEBUG(\"Heltec V3 service: active BLE burst detected; 120s idle timer reset\");\n                v3BleActivityWindowStartedMs = now ? now : 1;\n                v3BleActivityWindowCount = 0;\n            }\n        }\n\n        const bool connectGraceExpired =\n            !v3ServiceEverConnected &&\n            (uint32_t)(now - v3ServiceStartedMs) >= (uint32_t)V3_SERVICE_CONNECT_GRACE_MS;\n        const bool hardCapReached = (uint32_t)(now - v3ServiceStartedMs) >= (uint32_t)V3_SERVICE_MAX_MS;\n        const bool idleExpired = (uint32_t)(now - v3ServiceLastActivityMs) >= (uint32_t)V3_SERVICE_IDLE_MS;\n        if (connectGraceExpired || hardCapReached || idleExpired) {\n            if (connectGraceExpired)\n                LOG_INFO(\"Heltec V3 service: no BLE connection within %us; closing service\",\n                         (unsigned)(V3_SERVICE_CONNECT_GRACE_MS / 1000UL));\n            stopV3ServiceMode();\n            continue;\n        }\n""",
    "BLE 3-in-10s activity burst timeout policy",
)

# Expose a V3-safe meaningful traffic counter from NimBLE. We deliberately do
# not use the existing readCount because it also counts empty polling reads,
# which would make a background client look artificially active.
nimble_h = replace_once(
    nimble_h,
    "    bool isConnected();\n    int getRssi();\n",
    "    bool isConnected();\n    uint32_t getMeaningfulTrafficCount();\n    int getRssi();\n",
    "declare meaningful BLE traffic counter",
)

nimble_cpp = replace_once(
    nimble_cpp,
    "static std::atomic<bool> bleDraining{false};\n",
    "static std::atomic<bool> bleDraining{false};\n"
    "static std::atomic<uint32_t> meaningfulBleTrafficCount{0};\n",
    "meaningful BLE traffic atomic",
)

nimble_cpp = replace_once(
    nimble_cpp,
    """        bluetoothPhoneAPI->readCount = 0;\n        bluetoothPhoneAPI->notifyCount = 0;\n        bluetoothPhoneAPI->writeCount = 0;\n""",
    """        bluetoothPhoneAPI->readCount = 0;\n        bluetoothPhoneAPI->notifyCount = 0;\n        bluetoothPhoneAPI->writeCount = 0;\n        meaningfulBleTrafficCount = 0;\n""",
    "reset meaningful BLE traffic counter",
)

nimble_cpp = replace_once(
    nimble_cpp,
    """                memcpy(lastToRadio, val.getData(), val.getLength());\n\n                { // scope for fromPhoneMutex mutexv, pCharacteristic->getLen\n""",
    """                memcpy(lastToRadio, val.getData(), val.getLength());\n                meaningfulBleTrafficCount.fetch_add(1);\n\n                { // scope for fromPhoneMutex mutexv, pCharacteristic->getLen\n""",
    "count accepted BLE writes",
)

nimble_cpp = replace_once(
    nimble_cpp,
    """        // If we sent something, wake up the main loop if it's sleeping in case there are more packets ready to enqueue.\n        if (numBytes != 0) {\n            bluetoothPhoneAPI->setIntervalFromNow(0);\n""",
    """        // Count only non-empty payload reads. Empty client polling reads are intentionally\n        // ignored so a background connection cannot keep the V3 service awake.\n        if (numBytes != 0) {\n            meaningfulBleTrafficCount.fetch_add(1);\n            bluetoothPhoneAPI->setIntervalFromNow(0);\n""",
    "count non-empty BLE reads",
)

nimble_cpp = replace_once(
    nimble_cpp,
    """bool NimbleBluetooth::isConnected()\n{\n    return nimbleBluetoothConnHandle.load() != BLE_HS_CONN_HANDLE_NONE;\n}\n\nint NimbleBluetooth::getRssi()\n""",
    """bool NimbleBluetooth::isConnected()\n{\n    return nimbleBluetoothConnHandle.load() != BLE_HS_CONN_HANDLE_NONE;\n}\n\nuint32_t NimbleBluetooth::getMeaningfulTrafficCount()\n{\n    return meaningfulBleTrafficCount.load();\n}\n\nint NimbleBluetooth::getRssi()\n""",
    "implement meaningful BLE traffic counter",
)

POLICY_PATH.write_text(policy)
NIMBLE_H_PATH.write_text(nimble_h)
NIMBLE_CPP_PATH.write_text(nimble_cpp)
print("V3 runtime fixes ready: phone GPS + BLE 3-in-10s activity detector + 120s idle + 30s connect grace")
