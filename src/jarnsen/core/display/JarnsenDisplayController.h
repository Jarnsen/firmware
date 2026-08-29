#pragma once

#include "jarnsen/core/capabilities/JarnsenCapabilities.h"
#include "jarnsen/core/display/JarnsenDisplayModel.h"

#include <cstdint>

namespace jarnsen
{

// Hardware-independent interaction state for the five Jarnsen pages. Board
// adapters only translate their physical button/input events into shortPress()
// and longPress(); they do not own page/menu semantics.
enum class DisplayInteractionMode : uint8_t {
    NORMAL = 0,
    MENU,
    NODE_NAVIGATION,
    MESHTASTIC_UI,
};

enum class MenuSection : uint8_t {
    ROOT = 0,
    PROFILE,
    TRACKER,
    TRACKER_POSITION,
    TRACKER_MOTION,
    TRACKER_PARKING,
    SERVICE,
    BLUETOOTH,
    WLAN_SERVICE,
    DIAGNOSTIC_LOG,
    SYSTEM,
    POWER,
};

struct DisplayControllerState {
    DisplayPage page = DisplayPage::MGRS;
    DisplayInteractionMode mode = DisplayInteractionMode::NORMAL;
    MenuSection section = MenuSection::ROOT;
    uint8_t selection = 0;
};

constexpr bool hasTrackerPositionMenu(const EffectiveCapabilities &caps)
{
    return caps.gps;
}

// Motion itself is logical/Core state and must not be tied to a sensor. The
// physical motion sensor is only an optional wake source and therefore only
// controls visibility of the WAKE SENSOR entry.
constexpr bool hasMotionMenu(const EffectiveCapabilities &)
{
    return true;
}

constexpr bool hasWakeSensorMenu(const EffectiveCapabilities &caps)
{
    return caps.motion;
}

constexpr bool hasBluetoothMenu(const EffectiveCapabilities &caps)
{
    return caps.bluetooth;
}

constexpr bool hasWlanServiceMenu(const EffectiveCapabilities &caps)
{
    return caps.wifi;
}

constexpr bool hasIna226Menu(const EffectiveCapabilities &caps)
{
    return caps.ina226;
}

constexpr bool hasPowerMenu(const EffectiveCapabilities &caps)
{
    return caps.battery || caps.usbPowerDetect || caps.ina226;
}

constexpr uint8_t rootMenuCount()
{
    // NODES, PROFIL, TRACKER, SERVICE, SYSTEM, ZURUECK
    return 6;
}

constexpr const char *rootMenuLabel(uint8_t index)
{
    switch (index % rootMenuCount()) {
    case 0:
        return "NODES";
    case 1:
        return "PROFIL";
    case 2:
        return "TRACKER";
    case 3:
        return "SERVICE";
    case 4:
        return "SYSTEM";
    default:
        return "ZURUECK";
    }
}

class DisplayController
{
  public:
    constexpr DisplayController() = default;

    constexpr const DisplayControllerState &state() const { return state_; }

    constexpr void reset()
    {
        state_ = {};
    }

    constexpr void showPage(DisplayPage page)
    {
        state_.page = page;
        state_.mode = DisplayInteractionMode::NORMAL;
        state_.section = MenuSection::ROOT;
        state_.selection = 0;
    }

    constexpr void shortPress()
    {
        if (state_.mode == DisplayInteractionMode::NORMAL) {
            state_.page = nextDisplayPage(state_.page);
            return;
        }

        // Menu and node-list adapters can clamp this against their dynamic
        // visible-item count. The common controller deliberately has no access
        // to runtime node data.
        if (state_.mode == DisplayInteractionMode::MENU)
            ++state_.selection;
    }

    constexpr void openMenu()
    {
        state_.mode = DisplayInteractionMode::MENU;
        state_.section = MenuSection::ROOT;
        state_.selection = 0;
    }

    constexpr void enterMenu(MenuSection section)
    {
        state_.mode = DisplayInteractionMode::MENU;
        state_.section = section;
        state_.selection = 0;
    }

    constexpr void enterNodeNavigation()
    {
        state_.mode = DisplayInteractionMode::NODE_NAVIGATION;
        state_.selection = 0;
    }

    constexpr void enterMeshtasticUi()
    {
        state_.mode = DisplayInteractionMode::MESHTASTIC_UI;
        state_.selection = 0;
    }

    constexpr void backToPages()
    {
        state_.mode = DisplayInteractionMode::NORMAL;
        state_.section = MenuSection::ROOT;
        state_.selection = 0;
    }

  private:
    DisplayControllerState state_{};
};

} // namespace jarnsen
