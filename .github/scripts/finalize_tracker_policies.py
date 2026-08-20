from pathlib import Path


def replace_once(path, old, new, label):
    p = Path(path)
    s = p.read_text()
    if old not in s:
        raise SystemExit(f"{label}: anchor missing in {path}")
    p.write_text(s.replace(old, new, 1))


def replace_all(path, old, new, label):
    p = Path(path)
    s = p.read_text()
    if old not in s:
        raise SystemExit(f"{label}: anchor missing in {path}")
    p.write_text(s.replace(old, new))


# -----------------------------------------------------------------------------
# Screen: let the normal Meshtastic boot logo finish, then give TAK/TAK_TRACKER
# exclusive post-boot frame and power ownership.
# -----------------------------------------------------------------------------
replace_once(
    "src/graphics/Screen.h",
    "} // namespace graphics\n\nbool shouldWakeOnReceivedMessage();",
    "bool isBootScreenComplete();\n} // namespace graphics\n\nbool shouldWakeOnReceivedMessage();",
    "Screen boot-state declaration",
)

replace_once(
    "src/graphics/Screen.cpp",
    "FrameCallback *normalFrames;\nstatic uint32_t targetFramerate = IDLE_FRAMERATE;",
    """FrameCallback *normalFrames;
static uint32_t targetFramerate = IDLE_FRAMERATE;
static bool bootScreenComplete = false;

bool isBootScreenComplete()
{
    return bootScreenComplete;
}

static bool trackerOwnsScreenAfterBoot()
{
#if defined(HELTEC_TRACKER_V1_1)
    return config.device.role == meshtastic_Config_DeviceConfig_Role_TAK ||
           config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER;
#else
    return false;
#endif
}""",
    "Screen boot-state storage",
)

replace_once(
    "src/graphics/Screen.cpp",
    """void Screen::handleSetOn(bool on, FrameCallback einkScreensaver)
{
    if (!useDisplay)
        return;""",
    """void Screen::handleSetOn(bool on, FrameCallback einkScreensaver)
{
    // Queued SET_ON/SET_OFF commands arrive here directly. Enforce the same
    // Tracker ownership gate used by Screen::setOn(), otherwise PowerFSM can
    // still power-cycle the V1.1 TFT underneath the service page.
    if (meshtasticTrackerScreenPowerAllowed && !meshtasticTrackerScreenPowerAllowed(on))
        return;

    if (!useDisplay)
        return;""",
    "Screen queued power gate",
)

replace_once(
    "src/graphics/Screen.cpp",
    """        case Cmd::STOP_ALERT_FRAME:
            NotificationRenderer::pauseBanner = false;
            // Return from one-off alert mode back to regular frames.
            if (!showingNormalScreen && NotificationRenderer::current_notification_type != notificationTypeEnum::text_input) {
                setFrames();
            }
            break;
        case Cmd::STOP_BOOT_SCREEN:
            EINK_ADD_FRAMEFLAG(dispdev, COSMETIC); // E-Ink: Explicitly use full-refresh for next frame
            if (NotificationRenderer::current_notification_type != notificationTypeEnum::text_input) {
                setFrames();
            }
            break;""",
    """        case Cmd::STOP_ALERT_FRAME:
            NotificationRenderer::pauseBanner = false;
            // TAK/TAK_TRACKER never fall back to the stock carousel after boot.
            if (!trackerOwnsScreenAfterBoot() && !showingNormalScreen &&
                NotificationRenderer::current_notification_type != notificationTypeEnum::text_input) {
                setFrames();
            }
            break;
        case Cmd::STOP_BOOT_SCREEN:
            EINK_ADD_FRAMEFLAG(dispdev, COSMETIC); // E-Ink: Explicitly use full-refresh for next frame
            bootScreenComplete = true;
            if (!trackerOwnsScreenAfterBoot() &&
                NotificationRenderer::current_notification_type != notificationTypeEnum::text_input) {
                setFrames();
            }
            break;""",
    "Screen boot/alert ownership",
)

replace_once(
    "src/graphics/Screen.cpp",
    """void Screen::setFrames(FrameFocus focus)
{
    // Block setFrames calls when virtual keyboard is active to prevent overlay interference""",
    """void Screen::setFrames(FrameFocus focus)
{
    // Once the genuine boot screen has ended, TAK/TAK_TRACKER expose only
    // their local service frame. Suppress all stock carousel rebuilds.
    if (bootScreenComplete && trackerOwnsScreenAfterBoot())
        return;

    // Block setFrames calls when virtual keyboard is active to prevent overlay interference""",
    "Screen stock-frame suppression",
)

# -----------------------------------------------------------------------------
# NimBLE: real phone writes are service activity. Pairing PIN becomes an overlay
# on the custom Tracker frame instead of replacing it with a separate alert.
# -----------------------------------------------------------------------------
replace_once(
    "src/nimble/NimbleBluetooth.cpp",
    '#include "sleep.h"\n',
    '#include "sleep.h"\n#if HAS_SCREEN\n#include "graphics/draw/NotificationRenderer.h"\n#endif\n\nextern "C" void meshtasticTrackerBleActivity() __attribute__((weak));\n',
    "NimBLE Tracker activity hook",
)

replace_once(
    "src/nimble/NimbleBluetooth.cpp",
    """#if HAS_SCREEN
    if (screen) {
        screen->endAlert();
    }
#endif""",
    """#if HAS_SCREEN
    if (screen) {
#if defined(HELTEC_TRACKER_V1_1)
        const bool trackerCustomRole = config.device.role == meshtastic_Config_DeviceConfig_Role_TAK ||
                                       config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER;
        if (trackerCustomRole) {
            graphics::NotificationRenderer::resetBanner();
            screen->runNow();
            return;
        }
#endif
        screen->endAlert();
    }
#endif""",
    "NimBLE pairing clear",
)

replace_once(
    "src/nimble/NimbleBluetooth.cpp",
    """        int currentWriteCount = bluetoothPhoneAPI->writeCount.fetch_add(1);

#ifdef DEBUG_NIMBLE_ON_WRITE_TIMING""",
    """        int currentWriteCount = bluetoothPhoneAPI->writeCount.fetch_add(1);
        if (meshtasticTrackerBleActivity)
            meshtasticTrackerBleActivity();

#ifdef DEBUG_NIMBLE_ON_WRITE_TIMING""",
    "NimBLE real phone-write activity",
)

replace_once(
    "src/nimble/NimbleBluetooth.cpp",
    """#if HAS_SCREEN
        if (screen) {
            screen->startAlert([passkey](OLEDDisplay *display, OLEDDisplayUiState *state, int16_t x, int16_t y) -> void {
                char btPIN[16] = "888888";
                snprintf(btPIN, sizeof(btPIN), "%06u", passkey);
                int x_offset = display->width() / 2;
                int y_offset = display->height() <= 80 ? 0 : 12;
                display->setTextAlignment(TEXT_ALIGN_CENTER);
                display->setFont(FONT_MEDIUM);
                display->drawString(x_offset + x, y_offset + y, "Bluetooth");
#if !defined(OLED_TINY)
                display->setFont(FONT_SMALL);
                y_offset = display->height() == 64 ? y_offset + FONT_HEIGHT_MEDIUM - 4 : y_offset + FONT_HEIGHT_MEDIUM + 5;
                display->drawString(x_offset + x, y_offset + y, "Enter this code");
#endif
                display->setFont(FONT_LARGE);
                char pin[8];
                snprintf(pin, sizeof(pin), "%.3s %.3s", btPIN, btPIN + 3);
                y_offset = display->height() == 64 ? y_offset + FONT_HEIGHT_SMALL - 5 : y_offset + FONT_HEIGHT_SMALL + 5;
                display->drawString(x_offset + x, y_offset + y, pin);

                display->setFont(FONT_SMALL);
                char deviceName[64];
                snprintf(deviceName, sizeof(deviceName), "Name: %s", getDeviceName());
                y_offset = display->height() == 64 ? y_offset + FONT_HEIGHT_LARGE - 6 : y_offset + FONT_HEIGHT_LARGE + 5;
                display->drawString(x_offset + x, y_offset + y, deviceName);
            });
        }
#endif""",
    """#if HAS_SCREEN
        if (screen) {
#if defined(HELTEC_TRACKER_V1_1)
            const bool trackerCustomRole = config.device.role == meshtastic_Config_DeviceConfig_Role_TAK ||
                                           config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER;
            if (trackerCustomRole) {
                char pinMessage[64];
                snprintf(pinMessage, sizeof(pinMessage), "Bluetooth\\nPIN %03u %03u", passkey / 1000U, passkey % 1000U);
                graphics::BannerOverlayOptions options;
                options.message = pinMessage;
                options.durationMs = 0;
                options.notificationType = graphics::notificationTypeEnum::pairing_pin;
                screen->showOverlayBanner(options);
            } else
#endif
            {
                screen->startAlert([passkey](OLEDDisplay *display, OLEDDisplayUiState *state, int16_t x, int16_t y) -> void {
                    char btPIN[16] = "888888";
                    snprintf(btPIN, sizeof(btPIN), "%06u", passkey);
                    int x_offset = display->width() / 2;
                    int y_offset = display->height() <= 80 ? 0 : 12;
                    display->setTextAlignment(TEXT_ALIGN_CENTER);
                    display->setFont(FONT_MEDIUM);
                    display->drawString(x_offset + x, y_offset + y, "Bluetooth");
#if !defined(OLED_TINY)
                    display->setFont(FONT_SMALL);
                    y_offset = display->height() == 64 ? y_offset + FONT_HEIGHT_MEDIUM - 4 : y_offset + FONT_HEIGHT_MEDIUM + 5;
                    display->drawString(x_offset + x, y_offset + y, "Enter this code");
#endif
                    display->setFont(FONT_LARGE);
                    char pin[8];
                    snprintf(pin, sizeof(pin), "%.3s %.3s", btPIN, btPIN + 3);
                    y_offset = display->height() == 64 ? y_offset + FONT_HEIGHT_SMALL - 5 : y_offset + FONT_HEIGHT_SMALL + 5;
                    display->drawString(x_offset + x, y_offset + y, pin);

                    display->setFont(FONT_SMALL);
                    char deviceName[64];
                    snprintf(deviceName, sizeof(deviceName), "Name: %s", getDeviceName());
                    y_offset = display->height() == 64 ? y_offset + FONT_HEIGHT_LARGE - 6 : y_offset + FONT_HEIGHT_LARGE + 5;
                    display->drawString(x_offset + x, y_offset + y, deviceName);
                });
            }
        }
#endif""",
    "NimBLE Tracker pairing overlay",
)

# -----------------------------------------------------------------------------
# Shared SW-18010P settings. NORMAL is deliberately 2 falling edges in 3 s.
# -----------------------------------------------------------------------------
replace_once(
    "src/vehicle/TrackerServiceSettings.cpp",
    """// Presets are intentionally small and conservative. Index 2 preserves the
// current project baseline: 3 falling edges within 3 seconds.""",
    """// SW-18010P + 100 nF produces short, mechanically variable pulses.
// NORMAL therefore needs two falling edges in three seconds; stronger and
// weaker qualification remains selectable from the local service menu.""",
    "motion preset comment",
)
replace_once(
    "src/vehicle/TrackerServiceSettings.cpp",
    """constexpr MotionPreset MOTION_PRESETS[] = {
    {"VERY SENS", 2, 3000},
    {"SENSITIVE", 3, 4000},
    {"NORMAL", 3, 3000},
    {"ROBUST", 4, 3000},
};""",
    """constexpr MotionPreset MOTION_PRESETS[] = {
    {"VERY SENS", 1, 3000},
    {"SENSITIVE", 2, 4000},
    {"NORMAL", 2, 3000},
    {"ROBUST", 3, 3000},
};""",
    "SW-18010P motion presets",
)

# -----------------------------------------------------------------------------
# TAK_TRACKER vehicle state machine: use the menu setting for qualification and
# continue processing motion on USB; USB only vetoes the final deep-sleep call.
# -----------------------------------------------------------------------------
replace_once(
    "src/vehicle/HeltecTrackerV11VehicleMotionTracker.cpp",
    '#include "NodeDB.h"\n',
    '#include "NodeDB.h"\n#include "TrackerServiceSettings.h"\n',
    "vehicle settings include",
)
replace_once(
    "src/vehicle/HeltecTrackerV11VehicleMotionTracker.cpp",
    """#ifndef VEHICLE_MOTION_CONFIRM_COUNT
#define VEHICLE_MOTION_CONFIRM_COUNT 3U
#endif

#ifndef VEHICLE_MOTION_CONFIRM_WINDOW_MS
#define VEHICLE_MOTION_CONFIRM_WINDOW_MS 3000UL
#endif

""",
    "",
    "remove fixed motion qualification",
)
replace_once(
    "src/vehicle/HeltecTrackerV11VehicleMotionTracker.cpp",
    """static void IRAM_ATTR vehicleMotionISR()
{
    motionEdgeSequence++;
}

extern "C" void meshtasticVehiclePhoneContact()""",
    """static void IRAM_ATTR vehicleMotionISR()
{
    motionEdgeSequence++;
}

static uint8_t vehicleMotionConfirmCount()
{
    return trackerMotionConfirmCount();
}

static uint32_t vehicleMotionConfirmWindowMs()
{
    return trackerMotionConfirmWindowMs();
}

extern "C" void meshtasticVehiclePhoneContact()""",
    "vehicle dynamic motion helpers",
)
replace_all(
    "src/vehicle/HeltecTrackerV11VehicleMotionTracker.cpp",
    "VEHICLE_MOTION_CONFIRM_COUNT",
    "vehicleMotionConfirmCount()",
    "vehicle motion count references",
)
replace_all(
    "src/vehicle/HeltecTrackerV11VehicleMotionTracker.cpp",
    "VEHICLE_MOTION_CONFIRM_WINDOW_MS",
    "vehicleMotionConfirmWindowMs()",
    "vehicle motion window references",
)
replace_once(
    "src/vehicle/HeltecTrackerV11VehicleMotionTracker.cpp",
    """    if (newEdges != 0) {
        processedMotionEdgeSequence = currentSequence;
        registerVehicleMotionEdges(newEdges);
    }""",
    """    if (newEdges != 0) {
        processedMotionEdgeSequence = currentSequence;
        LOG_DEBUG("Tracker motion: GPIO%d +%u edge(s), candidate=%u/%u active=%u", VEHICLE_MOTION_WAKE_PIN,
                  (unsigned)newEdges, (unsigned)motionCandidateCount, (unsigned)vehicleMotionConfirmCount(),
                  confirmedMotionStillActive(millis()) ? 1U : 0U);
        registerVehicleMotionEdges(newEdges);
    }""",
    "vehicle raw motion diagnostics",
)
replace_once(
    "src/vehicle/HeltecTrackerV11VehicleMotionTracker.cpp",
    """        observeLatestVehiclePosition();
        updateMotionWakePinHealth();

        if (vehicleUsbPowered())
            return 1000;

        const esp_sleep_wakeup_cause_t wakeCause = esp_sleep_get_wakeup_cause();""",
    """        observeLatestVehiclePosition();
        updateMotionWakePinHealth();

        // USB/serial is only a sleep veto. Continue consuming GPIO7 edges and
        // running the full vehicle state machine so bench testing behaves like
        // battery operation; requestVehicleSleep() already refuses deep sleep
        // while USB is present.
        const esp_sleep_wakeup_cause_t wakeCause = esp_sleep_get_wakeup_cause();""",
    "vehicle USB motion processing",
)

# -----------------------------------------------------------------------------
# TAK: genuine boot handoff, state-based TFT power, real BLE activity, robust
# GPIO0, dynamic motion presets, and explicit GPIO0 light-sleep wake.
# -----------------------------------------------------------------------------
tak = Path("src/vehicle/HeltecTrackerV11TakLeaderPolicy.cpp")
s = tak.read_text()
s = s.replace("""#ifndef TAK_LEADER_BOOT_HANDOFF_MS
// Meshtastic's normal Screen logo_timeout is 5 s on this target. Give its
// STOP_BOOT_SCREEN command another 500 ms to complete before TAK owns the TFT.
#define TAK_LEADER_BOOT_HANDOFF_MS 5500UL
#endif

""", "")
s = s.replace("""static bool leaderServiceActive = false;
static bool leaderBluetoothOn = false;
static bool leaderBootHandoffComplete = false;
static bool leaderScreenPowerAuthorized = false;
static uint32_t leaderBootTakeoverStartedMs = 0;""", """static bool leaderServiceActive = false;
static bool leaderBluetoothOn = false;
static bool leaderBootHandoffComplete = false;
static volatile uint32_t leaderPendingBleActivityMs = 0;""")
s = s.replace("""extern \"C\" bool meshtasticTrackerScreenPowerAllowed(bool on)
{
    (void)on;
    if (!takLeaderEnabled())
        return true;

    // During the stock boot logo Meshtastic may manage the TFT normally.
    // Afterwards TAK owns all power transitions; only calls wrapped by
    // setTakLeaderScreenPower() are accepted.
    if (!leaderBootHandoffComplete)
        return true;
    return leaderScreenPowerAuthorized;
}

static void setTakLeaderScreenPower(bool on)
{
    if (!screen)
        return;
    leaderScreenPowerAuthorized = true;
    screen->setOn(on);
    leaderScreenPowerAuthorized = false;
}""", """static bool takLeaderWantsScreenOn()
{
    if (!leaderServiceActive || leaderDisplayStartedMs == 0)
        return false;
    return (uint32_t)(millis() - leaderDisplayStartedMs) < leaderDisplayWindowMs;
}

bool takLeaderScreenPowerAllowed(bool on)
{
    if (!takLeaderEnabled() || !leaderBootHandoffComplete)
        return true;
    return on == takLeaderWantsScreenOn();
}

void takLeaderBleActivity()
{
    leaderPendingBleActivityMs = millis() ? millis() : 1;
}

static void setTakLeaderScreenPower(bool on)
{
    if (screen)
        screen->setOn(on);
}""")
s = s.replace("""static bool takLeaderBleConnected()
{
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
    return nimbleBluetooth && nimbleBluetooth->isConnected();
#else
    return false;
#endif
}

""", "")
s = s.replace("""static void setTakLeaderBluetooth(bool enabled)
{
    if (leaderBluetoothOn == enabled)
        return;
    setBluetoothEnable(enabled);
    leaderBluetoothOn = enabled;
}""", """static void setTakLeaderBluetooth(bool enabled)
{
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
    if (enabled) {
        config.bluetooth.enabled = true;
        if (!nimbleBluetooth || !nimbleBluetooth->isActive())
            setBluetoothEnable(true);
    } else {
        config.bluetooth.enabled = false;
        if (nimbleBluetooth && nimbleBluetooth->isActive())
            nimbleBluetooth->deinit();
    }
#else
    config.bluetooth.enabled = enabled;
    setBluetoothEnable(enabled);
#endif
    leaderBluetoothOn = enabled;
}""")
s = s.replace("""    if (!screen->isScreenOn()) {
        // Install the custom frame BEFORE powering the panel. On Tracker V1.1
        // every power-on reinitializes the TFT/UI; queueing our frame first
        // prevents the stock carousel from becoming visible during that wake.
        screen->startAlert(drawTakLeaderServiceFrame);
        leaderServiceFrameActive = true;
        setTakLeaderScreenPower(true);
        screen->runNow();
    } else if (!leaderServiceFrameActive) {""", """    if (!screen->isScreenOn()) {
        // SET_ON reinitializes the Tracker TFT. Queue our alert after SET_ON so
        // the custom frame is the final UI state in the same Screen pass.
        setTakLeaderScreenPower(true);
        screen->startAlert(drawTakLeaderServiceFrame);
        leaderServiceFrameActive = true;
        screen->runNow();
    } else if (!leaderServiceFrameActive) {""")
s = s.replace("""    leaderDisplayStartedMs = millis();
    leaderDisplayWindowMs = takLeaderLowBattery() ? TAK_LEADER_LOW_BATTERY_DISPLAY_MS : TAK_LEADER_DISPLAY_MS;
    powerFSM.trigger(EVENT_PRESS);
    startTakLeaderServiceFrame();""", """    leaderDisplayStartedMs = millis();
    leaderDisplayWindowMs = takLeaderLowBattery() ? TAK_LEADER_LOW_BATTERY_DISPLAY_MS : TAK_LEADER_DISPLAY_MS;
    startTakLeaderServiceFrame();""")
s = s.replace("""    if (config.bluetooth.enabled)
        setTakLeaderBluetooth(true);
    else
        LOG_WARN(\"TAK leader: Bluetooth disabled in saved config; enable it once so GPIO0 service can start BLE\");

    renderTakLeaderServicePage();
    powerFSM.trigger(EVENT_PRESS);""", """    // GPIO0 always opens a temporary local BLE service window regardless of
    // the persisted Bluetooth setting. It is deinitialized again on timeout.
    setTakLeaderBluetooth(true);
    renderTakLeaderServicePage();""")
s = s.replace("""static bool takLeaderDisplayWindowActive(uint32_t now)
{
    return leaderDisplayStartedMs != 0 && (uint32_t)(now - leaderDisplayStartedMs) < leaderDisplayWindowMs;
}""", """static bool takLeaderDisplayWindowActive(uint32_t now)
{
    (void)now;
    const uint32_t current = millis();
    return leaderDisplayStartedMs != 0 && (uint32_t)(current - leaderDisplayStartedMs) < leaderDisplayWindowMs;
}""")
s = s.replace("""    if (newEdges != 0) {
        if (leaderMotionActive) {""", """    if (newEdges != 0) {
        LOG_DEBUG(\"TAK motion: GPIO%d +%u edge(s), candidate=%u/%u active=%u\", VEHICLE_MOTION_WAKE_PIN,
                  (unsigned)newEdges, (unsigned)leaderMotionCandidateCount, (unsigned)trackerMotionConfirmCount(),
                  leaderMotionActive ? 1U : 0U);
        if (leaderMotionActive) {""")
s = s.replace("""        if (!leaderBootHandoffComplete && now >= TAK_LEADER_BOOT_HANDOFF_MS) {
            leaderBootHandoffComplete = true;
            leaderBootTakeoverStartedMs = now ? now : 1;
            LOG_INFO(\"TAK leader: boot logo complete; exclusive custom display ownership active\");

            if (leaderServiceActive) {
                renderTakLeaderServicePage();
            } else if (screen) {
                // Replace the boot frame with a blank custom alert first.
                // START_ALERT_FRAME also cancels Screen's internal boot state,
                // so STOP_BOOT_SCREEN can no longer expose standard frames.
                leaderBanner[0] = '\\0';
                screen->startAlert(drawTakLeaderServiceFrame);
                leaderServiceFrameActive = true;
                screen->runNow();
            }
        }

        // Give Screen one short scheduling window to consume START_ALERT_FRAME,
        // then blank/power off. This yields: boot logo -> off, never stock menu.
        if (leaderBootHandoffComplete && !leaderServiceActive && leaderBootTakeoverStartedMs != 0 &&
            (uint32_t)(now - leaderBootTakeoverStartedMs) >= 250U) {
            if (screen && screen->isScreenOn())
                setTakLeaderScreenPower(false);
            leaderBootTakeoverStartedMs = 0;
        }""", """        if (!leaderBootHandoffComplete && graphics::isBootScreenComplete()) {
            leaderBootHandoffComplete = true;
            LOG_INFO(\"TAK leader: Meshtastic boot screen complete; custom display ownership active\");
            if (leaderServiceActive)
                renderTakLeaderServicePage();
            else if (screen && screen->isScreenOn())
                setTakLeaderScreenPower(false);
        }""")
s = s.replace("""                    leaderOpenedServiceThisPress = false;
                    leaderLongPressHandled = false;
                    powerFSM.trigger(EVENT_PRESS);

                    if (!leaderServiceActive) {""", """                    leaderOpenedServiceThisPress = false;
                    leaderLongPressHandled = false;

                    if (leaderServiceActive)
                        leaderServiceLastActivityMs = now;

                    if (!leaderServiceActive) {""")
s = s.replace("""        if (leaderServiceActive && takLeaderBleConnected())
            leaderServiceLastActivityMs = now;

        if (leaderServiceActive) {""", """        const uint32_t pendingBleActivity = leaderPendingBleActivityMs;
        if (pendingBleActivity != 0) {
            leaderPendingBleActivityMs = 0;
            if (leaderServiceActive)
                leaderServiceLastActivityMs = now;
        }

        if (leaderServiceActive) {""")
s = s.replace("""    const gpio_num_t button = takLeaderButtonPin();
    if (button != GPIO_NUM_NC)
        pinMode(button, INPUT_PULLUP);""", """    const gpio_num_t button = takLeaderButtonPin();
    if (button != GPIO_NUM_NC) {
        pinMode(button, INPUT_PULLUP);
        gpio_wakeup_enable(button, GPIO_INTR_LOW_LEVEL);
    }""")
s = s.replace("""    // Do not touch the screen here. Meshtastic owns its normal boot logo for
    // the first 5 seconds; runOnce() takes display ownership afterwards.
    setTakLeaderBluetooth(false);""", """    // Do not touch the screen here. Meshtastic owns its normal boot logo until
    // Screen has actually processed STOP_BOOT_SCREEN.
    config.bluetooth.enabled = false;
    setTakLeaderBluetooth(false);""")
if s == tak.read_text():
    raise SystemExit("TAK policy: no replacements applied")
tak.write_text(s)

# -----------------------------------------------------------------------------
# TAK_TRACKER V3-style service: same reliable local UI behavior as TAK, but
# retain the existing deep-sleep vehicle state machine outside service.
# -----------------------------------------------------------------------------
v3 = Path("src/vehicle/VehicleServicePolicyV3Style.cpp")
s = v3.read_text()
s = s.replace("""static bool v3TrackerServiceActive = false;
static bool v3TrackerDisplayVisible = false;""", """static bool v3TrackerServiceActive = false;
static bool v3TrackerDisplayVisible = false;
static bool v3TrackerBootHandoffComplete = false;
static bool v3TrackerServiceFrameActive = false;
static volatile uint32_t v3TrackerPendingBleActivityMs = 0;""")
s = s.replace("""static uint32_t v3TrackerLastAcceptedButtonMs = 0;
static uint32_t v3TrackerButtonPressedSinceMs = 0;
static bool v3TrackerButtonWasPressed = false;
static bool v3TrackerButtonPrevPressed = false;
static bool v3TrackerOpenedServiceThisPress = false;
static bool v3TrackerLongPressHandled = false;""", """static uint32_t v3TrackerButtonPressedSinceMs = 0;
static uint32_t v3TrackerButtonHighSinceMs = 0;
static bool v3TrackerButtonWasPressed = false;
static bool v3TrackerOpenedServiceThisPress = false;
static bool v3TrackerLongPressHandled = false;""")
s = s.replace("""static bool v3TrackerBleConnected()
{
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
    return nimbleBluetooth && nimbleBluetooth->isConnected();
#else
    return false;
#endif
}

""", "")
insert_after = """static bool v3TrackerPositionKnown()
{
    return nodeDB && nodeDB->hasLocalPositionSinceBoot();
}

"""
replacement = insert_after + """static bool v3TrackerDisplayWindowActive()
{
    if (!v3TrackerServiceActive || !v3TrackerDisplayVisible || v3TrackerDisplayStartedMs == 0)
        return false;
    return (uint32_t)(millis() - v3TrackerDisplayStartedMs) < v3TrackerDisplayWindowMs;
}

bool vehicleV3StyleScreenPowerAllowed(bool on)
{
    if (!v3TrackerPolicyEnabled() || !v3TrackerBootHandoffComplete)
        return true;
    return on == v3TrackerDisplayWindowActive();
}

void vehicleV3StyleBleActivity()
{
    v3TrackerPendingBleActivityMs = millis() ? millis() : 1;
}

"""
if insert_after not in s:
    raise SystemExit("V3 service state hook anchor missing")
s = s.replace(insert_after, replacement, 1)
s = s.replace("""static void v3TrackerAssertFrame()
{
    if (!screen || !v3TrackerServiceActive || !v3TrackerDisplayVisible)
        return;

    // Install our one-frame UI before powering the Tracker TFT. The V1.1 TFT
    // reinitializes its UI on wake, so a low 1 Hz reassert closes any one-off
    // Meshtastic boot/UI rebuild without hammering the display worker.
    screen->startAlert(drawV3TrackerServiceFrame);
    screen->runNow();
    v3TrackerLastFrameAssertMs = millis();
}""", """static void v3TrackerAssertFrame()
{
    if (!screen || !v3TrackerServiceActive || !v3TrackerDisplayVisible || !v3TrackerBootHandoffComplete)
        return;

    // Power-up reinitializes the V1.1 TFT. Queue ON first and our alert second,
    // so the service frame is the final UI state of the same Screen pass.
    if (!screen->isScreenOn()) {
        screen->setOn(true);
        screen->startAlert(drawV3TrackerServiceFrame);
        v3TrackerServiceFrameActive = true;
    } else if (!v3TrackerServiceFrameActive) {
        screen->startAlert(drawV3TrackerServiceFrame);
        v3TrackerServiceFrameActive = true;
    }
    screen->runNow();
    v3TrackerLastFrameAssertMs = millis();
}""")
s = s.replace("""    v3TrackerDisplayVisible = true;
    v3TrackerLastFrameAssertMs = 0;
    v3TrackerAssertFrame();
    if (!screen->isScreenOn())
        screen->setOn(true);
    LOG_DEBUG(\"Tracker service: display window opened\");""", """    v3TrackerDisplayVisible = true;
    v3TrackerLastFrameAssertMs = 0;
    if (v3TrackerBootHandoffComplete)
        v3TrackerAssertFrame();
    LOG_DEBUG(\"Tracker service: display window opened\");""")
s = s.replace("""    v3TrackerDisplayVisible = false;
    v3TrackerLastFrameAssertMs = 0;
    if (screen && screen->isScreenOn())
        screen->setOn(false);
    v3TrackerServiceActive = false;""", """    v3TrackerDisplayVisible = false;
    v3TrackerLastFrameAssertMs = 0;
    v3TrackerServiceActive = false;
    if (screen && v3TrackerServiceFrameActive) {
        screen->endAlert();
        v3TrackerServiceFrameActive = false;
    }
    if (screen && screen->isScreenOn())
        screen->setOn(false);""")
old_run = """        const uint32_t now = millis();
        const gpio_num_t button = v3TrackerButtonPin();
        const bool pressed = button != GPIO_NUM_NC && digitalRead(button) == LOW;
        const bool pressEdge = pressed && !v3TrackerButtonPrevPressed;
        v3TrackerButtonPrevPressed = pressed;

        if (!v3TrackerServiceActive && pressEdge &&
            (uint32_t)(now - v3TrackerLastAcceptedButtonMs) >= (uint32_t)VEHICLE_V3_DEBOUNCE_MS) {
            v3TrackerLastAcceptedButtonMs = now ? now : 1;
            v3TrackerButtonPressedSinceMs = now ? now : 1;
            v3TrackerButtonWasPressed = true;
            v3TrackerOpenedServiceThisPress = true;
            v3TrackerLongPressHandled = false;
            v3TrackerStartService();
        } else if (v3TrackerServiceActive && !v3TrackerButtonWasPressed && pressEdge &&
                   (uint32_t)(now - v3TrackerLastAcceptedButtonMs) >= (uint32_t)VEHICLE_V3_DEBOUNCE_MS) {
            v3TrackerLastAcceptedButtonMs = now ? now : 1;
            v3TrackerButtonPressedSinceMs = now ? now : 1;
            v3TrackerButtonWasPressed = true;
            v3TrackerOpenedServiceThisPress = false;
            v3TrackerLongPressHandled = false;
        }

        if (!v3TrackerServiceActive) {
            v3TrackerBluetoothOff();
            if (screen && screen->isScreenOn())
                screen->setOn(false);
            return 50;
        }

        if (v3TrackerButtonWasPressed && pressed && !v3TrackerOpenedServiceThisPress && !v3TrackerLongPressHandled &&
            (uint32_t)(now - v3TrackerButtonPressedSinceMs) >= (uint32_t)VEHICLE_V3_LONG_PRESS_MS) {
            v3TrackerChangeSetting();
            v3TrackerLongPressHandled = true;
            v3TrackerServiceLastActivityMs = now;
        }

        if (v3TrackerButtonWasPressed && !pressed) {
            if (!v3TrackerOpenedServiceThisPress && !v3TrackerLongPressHandled) {
                v3TrackerServicePage = (uint8_t)((v3TrackerServicePage + 1U) % VEHICLE_V3_PAGE_COUNT);
                v3TrackerShowPage();
                v3TrackerServiceLastActivityMs = now;
            }
            v3TrackerButtonWasPressed = false;
            v3TrackerOpenedServiceThisPress = false;
            v3TrackerLongPressHandled = false;
            v3TrackerButtonPressedSinceMs = 0;
        }

        if (v3TrackerBleConnected()) {
            v3TrackerServiceLastActivityMs = now;
            // The deep-sleep vehicle state machine already uses this hook as
            // its real-phone-activity holdoff. Refresh it while connected.
            meshtasticVehiclePhoneContact();
        }
"""
new_run = """        const uint32_t now = millis();

        if (!v3TrackerBootHandoffComplete && graphics::isBootScreenComplete()) {
            v3TrackerBootHandoffComplete = true;
            LOG_INFO(\"TAK_TRACKER: Meshtastic boot screen complete; custom display ownership active\");
            if (v3TrackerServiceActive)
                v3TrackerShowPage();
            else if (screen && screen->isScreenOn())
                screen->setOn(false);
        }

        const gpio_num_t button = v3TrackerButtonPin();
        const bool pressed = button != GPIO_NUM_NC && digitalRead(button) == LOW;
        if (pressed) {
            v3TrackerButtonHighSinceMs = 0;
            if (!v3TrackerButtonWasPressed) {
                v3TrackerButtonWasPressed = true;
                v3TrackerButtonPressedSinceMs = now ? now : 1;
                v3TrackerOpenedServiceThisPress = false;
                v3TrackerLongPressHandled = false;

                if (!v3TrackerServiceActive) {
                    v3TrackerStartService();
                    v3TrackerOpenedServiceThisPress = true;
                } else {
                    v3TrackerServiceLastActivityMs = now;
                    if (!v3TrackerDisplayWindowActive() || (screen && !screen->isScreenOn())) {
                        // First press after display timeout only restores the
                        // current page; the release does not advance it.
                        v3TrackerShowPage();
                        v3TrackerOpenedServiceThisPress = true;
                    }
                }
            }

            if (v3TrackerServiceActive && !v3TrackerOpenedServiceThisPress && !v3TrackerLongPressHandled &&
                (uint32_t)(now - v3TrackerButtonPressedSinceMs) >= (uint32_t)VEHICLE_V3_LONG_PRESS_MS) {
                v3TrackerChangeSetting();
                v3TrackerLongPressHandled = true;
                v3TrackerServiceLastActivityMs = now;
            }
        } else if (v3TrackerButtonWasPressed) {
            if (v3TrackerButtonHighSinceMs == 0)
                v3TrackerButtonHighSinceMs = now ? now : 1;
            if ((uint32_t)(now - v3TrackerButtonHighSinceMs) >= 25U) {
                if (v3TrackerServiceActive && !v3TrackerOpenedServiceThisPress && !v3TrackerLongPressHandled) {
                    v3TrackerServicePage = (uint8_t)((v3TrackerServicePage + 1U) % VEHICLE_V3_PAGE_COUNT);
                    v3TrackerShowPage();
                    v3TrackerServiceLastActivityMs = now;
                    LOG_DEBUG(\"TAK_TRACKER: GPIO0 short press -> page %u/%u\",
                              (unsigned)(v3TrackerServicePage + 1U), (unsigned)VEHICLE_V3_PAGE_COUNT);
                }
                v3TrackerButtonWasPressed = false;
                v3TrackerOpenedServiceThisPress = false;
                v3TrackerLongPressHandled = false;
                v3TrackerButtonPressedSinceMs = 0;
                v3TrackerButtonHighSinceMs = 0;
            }
        } else {
            v3TrackerButtonHighSinceMs = 0;
        }

        const uint32_t pendingBleActivity = v3TrackerPendingBleActivityMs;
        if (pendingBleActivity != 0) {
            v3TrackerPendingBleActivityMs = 0;
            if (v3TrackerServiceActive) {
                v3TrackerServiceLastActivityMs = now;
                // Feed the deep-sleep tracker holdoff from the main task, not
                // directly from the NimBLE callback task.
                meshtasticVehiclePhoneContact();
            }
        }

        if (!v3TrackerServiceActive) {
            v3TrackerBluetoothOff();
            if (v3TrackerBootHandoffComplete && screen && screen->isScreenOn())
                screen->setOn(false);
            return v3TrackerBootHandoffComplete ? 10 : 20;
        }
"""
if old_run not in s:
    raise SystemExit("V3 service run-loop anchor missing")
s = s.replace(old_run, new_run, 1)
s = s.replace("""        const uint32_t frameNow = millis();
        if (v3TrackerDisplayVisible &&
            (v3TrackerLastFrameAssertMs == 0 ||
             (uint32_t)(frameNow - v3TrackerLastFrameAssertMs) >= (uint32_t)VEHICLE_V3_FRAME_REASSERT_MS)) {
            v3TrackerAssertFrame();
        }

        const uint32_t displayNow = millis();""", """        const uint32_t frameNow = millis();
        if (v3TrackerDisplayVisible && v3TrackerBootHandoffComplete &&
            (v3TrackerLastFrameAssertMs == 0 ||
             (uint32_t)(frameNow - v3TrackerLastFrameAssertMs) >= (uint32_t)VEHICLE_V3_FRAME_REASSERT_MS)) {
            // Low-rate recovery only; page changes themselves never power-cycle
            // the TFT. This also restores our frame after a pairing overlay.
            v3TrackerAssertFrame();
        }

        const uint32_t displayNow = millis();""")
s = s.replace("""        if (v3TrackerDisplayVisible &&
            (uint32_t)(displayNow - v3TrackerDisplayStartedMs) >= v3TrackerDisplayWindowMs) {
            v3TrackerDisplayVisible = false;
            if (screen && screen->isScreenOn())
                screen->setOn(false);""", """        if (v3TrackerDisplayVisible &&
            (uint32_t)(displayNow - v3TrackerDisplayStartedMs) >= v3TrackerDisplayWindowMs) {
            v3TrackerDisplayVisible = false;
            if (screen && screen->isScreenOn())
                screen->setOn(false);""")
s = s.replace("        return 20;\n", "        return 10;\n", 1)
s = s.replace("""    config.power.is_power_saving = true;
    config.bluetooth.enabled = false;
    v3TrackerBluetoothOff();
    if (screen && screen->isScreenOn())
        screen->setOn(false);

    vehicleV3StyleServiceThread = new VehicleV3StyleServiceThread();""", """    config.power.is_power_saving = true;
    config.bluetooth.enabled = false;
    v3TrackerBluetoothOff();

    // Leave the TFT alone until Screen reports that the real Meshtastic boot
    // logo has completed. The policy thread performs the handoff afterwards.
    vehicleV3StyleServiceThread = new VehicleV3StyleServiceThread();""")
s = s.replace("""        v3TrackerButtonPrevPressed = v3TrackerButtonWasPressed;
        v3TrackerButtonPressedSinceMs = millis();""", """        v3TrackerButtonPressedSinceMs = millis();""")
if s == v3.read_text():
    raise SystemExit("V3 service: no replacements applied")
v3.write_text(s)

# -----------------------------------------------------------------------------
# Shared hook dispatcher: Screen/NimBLE call one C hook and role-specific code
# decides whether TAK or TAK_TRACKER owns it.
# -----------------------------------------------------------------------------
variant = Path("src/vehicle/TrackerVariantPolicy.cpp")
s = variant.read_text()
s = s.replace("""#if !MESHTASTIC_EXCLUDE_GPS
void setupHeltecTrackerV11TakLeaderPolicy();
#endif

#if defined(VEHICLE_MOTION_WAKE_PIN) && !MESHTASTIC_EXCLUDE_GPS
void setupHeltecTrackerV11VehicleMotionTracker();
void setupVehicleServicePolicyV3Style();
void setupVehicleAdaptiveGnss();
#endif""", """#if !MESHTASTIC_EXCLUDE_GPS
void setupHeltecTrackerV11TakLeaderPolicy();
bool takLeaderScreenPowerAllowed(bool on);
void takLeaderBleActivity();
#endif

#if defined(VEHICLE_MOTION_WAKE_PIN) && !MESHTASTIC_EXCLUDE_GPS
void setupHeltecTrackerV11VehicleMotionTracker();
void setupVehicleServicePolicyV3Style();
void setupVehicleAdaptiveGnss();
bool vehicleV3StyleScreenPowerAllowed(bool on);
void vehicleV3StyleBleActivity();
#endif""")
insert = """
extern "C" bool meshtasticTrackerScreenPowerAllowed(bool on)
{
#if !MESHTASTIC_EXCLUDE_GPS
    if (config.device.role == meshtastic_Config_DeviceConfig_Role_TAK)
        return takLeaderScreenPowerAllowed(on);
#endif
#if defined(VEHICLE_MOTION_WAKE_PIN) && !MESHTASTIC_EXCLUDE_GPS
    if (config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER)
        return vehicleV3StyleScreenPowerAllowed(on);
#endif
    return true;
}

extern "C" void meshtasticTrackerBleActivity()
{
#if !MESHTASTIC_EXCLUDE_GPS
    if (config.device.role == meshtastic_Config_DeviceConfig_Role_TAK) {
        takLeaderBleActivity();
        return;
    }
#endif
#if defined(VEHICLE_MOTION_WAKE_PIN) && !MESHTASTIC_EXCLUDE_GPS
    if (config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER)
        vehicleV3StyleBleActivity();
#endif
}

"""
anchor = "static bool repairLegacyTrackerButtonConfig()\n"
if anchor not in s:
    raise SystemExit("TrackerVariantPolicy dispatcher anchor missing")
s = s.replace(anchor, insert + anchor, 1)
variant.write_text(s)

# Both custom roles own GPIO0; the generic Meshtastic button must never race the
# service UI after a wake.
replace_once(
    "src/vehicle/TrackerTakTrackerButtonOwnership.cpp",
    """static bool takTrackerButtonOwnerEnabled()
{
    return config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER;
}""",
    """static bool takTrackerButtonOwnerEnabled()
{
    return config.device.role == meshtastic_Config_DeviceConfig_Role_TAK ||
           config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER;
}""",
    "shared GPIO0 ownership",
)
replace_once(
    "src/vehicle/TrackerTakTrackerButtonOwnership.cpp",
    'LOG_INFO("TAK_TRACKER: generic Meshtastic UserButton disabled; GPIO0 exclusively owned by Tracker service");',
    'LOG_INFO("Tracker custom role: generic Meshtastic UserButton disabled; GPIO0 exclusively owned by service UI");',
    "GPIO0 ownership log",
)

# -----------------------------------------------------------------------------
# Documentation of the final role behavior.
# -----------------------------------------------------------------------------
Path("docs/tracker-v3-style-service.md").write_text("""# Tracker V1.1 custom TAK roles

## Common behavior

- GPIO0 is exclusively owned by the local service UI; stock Meshtastic button handling is disabled.
- The normal Meshtastic boot logo is allowed to complete. After `STOP_BOOT_SCREEN`, stock carousel frames are suppressed.
- GPIO0 opens Bluetooth and the custom full-screen menu. Display window: 20 s (10 s at <=20% battery).
- Service idle timeout: 120 s; hard cap: 15 min.
- Only physical GPIO0 use or real BLE PHONE->RADIO writes refresh the service idle timer. A merely connected/background phone does not.
- Bluetooth is deinitialized outside the service window.
- Pairing PIN is rendered as an overlay on the custom frame.
- Short GPIO0 press advances pages; long press (~1.2 s) changes supported settings.
- SW-18010P motion defaults to NORMAL = 2 falling edges within 3 s. The selected motion preset is used by both roles.
- Smart Position defaults remain 75 m minimum distance and 30 s minimum interval; parked reporting defaults to 60 min with deterministic 0..180 s desynchronization for hourly-or-longer intervals.

## TAK

- Onboard GNSS tracks while vehicle motion is active.
- 120 s motion quiet triggers a final fresh-position attempt (up to 30 s), then returns to light sleep.
- Parked mode uses light sleep so LoRa remains available for incoming mesh traffic.
- Periodic autonomous position heartbeat uses the configured parked interval.

## TAK_TRACKER

- Onboard GNSS tracks while vehicle motion is active.
- 120 s motion quiet triggers a final fresh-position attempt (up to 30 s), then deep sleep after the post-position guard interval.
- GPIO7/SW-18010P wakes the tracker from deep sleep; timer wake performs the parked position report.
- Parked GNSS acquisition is adaptive (learned TTFF, low-battery limits, periodic full retries).
- USB/serial prevents managed deep sleep but does not suppress GPIO7 motion processing, so bench diagnostics match battery operation.
""")

# -----------------------------------------------------------------------------
# Replace the temporary self-modifying workflow with the final build-only one,
# then remove this patch script from the source tree. The workflow commit will
# trigger a clean build from the actual source files.
# -----------------------------------------------------------------------------
Path(".github/workflows/build-heltec-tracker-v11-vehicle-motion-wake.yml").write_text("""name: Build Heltec Tracker V1.1 Vehicle Motion Wake

on:
  push:
    branches:
      - heltec-tracker-v11-vehicle-motion-wake
  pull_request:
    branches:
      - develop
    paths:
      - src/vehicle/**
      - src/graphics/Screen.cpp
      - src/graphics/Screen.h
      - src/nimble/NimbleBluetooth.cpp
      - src/platform/extra_variants/heltec_wireless_tracker/variant.cpp
      - variants/esp32s3/heltec_wireless_tracker/**
      - .github/workflows/build-heltec-tracker-v11-vehicle-motion-wake.yml

concurrency:
  group: heltec-tracker-v11-vehicle-motion-wake-${{ github.ref }}
  cancel-in-progress: true

permissions:
  contents: read

jobs:
  build-heltec-tracker-v11:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v6
        with:
          python-version: 3.x
          cache: pip
      - name: Install PlatformIO
        run: pip install -U platformio
      - name: Stamp firmware build
        shell: bash
        env:
          BUILD_SHA: ${{ github.event.pull_request.head.sha || github.sha }}
        run: |
          set -euo pipefail
          SHORT_SHA="${BUILD_SHA:0:8}"
          printf '#pragma once\\n#define JARNSEN_BUILD_SHA "%s"\\n' "$SHORT_SHA" > src/vehicle/JarnsenBuildGenerated.h
      - name: Build Heltec Wireless Tracker V1.1
        run: pio run -e heltec-wireless-tracker
      - name: Collect firmware
        shell: bash
        run: |
          set -euo pipefail
          mkdir -p artifact
          BUILD_DIR=.pio/build/heltec-wireless-tracker
          APP_BIN=$(find "$BUILD_DIR" -maxdepth 1 -type f -name 'firmware-heltec-wireless-tracker-*.bin' ! -name '*.factory.bin' -print -quit)
          FACTORY_BIN=$(find "$BUILD_DIR" -maxdepth 1 -type f -name 'firmware-heltec-wireless-tracker-*.factory.bin' -print -quit)
          ELF=$(find "$BUILD_DIR" -maxdepth 1 -type f -name 'firmware-heltec-wireless-tracker-*.elf' -print -quit)
          test -n "$APP_BIN"
          test -n "$FACTORY_BIN"
          test -n "$ELF"
          cp "$FACTORY_BIN" artifact/heltec-tracker-v11-vehicle-motion-wake.factory.bin
          cp "$APP_BIN" artifact/heltec-tracker-v11-vehicle-motion-wake.update.bin
          cp "$ELF" artifact/heltec-tracker-v11-vehicle-motion-wake.elf
      - name: Upload firmware artifact
        uses: actions/upload-artifact@v4
        with:
          name: heltec-tracker-v11-vehicle-motion-wake
          path: artifact/
""")

Path(__file__).unlink()
