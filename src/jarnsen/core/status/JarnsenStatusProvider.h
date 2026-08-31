#pragma once

#include "jarnsen/core/status/JarnsenNodeStatus.h"

namespace jarnsen
{

using PeripheralCapabilitiesProvider = PeripheralCapabilities (*)();
using DeviceRoleProvider = DeviceRole (*)();

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

NodeStatusSnapshot readNodeStatus(const HardwareRoleProfile &profile);

} // namespace jarnsen
