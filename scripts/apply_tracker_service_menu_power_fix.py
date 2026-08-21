from pathlib import Path

COMMON_PATH = Path("src/vehicle/TrackerCommonPolicy.cpp")
STATUS_PATH = Path("src/vehicle/TrackerStatusModule.cpp")
STATUS_H_PATH = Path("src/vehicle/TrackerStatusModule.h")
NIMBLE_H_PATH = Path("src/nimble/NimbleBluetooth.h")
NIMBLE_CPP_PATH = Path("src/nimble/NimbleBluetooth.cpp")

common = COMMON_PATH.read_text()
status = STATUS_PATH.read_text()
status_h = STATUS_H_PATH.read_text()
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
# BLE: do not fully deinit NimBLE at the end of every service window.
# ESP-IDF/NimBLE re-init is not reliable on this S3 stack and the real device
# log shows a LoadProhibited/HLI magic crash on the second init. Suspend the
# service instead: disconnect, stop advertising and leave the idle host alive.
# This removes BLE radio traffic while parked and remains resumeable in the
# same boot. Deep sleep still uses the existing full deinit path.
# ---------------------------------------------------------------------------
nimble_h = replace_once(
    nimble_h,
    "    void shutdown();\n    void deinit();\n",
    "    void shutdown();\n    void suspend();\n    void resume();\n    void deinit();\n",
    "declare resumable BLE suspend",
)

nimble_cpp = replace_once(
    nimble_cpp,
    "static std::atomic<bool> bleDraining{false};\n",
    "static std::atomic<bool> bleDraining{false};\n"
    "static std::atomic<bool> bleSuspended{false};\n",
    "BLE suspended state",
)

nimble_cpp = replace_once(
    nimble_cpp,
    """        // Defer the advertising restart to runOnce (see pendingStartAdvertising): calling\n        // startAdvertising() here would crash if this disconnect was a host reset.\n        pendingStartAdvertising = true;\n        if (bluetoothPhoneAPI) {\n            bluetoothPhoneAPI->setIntervalFromNow(0);\n        }\n        concurrency::mainDelay.interrupt(); // wake the main loop to service the restart\n""",
    """        // Defer the advertising restart to runOnce unless the Tracker has\n        // deliberately suspended BLE between GPIO0 service windows.\n        if (!bleSuspended.load()) {\n            pendingStartAdvertising = true;\n            if (bluetoothPhoneAPI)\n                bluetoothPhoneAPI->setIntervalFromNow(0);\n            concurrency::mainDelay.interrupt();\n        } else {\n            pendingStartAdvertising = false;\n        }\n""",
    "suppress advertising restart while suspended",
)

nimble_cpp = replace_once(
    nimble_cpp,
    """void NimbleBluetooth::deinit()\n{\n#ifdef ARCH_ESP32\n""",
    """void NimbleBluetooth::suspend()\n{\n#ifdef ARCH_ESP32\n    if (!isActive())\n        return;\n\n    LOG_INFO(\"Suspend bluetooth service; keep NimBLE host resumeable\");\n    bleSuspended = true;\n    bleDraining = true;\n    pendingStartAdvertising = false;\n    if (bluetoothPhoneAPI)\n        bluetoothPhoneAPI->onReadCallbackIsWaitingForData = false;\n\n    const uint16_t connHandle = nimbleBluetoothConnHandle.load();\n    if (connHandle != BLE_HS_CONN_HANDLE_NONE && bleServer) {\n        bleServer->disconnect(connHandle);\n        const uint32_t started = millis();\n        while (nimbleBluetoothConnHandle.load() != BLE_HS_CONN_HANDLE_NONE &&\n               Throttle::isWithinTimespanMs(started, 1000))\n            delay(10);\n    }\n\n    BLEAdvertising *advertising = BLEDevice::getAdvertising();\n    if (advertising)\n        advertising->stop();\n    clearPairingDisplay();\n    resetBleSessionState();\n    bleDraining = false;\n#endif\n}\n\nvoid NimbleBluetooth::resume()\n{\n#ifdef ARCH_ESP32\n    if (!isActive()) {\n        setup();\n        return;\n    }\n    if (!bleSuspended.exchange(false))\n        return;\n\n    bleDraining = false;\n    isDeInit = false;\n    pendingStartAdvertising = false;\n    LOG_INFO(\"Resume bluetooth service without NimBLE re-init\");\n    startAdvertising();\n#endif\n}\n\nvoid NimbleBluetooth::deinit()\n{\n#ifdef ARCH_ESP32\n""",
    "resumable BLE suspend implementation",
)

nimble_cpp = replace_once(
    nimble_cpp,
    """    bleDraining = false;\n    isDeInit = false;\n\n#ifdef ARCH_ESP32\n""",
    """    bleDraining = false;\n    bleSuspended = false;\n    isDeInit = false;\n\n#ifdef ARCH_ESP32\n""",
    "clear BLE suspend state at setup",
)

# ---------------------------------------------------------------------------
# Shared Tracker policy: moving GNSS stays fast locally (5 s) so 75 m motion is
# detected promptly, but LoRa broadcasts remain governed by Smart Position.
# Once TAK is parked, GNSS is put into its own low-power interval and is only
# woken for the hourly-ish heartbeat. LoRa reception remains active in TAK.
# ---------------------------------------------------------------------------
common = replace_once(
    common,
    '#include "gps/RTC.h"\n',
    '#include "gps/RTC.h"\n#include "gps/GPS.h"\n',
    "Tracker GPS power-control include",
)

common = replace_once(
    common,
    '#ifndef TRACKER_COMMON_BLE_ACTIVITY_THRESHOLD\n',
    '#ifndef TRACKER_COMMON_MOVING_GPS_UPDATE_SECS\n#define TRACKER_COMMON_MOVING_GPS_UPDATE_SECS 5U\n#endif\n'
    '#ifndef TRACKER_COMMON_PARK_GPS_WAIT_MS\n#define TRACKER_COMMON_PARK_GPS_WAIT_MS (30UL * 1000UL)\n#endif\n'
    '#ifndef TRACKER_COMMON_BUTTON_LONG_MS\n#define TRACKER_COMMON_BUTTON_LONG_MS 1200UL\n#endif\n'
    '#ifndef TRACKER_COMMON_BLE_ACTIVITY_THRESHOLD\n',
    "Tracker GNSS/menu timing constants",
)

common = replace_once(
    common,
    'uint32_t lastPositionHeartbeatEpoch = 0;\n',
    'uint32_t lastPositionHeartbeatEpoch = 0;\n'
    'bool parkHeartbeatFixPending = false;\n'
    'uint32_t parkHeartbeatFixStartedMs = 0;\n',
    "park heartbeat GNSS state",
)

common = replace_once(
    common,
    'uint32_t buttonHighSinceMs = 0;\n',
    'uint32_t buttonHighSinceMs = 0;\n'
    'bool buttonLongHandled = false;\n',
    "Tracker service-menu long press state",
)

common = replace_once(
    common,
    """void bluetoothOn()\n{\n#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH\n    config.bluetooth.enabled = true;\n    if (!nimbleBluetooth || !nimbleBluetooth->isActive())\n        setBluetoothEnable(true);\n#else\n    config.bluetooth.enabled = true;\n    setBluetoothEnable(true);\n#endif\n}\n\nvoid bluetoothOff()\n{\n#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH\n    config.bluetooth.enabled = false;\n    if (nimbleBluetooth && nimbleBluetooth->isActive())\n        nimbleBluetooth->deinit();\n#else\n    config.bluetooth.enabled = false;\n    setBluetoothEnable(false);\n#endif\n}\n""",
    """void bluetoothOn()\n{\n#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH\n    config.bluetooth.enabled = true;\n    if (!nimbleBluetooth || !nimbleBluetooth->isActive())\n        setBluetoothEnable(true);\n    else\n        nimbleBluetooth->resume();\n#else\n    config.bluetooth.enabled = true;\n    setBluetoothEnable(true);\n#endif\n}\n\nvoid bluetoothOff()\n{\n#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH\n    config.bluetooth.enabled = false;\n    if (nimbleBluetooth && nimbleBluetooth->isActive())\n        nimbleBluetooth->suspend();\n#else\n    config.bluetooth.enabled = false;\n    setBluetoothEnable(false);\n#endif\n}\n\nvoid useMovingGnssPolicy()\n{\n    config.position.gps_update_interval = TRACKER_COMMON_MOVING_GPS_UPDATE_SECS;\n    if (gps && gps->isEnabled())\n        gps->up();\n}\n\nvoid useParkedGnssPolicy()\n{\n    if (trackerUsesDeepSleep())\n        return;\n    config.position.gps_update_interval = trackerEffectiveParkIntervalSecs();\n    if (gps && gps->isEnabled())\n        gps->down();\n}\n""",
    "resumable BLE and dynamic GNSS policy",
)

common = replace_once(
    common,
    """    timerPositionRequested = false;\n    timerPositionRequestedAtMs = 0;\n    resetFinalPositionState();\n    trackerStatusSetMotionActive(true);\n""",
    """    timerPositionRequested = false;\n    timerPositionRequestedAtMs = 0;\n    parkHeartbeatFixPending = false;\n    parkHeartbeatFixStartedMs = 0;\n    resetFinalPositionState();\n    useMovingGnssPolicy();\n    trackerStatusSetMotionActive(true);\n""",
    "wake GNSS promptly on confirmed movement",
)

common = replace_once(
    common,
    """        resetFinalPositionState();\n        LOG_INFO(\"Tracker V1.1: %s; TAK returning to always-listening light sleep\", reason);\n""",
    """        resetFinalPositionState();\n        useParkedGnssPolicy();\n        LOG_INFO(\"Tracker V1.1: %s; TAK returning to always-listening light sleep; GNSS parked at %us interval\",\n                 reason, (unsigned)trackerEffectiveParkIntervalSecs());\n""",
    "park TAK GNSS with LoRa still listening",
)

old_heartbeat = '''void updateLightSleepHeartbeat()\n{\n    if (trackerUsesDeepSleep() || !parked || motionActive || serviceActive || !positionModule)\n        return;\n\n    const uint32_t nowEpoch = getValidTime(RTCQualityDevice);\n    if (nowEpoch == 0)\n        return;\n\n    if (lastPositionHeartbeatEpoch == 0) {\n        lastPositionHeartbeatEpoch = nowEpoch;\n        return;\n    }\n\n    const uint32_t heartbeatSecs = trackerEffectiveParkIntervalSecs();\n    if (nowEpoch >= lastPositionHeartbeatEpoch && nowEpoch - lastPositionHeartbeatEpoch >= heartbeatSecs) {\n        if (!sendFreshPosition(false))\n            sendBestPosition(false);\n        lastPositionHeartbeatEpoch = nowEpoch;\n        LOG_INFO(\"Tracker V1.1: TAK light-sleep heartbeat sent after %us\", (unsigned)heartbeatSecs);\n    }\n}\n'''
new_heartbeat = '''void updateLightSleepHeartbeat()\n{\n    if (trackerUsesDeepSleep() || !parked || motionActive || serviceActive || !positionModule)\n        return;\n\n    const uint32_t nowEpoch = getValidTime(RTCQualityDevice);\n    if (nowEpoch == 0)\n        return;\n\n    if (lastPositionHeartbeatEpoch == 0) {\n        lastPositionHeartbeatEpoch = nowEpoch;\n        return;\n    }\n\n    const uint32_t heartbeatSecs = trackerEffectiveParkIntervalSecs();\n    if (!parkHeartbeatFixPending) {\n        if (nowEpoch < lastPositionHeartbeatEpoch || nowEpoch - lastPositionHeartbeatEpoch < heartbeatSecs)\n            return;\n\n        parkHeartbeatFixPending = true;\n        parkHeartbeatFixStartedMs = millis() ? millis() : 1;\n        if (gps && gps->isEnabled())\n            gps->up();\n        LOG_INFO(\"Tracker V1.1: parked heartbeat due; waking GNSS for fresh fix\");\n        return;\n    }\n\n    if (sendFreshPosition(false)) {\n        lastPositionHeartbeatEpoch = nowEpoch;\n        parkHeartbeatFixPending = false;\n        parkHeartbeatFixStartedMs = 0;\n        useParkedGnssPolicy();\n        LOG_INFO(\"Tracker V1.1: TAK parked heartbeat sent with fresh GNSS fix after %us\", (unsigned)heartbeatSecs);\n        return;\n    }\n\n    if ((uint32_t)(millis() - parkHeartbeatFixStartedMs) >= TRACKER_COMMON_PARK_GPS_WAIT_MS) {\n        sendBestPosition(false);\n        lastPositionHeartbeatEpoch = nowEpoch;\n        parkHeartbeatFixPending = false;\n        parkHeartbeatFixStartedMs = 0;\n        useParkedGnssPolicy();\n        LOG_WARN(\"Tracker V1.1: parked heartbeat GNSS wait expired; sent best stored position\");\n    }\n}\n'''
common = replace_once(common, old_heartbeat, new_heartbeat, "fresh-fix TAK parked heartbeat")

common = replace_once(
    common,
    """        return (serviceActive || motionActive || motionCandidatePending || finalPositionWaitStartedMs != 0) ? 1 : 0;\n""",
    """        return (serviceActive || motionActive || motionCandidatePending || finalPositionWaitStartedMs != 0 ||\n                parkHeartbeatFixPending)\n                   ? 1\n                   : 0;\n""",
    "keep CPU awake during parked GNSS heartbeat acquisition",
)

# Service menu interaction. Normal native pages remain fast on press; holding
# GPIO0 for 1.2 s enters the dedicated Service page. Inside the service menu,
# short presses advance its sub-pages and long presses change a setting/exit.
common = replace_once(
    common,
    """                buttonPressedSinceMs = now ? now : 1;\n                openedServiceThisPress = false;\n\n                if (!serviceActive) {\n""",
    """                buttonPressedSinceMs = now ? now : 1;\n                openedServiceThisPress = false;\n                buttonLongHandled = false;\n\n                if (!serviceActive) {\n""",
    "reset service-menu long press state",
)

common = replace_once(
    common,
    """                    if (!displayWindowActive() || (screen && !screen->isScreenOn())) {\n                        showTrackerScreen();\n                        openedServiceThisPress = true;\n                    } else if (bootHandoffComplete && screen) {\n                        const uint32_t pressNow = millis();\n                        displayStartedMs = pressNow ? pressNow : 1;\n                        displayVisible = true;\n                        screen->showNextFrame();\n                        screen->runNow();\n                        openedServiceThisPress = true;\n                        LOG_DEBUG(\"Tracker service: GPIO0 press -> next Meshtastic page\");\n                    }\n                }\n            }\n""",
    """                    if (!displayWindowActive() || (screen && !screen->isScreenOn())) {\n                        showTrackerScreen();\n                        openedServiceThisPress = true;\n                    } else if (!trackerServiceMenuActive() && bootHandoffComplete && screen) {\n                        const uint32_t pressNow = millis();\n                        displayStartedMs = pressNow ? pressNow : 1;\n                        displayVisible = true;\n                        screen->showNextFrame();\n                        screen->runNow();\n                        openedServiceThisPress = true;\n                        LOG_DEBUG(\"Tracker service: GPIO0 press -> next Meshtastic page\");\n                    }\n                }\n            }\n\n            if (serviceActive && !buttonLongHandled && buttonPressedSinceMs != 0 &&\n                (uint32_t)(now - buttonPressedSinceMs) >= TRACKER_COMMON_BUTTON_LONG_MS) {\n                serviceLastActivityMs = now;\n                displayStartedMs = now ? now : 1;\n                displayVisible = true;\n                if (trackerServiceMenuActive())\n                    trackerServiceMenuLongAction();\n                else\n                    trackerServiceMenuOpen();\n                buttonLongHandled = true;\n                openedServiceThisPress = true;\n                LOG_DEBUG(\"Tracker service: GPIO0 long press -> service menu action\");\n            }\n""",
    "long press opens/operates Tracker service menu",
)

common = replace_once(
    common,
    """                if (serviceActive && !openedServiceThisPress) {\n                    const uint32_t releaseNow = millis();\n                    serviceLastActivityMs = releaseNow;\n                    displayStartedMs = releaseNow ? releaseNow : 1;\n                    displayVisible = true;\n                    if (bootHandoffComplete && screen) {\n                        screen->showNextFrame();\n                        screen->runNow();\n                        LOG_DEBUG(\"Tracker service: GPIO0 short press -> next Meshtastic page\");\n                    }\n                }\n                buttonWasPressed = false;\n""",
    """                if (serviceActive && !openedServiceThisPress && !buttonLongHandled && trackerServiceMenuActive()) {\n                    const uint32_t releaseNow = millis();\n                    serviceLastActivityMs = releaseNow;\n                    displayStartedMs = releaseNow ? releaseNow : 1;\n                    displayVisible = true;\n                    trackerServiceMenuNext();\n                    LOG_DEBUG(\"Tracker service: GPIO0 short press -> next service sub-page\");\n                }\n                buttonWasPressed = false;\n""",
    "short press advances service sub-pages only when menu active",
)

common = replace_once(
    common,
    """                buttonPressedSinceMs = 0;\n                buttonHighSinceMs = 0;\n""",
    """                buttonPressedSinceMs = 0;\n                buttonHighSinceMs = 0;\n                buttonLongHandled = false;\n""",
    "clear service-menu long press after release",
)

common = replace_once(
    common,
    """    config.position.gps_mode = meshtastic_Config_PositionConfig_GpsMode_ENABLED;\n    config.position.fixed_position = false;\n    trackerApplyPositionSettings();\n""",
    """    config.position.gps_mode = meshtastic_Config_PositionConfig_GpsMode_ENABLED;\n    config.position.fixed_position = false;\n    config.position.gps_update_interval = TRACKER_COMMON_MOVING_GPS_UPDATE_SECS;\n    trackerApplyPositionSettings();\n""",
    "set fast local GNSS refresh while moving",
)

# ---------------------------------------------------------------------------
# Dedicated Tracker Service UI module. It is one additional native Meshtastic
# page in the carousel. Long GPIO0 enters its internal sub-pages, restoring the
# STATUS/DIAG/VERSION/MOTION/DISTANCE/INTERVAL/PARK controls from the old menu.
# ---------------------------------------------------------------------------
status = replace_once(
    status,
    '#include "GPSStatus.h"\n#include "NodeDB.h"\n',
    '#include "GPSStatus.h"\n#include "NodeDB.h"\n#include "PowerStatus.h"\n',
    "service page power include",
)
status = replace_once(
    status,
    '#include "vehicle/TrackerStatusModule.h"\n',
    '#include "vehicle/JarnsenBuildInfo.h"\n#include "vehicle/TrackerEnhancements.h"\n#include "vehicle/TrackerServiceSettings.h"\n#include "vehicle/TrackerStatusModule.h"\n',
    "service page Tracker includes",
)

status = replace_once(
    status,
    'volatile bool trackerMotionActive = false;\n',
    '''volatile bool trackerMotionActive = false;\n\nenum TrackerServicePage : uint8_t {\n    TRACKER_SERVICE_OVERVIEW = 0,\n    TRACKER_SERVICE_DIAG,\n    TRACKER_SERVICE_VERSION,\n    TRACKER_SERVICE_MOTION,\n    TRACKER_SERVICE_DISTANCE,\n    TRACKER_SERVICE_INTERVAL,\n    TRACKER_SERVICE_PARK,\n    TRACKER_SERVICE_EXIT,\n    TRACKER_SERVICE_PAGE_COUNT,\n};\n\nbool trackerServiceMenuMode = false;\nuint8_t trackerServicePage = TRACKER_SERVICE_OVERVIEW;\n''',
    "service menu state",
)

service_class = r'''
class TrackerServiceModule : public MeshModule
{
  public:
    TrackerServiceModule() : MeshModule("Tracker Service") {}

    bool wantPacket(const meshtastic_MeshPacket *) override { return false; }
    bool wantUIFrame() override { return trackerUiRoleEnabled(); }
    void requestServiceFocus() { requestFocus(); }

    void drawFrame(OLEDDisplay *display, OLEDDisplayUiState *, int16_t x, int16_t y) override
    {
        if (!display)
            return;

        display->setTextAlignment(TEXT_ALIGN_CENTER);
        const int center = display->getWidth() / 2 + x;
        const char *mode = trackerServiceMenuMode ? "MENU" : "SERVICE";
        char line[72] = {};

        display->setFont(FONT_MEDIUM);
        display->drawString(center, 10 + y, mode);
        display->setFont(FONT_SMALL);

        switch ((TrackerServicePage)trackerServicePage) {
        case TRACKER_SERVICE_OVERVIEW:
            snprintf(line, sizeof(line), "Motion %s | Smart %um/%us", trackerMotionSensitivityName(),
                     (unsigned)trackerSmartDistanceM(), (unsigned)trackerSmartIntervalSecs());
            display->drawString(center, 32 + y, line);
            snprintf(line, sizeof(line), "Park %umin (eff %us)", (unsigned)trackerParkIntervalMinutes(),
                     (unsigned)trackerEffectiveParkIntervalSecs());
            display->drawString(center, 47 + y, line);
            display->drawString(center, 62 + y, trackerServiceMenuMode ? "SHORT: NEXT" : "HOLD GPIO0: MENU");
            break;
        case TRACKER_SERVICE_DIAG:
            snprintf(line, sizeof(line), "GPS age %us | %s", trackerLastFixAgeSecs() == UINT32_MAX ? 9999U :
                         (unsigned)trackerLastFixAgeSecs(), trackerMotionSensorStatus());
            display->drawString(center, 32 + y, line);
            snprintf(line, sizeof(line), "miss %u | wake %s", (unsigned)trackerMotionSensorMissedMovementEvents(),
                     trackerBootWakeReason());
            display->drawString(center, 48 + y, line);
            break;
        case TRACKER_SERVICE_VERSION:
            snprintf(line, sizeof(line), "%s", JARNSEN_FIRMWARE_VERSION);
            display->drawString(center, 32 + y, line);
            snprintf(line, sizeof(line), "build %.8s | up %umin", JARNSEN_BUILD_SHA, (unsigned)(millis() / 60000UL));
            display->drawString(center, 48 + y, line);
            break;
        case TRACKER_SERVICE_MOTION:
            snprintf(line, sizeof(line), "Motion: %s", trackerMotionSensitivityName());
            display->drawString(center, 30 + y, line);
            snprintf(line, sizeof(line), "%u pulses / %us", (unsigned)trackerMotionConfirmCount(),
                     (unsigned)(trackerMotionConfirmWindowMs() / 1000UL));
            display->drawString(center, 46 + y, line);
            display->drawString(center, 62 + y, "HOLD: CHANGE");
            break;
        case TRACKER_SERVICE_DISTANCE:
            snprintf(line, sizeof(line), "Min distance: %u m", (unsigned)trackerSmartDistanceM());
            display->drawString(center, 36 + y, line);
            display->drawString(center, 57 + y, "HOLD: CHANGE");
            break;
        case TRACKER_SERVICE_INTERVAL:
            snprintf(line, sizeof(line), "Min interval: %u s", (unsigned)trackerSmartIntervalSecs());
            display->drawString(center, 36 + y, line);
            display->drawString(center, 57 + y, "HOLD: CHANGE");
            break;
        case TRACKER_SERVICE_PARK:
            snprintf(line, sizeof(line), "Park: %u min", (unsigned)trackerParkIntervalMinutes());
            display->drawString(center, 32 + y, line);
            snprintf(line, sizeof(line), "effective: %u s", (unsigned)trackerEffectiveParkIntervalSecs());
            display->drawString(center, 48 + y, line);
            display->drawString(center, 64 + y, "HOLD: CHANGE");
            break;
        case TRACKER_SERVICE_EXIT:
            display->drawString(center, 37 + y, "SERVICE MENU EXIT");
            display->drawString(center, 57 + y, "HOLD: EXIT");
            break;
        default:
            trackerServicePage = TRACKER_SERVICE_OVERVIEW;
            break;
        }
    }
};

TrackerServiceModule trackerServiceModule;
'''

status = replace_once(
    status,
    'TrackerStatusModule trackerStatusModule;\n} // namespace\n',
    'TrackerStatusModule trackerStatusModule;\n' + service_class + '} // namespace\n',
    "dedicated Tracker Service UI module",
)

status = replace_once(
    status,
    '''void trackerStatusSetMotionActive(bool active)\n{\n    trackerMotionActive = active;\n    if (screen && screen->isScreenOn())\n        screen->runNow();\n}\n''',
    '''void trackerStatusSetMotionActive(bool active)\n{\n    trackerMotionActive = active;\n    if (screen && screen->isScreenOn())\n        screen->runNow();\n}\n\nbool trackerServiceMenuActive()\n{\n    return trackerServiceMenuMode;\n}\n\nvoid trackerServiceMenuOpen()\n{\n    if (!trackerUiRoleEnabled())\n        return;\n    trackerServiceMenuMode = true;\n    trackerServicePage = TRACKER_SERVICE_OVERVIEW;\n    trackerServiceModule.requestServiceFocus();\n    if (screen) {\n        screen->setFrames(graphics::Screen::FOCUS_MODULE);\n        screen->runNow();\n    }\n}\n\nvoid trackerServiceMenuNext()\n{\n    if (!trackerServiceMenuMode)\n        return;\n    trackerServicePage = (uint8_t)((trackerServicePage + 1U) % TRACKER_SERVICE_PAGE_COUNT);\n    if (screen)\n        screen->runNow();\n}\n\nvoid trackerServiceMenuClose()\n{\n    trackerServiceMenuMode = false;\n    trackerServicePage = TRACKER_SERVICE_OVERVIEW;\n    trackerStatusRequestFocus();\n}\n\nvoid trackerServiceMenuLongAction()\n{\n    if (!trackerServiceMenuMode)\n        return;\n\n    switch ((TrackerServicePage)trackerServicePage) {\n    case TRACKER_SERVICE_MOTION:\n        trackerCycleMotionSensitivity();\n        break;\n    case TRACKER_SERVICE_DISTANCE:\n        trackerCycleSmartDistance();\n        break;\n    case TRACKER_SERVICE_INTERVAL:\n        trackerCycleSmartInterval();\n        break;\n    case TRACKER_SERVICE_PARK:\n        trackerCycleParkInterval();\n        break;\n    case TRACKER_SERVICE_EXIT:\n        trackerServiceMenuClose();\n        return;\n    default:\n        return;\n    }\n    if (screen)\n        screen->runNow();\n}\n''',
    "Tracker service menu public actions",
)

status = replace_once(
    status,
    '''void trackerStatusRequestFocus() {}\nvoid trackerStatusSetMotionActive(bool) {}\n''',
    '''void trackerStatusRequestFocus() {}\nvoid trackerStatusSetMotionActive(bool) {}\nbool trackerServiceMenuActive() { return false; }\nvoid trackerServiceMenuOpen() {}\nvoid trackerServiceMenuNext() {}\nvoid trackerServiceMenuLongAction() {}\nvoid trackerServiceMenuClose() {}\n''',
    "Tracker service menu no-screen stubs",
)

status_h = replace_once(
    status_h,
    'void trackerStatusSetMotionActive(bool active);\n',
    'void trackerStatusSetMotionActive(bool active);\n'
    'bool trackerServiceMenuActive();\n'
    'void trackerServiceMenuOpen();\n'
    'void trackerServiceMenuNext();\n'
    'void trackerServiceMenuLongAction();\n'
    'void trackerServiceMenuClose();\n',
    "Tracker service menu declarations",
)

for needle, text in [
    ('Suspend bluetooth service; keep NimBLE host resumeable', nimble_cpp),
    ('Resume bluetooth service without NimBLE re-init', nimble_cpp),
    ('TRACKER_COMMON_MOVING_GPS_UPDATE_SECS 5U', common),
    ('parked heartbeat due; waking GNSS for fresh fix', common),
    ('trackerServiceMenuOpen();', common),
    ('class TrackerServiceModule', status),
    ('HOLD GPIO0: MENU', status),
    ('void trackerServiceMenuLongAction()', status),
]:
    if needle not in text:
        raise SystemExit(f"Tracker service/power verification failed: {needle}")

COMMON_PATH.write_text(common)
STATUS_PATH.write_text(status)
STATUS_H_PATH.write_text(status_h)
NIMBLE_H_PATH.write_text(nimble_h)
NIMBLE_CPP_PATH.write_text(nimble_cpp)
