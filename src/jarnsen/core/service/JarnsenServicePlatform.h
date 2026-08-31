#pragma once

#include "configuration.h"
#include "jarnsen/core/service/JarnsenServiceModel.h"

namespace jarnsen
{

// Transitional compile-time selector used while legacy board entry points are
// moved onto the Unified Core. New boards can be added here without teaching
// Captive Portal, display or desktop tooling about their preprocessor symbols.
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
