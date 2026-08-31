#pragma once

#include "configuration.h"
#include "jarnsen/core/service/JarnsenServiceModel.h"

namespace jarnsen
{

// Compile-time hardware selector. Keep board preprocessor knowledge in the
// hardware layer so service, display and tooling only consume common metadata.
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
