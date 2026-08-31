#include "jarnsen/core/service/JarnsenStatusProvider.h"

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

NodeStatusSnapshot readNodeStatus(const NodeServiceDescriptor &descriptor)
{
    const PeripheralCapabilities peripherals = hooks.peripherals ? hooks.peripherals() : PeripheralCapabilities{};
    const bool roleKnown = hooks.activeRole != nullptr;
    const DeviceRole role = roleKnown ? hooks.activeRole() : DeviceRole::UNCONFIGURED;
    return makeNodeStatusSnapshot(descriptor, peripherals, role, roleKnown);
}

} // namespace jarnsen
