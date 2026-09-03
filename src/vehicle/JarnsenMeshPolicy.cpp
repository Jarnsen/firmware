#include "vehicle/JarnsenMeshPolicy.h"

#if defined(HELTEC_TRACKER_V1_1)

#include "NodeDB.h"
#include "jarnsen/core/mesh/JarnsenMeshPolicy.h"
#include "vehicle/TrackerDiagnosticLog.h"
#include "vehicle/TrackerServiceSettings.h"

#include <Preferences.h>

namespace
{
constexpr const char *PREF_NAMESPACE = "jmesh";
constexpr const char *NEIGHBOR_KEY = "neighbor";
bool initialized = false;
bool localNeighborEnabled = true;

void loadLocalPolicy()
{
    Preferences prefs;
    if (prefs.begin(PREF_NAMESPACE, true)) {
        localNeighborEnabled = prefs.getBool(NEIGHBOR_KEY, true);
        prefs.end();
    }
}
}

void jarnsenMeshPolicyInit()
{
    if (initialized)
        return;
    loadLocalPolicy();
    initialized = true;
    jarnsenMeshPolicyEnforce();
    trackerDiagLog("MESH_POLICY", "positionTx=locked-on neighbor=%u source=local-service", localNeighborEnabled ? 1U : 0U);
}

bool jarnsenNeighborInfoEnabled()
{
    if (!initialized)
        jarnsenMeshPolicyInit();
    return localNeighborEnabled;
}

void jarnsenSetNeighborInfoEnabled(bool enabled)
{
    localNeighborEnabled = enabled;
    initialized = true;
    Preferences prefs;
    if (prefs.begin(PREF_NAMESPACE, false)) {
        prefs.putBool(NEIGHBOR_KEY, enabled);
        prefs.end();
    }
    jarnsenMeshPolicyEnforce();
    trackerDiagLog("MESH_POLICY", "neighbor local override=%u", enabled ? 1U : 0U);
}

void jarnsenMeshPolicyEnforce()
{
    if (!initialized) {
        loadLocalPolicy();
        initialized = true;
    }

    const jarnsen::MeshPolicyState current{
        config.position.position_broadcast_secs,
        config.position.position_broadcast_smart_enabled,
        moduleConfig.neighbor_info.enabled,
        moduleConfig.neighbor_info.transmit_over_lora,
        moduleConfig.neighbor_info.update_interval,
    };
    const jarnsen::MeshPolicyResult normalized =
        jarnsen::normalizeMeshPolicy(current, trackerEffectiveParkIntervalSecs(), localNeighborEnabled);

    config.position.position_broadcast_secs = normalized.state.positionBroadcastSecs;
    config.position.position_broadcast_smart_enabled = normalized.state.positionSmartEnabled;
    moduleConfig.neighbor_info.enabled = normalized.state.neighborEnabled;
    moduleConfig.neighbor_info.transmit_over_lora = normalized.state.neighborTransmitOverLora;
    moduleConfig.neighbor_info.update_interval = normalized.state.neighborUpdateInterval;

    if (normalized.corrected)
        trackerDiagLog("MESH_POLICY", "external config normalized positionTx=1 neighbor=%u interval=%u",
                       localNeighborEnabled ? 1U : 0U, (unsigned)moduleConfig.neighbor_info.update_interval);
}

#endif
