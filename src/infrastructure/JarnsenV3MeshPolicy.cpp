#include "infrastructure/JarnsenV3MeshPolicy.h"

#if defined(_VARIANT_HELTEC_V3)

#include "NodeDB.h"
#include "infrastructure/HeltecV3DiagnosticLog.h"

#include <Preferences.h>

namespace
{
constexpr const char *PREF_NAMESPACE = "v3mesh";
constexpr const char *NEIGHBOR_KEY = "neighbor";
bool initialized = false;
bool localNeighborEnabled = true;

void loadPolicy()
{
    Preferences prefs;
    if (prefs.begin(PREF_NAMESPACE, true)) {
        localNeighborEnabled = prefs.getBool(NEIGHBOR_KEY, true);
        prefs.end();
    }
}
}

void jarnsenV3MeshPolicyInit()
{
    if (initialized)
        return;
    loadPolicy();
    initialized = true;
    jarnsenV3MeshPolicyEnforce();
    heltecV3DiagLog("MESH_POLICY", "positionTx=locked-on neighbor=%u source=local-service", localNeighborEnabled ? 1U : 0U);
}

bool jarnsenV3NeighborInfoEnabled()
{
    if (!initialized)
        jarnsenV3MeshPolicyInit();
    return localNeighborEnabled;
}

void jarnsenV3SetNeighborInfoEnabled(bool enabled)
{
    localNeighborEnabled = enabled;
    initialized = true;
    Preferences prefs;
    if (prefs.begin(PREF_NAMESPACE, false)) {
        prefs.putBool(NEIGHBOR_KEY, enabled);
        prefs.end();
    }
    jarnsenV3MeshPolicyEnforce();
    heltecV3DiagLog("MESH_POLICY", "neighbor local override=%u", enabled ? 1U : 0U);
}

void jarnsenV3MeshPolicyEnforce()
{
    if (!initialized) {
        loadPolicy();
        initialized = true;
    }
    bool corrected = false;
    if (config.position.position_broadcast_secs == 0) {
        config.position.position_broadcast_secs = 3600U;
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
        heltecV3DiagLog("MESH_POLICY", "external config normalized positionTx=1 neighbor=%u interval=%u",
                        localNeighborEnabled ? 1U : 0U, (unsigned)moduleConfig.neighbor_info.update_interval);
}

#endif
