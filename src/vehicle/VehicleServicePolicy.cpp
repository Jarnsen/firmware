#include "configuration.h"

#if defined(HELTEC_TRACKER_V1_1) && defined(VEHICLE_MOTION_WAKE_PIN)

#include "JarnsenBuildInfo.h"
#include "NodeDB.h"
#include "PowerFSM.h"
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

#include <cstdio>
#include <esp_sleep.h>

#ifndef VEHICLE_SERVICE_MODE_MS
#define VEHICLE_SERVICE_MODE_MS (120UL * 1000UL)
#endif

#ifndef VEHICLE_SERVICE_MAX_MS
#define VEHICLE_SERVICE_MAX_MS (15UL * 60UL * 1000UL)
#endif

#ifndef VEHICLE_SERVICE_DISPLAY_MS
#define VEHICLE_SERVICE_DISPLAY_MS (20UL * 1000UL)
#endif

#ifndef VEHICLE_LOW_BATTERY_DISPLAY_MS
#define VEHICLE_LOW_BATTERY_DISPLAY_MS (10UL * 1000UL)
#endif

#ifndef VEHICLE_SERVICE_KEEPALIVE_MS
#define VEHICLE_SERVICE_KEEPALIVE_MS (45UL * 1000UL)
#endif

#ifndef VEHICLE_LOW_BATTERY_PERCENT
#define VEHICLE_LOW_BATTERY_PERCENT 20U
#endif

#ifndef VEHICLE_MENU_LONG_PRESS_MS
#define VEHICLE_MENU_LONG_PRESS_MS 1200UL
#endif

enum VehicleServicePage : uint8_t {
    VEHICLE_PAGE_STATUS = 0,
    VEHICLE_PAGE_DIAG,
    VEHICLE_PAGE_VERSION,
    VEHICLE_PAGE_MOTION,
    VEHICLE_PAGE_DISTANCE,
    VEHICLE_PAGE_INTERVAL,
    VEHICLE_PAGE_PARK,
    VEHICLE_PAGE_COUNT,
};

static bool policyInitialized = false;
static bool serviceModeActive = false;
static bool serviceSavedPowerSaving = true;
static uint32_t serviceModeStartedMs = 0;
static uint32_t serviceModeLastActivityMs = 0;
static uint32_t displayStartedMs = 0;
static uint32_t displayWindowMs = VEHICLE_SERVICE_DISPLAY_MS;
static uint32_t lastServiceKeepaliveMs = 0;
static bool buttonWasPressed = false;
static bool openedServiceThisPress = false;
static bool longPressHandled = false;
static uint32_t buttonPressedSinceMs = 0;
static uint8_t servicePage = VEHICLE_PAGE_STATUS;
static char serviceBanner[160];
static bool serviceFrameActive = false;
static bool pairingPinWasVisible = false;

static bool vehicleServicePolicyEnabled()
{
    return config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER;
}

static gpio_num_t vehicleUserButtonPin()
{
#ifdef BUTTON_PIN
    return (gpio_num_t)(config.device.button_gpio ? config.device.button_gpio : BUTTON_PIN);
#else
    return GPIO_NUM_NC;
#endif
}

static bool vehicleLowBattery()
{
    if (!powerStatus || !powerStatus->getHasBattery())
        return false;

    const uint8_t percent = powerStatus->getBatteryChargePercent();
    return percent > 0 && percent <= VEHICLE_LOW_BATTERY_PERCENT;
}

static bool vehiclePositionKnown()
{
    return nodeDB && nodeDB->hasLocalPositionSinceBoot();
}

static bool vehicleBleConnected()
{
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
    return nimbleBluetooth && nimbleBluetooth->isConnected();
#else
    return false;
#endif
}

static bool vehiclePairingPinVisible()
{
    return graphics::NotificationRenderer::current_notification_type == graphics::notificationTypeEnum::pairing_pin;
}

static unsigned displayAgeSeconds(uint32_t age)
{
    return age == UINT32_MAX ? 9999U : (unsigned)age;
}

static void drawVehicleServiceFrame(OLEDDisplay *display, OLEDDisplayUiState *, int16_t x, int16_t y)
{
    if (!display)
        return;

    display->clear();
    display->setTextAlignment(TEXT_ALIGN_CENTER);

    char lines[4][64] = {};
    uint8_t lineCount = 0;
    const char *p = serviceBanner;
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
}

static void stopVehicleServiceFrame()
{
    if (screen && serviceFrameActive)
        screen->endAlert();
    serviceFrameActive = false;
}

static void renderVehicleServicePage()
{
    if (!screen || !serviceModeActive)
        return;

    unsigned battery = 0;
    if (powerStatus && powerStatus->getHasBattery())
        battery = powerStatus->getBatteryChargePercent();

    switch ((VehicleServicePage)servicePage) {
    case VEHICLE_PAGE_STATUS:
        snprintf(serviceBanner, sizeof(serviceBanner), "Kfz SERVICE\nBAT %u%% GPS %s\nBT ON  SHORT>NEXT", battery,
                 vehiclePositionKnown() ? "FIX" : "WAIT");
        break;
    case VEHICLE_PAGE_DIAG:
        snprintf(serviceBanner, sizeof(serviceBanner), "DIAG GPS %s\nFIX %us TTFF %us\nSENSOR %s M%u",
                 vehiclePositionKnown() ? "FIX" : "WAIT", displayAgeSeconds(trackerLastFixAgeSecs()),
                 (unsigned)(trackerLearnedTtffMs() / 1000UL), trackerMotionSensorStatus(),
                 (unsigned)trackerMotionSensorMissedMovementEvents());
        break;
    case VEHICLE_PAGE_VERSION:
        snprintf(serviceBanner, sizeof(serviceBanner), "%s\nBUILD %.8s\nUP %umin %s", JARNSEN_FIRMWARE_VERSION,
                 JARNSEN_BUILD_SHA, (unsigned)(millis() / 60000UL), trackerBootWakeReason());
        break;
    case VEHICLE_PAGE_MOTION:
        snprintf(serviceBanner, sizeof(serviceBanner), "MOTION %s\n%u PULSES / %us\nLONG=CHANGE",
                 trackerMotionSensitivityName(), (unsigned)trackerMotionConfirmCount(),
                 (unsigned)(trackerMotionConfirmWindowMs() / 1000UL));
        break;
    case VEHICLE_PAGE_DISTANCE:
        snprintf(serviceBanner, sizeof(serviceBanner), "MIN DISTANCE\n%u m\nLONG=CHANGE", (unsigned)trackerSmartDistanceM());
        break;
    case VEHICLE_PAGE_INTERVAL:
        snprintf(serviceBanner, sizeof(serviceBanner), "MIN INTERVAL\n%u s\nLONG=CHANGE", (unsigned)trackerSmartIntervalSecs());
        break;
    case VEHICLE_PAGE_PARK:
        snprintf(serviceBanner, sizeof(serviceBanner), "PARK UPDATE\n%u min / eff %us\nLONG=CHANGE",
                 (unsigned)trackerParkIntervalMinutes(), (unsigned)trackerEffectiveParkIntervalSecs());
        break;
    default:
        servicePage = VEHICLE_PAGE_STATUS;
        renderVehicleServicePage();
        return;
    }

    displayStartedMs = millis();
    displayWindowMs = vehicleLowBattery() ? VEHICLE_LOW_BATTERY_DISPLAY_MS : VEHICLE_SERVICE_DISPLAY_MS;

    // Pairing PIN is operationally more important than the local menu. Release
    // the full-screen service frame while the Meshtastic pairing overlay is active.
    if (vehiclePairingPinVisible()) {
        pairingPinWasVisible = true;
        stopVehicleServiceFrame();
        screen->setOn(true);
        return;
    }

    screen->setOn(true);
    screen->startAlert(drawVehicleServiceFrame);
    serviceFrameActive = true;
}

static void changeVehicleServiceSetting()
{
    switch ((VehicleServicePage)servicePage) {
    case VEHICLE_PAGE_MOTION:
        trackerCycleMotionSensitivity();
        break;
    case VEHICLE_PAGE_DISTANCE:
        trackerCycleSmartDistance();
        break;
    case VEHICLE_PAGE_INTERVAL:
        trackerCycleSmartInterval();
        break;
    case VEHICLE_PAGE_PARK:
        trackerCycleParkInterval();
        break;
    default:
        return;
    }

    renderVehicleServicePage();
}

static void startVehicleServiceMode()
{
    if (!vehicleServicePolicyEnabled())
        return;

    trackerServiceSettingsInit();

    const uint32_t now = millis();
    serviceModeActive = true;
    serviceModeStartedMs = now;
    serviceModeLastActivityMs = now;
    lastServiceKeepaliveMs = now;
    servicePage = VEHICLE_PAGE_STATUS;
    pairingPinWasVisible = false;

    // Temporarily suspend the autonomous parked-sleep policy while the user is
    // intentionally servicing the unit. This prevents a vehicle that has just
    // become stationary from deep-sleeping in the middle of a settings session.
    serviceSavedPowerSaving = config.power.is_power_saving;
    config.power.is_power_saving = false;

    // Wake the normal power FSM and deliberately enable BLE. Saved Bluetooth
    // must remain enabled so its stack memory exists, but outside this service
    // window the policy forces the radio back off.
    powerFSM.trigger(EVENT_PRESS);
    if (config.bluetooth.enabled)
        setBluetoothEnable(true);
    else
        LOG_WARN("Vehicle service: Bluetooth disabled in saved config; enable it once so GPIO0 service can start BLE");

    renderVehicleServicePage();
    LOG_INFO("Vehicle service: GPIO0 opened Bluetooth/settings; %us idle timeout, %us hard cap",
             (unsigned)(VEHICLE_SERVICE_MODE_MS / 1000UL), (unsigned)(VEHICLE_SERVICE_MAX_MS / 1000UL));
}

static bool vehicleServiceStillActive(uint32_t now)
{
    if (!serviceModeActive)
        return false;

    const bool belowHardCap = (uint32_t)(now - serviceModeStartedMs) < (uint32_t)VEHICLE_SERVICE_MAX_MS;
    const bool belowIdleTimeout = (uint32_t)(now - serviceModeLastActivityMs) < (uint32_t)VEHICLE_SERVICE_MODE_MS;
    return belowHardCap && belowIdleTimeout;
}

static bool vehicleDisplayStillActive(uint32_t now)
{
    return serviceModeActive && (uint32_t)(now - displayStartedMs) < displayWindowMs;
}

static bool vehicleBootWasUserWake()
{
    const auto cause = esp_sleep_get_wakeup_cause();
    if (cause == ESP_SLEEP_WAKEUP_EXT1)
        return true;
#if defined(ESP_SLEEP_WAKEUP_GPIO)
    if (cause == ESP_SLEEP_WAKEUP_GPIO)
        return true;
#endif
    return false;
}

static void initializeVehicleServicePolicy()
{
    if (policyInitialized || !vehicleServicePolicyEnabled())
        return;

    policyInitialized = true;
    trackerServiceSettingsInit();

    const gpio_num_t button = vehicleUserButtonPin();
    if (button != GPIO_NUM_NC)
        pinMode(button, INPUT_PULLUP);

    if (vehicleBootWasUserWake()) {
        startVehicleServiceMode();
        // A button deep-sleep wake is itself the opening press; do not let its
        // release immediately advance the menu page.
        openedServiceThisPress = true;
        buttonWasPressed = button != GPIO_NUM_NC && digitalRead(button) == LOW;
        buttonPressedSinceMs = millis();
    } else {
        stopVehicleServiceFrame();
        setBluetoothEnable(false);
        if (screen)
            screen->setOn(false);
    }
}

class VehicleServicePolicyThread : public concurrency::OSThread
{
  public:
    VehicleServicePolicyThread() : concurrency::OSThread("VehicleService") {}

  protected:
    int32_t runOnce() override
    {
        if (!vehicleServicePolicyEnabled())
            return 30000;

        initializeVehicleServicePolicy();

        const uint32_t now = millis();
        const gpio_num_t button = vehicleUserButtonPin();

        if (button != GPIO_NUM_NC) {
            const bool pressed = digitalRead(button) == LOW;

            if (pressed) {
                if (buttonPressedSinceMs == 0)
                    buttonPressedSinceMs = now ? now : 1;

                if (!buttonWasPressed && (uint32_t)(now - buttonPressedSinceMs) >= 80U) {
                    buttonWasPressed = true;
                    openedServiceThisPress = false;
                    longPressHandled = false;

                    if (!serviceModeActive) {
                        startVehicleServiceMode();
                        openedServiceThisPress = true;
                    }
                }

                if (buttonWasPressed && serviceModeActive && !openedServiceThisPress && !longPressHandled &&
                    (uint32_t)(now - buttonPressedSinceMs) >= (uint32_t)VEHICLE_MENU_LONG_PRESS_MS) {
                    changeVehicleServiceSetting();
                    longPressHandled = true;
                }
            } else {
                if (buttonWasPressed && serviceModeActive && !openedServiceThisPress && !longPressHandled) {
                    servicePage = (uint8_t)((servicePage + 1U) % VEHICLE_PAGE_COUNT);
                    renderVehicleServicePage();
                }

                buttonWasPressed = false;
                openedServiceThisPress = false;
                longPressHandled = false;
                buttonPressedSinceMs = 0;
            }
        }

        // A live ATAK/Meshtastic BLE connection refreshes the idle timer. This
        // lets a real service session continue past two minutes without another
        // button press, while the 15-minute hard cap prevents an accidental
        // permanent battery drain.
        if (serviceModeActive && vehicleBleConnected())
            serviceModeLastActivityMs = now;

        if (vehicleServiceStillActive(now)) {
            if ((uint32_t)(now - lastServiceKeepaliveMs) >= (uint32_t)VEHICLE_SERVICE_KEEPALIVE_MS) {
                powerFSM.trigger(EVENT_PRESS);
                if (config.bluetooth.enabled)
                    setBluetoothEnable(true);
                lastServiceKeepaliveMs = now;
            }
        } else if (serviceModeActive) {
            serviceModeActive = false;
            pairingPinWasVisible = false;
            stopVehicleServiceFrame();
            setBluetoothEnable(false);
            config.power.is_power_saving = serviceSavedPowerSaving;
            trackerApplyPositionSettings();
            if (screen)
                screen->setOn(false);
            LOG_INFO("Vehicle service: Bluetooth/settings window complete; autonomous power saving restored");
        } else {
            // Normal TAK_TRACKER operation is autonomous; BLE is available only
            // after an intentional GPIO0 press.
            pairingPinWasVisible = false;
            stopVehicleServiceFrame();
            setBluetoothEnable(false);
        }

        if (screen && serviceModeActive) {
            const bool pairingPinVisible = vehiclePairingPinVisible();
            if (pairingPinVisible) {
                // startAlert() pauses overlays. Drop our service alert while the
                // pairing PIN exists so the PIN is guaranteed to be readable.
                pairingPinWasVisible = true;
                displayStartedMs = now;
                stopVehicleServiceFrame();
                screen->setOn(true);
            } else {
                if (pairingPinWasVisible) {
                    pairingPinWasVisible = false;
                    renderVehicleServicePage();
                }

                if (vehicleDisplayStillActive(now)) {
                    screen->setOn(true);
                } else {
                    stopVehicleServiceFrame();
                    screen->setOn(false);
                }
            }
        } else if (screen) {
            screen->setOn(false);
        }

        return 100;
    }
};

static VehicleServicePolicyThread *vehicleServicePolicyThread = nullptr;

void setupVehicleServicePolicy()
{
    if (vehicleServicePolicyThread == nullptr)
        vehicleServicePolicyThread = new VehicleServicePolicyThread();
}

#endif // HELTEC_TRACKER_V1_1 && VEHICLE_MOTION_WAKE_PIN