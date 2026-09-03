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

bool readActiveDeviceRole(DeviceRole &role)
{
    role = DeviceRole::UNCONFIGURED;
    return hooks.activeRole ? hooks.activeRole(role) : false;
}

DeviceRole activeDeviceRoleOr(DeviceRole fallback)
{
    DeviceRole role = DeviceRole::UNCONFIGURED;
    return readActiveDeviceRole(role) ? role : fallback;
}

bool activeDeviceRoleIs(DeviceRole role)
{
    DeviceRole active = DeviceRole::UNCONFIGURED;
    return readActiveDeviceRole(active) && active == role;
}

NodeStatusSnapshot readNodeStatus(const HardwareRoleProfile &profile)
{
    const bool peripheralsKnown = hooks.peripherals != nullptr;
    const PeripheralCapabilities peripherals = peripheralsKnown ? hooks.peripherals() : PeripheralCapabilities{};
    DeviceRole role = DeviceRole::UNCONFIGURED;
    const bool roleKnown = readActiveDeviceRole(role);
    return makeNodeStatusSnapshot(profile, peripherals, role, roleKnown, peripheralsKnown);
}

} // namespace jarnsen
