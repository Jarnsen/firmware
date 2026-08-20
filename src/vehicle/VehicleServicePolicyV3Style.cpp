#include "configuration.h"

#if defined(HELTEC_TRACKER_V1_1) && defined(VEHICLE_MOTION_WAKE_PIN)

#include "JarnsenBuildInfo.h"
#include "NodeDB.h"
#include "PowerStatus.h"
#include "TrackerEnhancements.h"
#include "TrackerServiceSettings.h"
#include "concurrency/OSThread.h"
#include "graphics/Screen.h"
#include "graphics/ScreenFonts.h"
#include "graphics/draw/NotificationRenderer.h"
#include "main.h"
#include "sleep.h"
#include "target_specific.h"

#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
#include "nimble/NimbleBluetooth.h"
#endif

#include <driver/gpio.h>
#include <esp_sleep.h>

#ifndef VEHICLE_V3_SERVICE_IDLE_MS
#define VEHICLE_V3_SERVICE_IDLE_MS (120UL * 1000UL)
#endif
#ifndef VEHICLE_V3_SERVICE_MAX_MS
#define VEHICLE_V3_SERVICE_MAX_MS (15UL * 60UL * 1000UL)
#endif
#ifndef VEHICLE_V3_SERVICE_DISPLAY_MS
#define VEHICLE_V3_SERVICE_DISPLAY_MS (20UL * 1000UL)
#endif
#ifndef VEHICLE_V3_LOW_BATTERY_DISPLAY_MS
#define VEHICLE_V3_LOW_BATTERY_DISPLAY_MS (10UL * 1000UL)
#endif
#ifndef VEHICLE_V3_LOW_BATTERY_PERCENT
#define VEHICLE_V3_LOW_BATTERY_PERCENT 20U
#endif
#ifndef VEHICLE_V3_LONG_PRESS_MS
#define VEHICLE_V3_LONG_PRESS_MS 1200UL
#endif
#ifndef VEHICLE_V3_DEBOUNCE_MS
#define VEHICLE_V3_DEBOUNCE_MS 80UL
#endif
#ifndef VEHICLE_V3_FRAME_REASSERT_MS
#define VEHICLE_V3_FRAME_REASSERT_MS 1000UL
#endif

enum VehicleV3ServicePage : uint8_t {
    VEHICLE_V3_PAGE_STATUS = 0,
    VEHICLE_V3_PAGE_DIAG,
    VEHICLE_V3_PAGE_VERSION,
    VEHICLE_V3_PAGE_MOTION,
    VEHICLE_V3_PAGE_DISTANCE,
    VEHICLE_V3_PAGE_INTERVAL,
    VEHICLE_V3_PAGE_PARK,
    VEHICLE_V3_PAGE_COUNT,
};

static bool v3TrackerServiceActive = false;
static bool v3TrackerDisplayVisible = false;
static bool v3TrackerBootHandoffComplete = false;
static bool v3TrackerServiceFrameActive = false;
static volatile uint32_t v3TrackerPendingBleActivityMs = 0;
static uint32_t v3TrackerServiceStartedMs = 0;
static uint32_t v3TrackerServiceLastActivityMs = 0;
static uint32_t v3TrackerDisplayStartedMs = 0;
static uint32_t v3TrackerDisplayWindowMs = VEHICLE_V3_SERVICE_DISPLAY_MS;
static uint32_t v3TrackerLastFrameAssertMs = 0;
static uint32_t v3TrackerButtonPressedSinceMs = 0;
static uint32_t v3TrackerButtonHighSinceMs = 0;
static bool v3TrackerButtonWasPressed = false;
static bool v3TrackerOpenedServiceThisPress = false;
static bool v3TrackerLongPressHandled = false;
static uint8_t v3TrackerServicePage = VEHICLE_V3_PAGE_STATUS;
static char v3TrackerBanner[160];

extern "C" void meshtasticVehiclePhoneContact();

static bool v3TrackerPolicyEnabled()
{
    return config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER;
}

static gpio_num_t v3TrackerButtonPin()
{
#ifdef BUTTON_PIN
    return (gpio_num_t)(config.device.button_gpio ? config.device.button_gpio : BUTTON_PIN);
#else
    return GPIO_NUM_NC;
#endif
}

static bool v3TrackerLowBattery()
{
    if (!powerStatus || !powerStatus->getHasBattery())
        return false;
    const uint8_t percent = powerStatus->getBatteryChargePercent();
    return percent > 0 && percent <= VEHICLE_V3_LOW_BATTERY_PERCENT;
}

static bool v3TrackerPositionKnown()
{
    return nodeDB && nodeDB->hasLocalPositionSinceBoot();
}

static bool v3TrackerDisplayWindowActive()
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

static void v3TrackerBluetoothOn()
{
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
    if (!nimbleBluetooth || !nimbleBluetooth->isActive()) {
        LOG_INFO("Tracker service: initialize BLE");
        setBluetoothEnable(true);
    }
#endif
}

static void v3TrackerBluetoothOff()
{
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
    if (nimbleBluetooth && nimbleBluetooth->isActive()) {
        LOG_DEBUG("Tracker service: deinit BLE outside service window");
        nimbleBluetooth->deinit();
    }
#endif
}

static unsigned v3TrackerDisplayAge(uint32_t age)
{
    return age == UINT32_MAX ? 9999U : (unsigned)age;
}

static void drawV3TrackerServiceFrame(OLEDDisplay *display, OLEDDisplayUiState *state, int16_t x, int16_t y)
{
    if (!display)
        return;

    display->clear();
    display->setTextAlignment(TEXT_ALIGN_CENTER);

    char lines[4][64] = {};
    uint8_t lineCount = 0;
    const char *p = v3TrackerBanner;
    while (*p && lineCount < 4) {
        size_t len = 0;
        while (p[len] && p[len] != '\n' && len < sizeof(lines[0]) - 1)
            len++;
        memcpy(lines[lineCount], p, len);
        lines[lineCount][len] = '\0';
        lineCount++;
        p += len;
        if (*p == '\n')
            p++;
    }

    const int titleHeight = FONT_HEIGHT_MEDIUM;
    const int bodyHeight = FONT_HEIGHT_SMALL;
    const int spacing = 3;
    int totalHeight = lineCount ? titleHeight : 0;
    if (lineCount > 1)
        totalHeight += (lineCount - 1) * (bodyHeight + spacing);
    int top = (display->getHeight() - totalHeight) / 2;
    if (top < 0)
        top = 0;

    for (uint8_t i = 0; i < lineCount; i++) {
        display->setFont(i == 0 ? FONT_MEDIUM : FONT_SMALL);
        display->drawString(display->getWidth() / 2 + x, top + y, lines[i]);
        top += (i == 0 ? titleHeight : bodyHeight) + spacing;
    }

    // Keep the Meshtastic pairing PIN visible above our exclusive service page.
    if (graphics::NotificationRenderer::current_notification_type == graphics::notificationTypeEnum::pairing_pin)
        graphics::NotificationRenderer::drawBannercallback(display, state);
}

static void v3TrackerAssertFrame()
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
}

static void v3TrackerBuildPage()
{
    unsigned battery = 0;
    if (powerStatus && powerStatus->getHasBattery())
        battery = powerStatus->getBatteryChargePercent();

    switch ((VehicleV3ServicePage)v3TrackerServicePage) {
    case VEHICLE_V3_PAGE_STATUS:
        snprintf(v3TrackerBanner, sizeof(v3TrackerBanner), "TRACKER SERVICE\nBAT %u%%  GPS %s\nSHORT: NEXT\nBT SERVICE", battery,
                 v3TrackerPositionKnown() ? "FIX" : "WAIT");
        break;
    case VEHICLE_V3_PAGE_DIAG:
        snprintf(v3TrackerBanner, sizeof(v3TrackerBanner), "DIAG GPS %s\nFIX %us TTFF %us\nSENSOR %s M%u",
                 v3TrackerPositionKnown() ? "FIX" : "WAIT", v3TrackerDisplayAge(trackerLastFixAgeSecs()),
                 (unsigned)(trackerLearnedTtffMs() / 1000UL), trackerMotionSensorStatus(),
                 (unsigned)trackerMotionSensorMissedMovementEvents());
        break;
    case VEHICLE_V3_PAGE_VERSION:
        snprintf(v3TrackerBanner, sizeof(v3TrackerBanner), "%s\nBUILD %.8s\nUP %umin %s", JARNSEN_FIRMWARE_VERSION,
                 JARNSEN_BUILD_SHA, (unsigned)(millis() / 60000UL), trackerBootWakeReason());
        break;
    case VEHICLE_V3_PAGE_MOTION:
        snprintf(v3TrackerBanner, sizeof(v3TrackerBanner), "MOTION %s\n%u PULSES / %us\nLONG: CHANGE",
                 trackerMotionSensitivityName(), (unsigned)trackerMotionConfirmCount(),
                 (unsigned)(trackerMotionConfirmWindowMs() / 1000UL));
        break;
    case VEHICLE_V3_PAGE_DISTANCE:
        snprintf(v3TrackerBanner, sizeof(v3TrackerBanner), "MIN DISTANCE\n%u m\nLONG: CHANGE", (unsigned)trackerSmartDistanceM());
        break;
    case VEHICLE_V3_PAGE_INTERVAL:
        snprintf(v3TrackerBanner, sizeof(v3TrackerBanner), "MIN INTERVAL\n%u s\nLONG: CHANGE", (unsigned)trackerSmartIntervalSecs());
        break;
    case VEHICLE_V3_PAGE_PARK:
        snprintf(v3TrackerBanner, sizeof(v3TrackerBanner), "PARK UPDATE\n%u min / eff %us\nLONG: CHANGE",
                 (unsigned)trackerParkIntervalMinutes(), (unsigned)trackerEffectiveParkIntervalSecs());
        break;
    default:
        v3TrackerServicePage = VEHICLE_V3_PAGE_STATUS;
        v3TrackerBuildPage();
        break;
    }
}

static void v3TrackerShowPage()
{
    if (!screen || !v3TrackerServiceActive)
        return;

    v3TrackerBuildPage();
    v3TrackerDisplayStartedMs = millis();
    v3TrackerDisplayWindowMs = v3TrackerLowBattery() ? VEHICLE_V3_LOW_BATTERY_DISPLAY_MS : VEHICLE_V3_SERVICE_DISPLAY_MS;
    v3TrackerDisplayVisible = true;
    v3TrackerLastFrameAssertMs = 0;
    if (v3TrackerBootHandoffComplete)
        v3TrackerAssertFrame();
    LOG_DEBUG("Tracker service: display window opened");
}

static void v3TrackerChangeSetting()
{
    switch ((VehicleV3ServicePage)v3TrackerServicePage) {
    case VEHICLE_V3_PAGE_MOTION:
        trackerCycleMotionSensitivity();
        break;
    case VEHICLE_V3_PAGE_DISTANCE:
        trackerCycleSmartDistance();
        break;
    case VEHICLE_V3_PAGE_INTERVAL:
        trackerCycleSmartInterval();
        break;
    case VEHICLE_V3_PAGE_PARK:
        trackerCycleParkInterval();
        break;
    default:
        return;
    }
    v3TrackerShowPage();
}

static void v3TrackerStartService()
{
    const uint32_t now = millis();
    v3TrackerServiceActive = true;
    v3TrackerServiceStartedMs = now;
    v3TrackerServiceLastActivityMs = now;
    v3TrackerServicePage = VEHICLE_V3_PAGE_STATUS;
    v3TrackerDisplayVisible = false;
    v3TrackerLastFrameAssertMs = 0;

    // Keep power saving ON exactly like the V3 repeater. The preflight sleep
    // observer below vetoes hardware light sleep only while service is active.
    config.power.is_power_saving = true;
    config.bluetooth.enabled = true;
    v3TrackerBluetoothOn();
    v3TrackerShowPage();

    LOG_INFO("Tracker service: GPIO0 opened display/Bluetooth; idle=%us hard-cap=%us power-save=%s",
             (unsigned)(VEHICLE_V3_SERVICE_IDLE_MS / 1000UL), (unsigned)(VEHICLE_V3_SERVICE_MAX_MS / 1000UL),
             config.power.is_power_saving ? "on" : "off");
}

static void v3TrackerStopService()
{
    if (!v3TrackerServiceActive)
        return;

    v3TrackerBluetoothOff();
    config.bluetooth.enabled = false;
    config.power.is_power_saving = true;
    trackerApplyPositionSettings();

    v3TrackerDisplayVisible = false;
    v3TrackerLastFrameAssertMs = 0;
    v3TrackerServiceActive = false;
    if (screen && v3TrackerServiceFrameActive) {
        screen->endAlert();
        v3TrackerServiceFrameActive = false;
    }
    if (screen && screen->isScreenOn())
        screen->setOn(false);
    LOG_INFO("Tracker service: window complete; Bluetooth/display off, autonomous power saving restored");
}

static bool v3TrackerBootWasUserWake()
{
    const esp_sleep_wakeup_cause_t cause = esp_sleep_get_wakeup_cause();
    if (cause == ESP_SLEEP_WAKEUP_EXT1)
        return true;
#if defined(ESP_SLEEP_WAKEUP_GPIO)
    if (cause == ESP_SLEEP_WAKEUP_GPIO)
        return true;
#endif
    return false;
}

class V3TrackerPreflightSleepObserver : public Observer<void *>
{
  protected:
    int onNotify(void *) override
    {
        if (!v3TrackerPolicyEnabled())
            return 0;
        return v3TrackerServiceActive ? 1 : 0;
    }
};

static V3TrackerPreflightSleepObserver v3TrackerPreflightSleepObserver;
static bool v3TrackerSleepObserverInstalled = false;

class VehicleV3StyleServiceThread : public concurrency::OSThread
{
  public:
    VehicleV3StyleServiceThread() : concurrency::OSThread("VehicleServiceV3") {}

  protected:
    int32_t runOnce() override
    {
        if (!v3TrackerPolicyEnabled())
            return 30000;

        const uint32_t now = millis();

        if (!v3TrackerBootHandoffComplete && graphics::isBootScreenComplete()) {
            v3TrackerBootHandoffComplete = true;
            LOG_INFO("TAK_TRACKER: Meshtastic boot screen complete; custom display ownership active");
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
                    LOG_DEBUG("TAK_TRACKER: GPIO0 short press -> page %u/%u",
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

        const bool hardCapReached = (uint32_t)(now - v3TrackerServiceStartedMs) >= (uint32_t)VEHICLE_V3_SERVICE_MAX_MS;
        const bool idleExpired = (uint32_t)(now - v3TrackerServiceLastActivityMs) >= (uint32_t)VEHICLE_V3_SERVICE_IDLE_MS;
        if (hardCapReached || idleExpired) {
            v3TrackerStopService();
            return 50;
        }

        const uint32_t frameNow = millis();
        if (v3TrackerDisplayVisible && v3TrackerBootHandoffComplete &&
            (v3TrackerLastFrameAssertMs == 0 ||
             (uint32_t)(frameNow - v3TrackerLastFrameAssertMs) >= (uint32_t)VEHICLE_V3_FRAME_REASSERT_MS)) {
            // Low-rate recovery only; page changes themselves never power-cycle
            // the TFT. This also restores our frame after a pairing overlay.
            v3TrackerAssertFrame();
        }

        const uint32_t displayNow = millis();
        if (v3TrackerDisplayVisible &&
            (uint32_t)(displayNow - v3TrackerDisplayStartedMs) >= v3TrackerDisplayWindowMs) {
            v3TrackerDisplayVisible = false;
            if (screen && screen->isScreenOn())
                screen->setOn(false);
            LOG_DEBUG("Tracker service: display window closed");
        }

        return 10;
    }
};

static VehicleV3StyleServiceThread *vehicleV3StyleServiceThread = nullptr;

void setupVehicleServicePolicyV3Style()
{
    if (!v3TrackerPolicyEnabled() || vehicleV3StyleServiceThread)
        return;

    trackerServiceSettingsInit();
    const gpio_num_t button = v3TrackerButtonPin();
    if (button != GPIO_NUM_NC)
        pinMode(button, INPUT_PULLUP);

    if (!v3TrackerSleepObserverInstalled) {
        v3TrackerPreflightSleepObserver.observe(&preflightSleep);
        v3TrackerSleepObserverInstalled = true;
    }

    config.power.is_power_saving = true;
    config.bluetooth.enabled = false;
    v3TrackerBluetoothOff();

    // Leave the TFT alone until Screen reports that the real Meshtastic boot
    // logo has completed. The policy thread performs the handoff afterwards.
    vehicleV3StyleServiceThread = new VehicleV3StyleServiceThread();

    if (v3TrackerBootWasUserWake()) {
        v3TrackerStartService();
        v3TrackerOpenedServiceThisPress = true;
        v3TrackerButtonWasPressed = button != GPIO_NUM_NC && digitalRead(button) == LOW;
        v3TrackerButtonPressedSinceMs = millis();
    }

    LOG_INFO("Tracker V1.1 TAK_TRACKER V3-style service enabled: power-save on, exclusive pages, BLE only via GPIO0");
}

#endif // HELTEC_TRACKER_V1_1 && VEHICLE_MOTION_WAKE_PIN
