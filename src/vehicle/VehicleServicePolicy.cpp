#include "configuration.h"

#if (defined(HELTEC_V3) || defined(HELTEC_TRACKER_V1_1)) && defined(VEHICLE_MOTION_WAKE_PIN)

#include "NodeDB.h"
#include "PowerFSM.h"
#include "PowerStatus.h"
#include "concurrency/OSThread.h"
#include "graphics/Screen.h"
#include "main.h"
#include "sleep.h"
#include "target_specific.h"

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

static bool serviceModeActive = false;
static uint32_t serviceModeStartedMs = 0;
static uint32_t displayStartedMs = 0;
static uint32_t displayWindowMs = VEHICLE_SERVICE_DISPLAY_MS;
static uint32_t lastServiceKeepaliveMs = 0;
static bool buttonWasPressed = false;
static uint32_t buttonPressedSinceMs = 0;
static char serviceBanner[128];

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

static void updateServiceBanner()
{
    unsigned battery = 0;
    if (powerStatus && powerStatus->getHasBattery())
        battery = powerStatus->getBatteryChargePercent();

    const bool motionPinHealthy = digitalRead(VEHICLE_MOTION_WAKE_PIN) != LOW;
#if defined(HELTEC_TRACKER_V1_1)
    const char *positionSource = vehiclePositionKnown() ? "GPS FIX" : "GPS WAIT";
#else
    const char *positionSource = vehiclePositionKnown() ? "PHONE POS" : "NO POS";
#endif

    snprintf(serviceBanner, sizeof(serviceBanner), "VEHICLE SERVICE\nBAT %u%%  %s\n%s  MOT %s", battery, positionSource,
             vehicleWakeLabel(), motionPinHealthy ? "OK" : "ACTIVE");
}

static void startVehicleServiceMode()
{
    const uint32_t now = millis();
    serviceModeActive = true;
    serviceModeStartedMs = now;
    displayStartedMs = now;
    displayWindowMs = vehicleLowBattery() ? VEHICLE_LOW_BATTERY_DISPLAY_MS : VEHICLE_SERVICE_DISPLAY_MS;
    lastServiceKeepaliveMs = now;

    if (config.bluetooth.enabled)
        setBluetoothEnable(true);

    if (screen) {
        updateServiceBanner();
        screen->setOn(true);
        screen->showSimpleBanner(serviceBanner, displayWindowMs);
    }

    LOG_INFO("Vehicle service: user button service window started for %us%s",
             (unsigned)(VEHICLE_SERVICE_MODE_MS / 1000UL), vehicleLowBattery() ? " (low battery)" : "");
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

class VehicleServicePolicyThread : public concurrency::OSThread
{
  public:
    VehicleServicePolicyThread() : concurrency::OSThread("VehicleService")
    {
        const gpio_num_t button = vehicleUserButtonPin();
        if (button != GPIO_NUM_NC)
            pinMode(button, INPUT_PULLUP);

        if (vehicleBootWasUserWake())
            startVehicleServiceMode();
        else if (screen)
            screen->setOn(false);
    }

  protected:
    int32_t runOnce() override
    {
        const uint32_t now = millis();
        const gpio_num_t button = vehicleUserButtonPin();

        if (button != GPIO_NUM_NC) {
            const bool pressed = digitalRead(button) == LOW;
            if (pressed && !buttonWasPressed) {
                if (buttonPressedSinceMs == 0)
                    buttonPressedSinceMs = now ? now : 1;
                else if ((uint32_t)(now - buttonPressedSinceMs) >= 80U) {
                    buttonWasPressed = true;
                    startVehicleServiceMode();
                }
            } else if (!pressed) {
                buttonWasPressed = false;
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
            LOG_INFO("Vehicle service: two-minute user service window complete");
        }

        if (screen) {
            if (vehicleDisplayStillActive(now))
                screen->setOn(true);
            else
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

#endif
