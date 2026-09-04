#include "jarnsen/adapters/JarnsenLegacyStatusBridge.h"

#include "configuration.h"
#include "mesh/NodeDB.h"
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
    // DRONE_REPEATER historically used its own JARNSEN build marker rather than
    // a Meshtastic protobuf role. Preserve that exact source of truth here.
#if defined(JARNSEN_DRONE_REPEATER_BUILD)
    role = DeviceRole::DRONE_REPEATER;
    return true;
#endif

    // The legacy Meshtastic role still lives in the global LocalConfig owned by
    // NodeDB. NodeDB.h provides the canonical extern declaration for `config`.
    switch (config.device.role) {
    case meshtastic_Config_DeviceConfig_Role_TAK:
        role = DeviceRole::TAK;
        return true;
    case meshtastic_Config_DeviceConfig_Role_TAK_TRACKER:
        role = DeviceRole::TAK_TRACKER;
        return true;
#if defined(_VARIANT_HELTEC_V3) || defined(HELTEC_V3)
    case meshtastic_Config_DeviceConfig_Role_REPEATER:
        // The proven Heltec V3 repeater firmware used Meshtastic REPEATER as
        // its persisted role. Map it only on V3; other boards remain explicit.
        role = DeviceRole::TAK_REPEATER;
        return true;
#endif
    default:
        // Other JARNSEN-MESH custom roles remain unknown until their historical
        // persistence path has been verified. Never manufacture a Core role.
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
