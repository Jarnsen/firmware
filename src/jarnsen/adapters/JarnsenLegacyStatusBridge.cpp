#include "jarnsen/adapters/JarnsenLegacyStatusBridge.h"

#include "configuration.h"
#include "jarnsen/core/roles/JarnsenRolePersistence.h"
#include "jarnsen/core/service/JarnsenDiagnosticLog.h"
#include "jarnsen/core/status/JarnsenStatusProvider.h"
#include "mesh/NodeDB.h"

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
    case meshtastic_Config_DeviceConfig_Role_REPEATER:
        // Unified-Core migration path: legacy stock REPEATER represents the
        // JARNSEN TAK_REPEATER role on every supported board. The TAK policy
        // persists the Core role before normalizing runtime routing to ROUTER_LATE.
        role = DeviceRole::TAK_REPEATER;
        return true;
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

bool reconcilePersistedDeviceRole()
{
    static bool persistencePending = false;
    DeviceRole role = DeviceRole::UNCONFIGURED;
    if (!readPersistedDeviceRole(role) || role == DeviceRole::UNCONFIGURED)
        return true;
    if (!nodeDB || !deviceRoleAllowedOnCurrentHardware(role))
        return false;

    auto desired = config.device.role;
    switch (role) {
    case DeviceRole::TAK:
        desired = meshtastic_Config_DeviceConfig_Role_TAK;
        break;
    case DeviceRole::TAK_TRACKER:
        desired = meshtastic_Config_DeviceConfig_Role_TAK_TRACKER;
        break;
    case DeviceRole::TAK_REPEATER:
    case DeviceRole::DRONE_REPEATER:
        desired = meshtastic_Config_DeviceConfig_Role_ROUTER_LATE;
        break;
    default:
        return false;
    }

    const auto previous = config.device.role;
    const bool changed = previous != desired || owner.role != desired;
    bool saved = true;
    if (changed) {
        config.device.role = desired;
        owner.role = desired;
        nodeDB->updateUser(nodeDB->getNodeNum(), owner);
        persistencePending = true;
    }
    if (persistencePending) {
        saved = nodeDB->saveToDisk(SEGMENT_CONFIG | SEGMENT_DEVICESTATE | SEGMENT_NODEDATABASE);
        persistencePending = !saved;
    }
    diagnosticLog("ROLE_CONTRACT", "role=%s meshtastic=%u previous=%u changed=%u persisted=%u result=%s", roleKey(role),
                  (unsigned)desired, (unsigned)previous, changed ? 1U : 0U, saved ? 1U : 0U, saved ? "ok" : "error");
    return saved;
}

} // namespace jarnsen
