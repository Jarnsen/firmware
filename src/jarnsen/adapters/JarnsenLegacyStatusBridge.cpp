#include "jarnsen/adapters/JarnsenLegacyStatusBridge.h"

#include "configuration.h"
#include "mesh/NodeDB.h"
#include "jarnsen/core/status/JarnsenStatusProvider.h"
#include "jarnsen/core/roles/JarnsenRolePersistence.h"

#if !MESHTASTIC_EXCLUDE_GPS
#include "GPS.h"
#endif

#if defined(HELTEC_TRACKER_V1_1)
#include "vehicle/TrackerServiceSettings.h"
#endif

namespace jarnsen
{
namespace
{

bool readLegacyRole(DeviceRole &role)
{
    // role_api=1 persistence is authoritative. Proven legacy mappings remain a
    // migration fallback only for nodes that have not been provisioned yet.
    if (readPersistedDeviceRole(role))
        return true;

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

#if defined(HELTEC_TRACKER_V1_1) || defined(HELTEC_V3) || defined(_VARIANT_HELTEC_V3) || defined(HELTEC_V4)
PeripheralCapabilities readRuntimePeripherals()
{
    PeripheralCapabilities peripherals{};
#if defined(HELTEC_TRACKER_V1_1)
#ifdef VEHICLE_MOTION_WAKE_PIN
    peripherals.motion = true;
#endif
    peripherals.ina226 = trackerIna226Enabled();
#endif

#if !MESHTASTIC_EXCLUDE_GPS && (defined(HELTEC_V3) || defined(_VARIANT_HELTEC_V3) || defined(HELTEC_V4))
    peripherals.externalGps = gps && gps->isConnected();
#endif
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

#if defined(HELTEC_TRACKER_V1_1) || defined(HELTEC_V3) || defined(_VARIANT_HELTEC_V3) || defined(HELTEC_V4)
    setPeripheralCapabilitiesProvider(readRuntimePeripherals);
#endif

    installed = true;
}

} // namespace jarnsen
