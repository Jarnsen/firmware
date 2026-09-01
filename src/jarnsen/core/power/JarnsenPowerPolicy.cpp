#include "jarnsen/core/power/JarnsenPowerPolicy.h"
#include "jarnsen/hardware/JarnsenHardwareProfiles.h"

namespace jarnsen
{
namespace
{

constexpr HardwareRoleProfile tracker = trackerV11Profile();
constexpr HardwareRoleProfile v3 = heltecV3Profile();
constexpr HardwareRoleProfile wioL1 = seeedWioTrackerL1Profile();

constexpr PeripheralCapabilities trackerPeripherals = {false, true, false};
constexpr PeripheralCapabilities noPeripherals = {false, false, false};

constexpr EffectiveCapabilities trackerCaps = resolveCapabilities(tracker.hardware.capabilities, trackerPeripherals);
constexpr EffectiveCapabilities v3Caps = resolveCapabilities(v3.hardware.capabilities, noPeripherals);
constexpr EffectiveCapabilities wioL1Caps = resolveCapabilities(wioL1.hardware.capabilities, noPeripherals);

static_assert(deepestSupportedSleep(trackerCaps) == SleepMode::DEEP_SLEEP,
              "Tracker V1.1 power policy must retain deep-sleep capability");
static_assert(canWakeFromButton(trackerCaps), "Tracker V1.1 power policy must retain button wake");
static_assert(canWakeFromMotion(trackerCaps), "Tracker V1.1 motion peripheral must remain a usable wake capability");

static_assert(deepestSupportedSleep(v3Caps) == SleepMode::DEEP_SLEEP,
              "Heltec V3 power policy must retain deep-sleep capability");
static_assert(canWakeFromButton(v3Caps), "Heltec V3 power policy must retain button wake");
static_assert(!canWakeFromMotion(v3Caps), "Heltec V3 must not invent a motion wake source without a peripheral");

static_assert(deepestSupportedSleep(wioL1Caps) == SleepMode::DEEP_SLEEP,
              "Wio Tracker L1 power policy must remain platform independent");
static_assert(canWakeFromButton(wioL1Caps), "Wio Tracker L1 power policy must retain button wake");

constexpr EffectiveCapabilities lightSleepOnly = {false, {}, false, false, false, false, true, false, false, false, false};
constexpr EffectiveCapabilities noSleep = {};
static_assert(deepestSupportedSleep(lightSleepOnly) == SleepMode::LIGHT_SLEEP,
              "Power policy must fall back to light sleep when deep sleep is unavailable");
static_assert(deepestSupportedSleep(noSleep) == SleepMode::AWAKE,
              "Power policy must stay awake when the platform exposes no sleep support");
static_assert(!supportsSleepMode(SleepMode::DEEP_SLEEP, lightSleepOnly),
              "Core policy must never request unsupported deep sleep");

} // namespace
} // namespace jarnsen
