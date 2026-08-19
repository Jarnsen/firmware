#include "configuration.h"

#if defined(HELTEC_TRACKER_V1_1) && defined(VEHICLE_MOTION_WAKE_PIN)

#include "NodeDB.h"
#include "PowerFSM.h"
#include "PowerStatus.h"
#include "TrackerServiceSettings.h"
#include "concurrency/OSThread.h"
#include "graphics/Screen.h"
#include "main.h"
#include "sleep.h"
#include "target_specific.h"

#include <cstdio>
#include <esp_sleep.h>

#ifndef VEHICLE_SERVICE_MODE_MS
#define VEHICLE_SERVICE_MODE_MS (120UL * 1000UL)
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
    VEHICLE_PAGE_MOTION,
    VEHICLE_PAGE_DISTANCE,
    VEHICLE_PAGE_INTERVAL,
    VEHICLE_PAGE_PARK,
    VEHICLE_PAGE_COUNT,
};

static bool policyInitialized = false;
static bool serviceModeActive = false;
static uint32_t serviceModeStartedMs = 0;
static uint32_t displayStartedMs = 0;
static uint32_t displayWindowMs = VEHICLE_SERVICE_DISPLAY_MS;
static uint32_t lastServiceKeepaliveMs = 0;
static bool buttonWasPressed = false;
static bool openedServiceThisPress = false;
static bool longPressHandled = false;
static uint32_t buttonPressedSinceMs = 0;
static uint8_t servicePage = VEHICLE_PAGE_STATUS;
static char serviceBanner[160];

static bool vehicleServicePolicyEnabled()
{
    return config.power.is_power_saving && config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER;
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

static const char *vehicleWakeLabel()
{
    switch (esp_sleep_get_wakeup_cause()) {
    case ESP_SLEEP_WAKEUP_EXT0:
        return "MOTION";
    case ESP_SLEEP_WAKEUP_EXT1:
        return "BUTTON";
    case ESP_SLEEP_WAKEUP_TIMER:
        return "TIMER";
#if defined(ESP_SLEEP_WAKEUP_GPIO)
    case ESP_SLEEP_WAKEUP_GPIO:
        return "BUTTON";
#endif
    default:
        return "BOOT";
    }
}

static bool vehiclePositionKnown()
{
    return nodeDB && nodeDB->hasLocalPositionSinceBoot();
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
    case VEHICLE_PAGE_MOTION:
        snprintf(serviceBanner, sizeof(serviceBanner), "MOTION %s\n%u PULSES / %.1fs\nLONG=CHANGE",
                 trackerMotionSensitivityName(), (unsigned)trackerMotionConfirmCount(),
                 trackerMotionConfirmWindowMs() / 1000.0f);
        break;
    case VEHICLE_PAGE_DISTANCE:
        snprintf(serviceBanner, sizeof(serviceBanner), "MIN DISTANCE\n%u m\nLONG=CHANGE", (unsigned)trackerSmartDistanceM());
        break;
    case VEHICLE_PAGE_INTERVAL:
        snprintf(serviceBanner, sizeof(serviceBanner), "MIN INTERVAL\n%u s\nLONG=CHANGE", (unsigned)trackerSmartIntervalSecs());
        break;
    case VEHICLE_PAGE_PARK:
        snprintf(serviceBanner, sizeof(serviceBanner), "PARK UPDATE\n%u min\nLONG=CHANGE", (unsigned)trackerParkIntervalMinutes());
        break;
    default:
        servicePage = VEHICLE_PAGE_STATUS;
        return renderVehicleServicePage();
    }

    displayStartedMs = millis();
    displayWindowMs = vehicleLowBattery() ? VEHICLE_LOW_BATTERY_DISPLAY_MS : VEHICLE_SERVICE_DISPLAY_MS;
    screen->setOn(true);
    screen->showSimpleBanner(serviceBanner, displayWindowMs);
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
    lastServiceKeepaliveMs = now;
    servicePage = VEHICLE_PAGE_STATUS;

    // Wake the normal power FSM and deliberately enable BLE. Saved Bluetooth
    // must remain enabled so its stack memory exists, but outside this service
    // window the policy forces the radio back off.
    powerFSM.trigger(EVENT_PRESS);
    if (config.bluetooth.enabled)
        setBluetoothEnable(true);
    else
        LOG_WARN("Vehicle service: Bluetooth disabled in saved config; enable it once so GPIO0 service can start BLE");

    renderVehicleServicePage();
    LOG_INFO("Vehicle service: GPIO0 opened Bluetooth/settings for %us", (unsigned)(VEHICLE_SERVICE_MODE_MS / 1000UL));
}

static bool vehicleServiceStillActive(uint32_t now)
{
    return serviceModeActive && (uint32_t)(now - serviceModeStartedMs) < (uint32_t)VEHICLE_SERVICE_MODE_MS;
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
        buttonWasPressed = digitalRead(button) == LOW;
        buttonPressedSinceMs = millis();
    } else {
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

        if (vehicleServiceStillActive(now)) {
            if ((uint32_t)(now - lastServiceKeepaliveMs) >= (uint32_t)VEHICLE_SERVICE_KEEPALIVE_MS) {
                powerFSM.trigger(EVENT_PRESS);
                if (config.bluetooth.enabled)
                    setBluetoothEnable(true);
                lastServiceKeepaliveMs = now;
            }
        } else if (serviceModeActive) {
            serviceModeActive = false;
            setBluetoothEnable(false);
            if (screen)
                screen->setOn(false);
            LOG_INFO("Vehicle service: Bluetooth/settings window complete");
        } else {
            // Normal TAK_TRACKER operation is autonomous; BLE is available only
            // after an intentional GPIO0 press.
            setBluetoothEnable(false);
        }

        if (screen) {
            if (vehicleDisplayStillActive(now))
                screen->setOn(true);
            else if (!serviceModeActive)
                screen->setOn(false);
            else if ((uint32_t)(now - displayStartedMs) >= displayWindowMs)
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
