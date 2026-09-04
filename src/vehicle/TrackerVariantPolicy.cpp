#include "TrackerVariantPolicy.h"

#include "configuration.h"

#if defined(HELTEC_TRACKER_V1_1)

#include "NodeDB.h"
#include "TrackerCommonPolicy.h"
#include "jarnsen/adapters/JarnsenLegacyStatusBridge.h"
#include "jarnsen/core/status/JarnsenStatusProvider.h"
#include "main.h"

#include <Preferences.h>

namespace
{
constexpr const char *JARNSEN_PREF_NAMESPACE = "jmeshCore";
constexpr const char *TRACKER_INIT_KEY = "trackerInit";
constexpr uint8_t TRACKER_INIT_SCHEMA = 1;

jarnsen::DeviceRole trackerCoreRole()
{
    // Make the adapter installation explicit at the runtime entry point. This
    // keeps Tracker startup independent from static-initialization ordering.
    jarnsen::ensureLegacyStatusBridge();
    return jarnsen::activeDeviceRoleOr(jarnsen::DeviceRole::UNCONFIGURED);
}

bool trackerRuntimeRoleEnabled()
{
    const jarnsen::DeviceRole role = trackerCoreRole();
    return role == jarnsen::DeviceRole::TAK || role == jarnsen::DeviceRole::TAK_TRACKER;
}

bool trackerJarnsenRoleProvisioned()
{
    // Device roles are provisioned by the flashed build or by an external
    // profile/config writer. They are deliberately not selectable on-device.
    // Keep this check separate from trackerRuntimeRoleEnabled(): repeater roles
    // are valid JARNSEN roles even though they must not inherit Tracker policy.
    switch (trackerCoreRole()) {
    case jarnsen::DeviceRole::TAK:
    case jarnsen::DeviceRole::TAK_TRACKER:
    case jarnsen::DeviceRole::TAK_REPEATER:
    case jarnsen::DeviceRole::DRONE_REPEATER:
        return true;
    default:
        return false;
    }
}

bool bootstrapTrackerUnifiedCoreDefaults()
{
    Preferences prefs;
    bool alreadyInitialized = false;
    if (prefs.begin(JARNSEN_PREF_NAMESPACE, true)) {
        alreadyInitialized = prefs.getUChar(TRACKER_INIT_KEY, 0) >= TRACKER_INIT_SCHEMA;
        prefs.end();
    }
    if (alreadyInitialized)
        return false;

    const bool roleAlreadyProvisioned = trackerJarnsenRoleProvisioned();
    const bool roleChanged = !roleAlreadyProvisioned;

    // A Tracker that receives the generic JARNSEN-MESH build on top of stock
    // Meshtastic has no JARNSEN role marker yet. Bootstrap that unprovisioned
    // case once as TAK_TRACKER. A role supplied by a dedicated flash build or
    // by an external profile writer is authoritative and must never be changed
    // here. In particular, TAK_REPEATER and DRONE_REPEATER are valid provisioned
    // roles even though this Tracker runtime policy does not execute for them.
    if (roleChanged) {
        config.device.role = meshtastic_Config_DeviceConfig_Role_TAK_TRACKER;
        if (!nodeDB) {
            LOG_WARN("JARNSEN-MESH Tracker bootstrap deferred: NodeDB unavailable");
            return false;
        }
        nodeDB->saveToDisk(SEGMENT_CONFIG);
    }

    Preferences writePrefs;
    if (!writePrefs.begin(JARNSEN_PREF_NAMESPACE, false)) {
        LOG_WARN("JARNSEN-MESH Tracker bootstrap marker could not be persisted");
        return roleChanged;
    }
    writePrefs.putUChar(TRACKER_INIT_KEY, TRACKER_INIT_SCHEMA);
    writePrefs.end();

    LOG_INFO("JARNSEN-MESH Tracker bootstrap schema=%u role=%s",
             (unsigned)TRACKER_INIT_SCHEMA, roleChanged ? "TAK_TRACKER (new)" : "preserved");
    return roleChanged;
}
} // namespace

extern "C" bool meshtasticTrackerScreenPowerAllowed(bool on)
{
    return trackerCommonScreenPowerAllowed(on);
}

extern "C" void meshtasticTrackerBleActivity()
{
    trackerCommonBleActivity();
}

static bool repairLegacyTrackerButtonConfig()
{
    if (config.device.button_gpio == 0)
        return false;

    const uint8_t oldPin = config.device.button_gpio;
    config.device.button_gpio = 0;
    if (nodeDB)
        nodeDB->saveToDisk(SEGMENT_CONFIG);

    LOG_WARN("Tracker V1.1: repaired persisted button_gpio=%u -> GPIO0; "
             "rebooting once to rebind InputBroker safely",
             (unsigned)oldPin);
    return true;
}

#endif

void setupJarnsenTrackerVariantPolicy()
{
#if defined(HELTEC_TRACKER_V1_1)
    if (bootstrapTrackerUnifiedCoreDefaults()) {
        // Reboot once after changing the persisted role so every role-sensitive
        // Meshtastic module starts from a consistent configuration on the next
        // boot. Existing JARNSEN installations never take this path again.
        rebootAtMsec = millis() + 1500UL;
        return;
    }

    if (!trackerRuntimeRoleEnabled())
        return;

    config.display.screen_on_secs = 20;

#if defined(VEHICLE_MOTION_WAKE_PIN)
    pinMode(VEHICLE_MOTION_WAKE_PIN, INPUT_PULLUP);
#endif

    if (repairLegacyTrackerButtonConfig()) {
        rebootAtMsec = millis() + 1500UL;
        return;
    }

    // TAK and TAK_TRACKER intentionally use one runtime policy. Their only
    // operational difference is the parked sleep depth selected inside it.
    setupTrackerCommonPolicy();
#endif
}
