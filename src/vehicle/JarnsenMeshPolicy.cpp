#include "vehicle/JarnsenMeshPolicy.h"

#if defined(HELTEC_TRACKER_V1_1)

#include "NodeDB.h"
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

    bool corrected = false;
    if (config.position.position_broadcast_secs == 0) {
        uint32_t interval = trackerEffectiveParkIntervalSecs();
        config.position.position_broadcast_secs = interval ? interval : 900U;
        corrected = true;
    }
    if (!config.position.position_broadcast_smart_enabled) {
        config.position.position_broadcast_smart_enabled = true;
        corrected = true;
    }

    if (moduleConfig.neighbor_info.enabled != localNeighborEnabled) {
        moduleConfig.neighbor_info.enabled = localNeighborEnabled;
        corrected = true;
    }
    if (moduleConfig.neighbor_info.transmit_over_lora != localNeighborEnabled) {
        moduleConfig.neighbor_info.transmit_over_lora = localNeighborEnabled;
        corrected = true;
    }
    if (moduleConfig.neighbor_info.update_interval < 14400U) {
        moduleConfig.neighbor_info.update_interval = 14400U;
        corrected = true;
    }

    if (corrected)
        trackerDiagLog("MESH_POLICY", "external config normalized positionTx=1 neighbor=%u interval=%u",
                       localNeighborEnabled ? 1U : 0U, (unsigned)moduleConfig.neighbor_info.update_interval);
}

#endif
