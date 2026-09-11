#include "jarnsen/core/runtime/JarnsenRuntimePolicy.h"

#include "jarnsen/adapters/JarnsenLegacyStatusBridge.h"
#include "jarnsen/core/runtime/JarnsenDroneRepeaterPolicy.h"
#include "jarnsen/core/status/JarnsenStatusProvider.h"
#include "FSCommon.h"
#include "SPILock.h"
#include "concurrency/LockGuard.h"
#include "configuration.h"
#include "jarnsen/core/build/JarnsenBuildInfo.h"
#include "jarnsen/core/mesh/JarnsenRadioProfiles.h"
#include "jarnsen/core/service/JarnsenDiagnosticLog.h"
#include "main.h"
#include "sleep.h"

#include <Arduino.h>

#ifdef ARCH_ESP32
#include <driver/rtc_io.h>
#include <esp_sleep.h>
#endif

namespace jarnsen
{
namespace
{

#if defined(HELTEC_TRACKER_V1_1) || defined(HELTEC_V3) || defined(_VARIANT_HELTEC_V3) || defined(HELTEC_V4) ||              \
    defined(SEEED_WIO_TRACKER_L1) || defined(TBEAM_V10) || defined(LILYGO_TBEAM_S3_CORE)
#define JARNSEN_RUNTIME_TARGET 1
#else
#define JARNSEN_RUNTIME_TARGET 0
#endif

#if JARNSEN_RUNTIME_TARGET
constexpr const char *RADIO_DEFAULTS_MARKER = "/prefs/jarnsen-radio-defaults-v1";
constexpr float JARNSEN_1_DEFAULT_MHZ = 915.625f;
constexpr float JARNSEN_2_DEFAULT_MHZ = 917.375f;
constexpr uint8_t FALLBACK_HOPS = 3U;

const char *platformLabel()
{
#if defined(ARCH_ESP32)
    return "esp32";
#elif defined(ARCH_NRF54L15)
    return "nrf54l15";
#elif defined(ARCH_NRF52)
    return "nrf52";
#else
    return "other";
#endif
}

int configuredUserButtonPin()
{
#ifdef BUTTON_PIN
    return config.device.button_gpio ? (int)config.device.button_gpio : (int)BUTTON_PIN;
#else
    return -1;
#endif
}

const char *bootWakeLabel()
{
#ifdef ARCH_ESP32
    switch (esp_sleep_get_wakeup_cause()) {
    case ESP_SLEEP_WAKEUP_EXT1:
        return "deep_ext1";
    case ESP_SLEEP_WAKEUP_TIMER:
        return "deep_timer";
    case ESP_SLEEP_WAKEUP_UNDEFINED:
        return "cold_or_reset";
    default:
        return "deep_other";
    }
#else
    // Nordic boards expose wake/reset state through a different platform path.
    // The shared diagnostics still record all post-boot button events so a
    // hardware wake can be correlated even when there is no ESP-style cause.
    return "platform_reset_or_wake";
#endif
}

bool radioDefaultsMigrated()
{
#ifdef FSCom
    return FSCom.exists(RADIO_DEFAULTS_MARKER);
#else
    return false;
#endif
}

bool writeRadioDefaultsMarker()
{
#ifdef FSCom
    concurrency::LockGuard guard(spiLock);
    File file = FSCom.open(RADIO_DEFAULTS_MARKER, FILE_O_WRITE);
    if (!file)
        return false;
    const uint8_t version = 1U;
    const bool ok = file.write(&version, 1U) == 1U;
    file.flush();
    file.close();
    return ok;
#else
    return false;
#endif
}

bool ensureRadioProfileDefaults()
{
    // This is a one-time migration. Existing slots are never overwritten, and
    // after the marker is present an intentionally deleted slot stays missing.
    if (radioDefaultsMigrated())
        return true;
    if (!config.has_lora)
        return false;

    if (!radioProfileSlotExists(RadioProfileSlot::STANDARD) && !radioProfileCaptureStandard())
        return false;

    const auto preset = config.lora.use_preset ? config.lora.modem_preset
                                               : meshtastic_Config_LoRaConfig_ModemPreset_LONG_FAST;
    const uint8_t hops = config.lora.hop_limit >= 1U && config.lora.hop_limit <= 20U ? config.lora.hop_limit : FALLBACK_HOPS;

    if (!radioProfileSlotExists(RadioProfileSlot::JARNSEN_1) &&
        !radioProfileConfigureJarnsen(RadioProfileSlot::JARNSEN_1, JARNSEN_1_DEFAULT_MHZ, preset, hops))
        return false;
    if (!radioProfileSlotExists(RadioProfileSlot::JARNSEN_2) &&
        !radioProfileConfigureJarnsen(RadioProfileSlot::JARNSEN_2, JARNSEN_2_DEFAULT_MHZ, preset, hops))
        return false;

    return writeRadioDefaultsMarker();
}

void recordRadioRuntime(bool migrationOk)
{
    const bool migrated = radioDefaultsMigrated();
    const bool standard = radioProfileSlotExists(RadioProfileSlot::STANDARD);
    const bool j1 = radioProfileSlotExists(RadioProfileSlot::JARNSEN_1);
    const bool j2 = radioProfileSlotExists(RadioProfileSlot::JARNSEN_2);
    const auto active = radioProfileActive();
    diagnosticLog("RADIO_RUNTIME",
                  "migration_ok=%u marker=%u standard=%u j1=%u j2=%u active=%s region=%u frequency=%.3f hops=%u",
                  migrationOk ? 1U : 0U, migrated ? 1U : 0U, standard ? 1U : 0U, j1 ? 1U : 0U, j2 ? 1U : 0U,
                  radioProfileKey(active), config.has_lora ? (unsigned)config.lora.region : 0U,
                  config.has_lora ? (double)config.lora.override_frequency : 0.0,
                  config.has_lora ? (unsigned)config.lora.hop_limit : 0U);
}

#ifdef ARCH_ESP32

gpio_num_t userButtonPin()
{
    const int pin = configuredUserButtonPin();
    return pin >= 0 ? (gpio_num_t)pin : GPIO_NUM_NC;
}

void armDeepSleepUserButtonWake()
{
#ifdef BUTTON_PIN
    const gpio_num_t pin = userButtonPin();
    if (pin == GPIO_NUM_NC || !rtc_gpio_is_valid_gpio(pin)) {
        diagnosticLog("WAKE", "deep_arm=unsupported pin=%d reason=not_rtc_gpio", (int)pin);
        return;
    }

    rtc_gpio_hold_dis(pin);
    rtc_gpio_pulldown_dis(pin);
    rtc_gpio_pullup_en(pin);
    const uint64_t mask = 1ULL << (uint32_t)pin;
#if defined(CONFIG_IDF_TARGET_ESP32)
    const esp_err_t err = esp_sleep_enable_ext1_wakeup(mask, ESP_EXT1_WAKEUP_ALL_LOW);
#else
    const esp_err_t err = esp_sleep_enable_ext1_wakeup(mask, ESP_EXT1_WAKEUP_ANY_LOW);
#endif
    if (err != ESP_OK) {
        diagnosticLog("WAKE", "deep_arm=error pin=%d err=%d", (int)pin, (int)err);
        LOG_ERROR("JARNSEN: failed to arm deep-sleep Userbutton GPIO%d wake: %d", (int)pin, (int)err);
        return;
    }
    diagnosticLog("WAKE", "deep_arm=ok pin=%d mask=0x%llx", (int)pin, (unsigned long long)mask);
#endif
}

void normalizeDeepSleepUserButtonWake()
{
#ifdef BUTTON_PIN
    const esp_sleep_wakeup_cause_t cause = esp_sleep_get_wakeup_cause();
    if (cause != ESP_SLEEP_WAKEUP_EXT1)
        return;
    const gpio_num_t pin = userButtonPin();
    if (pin == GPIO_NUM_NC || !rtc_gpio_is_valid_gpio(pin)) {
        diagnosticLog("WAKE", "deep_boot=ext1 userbutton=unknown pin=%d", (int)pin);
        return;
    }
    const uint64_t mask = esp_sleep_get_ext1_wakeup_status();
    if ((mask & (1ULL << (uint32_t)pin)) == 0) {
        diagnosticLog("WAKE", "deep_boot=ext1 userbutton=0 pin=%d mask=0x%llx", (int)pin, (unsigned long long)mask);
        return;
    }

    diagnosticLog("WAKE", "deep_boot=userbutton pin=%d mask=0x%llx wake_only=1", (int)pin, (unsigned long long)mask);

    // Return the RTC pad to normal GPIO ownership before the input/button
    // threads start. This avoids a retained RTC configuration making the first
    // post-deep-sleep press/release unreliable.
    rtc_gpio_hold_dis(pin);
    rtc_gpio_deinit(pin);
    pinMode((uint8_t)pin, INPUT_PULLUP);
#endif
}

class JarnsenDeepSleepButtonObserver final : public Observer<void *>
{
  protected:
    int onNotify(void *deepSleep) override
    {
        if (deepSleep)
            armDeepSleepUserButtonWake();
        return 0;
    }
};

JarnsenDeepSleepButtonObserver deepSleepButtonObserver;
bool deepSleepButtonObserverInstalled = false;

#endif // ARCH_ESP32
#endif // JARNSEN_RUNTIME_TARGET

} // namespace

void runtimePolicyInit()
{
#if JARNSEN_RUNTIME_TARGET
    // NodeDB/config and FS are available here. Start the shared logger before
    // any wake/profile diagnostics so early boot evidence is retained on every
    // JARNSEN target, including the Tracker adapter and Wio/nRF backend.
    diagnosticLogInit();
    ensureLegacyStatusBridge();

    // JARNSEN operator UI rule: the display remains on for exactly 20 seconds
    // after the most recent button/input event. PowerFSM and the Tracker service
    // both consume this runtime config value, so they share one deadline.
    config.display.screen_on_secs = JARNSEN_DISPLAY_ON_MS / 1000U;

#if HAS_WIFI
    // JARNSEN never uses the normal persistent Meshtastic station-WLAN path.
    // Service WLAN is started explicitly and temporarily by JarnsenServiceWeb.
    // Do not persist this runtime override: a service session must never turn a
    // saved station setting back on, and every JARNSEN boot starts with WLAN off.
    config.network.wifi_enabled = false;
#endif

    if (activeDeviceRoleIs(DeviceRole::DRONE_REPEATER) && !droneRepeaterApplyBaseConfig(true))
        LOG_ERROR("JARNSEN: Drone Repeater base configuration could not be persisted");

    diagnosticLog("BOOT_RUNTIME", "board=%s platform=%s wake=%s button_pin=%d display_on_ms=%u", build::hardwareName,
                  platformLabel(), bootWakeLabel(), configuredUserButtonPin(), (unsigned)JARNSEN_DISPLAY_ON_MS);

    const bool migrationOk = ensureRadioProfileDefaults();
    if (!migrationOk)
        LOG_WARN("JARNSEN: radio profile default migration deferred");
    recordRadioRuntime(migrationOk);

#ifdef ARCH_ESP32
    normalizeDeepSleepUserButtonWake();
    const gpio_num_t pin = userButtonPin();
    diagnosticLog("WAKE", "deep_capability=%s pin=%d", pin != GPIO_NUM_NC && rtc_gpio_is_valid_gpio(pin) ? "rtc_ext1" : "none",
                  (int)pin);
    if (!deepSleepButtonObserverInstalled) {
        deepSleepButtonObserver.observe(&preflightSleep);
        deepSleepButtonObserverInstalled = true;
    }
#else
    diagnosticLog("WAKE", "deep_capability=platform_specific button_pin=%d", configuredUserButtonPin());
#endif

    droneRepeaterRuntimeInit();
#endif
}

} // namespace jarnsen
