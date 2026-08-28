#include "jarnsen/core/features/JarnsenFeatureManager.h"
#include "jarnsen/hardware/JarnsenHardwareProfiles.h"

// Phase 1 compile contract: this translation unit must compile unchanged for
// every supported hardware build from the same Unified Core source tree.
namespace jarnsen
{
namespace
{

constexpr HardwareRoleProfile tracker = trackerV11Profile();
constexpr HardwareRoleProfile v3 = heltecV3Profile();

constexpr PeripheralCapabilities trackerPeripherals = {
    false, // externalGps
    true,  // motion sensor configured/present for the reference tracker setup
    false, // ina226 optional
};

constexpr PeripheralCapabilities v3NoPeripherals = {
    false, // externalGps
    false, // motion
    false, // ina226
};

constexpr PeripheralCapabilities v3WithExternalGps = {
    true,  // externalGps
    false, // motion
    false, // ina226
};

constexpr EffectiveCapabilities trackerCaps = resolveCapabilities(tracker.hardware.capabilities, trackerPeripherals);
constexpr EffectiveCapabilities v3BaseCaps = resolveCapabilities(v3.hardware.capabilities, v3NoPeripherals);
constexpr EffectiveCapabilities v3GpsCaps = resolveCapabilities(v3.hardware.capabilities, v3WithExternalGps);

static_assert(trackerCaps.gps, "Tracker V1.1 must expose integrated GPS");
static_assert(trackerCaps.motion, "Reference Tracker V1.1 motion peripheral must resolve to an effective capability");
static_assert(roleSupported(DeviceRole::TAK_TRACKER, tracker.roles, trackerCaps), "Tracker must support TAK Tracker");
static_assert(roleSupported(DeviceRole::TAK_REPEATER, tracker.roles, trackerCaps), "Tracker must support TAK Repeater");
static_assert(roleSupported(DeviceRole::DRONE_REPEATER, tracker.roles, trackerCaps), "Tracker must support Drone Repeater");

static_assert(!v3BaseCaps.gps, "V3 without external GPS must not advertise GPS");
static_assert(!roleSupported(DeviceRole::TAK_TRACKER, v3.roles, v3BaseCaps),
              "V3 without GPS must not support TAK Tracker");
static_assert(roleSupported(DeviceRole::TAK_REPEATER, v3.roles, v3BaseCaps), "V3 must support TAK Repeater");
static_assert(!featureEnabled(Feature::TAK_TRACKING_POLICY, DeviceRole::TAK_TRACKER, v3.roles, v3BaseCaps),
              "Invalid V3 TAK Tracker role must not start tracking policy without GPS");
static_assert(featureEnabled(Feature::BLUETOOTH_SERVICE, DeviceRole::TAK_TRACKER, v3.roles, v3BaseCaps),
              "BLE recovery must remain available when a persisted role loses GPS");
static_assert(featureEnabled(Feature::WIFI_SERVICE, DeviceRole::TAK_TRACKER, v3.roles, v3BaseCaps),
              "WiFi recovery must remain available when a persisted role loses GPS");

static_assert(v3GpsCaps.gps, "V3 with configured external GPS must advertise GPS");
static_assert(roleSupported(DeviceRole::TAK_TRACKER, v3.roles, v3GpsCaps),
              "V3 with external GPS must be eligible for TAK Tracker");
static_assert(!roleSupported(DeviceRole::DRONE_REPEATER, v3.roles, v3GpsCaps),
              "External GPS must not accidentally unlock Drone Repeater on V3");

static_assert(featureEnabled(Feature::TAK_TRACKING_POLICY, DeviceRole::TAK_TRACKER, v3.roles, v3GpsCaps),
              "TAK tracking feature must follow role plus effective capabilities");
static_assert(!featureEnabled(Feature::DRONE_REPEATER_POLICY, DeviceRole::DRONE_REPEATER, v3.roles, v3GpsCaps),
              "Drone feature must remain blocked by V3 role availability");

} // namespace
} // namespace jarnsen
