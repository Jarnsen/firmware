#include "jarnsen/core/bluetooth/JarnsenBluetoothPolicy.h"
#include "jarnsen/hardware/JarnsenHardwareProfiles.h"

namespace jarnsen
{
namespace bluetooth
{
namespace
{

constexpr HardwareRoleProfile tracker = trackerV11Profile();
constexpr HardwareRoleProfile v3 = heltecV3Profile();
constexpr HardwareRoleProfile wio = seeedWioTrackerL1Profile();
constexpr PeripheralCapabilities none{};

constexpr EffectiveCapabilities trackerCaps = resolveCapabilities(tracker.hardware.capabilities, none);
constexpr EffectiveCapabilities v3Caps = resolveCapabilities(v3.hardware.capabilities, none);
constexpr EffectiveCapabilities wioCaps = resolveCapabilities(wio.hardware.capabilities, none);
constexpr EffectiveCapabilities noBluetooth{};

static_assert(serviceAvailable(trackerCaps), "Tracker V1.1 must expose Bluetooth service capability");
static_assert(desiredLifecycle(trackerCaps, false) == Lifecycle::SUSPENDED,
              "Tracker Bluetooth must suspend outside a service window");
static_assert(desiredLifecycle(trackerCaps, true) == Lifecycle::ACTIVE,
              "Tracker Bluetooth must activate during a service window");
static_assert(shouldBeActive(v3Caps, true), "Heltec V3 Bluetooth service must remain available");
static_assert(shouldBeActive(wioCaps, true), "Wio Tracker L1 Bluetooth service must remain platform independent");
static_assert(desiredLifecycle(noBluetooth, true) == Lifecycle::UNAVAILABLE,
              "Core must not request Bluetooth on hardware without the capability");

} // namespace
} // namespace bluetooth
} // namespace jarnsen
