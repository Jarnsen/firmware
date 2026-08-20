#include "configuration.h"

#ifdef _VARIANT_HELTEC_V3

#include "NodeDB.h"
#include "PowerFSM.h"
#include "PowerStatus.h"
#include "graphics/Screen.h"
#include "main.h"
#include "target_specific.h"

#include <driver/gpio.h>
#include <esp_sleep.h>
#include <esp_system.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

#ifndef V3_SERVICE_IDLE_MS
#define V3_SERVICE_IDLE_MS (120UL * 1000UL)
#endif

#ifndef V3_SERVICE_MAX_MS
#define V3_SERVICE_MAX_MS (15UL * 60UL * 1000UL)
#endif

#ifndef V3_SERVICE_DISPLAY_MS
#define V3_SERVICE_DISPLAY_MS (20UL * 1000UL)
#endif

#ifndef V3_SERVICE_DEBOUNCE_MS
#define V3_SERVICE_DEBOUNCE_MS 250UL
#endif

static TaskHandle_t v3ServiceTaskHandle = nullptr;
static volatile bool v3ServiceButtonInterrupt = false;
static bool v3ServiceActive = false;
static bool v3ServiceSavedPowerSaving = true;
static uint32_t v3ServiceStartedMs = 0;
static uint32_t v3ServiceLastActivityMs = 0;
static uint32_t v3DisplayStartedMs = 0;
static uint32_t v3LastAcceptedButtonMs = 0;
static char v3ServiceBanner[128];

static bool v3RepeaterRoleEnabled()
{
    return config.device.role == meshtastic_Config_DeviceConfig_Role_ROUTER_LATE ||
           config.device.role == meshtastic_Config_DeviceConfig_Role_REPEATER;
}

static uint32_t repeaterHealthIntervalSecs()
{
    if (!nodeDB)
        return 3600UL;

    uint32_t x = nodeDB->getNodeNum();
    x ^= x >> 16;
    x *= 0x7feb352dU;
    x ^= x >> 15;
    return 3300UL + (x % 301U);
}

static bool v3BleConnected()
{
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
    return nimbleBluetooth && nimbleBluetooth->isConnected();
#else
    return false;
#endif
}

static void showV3ServiceStatus()
{
    if (!screen)
        return;

    unsigned battery = 0;
    if (powerStatus && powerStatus->getHasBattery())
        battery = powerStatus->getBatteryChargePercent();

    const char *role = config.device.role == meshtastic_Config_DeviceConfig_Role_ROUTER_LATE ? "ROUTER_LATE" : "REPEATER";
    const unsigned remaining = v3ServiceActive
                                   ? (unsigned)((V3_SERVICE_IDLE_MS -
                                                 min((uint32_t)V3_SERVICE_IDLE_MS,
                                                     (uint32_t)(millis() - v3ServiceLastActivityMs))) /
                                                1000UL)
                                   : 0U;

    snprintf(v3ServiceBanner, sizeof(v3ServiceBanner), "V3 SERVICE\n%s BAT %u%%\nBT ON %us UP %umin", role, battery,
             remaining, (unsigned)(millis() / 60000UL));
    v3DisplayStartedMs = millis();
    screen->setOn(true);
    screen->showSimpleBanner(v3ServiceBanner, V3_SERVICE_DISPLAY_MS);
}

static void startV3ServiceMode()
{
    const uint32_t now = millis();

    if (!v3ServiceActive) {
        v3ServiceActive = true;
        v3ServiceStartedMs = now;
        v3ServiceSavedPowerSaving = config.power.is_power_saving;
        config.power.is_power_saving = false;

        // Bluetooth remains compiled and configured so its stack is available,
        // but the radio is forced off outside this intentional service window.
        config.bluetooth.enabled = true;
        powerFSM.trigger(EVENT_PRESS);
        setBluetoothEnable(true);

        LOG_INFO("Heltec V3 service: GPIO0 opened display/Bluetooth; idle=%us hard-cap=%us",
                 (unsigned)(V3_SERVICE_IDLE_MS / 1000UL), (unsigned)(V3_SERVICE_MAX_MS / 1000UL));
    }

    // A further press during service refreshes the idle window and display.
    v3ServiceLastActivityMs = now;
    showV3ServiceStatus();
}

static void stopV3ServiceMode()
{
    if (!v3ServiceActive)
        return;

    v3ServiceActive = false;
    setBluetoothEnable(false);
    config.power.is_power_saving = v3ServiceSavedPowerSaving;

    if (screen)
        screen->setOn(false);

    LOG_INFO("Heltec V3 service: window complete; Bluetooth/display off, repeater power policy restored");
}

static void IRAM_ATTR v3ServiceButtonISR()
{
    v3ServiceButtonInterrupt = true;

    BaseType_t higherPriorityTaskWoken = pdFALSE;
    if (v3ServiceTaskHandle)
        vTaskNotifyGiveFromISR(v3ServiceTaskHandle, &higherPriorityTaskWoken);
    if (higherPriorityTaskWoken == pdTRUE)
        portYIELD_FROM_ISR();
}

static void v3ServiceTask(void *)
{
    for (;;) {
        // No periodic wakeups in normal repeater operation. During service only,
        // wake twice per second to maintain the idle/hard-cap timers and BLE link.
        const TickType_t waitTicks = v3ServiceActive ? pdMS_TO_TICKS(500) : portMAX_DELAY;
        ulTaskNotifyTake(pdTRUE, waitTicks);

        const uint32_t now = millis();

        if (v3ServiceButtonInterrupt) {
            v3ServiceButtonInterrupt = false;
            if ((uint32_t)(now - v3LastAcceptedButtonMs) >= (uint32_t)V3_SERVICE_DEBOUNCE_MS) {
                v3LastAcceptedButtonMs = now ? now : 1;
                startV3ServiceMode();
            }
        }

        if (!v3ServiceActive)
            continue;

        // A real phone connection keeps the two-minute idle window alive, but
        // never beyond the absolute 15-minute cap.
        if (v3BleConnected())
            v3ServiceLastActivityMs = now;

        const bool hardCapReached = (uint32_t)(now - v3ServiceStartedMs) >= (uint32_t)V3_SERVICE_MAX_MS;
        const bool idleExpired = (uint32_t)(now - v3ServiceLastActivityMs) >= (uint32_t)V3_SERVICE_IDLE_MS;
        if (hardCapReached || idleExpired) {
            stopV3ServiceMode();
            continue;
        }

        // The display is intentionally much shorter than the BLE service window.
        if (screen && (uint32_t)(now - v3DisplayStartedMs) >= (uint32_t)V3_SERVICE_DISPLAY_MS)
            screen->setOn(false);
    }
}

static void setupV3ServiceButton()
{
#ifdef BUTTON_PIN
    const gpio_num_t button = (gpio_num_t)BUTTON_PIN;
    pinMode(BUTTON_PIN, INPUT_PULLUP);

    if (!v3ServiceTaskHandle) {
        xTaskCreate(v3ServiceTask, "V3Service", 4096, nullptr, 1, &v3ServiceTaskHandle);
        attachInterrupt(digitalPinToInterrupt(BUTTON_PIN), v3ServiceButtonISR, FALLING);
    }

#if defined(ARCH_ESP32)
    // Keep GPIO0 able to wake the ESP32-S3 from light sleep without introducing
    // a periodic polling timer. LoRa IRQ wake remains enabled independently.
    gpio_wakeup_enable(button, GPIO_INTR_LOW_LEVEL);
    esp_sleep_enable_gpio_wakeup();
#endif
#endif
}

// Heltec V3 infrastructure/repeater policy.
//
// ROUTER_LATE is preferred because current Meshtastic deprecates the old
// REPEATER role. Both profiles use light sleep so the SX1262 remains available
// as an immediate LoRa wake source. GPIO0 opens a temporary local service mode.
void lateInitVariant()
{
    if (!v3RepeaterRoleEnabled()) {
        LOG_INFO("Heltec V3 repeater policy inactive (role=%d); use ROUTER_LATE (recommended) or REPEATER", (int)config.device.role);
        return;
    }

    // Keep the BLE stack available for intentional GPIO0 servicing. The actual
    // Bluetooth radio remains OFF during unattended repeater operation.
    config.bluetooth.enabled = true;
    config.power.wait_bluetooth_secs = 1;
    config.network.wifi_enabled = false;
    config.display.screen_on_secs = 1;
    config.device.led_heartbeat_disabled = true;

    config.power.is_power_saving = true;
    config.power.min_wake_secs = 1;
    config.power.ls_secs = 3600;

    moduleConfig.telemetry.device_telemetry_enabled = true;
    moduleConfig.telemetry.device_update_interval = repeaterHealthIntervalSecs();

    if (config.device.role == meshtastic_Config_DeviceConfig_Role_REPEATER)
        config.device.rebroadcast_mode = meshtastic_Config_DeviceConfig_RebroadcastMode_ALL_SKIP_DECODING;

    setBluetoothEnable(false);
    if (screen)
        screen->setOn(false);

    setupV3ServiceButton();

    LOG_INFO("Heltec V3 %s duty: LS + LoRa wake, BLE/WiFi/display/LED off, GPIO0 service, health=%us, resetReason=%d",
             config.device.role == meshtastic_Config_DeviceConfig_Role_ROUTER_LATE ? "ROUTER_LATE repeater" : "legacy REPEATER",
             (unsigned)moduleConfig.telemetry.device_update_interval, (int)esp_reset_reason());
}

#endif // _VARIANT_HELTEC_V3
