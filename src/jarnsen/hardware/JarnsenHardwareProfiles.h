#pragma once

#include "jarnsen/core/capabilities/JarnsenCapabilities.h"
#include "jarnsen/core/roles/JarnsenDeviceRole.h"

namespace jarnsen
{

struct HardwareRoleProfile {
    HardwareProfile hardware{};
    RoleAvailability roles{};
};

constexpr HardwareRoleProfile trackerV11Profile()
{
    return {
        {
            HardwareKind::HELTEC_TRACKER_V11,
            "HELTEC_TRACKER_V1.1",
            "Heltec Tracker V1.1",
            {
                true,  // internalGps
                false, // supportsExternalGps: not required by the current reference hardware profile
                true,  // display
                true,  // bluetooth
                true,  // wifi
                true,  // battery
                true,  // usbPowerDetect
                true,  // lightSleep
                true,  // deepSleep
                true,  // buttonWake
                true,  // supportsMotion
                true,  // supportsIna226
            },
        },
        {
            true, // TAK_TRACKER
            true, // TAK_REPEATER
            true, // DRONE_REPEATER
        },
    };
}

constexpr HardwareRoleProfile heltecV3Profile()
{
    return {
        {
            HardwareKind::HELTEC_V3,
            "HELTEC_V3",
            "Heltec V3",
            {
                false, // internalGps
                true,  // supportsExternalGps
                true,  // display
                true,  // bluetooth
                true,  // wifi
                true,  // battery
                true,  // usbPowerDetect
                true,  // lightSleep
                true,  // deepSleep capability; role policy decides whether it is used
                true,  // buttonWake
                false, // supportsMotion: not part of the current V3 hardware profile
                true,  // supportsIna226
            },
        },
        {
            true,  // TAK_TRACKER, but only when EffectiveCapabilities include GPS
            true,  // TAK_REPEATER
            false, // DRONE_REPEATER intentionally not offered on V3
        },
    };
}

} // namespace jarnsen
