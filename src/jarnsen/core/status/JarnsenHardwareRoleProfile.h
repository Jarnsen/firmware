#pragma once

#include "jarnsen/core/capabilities/JarnsenCapabilities.h"
#include "jarnsen/core/roles/JarnsenDeviceRole.h"

namespace jarnsen
{

// Core-owned description of one hardware family and the roles intentionally
// exposed on it. Concrete board profiles are supplied by the hardware layer.
struct HardwareRoleProfile {
    HardwareProfile hardware{};
    RoleAvailability roles{};
};

} // namespace jarnsen
