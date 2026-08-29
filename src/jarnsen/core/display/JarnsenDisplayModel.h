#pragma once

#include <cstdint>

namespace jarnsen
{

enum class DisplayPage : uint8_t {
    MGRS = 0,
    SERVICE,
    RADIO,
    NETWORK,
    SYSTEM,
    COUNT,
};

constexpr DisplayPage nextDisplayPage(DisplayPage page)
{
    const uint8_t next = (static_cast<uint8_t>(page) + 1U) % static_cast<uint8_t>(DisplayPage::COUNT);
    return static_cast<DisplayPage>(next);
}

constexpr const char *displayPageName(DisplayPage page)
{
    switch (page) {
    case DisplayPage::MGRS:
        return "MGRS";
    case DisplayPage::SERVICE:
        return "SERVICE";
    case DisplayPage::RADIO:
        return "FUNK";
    case DisplayPage::NETWORK:
        return "NETZ";
    case DisplayPage::SYSTEM:
        return "SYSTEM";
    default:
        return "?";
    }
}

enum class MainMenuItem : uint8_t {
    NODES = 0,
    PROFILE,
    ANTENNA_TEST,
    TRACKER,
    SERVICE,
    POWER,
    DIAG_SYSTEM,
    BACK,
    COUNT,
};

enum class TrackerMenuItem : uint8_t {
    POSITION = 0,
    MOTION,
    PARKING,
    BACK,
    COUNT,
};

enum class TrackerPositionItem : uint8_t {
    SMART_DISTANCE = 0,
    MIN_TX_INTERVAL,
    MOVING_GNSS,
    BACK,
    COUNT,
};

enum class TrackerMotionItem : uint8_t {
    MOTION_STATUS = 0,
    WAKE_SENSOR,
    BACK,
    COUNT,
};

enum class WakeSensorItem : uint8_t {
    ENABLED = 0,
    SENSITIVITY,
    BACK,
    COUNT,
};

enum class TrackerParkingItem : uint8_t {
    PARK_INTERVAL = 0,
    GPS_SEARCH_TIME,
    BACK,
    COUNT,
};

enum class ServiceMenuItem : uint8_t {
    BLUETOOTH = 0,
    WLAN_SERVICE,
    DIAGNOSTIC_LOG,
    BACK,
    COUNT,
};

enum class BluetoothMenuItem : uint8_t {
    IDLE_TIMEOUT = 0,
    HARD_TIMEOUT,
    BACK,
    COUNT,
};

enum class DiagnosticLogItem : uint8_t {
    STATUS = 0,
    ENABLED,
    USB_EXPORT,
    CLEAR,
    BACK,
    COUNT,
};

enum class SystemMenuItem : uint8_t {
    SYSTEM_INFO = 0,
    DIAGNOSTICS,
    POWER,
    ANTENNA_TEST,
    BACK,
    COUNT,
};

enum class PowerMenuItem : uint8_t {
    STATISTICS = 0,
    INA226,
    BACK,
    COUNT,
};

constexpr const char *mainMenuLabel(MainMenuItem item)
{
    switch (item) {
    case MainMenuItem::NODES:
        return "NODES";
    case MainMenuItem::PROFILE:
        return "PROFIL";
    case MainMenuItem::ANTENNA_TEST:
        return "ANTENNENTEST";
    case MainMenuItem::TRACKER:
        return "TRACKER";
    case MainMenuItem::SERVICE:
        return "SERVICE";
    case MainMenuItem::POWER:
        return "POWER";
    case MainMenuItem::DIAG_SYSTEM:
        return "DIAG / SYSTEM";
    case MainMenuItem::BACK:
        return "ZURUECK";
    default:
        return "?";
    }
}

struct DisplayBands {
    uint16_t topY;
    uint16_t topHeight;
    uint16_t middleY;
    uint16_t middleHeight;
    uint16_t bottomY;
    uint16_t bottomHeight;
};

// Fixed logical 25/50/25 layout. The renderer receives only the actual panel
// height so Tracker TFT and compact OLED adapters use identical semantics.
constexpr DisplayBands displayBands(uint16_t height)
{
    const uint16_t top = height / 4U;
    const uint16_t middle = height / 2U;
    return {0U, top, top, middle, static_cast<uint16_t>(top + middle),
            static_cast<uint16_t>(height - top - middle)};
}

} // namespace jarnsen
