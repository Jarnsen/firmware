#pragma once

#include "configuration.h"
#include "jarnsen/hardware/JarnsenServiceProfiles.h"

namespace jarnsen
{

// Transitional compile-time selector owned by the hardware layer. Shared Core
// service code consumes only NodeServiceDescriptor and never board symbols.
constexpr NodeServiceDescriptor platformServiceDescriptor()
{
#if defined(HELTEC_TRACKER_V1_1)
    return trackerV11ServiceDescriptor();
#elif defined(_VARIANT_HELTEC_V3)
    return heltecV3ServiceDescriptor();
#elif defined(_VARIANT_HELTEC_V4)
    return heltecV4ServiceDescriptor();
#else
    return {};
#endif
}

constexpr bool platformServiceKnown()
{
    return platformServiceDescriptor().profile.hardware.kind != HardwareKind::UNKNOWN;
}

} // namespace jarnsen
