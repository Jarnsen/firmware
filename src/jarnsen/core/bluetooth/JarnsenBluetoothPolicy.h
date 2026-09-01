#pragma once

#include "jarnsen/core/capabilities/JarnsenCapabilities.h"

#include <stdint.h>

namespace jarnsen
{
namespace bluetooth
{

enum class Lifecycle : uint8_t {
    UNAVAILABLE = 0,
    SUSPENDED,
    ACTIVE,
};

// Hardware-neutral BLE lifecycle. Product/role code decides whether a service
// window is requested; the platform backend decides how that maps to NimBLE,
// SoftDevice, or another Bluetooth implementation.
constexpr Lifecycle desiredLifecycle(const EffectiveCapabilities &caps, bool serviceRequested)
{
    if (!caps.bluetooth)
        return Lifecycle::UNAVAILABLE;
    return serviceRequested ? Lifecycle::ACTIVE : Lifecycle::SUSPENDED;
}

constexpr bool serviceAvailable(const EffectiveCapabilities &caps)
{
    return caps.bluetooth;
}

constexpr bool shouldBeActive(const EffectiveCapabilities &caps, bool serviceRequested)
{
    return desiredLifecycle(caps, serviceRequested) == Lifecycle::ACTIVE;
}

class Backend
{
  public:
    virtual ~Backend() = default;
    virtual void suspend() = 0;
    virtual void resume() = 0;
    virtual void deinit() = 0;
    virtual bool isActive() = 0;
    virtual bool isConnected() = 0;
};

} // namespace bluetooth
} // namespace jarnsen
