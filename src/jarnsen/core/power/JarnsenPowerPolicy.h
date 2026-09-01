#pragma once

#include "jarnsen/core/capabilities/JarnsenCapabilities.h"

#include <stdint.h>

namespace jarnsen
{

enum class SleepMode : uint8_t {
    AWAKE = 0,
    LIGHT_SLEEP,
    DEEP_SLEEP,
};

struct WakeCapabilities {
    bool button = false;
    bool motion = false;
};

// Hardware-neutral power policy. The core decides which sleep level and wake
// sources are available; platform code remains responsible for entering sleep
// and configuring the board-specific wake circuitry.
constexpr SleepMode deepestSupportedSleep(const EffectiveCapabilities &caps)
{
    if (caps.deepSleep) {
        return SleepMode::DEEP_SLEEP;
    }
    if (caps.lightSleep) {
        return SleepMode::LIGHT_SLEEP;
    }
    return SleepMode::AWAKE;
}

constexpr bool supportsSleepMode(SleepMode mode, const EffectiveCapabilities &caps)
{
    switch (mode) {
    case SleepMode::DEEP_SLEEP:
        return caps.deepSleep;
    case SleepMode::LIGHT_SLEEP:
        return caps.lightSleep;
    case SleepMode::AWAKE:
    default:
        return true;
    }
}

constexpr WakeCapabilities wakeCapabilities(const EffectiveCapabilities &caps)
{
    return {caps.buttonWake, caps.motion};
}

constexpr bool canWakeFromButton(const EffectiveCapabilities &caps)
{
    return wakeCapabilities(caps).button;
}

constexpr bool canWakeFromMotion(const EffectiveCapabilities &caps)
{
    return wakeCapabilities(caps).motion;
}

} // namespace jarnsen
