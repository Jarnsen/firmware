from pathlib import Path

POLICY_PATH = Path("src/infrastructure/HeltecV3RepeaterPolicy.cpp")
PAGE_PATH = Path("src/infrastructure/HeltecV3PositionPage.cpp")
SCREEN_PATH = Path("src/graphics/Screen.cpp")
NIMBLE_H_PATH = Path("src/nimble/NimbleBluetooth.h")
NIMBLE_CPP_PATH = Path("src/nimble/NimbleBluetooth.cpp")

policy = POLICY_PATH.read_text()
page = PAGE_PATH.read_text()
screen = SCREEN_PATH.read_text()
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


# Give the phone a little more time to discover the service. This only affects
# the no-connection case; once connected the normal 120 s activity policy owns
# the window.
policy = replace_once(
    policy,
    "#define V3_SERVICE_CONNECT_GRACE_MS (30UL * 1000UL)",
    "#define V3_SERVICE_CONNECT_GRACE_MS (60UL * 1000UL)",
    "extend V3 BLE discovery grace to 60s",
)

# ---------------------------------------------------------------------------
# NimBLE: do NOT fully deinit/reinit the ESP32-S3 controller for every service
# window. The runtime logs show BLEDevice::deinit(true) followed by a second
# BLEDevice::init() in the same boot crashing in the controller/HLI path.
# Instead we park the already-created stack: stop advertising, disconnect any
# client, keep the host/controller objects alive, and resume advertising on the
# next GPIO0 service request.
# ---------------------------------------------------------------------------
nimble_h = replace_once(
    nimble_h,
    "    void startAdvertising();\n    bool isDeInit = false;\n",
    "    void startAdvertising();\n"
    "    void stopAdvertisingForService();\n"
    "    bool isAdvertisingSuppressed();\n"
    "    bool isDeInit = false;\n",
    "declare safe BLE advertising park/resume API",
)

nimble_cpp = replace_once(
    nimble_cpp,
    "static std::atomic<bool> pendingStartAdvertising{false};\n",
    "static std::atomic<bool> pendingStartAdvertising{false};\n"
    "// V3 service windows park advertising instead of destroying/recreating the\n"
    "// ESP32-S3 NimBLE controller. onDisconnect must respect this latch.\n"
    "static std::atomic<bool> serviceAdvertisingSuppressed{false};\n",
    "add BLE advertising suppression latch",
)

nimble_cpp = replace_once(
    nimble_cpp,
    """        const uint16_t connHandle = desc->conn_handle;\n\n        // With Google Pixel 8 Android devices, this causes ESP32 device crash\n""",
    """        const uint16_t connHandle = desc->conn_handle;\n        // Track a physical link immediately, not only after authentication. This\n        // prevents a pairing/config connection from being mistaken for 'no phone'.\n        nimbleBluetoothConnHandle = connHandle;\n\n        // With Google Pixel 8 Android devices, this causes ESP32 device crash\n""",
    "track physical BLE connection before authentication",
)

nimble_cpp = replace_once(
    nimble_cpp,
    """        // Defer the advertising restart to runOnce (see pendingStartAdvertising): calling\n        // startAdvertising() here would crash if this disconnect was a host reset.\n        pendingStartAdvertising = true;\n        if (bluetoothPhoneAPI) {\n            bluetoothPhoneAPI->setIntervalFromNow(0);\n        }\n        concurrency::mainDelay.interrupt(); // wake the main loop to service the restart\n""",
    """        // Defer the advertising restart to runOnce unless a V3 service close\n        // deliberately parked BLE. Never let a late disconnect re-open advertising.\n        pendingStartAdvertising = !serviceAdvertisingSuppressed.load();\n        if (pendingStartAdvertising && bluetoothPhoneAPI) {\n            bluetoothPhoneAPI->setIntervalFromNow(0);\n            concurrency::mainDelay.interrupt(); // wake the main loop to service the restart\n        }\n""",
    "respect V3 advertising suppression after disconnect",
)

nimble_cpp = replace_once(
    nimble_cpp,
    """void NimbleBluetooth::startAdvertising()\n{\n    BLEAdvertising *pAdvertising = BLEDevice::getAdvertising();\n""",
    """void NimbleBluetooth::startAdvertising()\n{\n    serviceAdvertisingSuppressed = false;\n    if (!ble_hs_synced()) {\n        // A wake/disconnect can briefly leave the host unsynchronised. Let the\n        // normal PhoneAPI worker retry once NimBLE is ready instead of touching\n        // GAP from the wrong phase.\n        pendingStartAdvertising = true;\n        if (bluetoothPhoneAPI)\n            bluetoothPhoneAPI->setIntervalFromNow(0);\n        concurrency::mainDelay.interrupt();\n        LOG_DEBUG(\"BLE advertising resume deferred until host sync\");\n        return;\n    }\n    pendingStartAdvertising = false;\n    BLEAdvertising *pAdvertising = BLEDevice::getAdvertising();\n""",
    "make BLE advertising resume host-sync safe",
)

nimble_cpp = replace_once(
    nimble_cpp,
    """void NimbleBluetooth::shutdown()\n{\n""",
    """void NimbleBluetooth::stopAdvertisingForService()\n{\n#ifdef ARCH_ESP32\n    if (!bleServer)\n        return;\n\n    serviceAdvertisingSuppressed = true;\n    pendingStartAdvertising = false;\n\n    // Stop discoverability first so no new client can race the service close.\n    BLEAdvertising *pAdvertising = BLEDevice::getAdvertising();\n    if (pAdvertising)\n        pAdvertising->stop();\n\n    // If a physical client is attached, request a clean disconnect. We keep\n    // NimBLE itself initialized; this avoids the ESP32-S3 controller crash seen\n    // when BLEDevice::deinit(true) is followed by BLEDevice::init() in one boot.\n    const uint16_t connHandle = nimbleBluetoothConnHandle.load();\n    if (connHandle != BLE_HS_CONN_HANDLE_NONE && bleServer)\n        bleServer->disconnect(connHandle);\n\n    clearPairingDisplay();\n    resetBleSessionState();\n    LOG_INFO(\"BLE advertising parked; NimBLE stack kept initialized for safe resume\");\n#else\n    shutdown();\n#endif\n}\n\nbool NimbleBluetooth::isAdvertisingSuppressed()\n{\n    return serviceAdvertisingSuppressed.load();\n}\n\nvoid NimbleBluetooth::shutdown()\n{\n""",
    "implement safe BLE advertising park/resume",
)

# The full generic deinit path still exists for normal firmware/admin shutdowns,
# but a later full setup must always clear the V3 suppression latch.
nimble_cpp = replace_once(
    nimble_cpp,
    """    bleDraining = false;\n    isDeInit = false;\n\n#ifdef ARCH_ESP32\n""",
    """    bleDraining = false;\n    isDeInit = false;\n    serviceAdvertisingSuppressed = false;\n\n#ifdef ARCH_ESP32\n""",
    "clear advertising suppression on full BLE setup",
)

# V3 policy uses advertising park/resume rather than controller deinit/reinit.
policy = replace_once(
    policy,
    """static void v3BluetoothOnNow()\n{\n#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH\n    if (!nimbleBluetooth || !nimbleBluetooth->isActive()) {\n        LOG_INFO(\"Heltec V3 service: initialize BLE\");\n        setBluetoothEnable(true);\n    }\n#endif\n}\n""",
    """static void v3BluetoothOnNow()\n{\n#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH\n    if (!nimbleBluetooth || !nimbleBluetooth->isActive()) {\n        LOG_INFO(\"Heltec V3 service: initialize BLE\");\n        setBluetoothEnable(true);\n    } else if (nimbleBluetooth->isAdvertisingSuppressed()) {\n        LOG_INFO(\"Heltec V3 service: resume BLE advertising\");\n        nimbleBluetooth->startAdvertising();\n    }\n#endif\n}\n""",
    "resume parked BLE advertising on GPIO0",
)

policy = replace_once(
    policy,
    """static void v3BluetoothOffNow()\n{\n#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH\n    if (nimbleBluetooth && nimbleBluetooth->isActive()) {\n        LOG_DEBUG(\"Heltec V3 service: deinit BLE outside service window\");\n        nimbleBluetooth->deinit();\n    }\n#endif\n}\n""",
    """static void v3BluetoothOffNow()\n{\n#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH\n    if (nimbleBluetooth && nimbleBluetooth->isActive() && !nimbleBluetooth->isAdvertisingSuppressed()) {\n        LOG_DEBUG(\"Heltec V3 service: park BLE advertising outside service window\");\n        nimbleBluetooth->stopAdvertisingForService();\n    }\n#endif\n}\n""",
    "park BLE instead of full deinit",
)

# Require a clean button release between service sessions. A level-triggered
# GPIO wake while GPIO0 is still low must not immediately reopen service after a
# timeout; that was the path that repeatedly hit BLE re-init in the log.
policy = replace_once(
    policy,
    "static bool v3LongPressHandled = false;\n",
    "static bool v3LongPressHandled = false;\nstatic bool v3RequireButtonRelease = false;\n",
    "add GPIO0 release latch",
)

policy = replace_once(
    policy,
    """    v3BluetoothOffNow();\n    config.bluetooth.enabled = false;\n""",
    """    v3BluetoothOffNow();\n#ifdef BUTTON_PIN\n    v3ServiceButtonEvent = false;\n    v3RequireButtonRelease = digitalRead(BUTTON_PIN) == LOW;\n    v3ButtonPrevPressed = v3RequireButtonRelease;\n#endif\n    config.bluetooth.enabled = false;\n""",
    "latch GPIO0 release when service closes",
)

policy = replace_once(
    policy,
    """        const bool pressEdge = pressed && !v3ButtonPrevPressed;\n        v3ButtonPrevPressed = pressed;\n\n        if (!v3ServiceActive && (v3ServiceButtonEvent || pressEdge)) {\n""",
    """        const bool pressEdge = pressed && !v3ButtonPrevPressed;\n        v3ButtonPrevPressed = pressed;\n\n        if (!v3ServiceActive && v3RequireButtonRelease) {\n            if (!pressed) {\n                v3RequireButtonRelease = false;\n                v3ServiceButtonEvent = false;\n                v3ButtonPrevPressed = false;\n                v3LastAcceptedButtonMs = now;\n                LOG_DEBUG(\"Heltec V3 service: GPIO0 released; next press armed\");\n            }\n            v3ForceIdlePeripheralsOff();\n            continue;\n        }\n\n        if (!v3ServiceActive && (v3ServiceButtonEvent || pressEdge)) {\n""",
    "require release before next GPIO0 service start",
)

# ---------------------------------------------------------------------------
# Position page order: keep one normal frame, but make it the first normal V3
# frame (after a critical-fault frame, if any). The MeshModule no longer appends
# a duplicate copy at the end of the module list.
# ---------------------------------------------------------------------------
page = replace_once(
    page,
    "    bool wantUIFrame() override { return v3PositionUiRoleEnabled(); }\n",
    "    // Screen.cpp inserts this V3 page explicitly as the first normal frame.\n"
    "    // Returning false here prevents a duplicate module copy at the end.\n"
    "    bool wantUIFrame() override { return false; }\n",
    "prevent duplicate V3 module frame at end",
)

page = replace_once(
    page,
    """void heltecV3PositionPageRequestFocus()\n{\n    if (!v3PositionUiRoleEnabled())\n        return;\n    heltecV3PositionModule.requestPositionFocus();\n    if (screen) {\n        screen->setFrames(graphics::Screen::FOCUS_MODULE);\n        screen->runNow();\n    }\n}\n""",
    """bool heltecV3PositionPageEnabled()\n{\n    return v3PositionUiRoleEnabled();\n}\n\nvoid heltecV3PositionPageDrawFrame(OLEDDisplay *display, OLEDDisplayUiState *state, int16_t x, int16_t y)\n{\n    heltecV3PositionModule.drawFrame(display, state, x, y);\n}\n\nvoid heltecV3PositionPageRequestFocus()\n{\n    if (!v3PositionUiRoleEnabled())\n        return;\n    if (screen) {\n        // On the V3, FOCUS_DEFAULT points to our explicitly inserted first\n        // position frame. No module-focus request or end-of-list jump needed.\n        screen->setFrames(graphics::Screen::FOCUS_DEFAULT);\n        screen->runNow();\n    }\n}\n""",
    "focus first V3 position frame instead of appended module",
)

page = replace_once(
    page,
    """void heltecV3PositionPageRequestFocus() {}\nvoid heltecV3PositionPageRefresh() {}\nbool heltecV3PositionPageRecentlyVisible() { return false; }\n""",
    """bool heltecV3PositionPageEnabled() { return false; }\nvoid heltecV3PositionPageDrawFrame(OLEDDisplay *, OLEDDisplayUiState *, int16_t, int16_t) {}\nvoid heltecV3PositionPageRequestFocus() {}\nvoid heltecV3PositionPageRefresh() {}\nbool heltecV3PositionPageRecentlyVisible() { return false; }\n""",
    "add no-screen V3 first-page stubs",
)

screen = replace_once(
    screen,
    "extern MessageStore messageStore;\n",
    "extern MessageStore messageStore;\n"
    "#if defined(_VARIANT_HELTEC_V3)\n"
    "bool heltecV3PositionPageEnabled();\n"
    "void heltecV3PositionPageDrawFrame(OLEDDisplay *display, OLEDDisplayUiState *state, int16_t x, int16_t y);\n"
    "#endif\n",
    "declare V3 first position frame in Screen",
)

screen = replace_once(
    screen,
    """    if (error_code) {\n        normalFrames[numframes++] = NotificationRenderer::drawCriticalFaultFrame;\n        indicatorIcons.push_back(icon_error);\n        focus = FOCUS_FAULT; // Change our \"focus\" parameter, to ensure we show the fault frame\n    }\n\n#if defined(DISPLAY_CLOCK_FRAME)\n""",
    """    if (error_code) {\n        normalFrames[numframes++] = NotificationRenderer::drawCriticalFaultFrame;\n        indicatorIcons.push_back(icon_error);\n        focus = FOCUS_FAULT; // Change our \"focus\" parameter, to ensure we show the fault frame\n    }\n\n#if defined(_VARIANT_HELTEC_V3)\n    // The repeater's MGRS/service position page is deliberately the first\n    // normal page. Critical faults still take precedence when present.\n    if (heltecV3PositionPageEnabled()) {\n        fsi.positions.deviceFocused = numframes;\n        normalFrames[numframes++] = heltecV3PositionPageDrawFrame;\n        indicatorIcons.push_back(icon_module);\n    }\n#endif\n\n#if defined(DISPLAY_CLOCK_FRAME)\n""",
    "insert V3 MGRS position page first",
)

POLICY_PATH.write_text(policy)
PAGE_PATH.write_text(page)
SCREEN_PATH.write_text(screen)
NIMBLE_H_PATH.write_text(nimble_h)
NIMBLE_CPP_PATH.write_text(nimble_cpp)

print("V3 follow-up ready: BLE park/resume + GPIO0 release latch + MGRS page first")
