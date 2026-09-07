#pragma once

#include "mesh/generated/meshtastic/config.pb.h"
#include <stdint.h>

namespace jarnsen
{

enum class RadioProfileSlot : uint8_t {
    STANDARD = 0,
    JARNSEN_1 = 1,
    JARNSEN_2 = 2,
};

constexpr uint8_t RADIO_PROFILE_SLOT_COUNT = 3;

const char *radioProfileKey(RadioProfileSlot profile);
const char *radioProfileLabel(RadioProfileSlot profile);
bool parseRadioProfile(const char *text, RadioProfileSlot &profile);
bool parseRadioModemPreset(const char *text, meshtastic_Config_LoRaConfig_ModemPreset &preset);

RadioProfileSlot radioProfileActive();
bool radioProfileSlotExists(RadioProfileSlot profile);
bool radioProfileCaptureStandard();
bool radioProfileConfigureJarnsen(RadioProfileSlot profile, float frequencyMhz,
                                  meshtastic_Config_LoRaConfig_ModemPreset preset, uint8_t hops);
bool radioProfileSelect(RadioProfileSlot profile, bool scheduleReboot = true);

} // namespace jarnsen
