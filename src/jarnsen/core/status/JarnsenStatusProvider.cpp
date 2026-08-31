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

StatusProviderHooks statusProviderHooks()
{
    return hooks;
}

NodeStatusSnapshot readNodeStatus(const HardwareRoleProfile &profile)
{
    const bool peripheralsKnown = hooks.peripherals != nullptr;
    const PeripheralCapabilities peripherals = peripheralsKnown ? hooks.peripherals() : PeripheralCapabilities{};
    const bool roleKnown = hooks.activeRole != nullptr;
    const DeviceRole role = roleKnown ? hooks.activeRole() : DeviceRole::UNCONFIGURED;
    return makeNodeStatusSnapshot(profile, peripherals, role, roleKnown, peripheralsKnown);
}

} // namespace jarnsen
