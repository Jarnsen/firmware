#pragma once

#include "jarnsen/core/status/JarnsenNodeStatus.h"

namespace jarnsen
{

using PeripheralCapabilitiesProvider = PeripheralCapabilities (*)();
using DeviceRoleProvider = bool (*)(DeviceRole &role);

struct StatusProviderHooks {
    PeripheralCapabilitiesProvider peripherals = nullptr;
    DeviceRoleProvider activeRole = nullptr;
};

// Hardware/role adapters register only the runtime facts they own. Consumers
// never need to know which board supplied those facts.
void setStatusProviderHooks(const StatusProviderHooks &hooks);
void setPeripheralCapabilitiesProvider(PeripheralCapabilitiesProvider provider);
void setDeviceRoleProvider(DeviceRoleProvider provider);
StatusProviderHooks statusProviderHooks();

// Read the normalized Core role supplied by the installed adapter. Runtime
// code should prefer these helpers over direct Meshtastic role comparisons.
bool readActiveDeviceRole(DeviceRole &role);
DeviceRole activeDeviceRoleOr(DeviceRole fallback = DeviceRole::UNCONFIGURED);
bool activeDeviceRoleIs(DeviceRole role);

NodeStatusSnapshot readNodeStatus(const HardwareRoleProfile &profile);

} // namespace jarnsen
