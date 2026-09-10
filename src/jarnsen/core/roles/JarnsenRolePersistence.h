#pragma once

#include "jarnsen/core/roles/JarnsenDeviceRole.h"

#include <stdint.h>

namespace jarnsen
{

constexpr uint8_t JARNSEN_ROLE_API_VERSION = 1U;

bool parseDeviceRoleKey(const char *text, DeviceRole &role);
bool deviceRoleAllowedOnCurrentHardware(DeviceRole role);
bool readPersistedDeviceRole(DeviceRole &role);
bool writePersistedDeviceRole(DeviceRole role);

} // namespace jarnsen
