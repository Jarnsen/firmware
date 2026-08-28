#pragma once

#include <stdint.h>

namespace jarnsen
{

enum class HardwareKind : uint8_t {
    UNKNOWN = 0,
    HELTEC_TRACKER_V11,
    HELTEC_V3,
};

struct BoardCapabilities {
    bool internalGps = false;
    bool supportsExternalGps = false;
    bool display = false;
    bool bluetooth = false;
    bool wifi = false;
    bool battery = false;
    bool usbPowerDetect = false;
    bool lightSleep = false;
    bool deepSleep = false;
    bool buttonWake = false;
    bool supportsMotion = false;
    bool supportsIna226 = false;
};

struct PeripheralCapabilities {
    bool externalGps = false;
    bool motion = false;
    bool ina226 = false;
};

struct EffectiveCapabilities {
    bool gps = false;
    bool display = false;
    bool bluetooth = false;
    bool wifi = false;
    bool battery = false;
    bool usbPowerDetect = false;
    bool lightSleep = false;
    bool deepSleep = false;
    bool buttonWake = false;
    bool motion = false;
    bool ina226 = false;
};

constexpr EffectiveCapabilities resolveCapabilities(const BoardCapabilities &board, const PeripheralCapabilities &peripherals)
{
    return {
        board.internalGps || (board.supportsExternalGps && peripherals.externalGps),
        board.display,
        board.bluetooth,
        board.wifi,
        board.battery,
        board.usbPowerDetect,
        board.lightSleep,
        board.deepSleep,
        board.buttonWake,
        board.supportsMotion && peripherals.motion,
        board.supportsIna226 && peripherals.ina226,
    };
}

struct HardwareProfile {
    HardwareKind kind = HardwareKind::UNKNOWN;
    const char *code = "UNKNOWN";
    const char *displayName = "Unknown";
    BoardCapabilities capabilities{};
};

} // namespace jarnsen
