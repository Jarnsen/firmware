#include "jarnsen/core/features/JarnsenFeatureManager.h"
#include "jarnsen/hardware/JarnsenHardwareProfiles.h"

namespace jarnsen
{
namespace
{

constexpr HardwareRoleProfile tracker = trackerV11Profile();
constexpr HardwareRoleProfile v3 = heltecV3Profile();
constexpr HardwareRoleProfile v4 = heltecV4Profile();
constexpr HardwareRoleProfile wioL1 = seeedWioTrackerL1Profile();
constexpr HardwareRoleProfile tbeam = lilygoTBeamProfile();
constexpr HardwareRoleProfile tbeamSupreme = lilygoTBeamSupremeProfile();

constexpr PeripheralCapabilities trackerPeripherals = {false, true, false};
constexpr PeripheralCapabilities noPeripherals = {false, false, false};
constexpr PeripheralCapabilities externalGpsOnly = {true, false, false};

constexpr EffectiveCapabilities trackerCaps = resolveCapabilities(tracker.hardware.capabilities, trackerPeripherals);
constexpr EffectiveCapabilities v3BaseCaps = resolveCapabilities(v3.hardware.capabilities, noPeripherals);
constexpr EffectiveCapabilities v3GpsCaps = resolveCapabilities(v3.hardware.capabilities, externalGpsOnly);
constexpr EffectiveCapabilities v4BaseCaps = resolveCapabilities(v4.hardware.capabilities, noPeripherals);
constexpr EffectiveCapabilities v4GpsCaps = resolveCapabilities(v4.hardware.capabilities, externalGpsOnly);
constexpr EffectiveCapabilities wioL1Caps = resolveCapabilities(wioL1.hardware.capabilities, noPeripherals);
constexpr EffectiveCapabilities tbeamCaps = resolveCapabilities(tbeam.hardware.capabilities, noPeripherals);
constexpr EffectiveCapabilities tbeamSupremeCaps = resolveCapabilities(tbeamSupreme.hardware.capabilities, noPeripherals);

static_assert(trackerCaps.gps, "Tracker V1.1 must expose integrated GPS");
static_assert(trackerCaps.motion, "Reference Tracker V1.1 motion peripheral must resolve to an effective capability");
static_assert(trackerCaps.display.present && trackerCaps.display.width == 160 && trackerCaps.display.height == 80,
              "Tracker V1.1 display geometry must be described by the hardware profile");
static_assert(roleSupported(DeviceRole::TAK, tracker.roles, trackerCaps), "Tracker must support TAK");
static_assert(roleSupported(DeviceRole::TAK_TRACKER, tracker.roles, trackerCaps), "Tracker must support TAK Tracker");
static_assert(roleSupported(DeviceRole::TAK_REPEATER, tracker.roles, trackerCaps), "Tracker must support TAK Repeater");
static_assert(roleSupported(DeviceRole::DRONE_REPEATER, tracker.roles, trackerCaps), "Tracker must support Drone Repeater");

static_assert(!v3BaseCaps.gps, "V3 without external GPS must not advertise GPS");
static_assert(roleSupported(DeviceRole::TAK, v3.roles, v3BaseCaps), "V3 must support TAK without integrated GPS");
static_assert(!roleSupported(DeviceRole::TAK_TRACKER, v3.roles, v3BaseCaps),
              "V3 without GPS must not support TAK Tracker");
static_assert(roleSupported(DeviceRole::TAK_REPEATER, v3.roles, v3BaseCaps), "V3 must support TAK Repeater");
static_assert(!featureEnabled(Feature::TAK_TRACKING_POLICY, DeviceRole::TAK_TRACKER, v3.roles, v3BaseCaps),
              "Invalid V3 TAK Tracker role must not start tracking policy without GPS");
static_assert(featureEnabled(Feature::BLUETOOTH_SERVICE, DeviceRole::TAK_TRACKER, v3.roles, v3BaseCaps),
              "BLE recovery must remain available when a persisted role loses GPS");
static_assert(featureEnabled(Feature::WIFI_SERVICE, DeviceRole::TAK_TRACKER, v3.roles, v3BaseCaps),
              "WiFi recovery must remain available when a persisted role loses GPS");
static_assert(v3BaseCaps.display.present && v3BaseCaps.display.width == 128 && v3BaseCaps.display.height == 64,
              "V3 display geometry must be described by the hardware profile");

static_assert(v3GpsCaps.gps, "V3 with configured external GPS must advertise GPS");
static_assert(roleSupported(DeviceRole::TAK_TRACKER, v3.roles, v3GpsCaps),
              "V3 with external GPS must be eligible for TAK Tracker");
static_assert(!roleSupported(DeviceRole::DRONE_REPEATER, v3.roles, v3GpsCaps),
              "External GPS must not accidentally unlock Drone Repeater on V3");

static_assert(!v4BaseCaps.gps, "V4 base profile must not claim an integrated GPS");
static_assert(roleSupported(DeviceRole::TAK, v4.roles, v4BaseCaps), "V4 must support TAK");
static_assert(roleSupported(DeviceRole::TAK_REPEATER, v4.roles, v4BaseCaps), "V4 must support TAK Repeater");
static_assert(!roleSupported(DeviceRole::TAK_TRACKER, v4.roles, v4BaseCaps),
              "V4 without configured GNSS must not support TAK Tracker");
static_assert(v4GpsCaps.gps && roleSupported(DeviceRole::TAK_TRACKER, v4.roles, v4GpsCaps),
              "V4 with configured external GPS must be eligible for TAK Tracker");
static_assert(!roleSupported(DeviceRole::DRONE_REPEATER, v4.roles, v4GpsCaps),
              "External GPS must not automatically unlock Drone Repeater on V4");

static_assert(wioL1Caps.gps, "Wio Tracker L1 must expose its integrated L76K GPS");
static_assert(wioL1Caps.display.present && wioL1Caps.display.width == 128 && wioL1Caps.display.height == 64,
              "Wio Tracker L1 OLED geometry must be described by the hardware profile");
static_assert(!wioL1Caps.wifi, "Wio Tracker L1 must not advertise Wi-Fi on nRF52840");
static_assert(roleSupported(DeviceRole::TAK, wioL1.roles, wioL1Caps), "Wio Tracker L1 must support TAK");
static_assert(roleSupported(DeviceRole::TAK_TRACKER, wioL1.roles, wioL1Caps), "Wio Tracker L1 must support TAK Tracker");
static_assert(roleSupported(DeviceRole::TAK_REPEATER, wioL1.roles, wioL1Caps), "Wio Tracker L1 must support TAK Repeater");
static_assert(!roleSupported(DeviceRole::DRONE_REPEATER, wioL1.roles, wioL1Caps),
              "Wio Tracker L1 Drone Repeater must stay disabled until separately validated");

static_assert(tbeamCaps.gps, "T-Beam must expose its integrated u-blox GPS");
static_assert(!tbeamCaps.display.present, "Base T-Beam target must not claim the optional display shield as built in");
static_assert(tbeamCaps.bluetooth && tbeamCaps.wifi && tbeamCaps.battery,
              "T-Beam must expose ESP32 connectivity and PMU-backed battery capability");
static_assert(roleSupported(DeviceRole::TAK, tbeam.roles, tbeamCaps), "T-Beam must support TAK");
static_assert(roleSupported(DeviceRole::TAK_TRACKER, tbeam.roles, tbeamCaps), "T-Beam must support TAK Tracker");
static_assert(roleSupported(DeviceRole::TAK_REPEATER, tbeam.roles, tbeamCaps), "T-Beam must support TAK Repeater");
static_assert(!roleSupported(DeviceRole::DRONE_REPEATER, tbeam.roles, tbeamCaps),
              "T-Beam Drone Repeater must stay disabled until separately validated");

static_assert(tbeamSupremeCaps.gps, "T-Beam Supreme must expose its integrated GPS");
static_assert(tbeamSupremeCaps.display.present && tbeamSupremeCaps.display.width == 128 &&
                  tbeamSupremeCaps.display.height == 64,
              "T-Beam Supreme SH1106 display geometry must be described by the hardware profile");
static_assert(tbeamSupremeCaps.bluetooth && tbeamSupremeCaps.wifi && tbeamSupremeCaps.battery,
              "T-Beam Supreme must expose ESP32-S3 connectivity and PMU-backed battery capability");
static_assert(roleSupported(DeviceRole::TAK, tbeamSupreme.roles, tbeamSupremeCaps), "T-Beam Supreme must support TAK");
static_assert(roleSupported(DeviceRole::TAK_TRACKER, tbeamSupreme.roles, tbeamSupremeCaps),
              "T-Beam Supreme must support TAK Tracker");
static_assert(roleSupported(DeviceRole::TAK_REPEATER, tbeamSupreme.roles, tbeamSupremeCaps),
              "T-Beam Supreme must support TAK Repeater");
static_assert(!roleSupported(DeviceRole::DRONE_REPEATER, tbeamSupreme.roles, tbeamSupremeCaps),
              "T-Beam Supreme Drone Repeater must stay disabled until separately validated");

static_assert(featureEnabled(Feature::TAK_POLICY, DeviceRole::TAK, v3.roles, v3BaseCaps),
              "TAK feature must not require integrated GPS");
static_assert(featureEnabled(Feature::TAK_TRACKING_POLICY, DeviceRole::TAK_TRACKER, v3.roles, v3GpsCaps),
              "TAK tracking feature must follow role plus effective capabilities");
static_assert(!featureEnabled(Feature::DRONE_REPEATER_POLICY, DeviceRole::DRONE_REPEATER, v3.roles, v3GpsCaps),
              "Drone feature must remain blocked by V3 role availability");

} // namespace
} // namespace jarnsen
