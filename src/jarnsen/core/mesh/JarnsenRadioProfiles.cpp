#include "jarnsen/core/mesh/JarnsenRadioProfiles.h"

#include "FSCommon.h"
#include "NodeDB.h"
#include "SPILock.h"
#include "concurrency/LockGuard.h"
#include "main.h"

#include <Arduino.h>
#include <cmath>
#include <cstring>

namespace jarnsen
{
namespace
{
constexpr const char *STANDARD_PATH = "/prefs/jarnsen-radio-standard.proto";
constexpr const char *JARNSEN_1_PATH = "/prefs/jarnsen-radio-j1.proto";
constexpr const char *JARNSEN_2_PATH = "/prefs/jarnsen-radio-j2.proto";
constexpr const char *ACTIVE_PATH = "/prefs/jarnsen-radio-active";

const char *slotPath(RadioProfileSlot profile)
{
    switch (profile) {
    case RadioProfileSlot::JARNSEN_1:
        return JARNSEN_1_PATH;
    case RadioProfileSlot::JARNSEN_2:
        return JARNSEN_2_PATH;
    case RadioProfileSlot::STANDARD:
    default:
        return STANDARD_PATH;
    }
}

bool loadSlot(RadioProfileSlot profile, meshtastic_Config_LoRaConfig &out)
{
    if (!nodeDB)
        return false;
    out = meshtastic_Config_LoRaConfig_init_zero;
    return nodeDB->loadProto(slotPath(profile), meshtastic_Config_LoRaConfig_size,
                             sizeof(meshtastic_Config_LoRaConfig), &meshtastic_Config_LoRaConfig_msg,
                             &out) == LoadFileResult::LOAD_SUCCESS;
}

bool saveSlot(RadioProfileSlot profile, const meshtastic_Config_LoRaConfig &value)
{
    return nodeDB && nodeDB->saveProto(slotPath(profile), meshtastic_Config_LoRaConfig_size,
                                      &meshtastic_Config_LoRaConfig_msg, &value);
}

bool writeActive(RadioProfileSlot profile)
{
#ifdef FSCom
    concurrency::LockGuard guard(spiLock);
    File file = FSCom.open(ACTIVE_PATH, FILE_O_WRITE);
    if (!file)
        return false;
    const uint8_t value = static_cast<uint8_t>(profile);
    const bool ok = file.write(&value, 1) == 1;
    file.flush();
    file.close();
    return ok;
#else
    (void)profile;
    return false;
#endif
}

bool readActive(RadioProfileSlot &profile)
{
#ifdef FSCom
    concurrency::LockGuard guard(spiLock);
    File file = FSCom.open(ACTIVE_PATH, FILE_O_READ);
    if (!file)
        return false;
    const int value = file.read();
    file.close();
    if (value < 0 || value >= RADIO_PROFILE_SLOT_COUNT)
        return false;
    profile = static_cast<RadioProfileSlot>(value);
    return true;
#else
    (void)profile;
    return false;
#endif
}

bool sameRadioSelection(const meshtastic_Config_LoRaConfig &a, const meshtastic_Config_LoRaConfig &b)
{
    return a.region == b.region && std::fabs(a.override_frequency - b.override_frequency) < 0.0005f &&
           a.hop_limit == b.hop_limit && a.use_preset == b.use_preset && a.modem_preset == b.modem_preset &&
           a.tx_power == b.tx_power && a.override_duty_cycle == b.override_duty_cycle;
}

bool currentMatchesSlot(RadioProfileSlot profile)
{
    if (!config.has_lora)
        return false;
    meshtastic_Config_LoRaConfig candidate = meshtastic_Config_LoRaConfig_init_zero;
    return loadSlot(profile, candidate) && sameRadioSelection(config.lora, candidate);
}

bool frequencyAllowed(meshtastic_Config_LoRaConfig_RegionCode region, float mhz)
{
    if (!std::isfinite(mhz) || mhz <= 0.0f)
        return false;

    switch (region) {
    case meshtastic_Config_LoRaConfig_RegionCode_EU_868:
        return mhz >= 869.400f && mhz <= 869.650f;
    case meshtastic_Config_LoRaConfig_RegionCode_US:
        return mhz >= 902.000f && mhz <= 928.000f;
    default:
        // Other regions remain subject to the firmware's normal radio validation.
        return true;
    }
}

} // namespace

const char *radioProfileKey(RadioProfileSlot profile)
{
    switch (profile) {
    case RadioProfileSlot::JARNSEN_1:
        return "jarnsen1";
    case RadioProfileSlot::JARNSEN_2:
        return "jarnsen2";
    case RadioProfileSlot::STANDARD:
    default:
        return "standard";
    }
}

const char *radioProfileLabel(RadioProfileSlot profile)
{
    switch (profile) {
    case RadioProfileSlot::JARNSEN_1:
        return "JARNSEN 1";
    case RadioProfileSlot::JARNSEN_2:
        return "JARNSEN 2";
    case RadioProfileSlot::STANDARD:
    default:
        return "STANDARD";
    }
}

bool parseRadioProfile(const char *text, RadioProfileSlot &profile)
{
    if (!text)
        return false;
    if (strcasecmp(text, "standard") == 0) {
        profile = RadioProfileSlot::STANDARD;
        return true;
    }
    if (strcasecmp(text, "jarnsen1") == 0 || strcasecmp(text, "jarnsen_1") == 0) {
        profile = RadioProfileSlot::JARNSEN_1;
        return true;
    }
    if (strcasecmp(text, "jarnsen2") == 0 || strcasecmp(text, "jarnsen_2") == 0) {
        profile = RadioProfileSlot::JARNSEN_2;
        return true;
    }
    return false;
}

bool parseRadioModemPreset(const char *text, meshtastic_Config_LoRaConfig_ModemPreset &preset)
{
    if (!text)
        return false;
#define MATCH_PRESET(name)                                                                                                      \
    if (strcasecmp(text, #name) == 0) {                                                                                         \
        preset = meshtastic_Config_LoRaConfig_ModemPreset_##name;                                                               \
        return true;                                                                                                             \
    }
    MATCH_PRESET(LONG_FAST)
    MATCH_PRESET(LONG_SLOW)
    MATCH_PRESET(VERY_LONG_SLOW)
    MATCH_PRESET(MEDIUM_SLOW)
    MATCH_PRESET(MEDIUM_FAST)
    MATCH_PRESET(SHORT_SLOW)
    MATCH_PRESET(SHORT_FAST)
    MATCH_PRESET(LONG_MODERATE)
    MATCH_PRESET(SHORT_TURBO)
    MATCH_PRESET(LONG_TURBO)
    MATCH_PRESET(LITE_FAST)
    MATCH_PRESET(LITE_SLOW)
    MATCH_PRESET(NARROW_FAST)
    MATCH_PRESET(NARROW_SLOW)
    MATCH_PRESET(TINY_FAST)
    MATCH_PRESET(TINY_SLOW)
    MATCH_PRESET(MEDIUM_TURBO)
#undef MATCH_PRESET
    return false;
}

RadioProfileSlot radioProfileActive()
{
    // The active marker is an optimization, not an authority by itself. Validate
    // it against the persisted slot so an interrupted two-file update cannot make
    // the display/USB report a profile that is not actually loaded in config.lora.
    RadioProfileSlot persisted = RadioProfileSlot::STANDARD;
    if (readActive(persisted) && currentMatchesSlot(persisted))
        return persisted;

    if (currentMatchesSlot(RadioProfileSlot::JARNSEN_1))
        return RadioProfileSlot::JARNSEN_1;
    if (currentMatchesSlot(RadioProfileSlot::JARNSEN_2))
        return RadioProfileSlot::JARNSEN_2;
    if (currentMatchesSlot(RadioProfileSlot::STANDARD))
        return RadioProfileSlot::STANDARD;
    return RadioProfileSlot::STANDARD;
}

bool radioProfileSlotExists(RadioProfileSlot profile)
{
    meshtastic_Config_LoRaConfig scratch = meshtastic_Config_LoRaConfig_init_zero;
    return loadSlot(profile, scratch);
}

bool radioProfileCaptureStandard()
{
    if (!config.has_lora)
        return false;
    return saveSlot(RadioProfileSlot::STANDARD, config.lora);
}

bool radioProfileConfigureJarnsen(RadioProfileSlot profile, float frequencyMhz,
                                  meshtastic_Config_LoRaConfig_ModemPreset preset, uint8_t hops)
{
    if (profile != RadioProfileSlot::JARNSEN_1 && profile != RadioProfileSlot::JARNSEN_2)
        return false;
    if (hops < 1 || hops > 20)
        return false;

    meshtastic_Config_LoRaConfig staged = meshtastic_Config_LoRaConfig_init_zero;
    if (!loadSlot(RadioProfileSlot::STANDARD, staged)) {
        if (!config.has_lora)
            return false;
        staged = config.lora;
        if (!saveSlot(RadioProfileSlot::STANDARD, staged))
            return false;
    }

    // JARNSEN 1/2 are complete, independent US LoRa profiles. Only the LoRa
    // structure is cloned from STANDARD; node identity, channels, modules,
    // position, power, Bluetooth, display and logs live in other config segments.
    staged.region = meshtastic_Config_LoRaConfig_RegionCode_US;
    if (!frequencyAllowed(staged.region, frequencyMhz))
        return false;

    staged.override_frequency = frequencyMhz;
    staged.hop_limit = hops;
    staged.override_duty_cycle = true;
    staged.tx_power = 0;
    staged.use_preset = true;
    staged.modem_preset = preset;
    return saveSlot(profile, staged);
}

bool radioProfileSelect(RadioProfileSlot profile, bool scheduleReboot)
{
    if (!nodeDB)
        return false;

    meshtastic_Config_LoRaConfig selected = meshtastic_Config_LoRaConfig_init_zero;
    if (!loadSlot(profile, selected))
        return false;

    const bool previousHasLora = config.has_lora;
    const meshtastic_Config_LoRaConfig previousLora = config.lora;
    const RadioProfileSlot previousProfile = radioProfileActive();

    config.lora = selected;
    config.has_lora = true;
    if (!nodeDB->saveToDisk(SEGMENT_CONFIG)) {
        config.lora = previousLora;
        config.has_lora = previousHasLora;
        return false;
    }

    if (!writeActive(profile)) {
        // Do not deliberately leave a half-switched profile. Restore both the
        // in-memory config and the persisted LoRa config; the active marker is
        // also restored on a best-effort basis. radioProfileActive() validates
        // the marker against config.lora, so a stale marker is never reported.
        config.lora = previousLora;
        config.has_lora = previousHasLora;
        const bool rollbackSaved = nodeDB->saveToDisk(SEGMENT_CONFIG);
        if (rollbackSaved)
            (void)writeActive(previousProfile);
        return false;
    }

    ++radioGeneration;
    if (scheduleReboot)
        rebootAtMsec = millis() + 1200U;
    return true;
}

} // namespace jarnsen
