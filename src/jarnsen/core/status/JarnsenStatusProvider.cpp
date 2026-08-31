#include "jarnsen/core/status/JarnsenStatusProvider.h"

namespace jarnsen
{
namespace
{
StatusProviderHooks hooks{};
}

void setStatusProviderHooks(const StatusProviderHooks &newHooks)
{
    hooks = newHooks;
}

void setPeripheralCapabilitiesProvider(PeripheralCapabilitiesProvider provider)
{
    hooks.peripherals = provider;
}

void setDeviceRoleProvider(DeviceRoleProvider provider)
{
    hooks.activeRole = provider;
}

StatusProviderHooks statusProviderHooks()
{
    return hooks;
}

NodeStatusSnapshot readNodeStatus(const HardwareRoleProfile &profile)
{
    const bool peripheralsKnown = hooks.peripherals != nullptr;
    const PeripheralCapabilities peripherals = peripheralsKnown ? hooks.peripherals() : PeripheralCapabilities{};
    DeviceRole role = DeviceRole::UNCONFIGURED;
    const bool roleKnown = hooks.activeRole ? hooks.activeRole(role) : false;
    return makeNodeStatusSnapshot(profile, peripherals, role, roleKnown, peripheralsKnown);
}

} // namespace jarnsen
