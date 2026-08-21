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


# ---------------------------------------------------------------------------
# BLE visibility/reliability
# ---------------------------------------------------------------------------
# Expose the real NimBLE GAP advertising state so the V3 service can verify that
# "startAdvertising() returned" also means the controller is actually still
# advertising afterwards.
nimble_h = replace_once(
    nimble_h,
    "    void stopAdvertisingForService();\n    bool isAdvertisingSuppressed();\n",
    "    void stopAdvertisingForService();\n    bool isAdvertisingSuppressed();\n    bool isAdvertisingActive();\n",
    "declare V3 BLE advertising health accessor",
)

nimble_cpp = replace_once(
    nimble_cpp,
    """bool NimbleBluetooth::isAdvertisingSuppressed()\n{\n    return serviceAdvertisingSuppressed.load();\n}\n\nvoid NimbleBluetooth::shutdown()\n""",
    """bool NimbleBluetooth::isAdvertisingSuppressed()\n{\n    return serviceAdvertisingSuppressed.load();\n}\n\nbool NimbleBluetooth::isAdvertisingActive()\n{\n#ifdef ARCH_ESP32\n    return bleServer != nullptr && !serviceAdvertisingSuppressed.load() && ble_hs_synced() && ble_gap_adv_active();\n#else\n    return false;\n#endif\n}\n\nvoid NimbleBluetooth::shutdown()\n""",
    "implement real GAP advertising health accessor",
)

# Parking an idle stack must not close/reset the PhoneAPI object. If a client is
# connected, onDisconnect already performs resetBleSessionState(). If no client
# is connected, preserving the primed PhoneAPI state makes the next advertising
# window identical to the original freshly-created service.
nimble_cpp = replace_once(
    nimble_cpp,
    """    clearPairingDisplay();\n    resetBleSessionState();\n    LOG_INFO(\"BLE advertising parked; NimBLE stack kept initialized for safe resume\");\n""",
    """    clearPairingDisplay();\n    // Do not reset/close PhoneAPI here. A real disconnect invokes onDisconnect()\n    // and performs the reset there; with no client attached the existing API\n    // state is already clean and should remain ready for the next service window.\n    LOG_INFO(\"BLE advertising parked; NimBLE stack and idle PhoneAPI kept initialized\");\n""",
    "keep PhoneAPI primed while V3 advertising is parked",
)

# Make the log prove the controller's GAP state rather than only the wrapper's
# start() return value.
nimble_cpp = replace_once(
    nimble_cpp,
    """    if (!pAdvertising->start(0)) {\n        LOG_ERROR(\"BLE failed to start advertising\");\n    } else {\n        LOG_DEBUG(\"BLE Advertising started\");\n    }\n""",
    """    if (!pAdvertising->start(0)) {\n        LOG_ERROR(\"BLE failed to start advertising\");\n    } else {\n        LOG_INFO(\"BLE Advertising started: name=%s gap-active=%s\", getDeviceName(),\n                 ble_gap_adv_active() ? \"yes\" : \"no\");\n    }\n""",
    "log actual GAP advertising state and device name",
)

# ---------------------------------------------------------------------------
# V3 policy: initialize NimBLE exactly once while the device is still fully
# awake at boot, then park it before entering the repeater duty cycle. GPIO0
# only resumes/stops advertising; it never creates the controller after LS.
# ---------------------------------------------------------------------------
policy = replace_once(
    policy,
    "static bool v3LongPressHandled = false;\nstatic bool v3RequireButtonRelease = false;\n",
    "static bool v3LongPressHandled = false;\nstatic bool v3RequireButtonRelease = false;\n"
    "static uint32_t v3LastPageAdvanceMs = 0;\n"
    "static uint32_t v3LastBleAdvertisingCheckMs = 0;\n",
    "add V3 button action guard and BLE health timer",
)

policy = replace_once(
    policy,
    """static uint32_t v3BleMeaningfulTrafficCount()\n""",
    """static bool v3BleAdvertisingActive()\n{\n#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH\n    return nimbleBluetooth && nimbleBluetooth->isAdvertisingActive();\n#else\n    return false;\n#endif\n}\n\nstatic uint32_t v3BleMeaningfulTrafficCount()\n""",
    "add V3 GAP advertising health accessor",
)

policy = replace_once(
    policy,
    """        v3BluetoothOnNow();\n        v3BleTrafficLast = v3BleMeaningfulTrafficCount();\n""",
    """        v3BluetoothOnNow();\n        v3LastBleAdvertisingCheckMs = now;\n        v3BleTrafficLast = v3BleMeaningfulTrafficCount();\n""",
    "arm BLE advertising health timer at service start",
)

# Re-check actual GAP state while waiting for the first phone. If advertising
# silently stops, restart it without destroying the stack.
policy = replace_once(
    policy,
    """        const uint32_t trafficNow = v3BleMeaningfulTrafficCount();\n""",
    """        if (!bleConnected &&\n            (uint32_t)(now - v3LastBleAdvertisingCheckMs) >= 2000UL) {\n            v3LastBleAdvertisingCheckMs = now;\n            if (!v3BleAdvertisingActive()) {\n                LOG_WARN(\"Heltec V3 service: GAP advertising inactive; restarting without BLE reinit\");\n#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH\n                if (nimbleBluetooth && nimbleBluetooth->isActive())\n                    nimbleBluetooth->startAdvertising();\n#endif\n            }\n        }\n\n        const uint32_t trafficNow = v3BleMeaningfulTrafficCount();\n""",
    "watch and self-heal V3 BLE advertising",
)

# One full NimBLE setup at boot, before the first Light Sleep. Immediately park
# advertising so the repeater is not normally discoverable. This avoids the
# observed first BLEDevice::init() happening only after a GPIO light-sleep wake.
policy = replace_once(
    policy,
    """    v3BluetoothOffNow();\n    if (screen)\n        screen->setOn(false);\n    setupV3ServiceButton();\n""",
    """    config.bluetooth.enabled = true;\n    LOG_INFO(\"Heltec V3 BLE: pre-initialize NimBLE once before first light sleep\");\n    v3BluetoothOnNow();\n    v3BluetoothOffNow();\n    config.bluetooth.enabled = false;\n    LOG_INFO(\"Heltec V3 BLE: boot initialization complete; advertising parked until GPIO0\");\n\n    if (screen)\n        screen->setOn(false);\n    setupV3ServiceButton();\n""",
    "pre-initialize and park NimBLE before first V3 light sleep",
)

# ---------------------------------------------------------------------------
# Button: exactly one page transition per human tap. The existing release-based
# state machine remains; add a minimum held time to reject switch bounce and a
# short post-action guard to reject a second synthetic press/release pair.
# ---------------------------------------------------------------------------
policy = replace_once(
    policy,
    """        if (v3ButtonWasPressed && !pressed) {\n            if (!v3OpenedServiceThisPress && !v3LongPressHandled) {\n                if (screen) {\n                    screen->showNextFrame();\n                    screen->runNow();\n                }\n                v3DisplayStartedMs = now;\n                v3DisplayVisible = true;\n                v3ServiceLastActivityMs = now;\n            }\n            v3ButtonWasPressed = false;\n""",
    """        if (v3ButtonWasPressed && !pressed) {\n            const uint32_t heldMs = v3ButtonPressedSinceMs != 0 ? (uint32_t)(now - v3ButtonPressedSinceMs) : 0U;\n            const bool validTap = heldMs >= 40UL;\n            const bool actionGuardExpired =\n                v3LastPageAdvanceMs == 0 || (uint32_t)(now - v3LastPageAdvanceMs) >= 120UL;\n\n            if (!v3OpenedServiceThisPress && !v3LongPressHandled && validTap && actionGuardExpired) {\n                if (screen) {\n                    screen->showNextFrame();\n                    screen->runNow();\n                }\n                v3LastPageAdvanceMs = now ? now : 1;\n                v3DisplayStartedMs = now;\n                v3DisplayVisible = true;\n                v3ServiceLastActivityMs = now;\n                LOG_DEBUG(\"Heltec V3 button: one tap -> one next frame (held=%ums)\", (unsigned)heldMs);\n            } else if (!v3OpenedServiceThisPress && !v3LongPressHandled && !validTap) {\n                LOG_DEBUG(\"Heltec V3 button: ignored bounce pulse (%ums)\", (unsigned)heldMs);\n            } else if (!v3OpenedServiceThisPress && !v3LongPressHandled && !actionGuardExpired) {\n                LOG_DEBUG(\"Heltec V3 button: ignored duplicate tap inside 120ms guard\");\n            }\n            v3ButtonWasPressed = false;\n""",
    "enforce one V3 page advance per physical tap",
)

POLICY_PATH.write_text(policy)
NIMBLE_H_PATH.write_text(nimble_h)
NIMBLE_CPP_PATH.write_text(nimble_cpp)

print("V3 BLE visibility/button fix ready: boot-time NimBLE init + GAP watchdog + 40ms/120ms one-tap guard")
