#include "jarnsen/adapters/JarnsenLegacyStatusBridge.h"

#include "configuration.h"
#include "jarnsen/core/status/JarnsenStatusProvider.h"

#if defined(HELTEC_TRACKER_V1_1)
#include "vehicle/TrackerServiceSettings.h"
#endif

namespace jarnsen
{
namespace
{

bool readLegacyRole(DeviceRole &role)
{
    switch (config.device.role) {
    case meshtastic_Config_DeviceConfig_Role_TAK:
        role = DeviceRole::TAK;
        return true;
    case meshtastic_Config_DeviceConfig_Role_TAK_TRACKER:
        role = DeviceRole::TAK_TRACKER;
        return true;
    default:
        // TAK_REPEATER and DRONE_REPEATER are JARN-MESH runtime roles. Until
        // their legacy policy mapping is explicit, report the old role as
        // unknown instead of manufacturing a potentially wrong Core role.
        role = DeviceRole::UNCONFIGURED;
        return false;
    }
}

#if defined(HELTEC_TRACKER_V1_1)
PeripheralCapabilities readTrackerPeripherals()
{
    PeripheralCapabilities peripherals{};
#ifdef VEHICLE_MOTION_WAKE_PIN
    peripherals.motion = true;
#endif
    peripherals.ina226 = trackerIna226Enabled();
    return peripherals;
}
#endif

struct LegacyStatusBridgeInstaller {
    LegacyStatusBridgeInstaller() { ensureLegacyStatusBridge(); }
};

LegacyStatusBridgeInstaller installer;

} // namespace

void ensureLegacyStatusBridge()
{
    static bool installed = false;
    if (installed)
        return;

    setDeviceRoleProvider(readLegacyRole);

#if defined(HELTEC_TRACKER_V1_1)
    setPeripheralCapabilitiesProvider(readTrackerPeripherals);
#endif

    installed = true;
}

} // namespace jarnsen
