#include "jarnsen/core/runtime/JarnsenRuntimePolicy.h"

#include "FSCommon.h"
#include "SPILock.h"
#include "concurrency/LockGuard.h"
#include "configuration.h"
#include "jarnsen/core/mesh/JarnsenRadioProfiles.h"
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

#ifdef ARCH_ESP32

gpio_num_t userButtonPin()
{
#ifdef BUTTON_PIN
    return (gpio_num_t)(config.device.button_gpio ? config.device.button_gpio : BUTTON_PIN);
#else
    return GPIO_NUM_NC;
#endif
}

void armDeepSleepUserButtonWake()
{
#ifdef BUTTON_PIN
    const gpio_num_t pin = userButtonPin();
    if (pin == GPIO_NUM_NC || !rtc_gpio_is_valid_gpio(pin))
        return;

    rtc_gpio_hold_dis(pin);
    rtc_gpio_pulldown_dis(pin);
    rtc_gpio_pullup_en(pin);
    const uint64_t mask = 1ULL << (uint32_t)pin;
#if defined(CONFIG_IDF_TARGET_ESP32)
    const esp_err_t err = esp_sleep_enable_ext1_wakeup(mask, ESP_EXT1_WAKEUP_ALL_LOW);
#else
    const esp_err_t err = esp_sleep_enable_ext1_wakeup(mask, ESP_EXT1_WAKEUP_ANY_LOW);
#endif
    if (err != ESP_OK)
        LOG_ERROR("JARNSEN: failed to arm deep-sleep Userbutton GPIO%d wake: %d", (int)pin, (int)err);
#endif
}

void normalizeDeepSleepUserButtonWake()
{
#ifdef BUTTON_PIN
    if (esp_sleep_get_wakeup_cause() != ESP_SLEEP_WAKEUP_EXT1)
        return;
    const gpio_num_t pin = userButtonPin();
    if (pin == GPIO_NUM_NC || !rtc_gpio_is_valid_gpio(pin))
        return;
    const uint64_t mask = esp_sleep_get_ext1_wakeup_status();
    if ((mask & (1ULL << (uint32_t)pin)) == 0)
        return;

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
    // JARNSEN operator UI rule: the display remains on for exactly 20 seconds
    // after the most recent button/input event. PowerFSM and the Tracker service
    // both consume this runtime config value, so they share one deadline.
    config.display.screen_on_secs = JARNSEN_DISPLAY_ON_MS / 1000U;

    if (!ensureRadioProfileDefaults())
        LOG_WARN("JARNSEN: radio profile default migration deferred");

#ifdef ARCH_ESP32
    normalizeDeepSleepUserButtonWake();
    if (!deepSleepButtonObserverInstalled) {
        deepSleepButtonObserver.observe(&preflightSleep);
        deepSleepButtonObserverInstalled = true;
    }
#endif
#endif
}

} // namespace jarnsen
