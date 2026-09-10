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
            HardwareKind::BOARD_HELTEC_TRACKER_V11,
            "HELTEC_TRACKER_V1.1",
            "Heltec Tracker V1.1",
            {
                true,
                false,
                {true, 160, 80, true, false},
                true,
                true,
                true,
                true,
                true,
                true,
                true,
                true,
                true,
            },
        },
        {true, true, true, true},
    };
}

constexpr HardwareRoleProfile heltecV3Profile()
{
    return {
        {
            HardwareKind::BOARD_HELTEC_V3,
            "HELTEC_V3",
            "Heltec V3",
            {
                false,
                true,
                {true, 128, 64, false, false},
                true,
                true,
                true,
                true,
                true,
                true,
                true,
                false,
                true,
            },
        },
        {true, true, true, false},
    };
}

constexpr HardwareRoleProfile heltecV4Profile()
{
    return {
        {
            HardwareKind::BOARD_HELTEC_V4,
            "HELTEC_V4",
            "Heltec V4",
            {
                false,
                true,
                {true, 128, 64, false, false},
                true,
                true,
                true,
                true,
                true,
                true,
                true,
                false,
                false,
            },
        },
        {true, true, true, true},
    };
}

constexpr HardwareRoleProfile seeedWioTrackerL1Profile()
{
    return {
        {
            HardwareKind::BOARD_SEEED_WIO_TRACKER_L1,
            "SEEED_WIO_TRACKER_L1",
            "Seeed Wio Tracker L1",
            {
                true,
                false,
                {true, 128, 64, false, false},
                true,
                false,
                true,
                true,
                true,
                true,
                true,
                false,
                false,
            },
        },
        {true, true, true, false},
    };
}

constexpr HardwareRoleProfile lilygoTBeamProfile()
{
    return {
        {
            HardwareKind::BOARD_LILYGO_TBEAM,
            "LILYGO_TBEAM",
            "LILYGO T-Beam",
            {
                true,
                false,
                {false, 0, 0, false, false},
                true,
                true,
                true,
                true,
                true,
                true,
                true,
                false,
                false,
            },
        },
        {true, true, true, false},
    };
}

constexpr HardwareRoleProfile lilygoTBeamSupremeProfile()
{
    return {
        {
            HardwareKind::BOARD_LILYGO_TBEAM_SUPREME,
            "LILYGO_TBEAM_S3_CORE",
            "LILYGO T-Beam Supreme",
            {
                true,
                false,
                {true, 128, 64, false, false},
                true,
                true,
                true,
                true,
                true,
                true,
                true,
                false,
                false,
            },
        },
        {true, true, true, false},
    };
}

constexpr HardwareRoleProfile currentHardwareRoleProfile()
{
#if defined(HELTEC_TRACKER_V1_1)
    return trackerV11Profile();
#elif defined(HELTEC_V3) || defined(_VARIANT_HELTEC_V3)
    return heltecV3Profile();
#elif defined(HELTEC_V4)
    return heltecV4Profile();
#elif defined(SEEED_WIO_TRACKER_L1)
    return seeedWioTrackerL1Profile();
#elif defined(TBEAM_V10)
    return lilygoTBeamProfile();
#elif defined(LILYGO_TBEAM_S3_CORE)
    return lilygoTBeamSupremeProfile();
#else
    return {};
#endif
}

} // namespace jarnsen
