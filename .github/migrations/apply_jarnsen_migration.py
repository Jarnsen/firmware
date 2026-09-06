from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"Expected exactly one match in {path}, found {count}: {old[:100]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


def write(path: str, content: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# 1) Runtime display adapter for every supported JARNSEN board with a display.
#    Tracker V1.1 keeps its proven advanced TrackerStatusModule implementation;
#    the common adapter owns V3/V4/Wio/T-Beam Supreme and never falls back to
#    stock Meshtastic unless the operator explicitly chooses it.
# ---------------------------------------------------------------------------
write(
    "src/jarnsen/adapters/JarnsenDisplayRuntime.h",
    r'''#pragma once

// Shared runtime ownership bridge for the JARNSEN five-page display.
// These functions are no-ops on unsupported boards and on the Heltec Tracker
// V1.1, whose richer TrackerStatusModule remains the hardware adapter there.
bool jarnsenDisplayOwnsScreen();
bool jarnsenDisplayStockUiActive();
void jarnsenDisplayRequestFocus();
bool jarnsenDisplayHandleFrameStep(bool next);
bool jarnsenDisplayHandleSelect();
bool jarnsenDisplayHandleBack();
''',
)

write(
    "src/jarnsen/adapters/JarnsenDisplayRuntime.cpp",
    r'''#include "jarnsen/adapters/JarnsenDisplayRuntime.h"

#include "configuration.h"

#if HAS_SCREEN && !defined(HELTEC_TRACKER_V1_1) && \
    (defined(HELTEC_V3) || defined(_VARIANT_HELTEC_V3) || defined(HELTEC_V4) || defined(SEEED_WIO_TRACKER_L1) || \
     defined(LILYGO_TBEAM_S3_CORE))

#include "NodeDB.h"
#include "PowerStatus.h"
#include "graphics/Screen.h"
#include "graphics/ScreenFonts.h"
#include "jarnsen/core/display/JarnsenDisplayModel.h"
#include "jarnsen/core/position/JarnsenPositionCore.h"
#include "mesh/Channels.h"
#include "mesh/MeshModule.h"

#include <Arduino.h>
#include <OLEDDisplay.h>
#include <algorithm>
#include <cstdio>
#include <cstring>

namespace
{
using jarnsen::DisplayPage;

enum class MenuView : uint8_t {
    NONE = 0,
    ROOT,
    SYSTEM,
};

DisplayPage currentPage = DisplayPage::MGRS;
MenuView menuView = MenuView::NONE;
uint8_t menuSelection = 0;
bool stockUiActive = false;

const char *boardLabel()
{
#if defined(HELTEC_V3) || defined(_VARIANT_HELTEC_V3)
    return "HELTEC V3";
#elif defined(HELTEC_V4)
    return "HELTEC V4";
#elif defined(SEEED_WIO_TRACKER_L1)
    return "WIO L1";
#elif defined(LILYGO_TBEAM_S3_CORE)
    return "T-BEAM SUPREME";
#else
    return "JARNSEN";
#endif
}

const char *roleLabel()
{
    switch (config.device.role) {
    case meshtastic_Config_DeviceConfig_Role_TAK:
        return "TAK";
    case meshtastic_Config_DeviceConfig_Role_TAK_TRACKER:
        return "TAK TRACKER";
    case meshtastic_Config_DeviceConfig_Role_REPEATER:
        return "REPEATER";
    default:
        return "JARNSEN";
    }
}

const char *regionLabel()
{
    switch (config.lora.region) {
    case meshtastic_Config_LoRaConfig_RegionCode_EU_868:
        return "EU868";
    case meshtastic_Config_LoRaConfig_RegionCode_US:
        return "US";
    default:
        return "REGION";
    }
}

const char *presetLabel()
{
    switch (config.lora.modem_preset) {
    case meshtastic_Config_LoRaConfig_ModemPreset_LONG_FAST:
        return "LONG FAST";
    case meshtastic_Config_LoRaConfig_ModemPreset_LONG_SLOW:
        return "LONG SLOW";
    case meshtastic_Config_LoRaConfig_ModemPreset_MEDIUM_FAST:
        return "MED FAST";
    case meshtastic_Config_LoRaConfig_ModemPreset_MEDIUM_SLOW:
        return "MED SLOW";
    case meshtastic_Config_LoRaConfig_ModemPreset_SHORT_FAST:
        return "SHORT FAST";
    case meshtastic_Config_LoRaConfig_ModemPreset_SHORT_SLOW:
        return "SHORT SLOW";
    default:
        return "CUSTOM";
    }
}

DisplayPage previousPage(DisplayPage page)
{
    switch (page) {
    case DisplayPage::MGRS:
        return DisplayPage::SYSTEM;
    case DisplayPage::NODE_STATUS:
        return DisplayPage::MGRS;
    case DisplayPage::RADIO:
        return DisplayPage::NODE_STATUS;
    case DisplayPage::NETWORK:
        return DisplayPage::RADIO;
    case DisplayPage::SYSTEM:
    case DisplayPage::SERVICE:
    default:
        return DisplayPage::NETWORK;
    }
}

void drawHeader(OLEDDisplay *display, int16_t x, int16_t y, const char *title)
{
    const int w = display->getWidth();
    display->setFont(FONT_SMALL);
    display->setTextAlignment(TEXT_ALIGN_CENTER);
    display->drawString(x + w / 2, y + 1, title);

    if (powerStatus && powerStatus->getHasBattery()) {
        char battery[12] = {};
        std::snprintf(battery, sizeof(battery), "%d%%", powerStatus->getBatteryChargePercent());
        display->setTextAlignment(TEXT_ALIGN_RIGHT);
        display->drawString(x + w - 2, y + 1, battery);
    }
}

void drawPageNumber(OLEDDisplay *display, int16_t x, int16_t y, DisplayPage page)
{
    char text[12] = {};
    std::snprintf(text, sizeof(text), "%u/%u", (unsigned)jarnsen::displayPageNumber(page),
                  (unsigned)jarnsen::displayPageCount());
    display->setFont(FONT_SMALL);
    display->setTextAlignment(TEXT_ALIGN_RIGHT);
    display->drawString(x + display->getWidth() - 2, y + display->getHeight() - 12, text);
}

bool ownPosition(meshtastic_PositionLite &position)
{
    if (!nodeDB)
        return false;
    if (!nodeDB->copyNodePosition(nodeDB->getNodeNum(), position))
        return false;
    return position.latitude_i != 0 || position.longitude_i != 0;
}

void drawMgrs(OLEDDisplay *display, int16_t x, int16_t y)
{
    drawHeader(display, x, y, "MGRS / POSITION");
    const auto bands = jarnsen::displayBands(display->getHeight());
    meshtastic_PositionLite pos = meshtastic_PositionLite_init_default;
    char mgrs[40] = {};

    display->setTextAlignment(TEXT_ALIGN_CENTER);
    if (ownPosition(pos) && jarnsenPositionFormatMgrs10(pos.latitude_i, pos.longitude_i, mgrs, sizeof(mgrs))) {
        display->setFont(FONT_MEDIUM);
        display->drawString(x + display->getWidth() / 2, y + bands.middleY + 4, mgrs);
        display->setFont(FONT_SMALL);
        char coord[44] = {};
        std::snprintf(coord, sizeof(coord), "%.5f  %.5f", pos.latitude_i / 1e7, pos.longitude_i / 1e7);
        display->drawString(x + display->getWidth() / 2, y + bands.bottomY + 1, coord);
    } else {
        display->setFont(FONT_MEDIUM);
        display->drawString(x + display->getWidth() / 2, y + bands.middleY + 8, "KEINE POSITION");
        display->setFont(FONT_SMALL);
        display->drawString(x + display->getWidth() / 2, y + bands.bottomY + 1, "GPS / MESH POSITION --");
    }
    drawPageNumber(display, x, y, DisplayPage::MGRS);
}

void drawNode(OLEDDisplay *display, int16_t x, int16_t y)
{
    drawHeader(display, x, y, "NODE");
    const auto bands = jarnsen::displayBands(display->getHeight());
    char name[40] = "JARNSEN NODE";
    const meshtastic_NodeInfoLite *node = nodeDB ? nodeDB->getMeshNode(nodeDB->getNodeNum()) : nullptr;
    if (node && nodeInfoLiteHasUser(node)) {
        if (node->long_name[0])
            std::snprintf(name, sizeof(name), "%s", node->long_name);
        else if (node->short_name[0])
            std::snprintf(name, sizeof(name), "%s", node->short_name);
    }

    display->setTextAlignment(TEXT_ALIGN_CENTER);
    display->setFont(FONT_MEDIUM);
    display->drawString(x + display->getWidth() / 2, y + bands.middleY + 6, name);
    char bottom[48] = {};
    std::snprintf(bottom, sizeof(bottom), "!%08lx   %s", nodeDB ? (unsigned long)nodeDB->getNodeNum() : 0UL, roleLabel());
    display->setFont(FONT_SMALL);
    display->drawString(x + display->getWidth() / 2, y + bands.bottomY + 1, bottom);
    drawPageNumber(display, x, y, DisplayPage::NODE_STATUS);
}

void drawRadio(OLEDDisplay *display, int16_t x, int16_t y)
{
    drawHeader(display, x, y, "FUNK / LORA");
    const auto bands = jarnsen::displayBands(display->getHeight());
    display->setTextAlignment(TEXT_ALIGN_CENTER);
    display->setFont(FONT_MEDIUM);
    display->drawString(x + display->getWidth() / 2, y + bands.middleY + 6, presetLabel());
    char bottom[48] = {};
    if (config.lora.tx_power > 0)
        std::snprintf(bottom, sizeof(bottom), "%s   TX %ddBm", regionLabel(), (int)config.lora.tx_power);
    else
        std::snprintf(bottom, sizeof(bottom), "%s   TX AUTO", regionLabel());
    display->setFont(FONT_SMALL);
    display->drawString(x + display->getWidth() / 2, y + bands.bottomY + 1, bottom);
    drawPageNumber(display, x, y, DisplayPage::RADIO);
}

void drawNetwork(OLEDDisplay *display, int16_t x, int16_t y)
{
    const char *channel = channels.getName(channels.getPrimaryIndex());
    drawHeader(display, x, y, channel && channel[0] ? channel : "NETZ");
    const auto bands = jarnsen::displayBands(display->getHeight());
    size_t known = 0;
    if (nodeDB) {
        known = nodeDB->getNumMeshNodes();
        if (known > 0)
            --known;
    }
    char middle[32] = {};
    std::snprintf(middle, sizeof(middle), "%u NODES", (unsigned)known);
    display->setTextAlignment(TEXT_ALIGN_CENTER);
    display->setFont(FONT_MEDIUM);
    display->drawString(x + display->getWidth() / 2, y + bands.middleY + 6, middle);
    char bottom[40] = {};
    const size_t online = nodeDB ? nodeDB->getNumOnlineMeshNodes(true) : 0;
    std::snprintf(bottom, sizeof(bottom), "ONLINE %u   MESH READY", (unsigned)online);
    display->setFont(FONT_SMALL);
    display->drawString(x + display->getWidth() / 2, y + bands.bottomY + 1, bottom);
    drawPageNumber(display, x, y, DisplayPage::NETWORK);
}

void drawSystem(OLEDDisplay *display, int16_t x, int16_t y)
{
    drawHeader(display, x, y, "SYSTEM / AKKU");
    const auto bands = jarnsen::displayBands(display->getHeight());
    char middle[48] = {};
    if (powerStatus && powerStatus->getHasBattery())
        std::snprintf(middle, sizeof(middle), "%d%% AKKU", powerStatus->getBatteryChargePercent());
    else if (powerStatus && powerStatus->getHasUSB())
        std::snprintf(middle, sizeof(middle), "USB POWER");
    else
        std::snprintf(middle, sizeof(middle), "POWER --");
    display->setTextAlignment(TEXT_ALIGN_CENTER);
    display->setFont(FONT_MEDIUM);
    display->drawString(x + display->getWidth() / 2, y + bands.middleY + 5, middle);

    char bottom[56] = {};
    const uint32_t uptimeMin = millis() / 60000UL;
    std::snprintf(bottom, sizeof(bottom), "%s   UP %lum", boardLabel(), (unsigned long)uptimeMin);
    display->setFont(FONT_SMALL);
    display->drawString(x + display->getWidth() / 2, y + bands.bottomY + 1, bottom);
    drawPageNumber(display, x, y, DisplayPage::SYSTEM);
}

void drawService(OLEDDisplay *display, int16_t x, int16_t y)
{
    drawHeader(display, x, y, "SERVICE");
    const auto bands = jarnsen::displayBands(display->getHeight());
    display->setTextAlignment(TEXT_ALIGN_CENTER);
    display->setFont(FONT_MEDIUM);
    display->drawString(x + display->getWidth() / 2, y + bands.middleY + 6, "READY");
    display->setFont(FONT_SMALL);
    display->drawString(x + display->getWidth() / 2, y + bands.bottomY + 1,
                        powerStatus && powerStatus->getHasUSB() ? "USB ON   BLE / APP" : "USB --   BLE / APP");
}

uint8_t menuCount()
{
    return menuView == MenuView::SYSTEM ? 3U : 6U;
}

const char *menuLabel(uint8_t index)
{
    if (menuView == MenuView::SYSTEM) {
        static const char *items[] = {"SYSTEM INFO", "MESHTASTIC", "ZURUECK"};
        return items[index % 3U];
    }
    return jarnsen::mainMenuLabel(static_cast<jarnsen::MainMenuItem>(index % 6U));
}

void drawMenu(OLEDDisplay *display, int16_t x, int16_t y)
{
    drawHeader(display, x, y, menuView == MenuView::SYSTEM ? "SYSTEM MENUE" : "MENUE");
    const uint8_t count = menuCount();
    if (menuSelection >= count)
        menuSelection = 0;
    const auto bands = jarnsen::displayBands(display->getHeight());
    char selected[48] = {};
    std::snprintf(selected, sizeof(selected), "> %s", menuLabel(menuSelection));
    display->setTextAlignment(TEXT_ALIGN_CENTER);
    display->setFont(FONT_MEDIUM);
    display->drawString(x + display->getWidth() / 2, y + bands.middleY + 3, selected);
    display->setFont(FONT_SMALL);
    char next[48] = {};
    std::snprintf(next, sizeof(next), "danach: %s", menuLabel((menuSelection + 1U) % count));
    display->drawString(x + display->getWidth() / 2, y + bands.bottomY + 1, next);
}

class JarnsenDisplayModule final : public MeshModule
{
  public:
    JarnsenDisplayModule() : MeshModule("JarnsenCore") {}
    bool wantPacket(const meshtastic_MeshPacket *) override { return false; }
    bool wantUIFrame() override { return true; }
    void requestDisplayFocus() { requestFocus(); }

    void drawFrame(OLEDDisplay *display, OLEDDisplayUiState *, int16_t x, int16_t y) override
    {
        if (!display)
            return;
        if (menuView != MenuView::NONE) {
            drawMenu(display, x, y);
            return;
        }
        switch (currentPage) {
        case DisplayPage::MGRS:
            drawMgrs(display, x, y);
            break;
        case DisplayPage::NODE_STATUS:
            drawNode(display, x, y);
            break;
        case DisplayPage::SERVICE:
            drawService(display, x, y);
            break;
        case DisplayPage::RADIO:
            drawRadio(display, x, y);
            break;
        case DisplayPage::NETWORK:
            drawNetwork(display, x, y);
            break;
        case DisplayPage::SYSTEM:
            drawSystem(display, x, y);
            break;
        default:
            drawMgrs(display, x, y);
            break;
        }
    }
};

JarnsenDisplayModule displayModule;

void redraw()
{
    displayModule.requestDisplayFocus();
    if (screen)
        screen->runNow();
}

void closeMenuTo(DisplayPage page)
{
    currentPage = page;
    menuView = MenuView::NONE;
    menuSelection = 0;
    redraw();
}
} // namespace

bool jarnsenDisplayOwnsScreen()
{
    return true;
}

bool jarnsenDisplayStockUiActive()
{
    return stockUiActive;
}

void jarnsenDisplayRequestFocus()
{
    if (stockUiActive)
        return;
    displayModule.requestDisplayFocus();
    if (screen) {
        screen->setFrames(graphics::Screen::FOCUS_MODULE);
        screen->runNow();
    }
}

bool jarnsenDisplayHandleFrameStep(bool next)
{
    if (stockUiActive)
        return false;
    if (menuView != MenuView::NONE) {
        const uint8_t count = menuCount();
        menuSelection = next ? (uint8_t)((menuSelection + 1U) % count)
                             : (uint8_t)((menuSelection + count - 1U) % count);
    } else {
        currentPage = next ? jarnsen::nextDisplayPage(currentPage) : previousPage(currentPage);
    }
    redraw();
    return true;
}

bool jarnsenDisplayHandleSelect()
{
    if (stockUiActive)
        return false;
    if (menuView == MenuView::NONE) {
        menuView = MenuView::ROOT;
        menuSelection = 0;
        redraw();
        return true;
    }

    if (menuView == MenuView::ROOT) {
        switch (static_cast<jarnsen::MainMenuItem>(menuSelection % 6U)) {
        case jarnsen::MainMenuItem::NODES:
            closeMenuTo(DisplayPage::NETWORK);
            return true;
        case jarnsen::MainMenuItem::PROFILE:
            closeMenuTo(DisplayPage::RADIO);
            return true;
        case jarnsen::MainMenuItem::TRACKER:
            closeMenuTo(DisplayPage::MGRS);
            return true;
        case jarnsen::MainMenuItem::SERVICE:
            closeMenuTo(DisplayPage::SERVICE);
            return true;
        case jarnsen::MainMenuItem::SYSTEM:
            menuView = MenuView::SYSTEM;
            menuSelection = 0;
            redraw();
            return true;
        case jarnsen::MainMenuItem::BACK:
        default:
            menuView = MenuView::NONE;
            menuSelection = 0;
            redraw();
            return true;
        }
    }

    // SYSTEM INFO, MESHTASTIC, ZURUECK
    if (menuSelection == 0U) {
        closeMenuTo(DisplayPage::SYSTEM);
    } else if (menuSelection == 1U) {
        menuView = MenuView::NONE;
        menuSelection = 0;
        stockUiActive = true;
        if (screen) {
            screen->setFrames(graphics::Screen::FOCUS_DEFAULT);
            screen->runNow();
        }
    } else {
        menuView = MenuView::ROOT;
        menuSelection = 0;
        redraw();
    }
    return true;
}

bool jarnsenDisplayHandleBack()
{
    if (stockUiActive) {
        stockUiActive = false;
        menuView = MenuView::NONE;
        currentPage = DisplayPage::MGRS;
        jarnsenDisplayRequestFocus();
        return true;
    }
    if (menuView == MenuView::SYSTEM) {
        menuView = MenuView::ROOT;
        menuSelection = 0;
        redraw();
        return true;
    }
    if (menuView == MenuView::ROOT) {
        menuView = MenuView::NONE;
        menuSelection = 0;
        redraw();
        return true;
    }
    return false;
}

#else

bool jarnsenDisplayOwnsScreen()
{
    return false;
}
bool jarnsenDisplayStockUiActive()
{
    return false;
}
void jarnsenDisplayRequestFocus() {}
bool jarnsenDisplayHandleFrameStep(bool)
{
    return false;
}
bool jarnsenDisplayHandleSelect()
{
    return false;
}
bool jarnsenDisplayHandleBack()
{
    return false;
}

#endif
''',
)

# Give the T-Beam Supreme a stable board marker like the other Unified Core
# targets so common runtime adapters do not have to guess from pin macros.
replace_once(
    "variants/esp32s3/tbeam-s3-core/platformio.ini",
    "build_flags = \n  ${esp32s3_base.build_flags} \n  -I variants/esp32s3/tbeam-s3-core\n",
    "build_flags = \n  ${esp32s3_base.build_flags} \n  -I variants/esp32s3/tbeam-s3-core\n  -D LILYGO_TBEAM_S3_CORE\n",
)

# ---------------------------------------------------------------------------
# 2) Screen ownership: common JARNSEN displays remain on the five-page UI.
#    Stock Meshtastic remains available only via the explicit menu fallback.
# ---------------------------------------------------------------------------
replace_once(
    "src/graphics/Screen.cpp",
    '#include "JarnsenLiveDisplay.h"\n',
    '#include "JarnsenLiveDisplay.h"\n#include "jarnsen/adapters/JarnsenDisplayRuntime.h"\n',
)

replace_once(
    "src/graphics/Screen.cpp",
    '''    if (bootScreenComplete && trackerOwnsScreenAfterBoot() && !showingNormalScreen && focus != FOCUS_MODULE)\n        return;\n\n    // Block setFrames calls when virtual keyboard is active to prevent overlay\n''',
    '''    if (bootScreenComplete && trackerOwnsScreenAfterBoot() && !showingNormalScreen && focus != FOCUS_MODULE)\n        return;\n\n    // V3/V4/Wio/T-Beam Supreme use the common JARNSEN module as the normal\n    // operator UI. Regeneration requests must return to that module instead of\n    // exposing the stock Meshtastic carousel. FOCUS_MODULE is the one allowed\n    // recursive path used by jarnsenDisplayRequestFocus() itself.\n    if (bootScreenComplete && jarnsenDisplayOwnsScreen() && !jarnsenDisplayStockUiActive() && focus != FOCUS_MODULE) {\n        jarnsenDisplayRequestFocus();\n        return;\n    }\n\n    // Block setFrames calls when virtual keyboard is active to prevent overlay\n''',
)

replace_once(
    "src/graphics/Screen.cpp",
    '''        case Cmd::STOP_ALERT_FRAME:\n            NotificationRenderer::pauseBanner = false;\n            // TAK/TAK_TRACKER never fall back to the stock carousel after boot.\n            if (!trackerOwnsScreenAfterBoot() && !showingNormalScreen &&\n                NotificationRenderer::current_notification_type != notificationTypeEnum::text_input) {\n                setFrames();\n            }\n            break;\n        case Cmd::STOP_BOOT_SCREEN:\n            EINK_ADD_FRAMEFLAG(dispdev,\n                               COSMETIC); // E-Ink: Explicitly use full-refresh for next frame\n            bootScreenComplete = true;\n            if (!trackerOwnsScreenAfterBoot() &&\n                NotificationRenderer::current_notification_type != notificationTypeEnum::text_input) {\n                setFrames();\n            }\n            break;\n''',
    '''        case Cmd::STOP_ALERT_FRAME:\n            NotificationRenderer::pauseBanner = false;\n            // Restore the JARNSEN-owned page after transient frames. Only an\n            // explicitly selected stock-UI session is allowed back to Meshtastic.\n            if (jarnsenDisplayOwnsScreen() && !jarnsenDisplayStockUiActive() &&\n                NotificationRenderer::current_notification_type != notificationTypeEnum::text_input) {\n                jarnsenDisplayRequestFocus();\n            } else if (!trackerOwnsScreenAfterBoot() && !showingNormalScreen &&\n                       NotificationRenderer::current_notification_type != notificationTypeEnum::text_input) {\n                setFrames();\n            }\n            break;\n        case Cmd::STOP_BOOT_SCREEN:\n            EINK_ADD_FRAMEFLAG(dispdev,\n                               COSMETIC); // E-Ink: Explicitly use full-refresh for next frame\n            bootScreenComplete = true;\n            if (jarnsenDisplayOwnsScreen() && !jarnsenDisplayStockUiActive() &&\n                NotificationRenderer::current_notification_type != notificationTypeEnum::text_input) {\n                jarnsenDisplayRequestFocus();\n            } else if (!trackerOwnsScreenAfterBoot() &&\n                       NotificationRenderer::current_notification_type != notificationTypeEnum::text_input) {\n                setFrames();\n            }\n            break;\n''',
)

replace_once(
    "src/graphics/Screen.cpp",
    '''void Screen::handleOnPress()\n{\n    // If screen was off, just wake it, otherwise advance to next frame\n    // If we are in a transition, the press must have bounced, drop it.\n    if (ui->getUiState()->frameState == FIXED) {\n        ui->nextFrame();\n        lastScreenTransition = millis();\n        setFastFramerate();\n    }\n}\n''',
    '''void Screen::handleOnPress()\n{\n    // If screen was off, just wake it, otherwise advance to next frame. The\n    // shared JARNSEN module owns page semantics on supported Unified boards.\n    if (ui->getUiState()->frameState == FIXED) {\n        if (jarnsenDisplayHandleFrameStep(true)) {\n            lastScreenTransition = millis();\n            setFastFramerate();\n            return;\n        }\n        ui->nextFrame();\n        lastScreenTransition = millis();\n        setFastFramerate();\n    }\n}\n''',
)

replace_once(
    "src/graphics/Screen.cpp",
    '''void Screen::showFrame(FrameDirection direction)\n{\n    // Only advance frames when UI is stable\n    if (ui->getUiState()->frameState == FIXED) {\n\n#ifdef USERPREFS_UI_TEST_LOG\n''',
    '''void Screen::showFrame(FrameDirection direction)\n{\n    // Only advance frames when UI is stable\n    if (ui->getUiState()->frameState == FIXED) {\n        if (jarnsenDisplayHandleFrameStep(direction == FrameDirection::NEXT)) {\n            lastScreenTransition = millis();\n            setFastFramerate();\n            return;\n        }\n\n#ifdef USERPREFS_UI_TEST_LOG\n''',
)

replace_once(
    "src/graphics/Screen.cpp",
    '''    if (NotificationRenderer::isOverlayBannerShowing()) {\n        NotificationRenderer::inEvent = *event;\n        static OverlayCallback overlays[] = {graphics::UIRenderer::drawNavigationBar, NotificationRenderer::drawBannercallback};\n        ui->setOverlays(overlays, 2);\n        setFastFramerate(); // Draw ASAP\n        updateUiFrame(ui);\n\n        menuHandler::handleMenuSwitch(dispdev);\n        return 0;\n    }\n    // UP/DOWN in message screen scrolls through message threads\n''',
    '''    if (NotificationRenderer::isOverlayBannerShowing()) {\n        NotificationRenderer::inEvent = *event;\n        static OverlayCallback overlays[] = {graphics::UIRenderer::drawNavigationBar, NotificationRenderer::drawBannercallback};\n        ui->setOverlays(overlays, 2);\n        setFastFramerate(); // Draw ASAP\n        updateUiFrame(ui);\n\n        menuHandler::handleMenuSwitch(dispdev);\n        return 0;\n    }\n\n    // Common JARNSEN interaction layer: directional input changes the five\n    // common pages/menu selection, SELECT opens/confirms the JARNSEN menu, and\n    // BACK exits the deliberately selected stock Meshtastic fallback.\n    if (event->inputEvent == INPUT_BROKER_UP && jarnsenDisplayHandleFrameStep(false)) {\n        setFastFramerate();\n        return 0;\n    }\n    if (event->inputEvent == INPUT_BROKER_DOWN && jarnsenDisplayHandleFrameStep(true)) {\n        setFastFramerate();\n        return 0;\n    }\n    if (event->inputEvent == INPUT_BROKER_SELECT && jarnsenDisplayHandleSelect()) {\n        setFastFramerate();\n        return 0;\n    }\n    if (event->inputEvent == INPUT_BROKER_BACK && jarnsenDisplayHandleBack()) {\n        setFastFramerate();\n        return 0;\n    }\n\n    // UP/DOWN in message screen scrolls through message threads\n''',
)

# ---------------------------------------------------------------------------
# 3) Build #141 runner robustness. Each matrix job gets a fresh PlatformIO core
#    directory in RUNNER_TEMP so self-hosted jobs cannot inherit corrupt/global
#    SCons/packages from another workflow or previous build.
# ---------------------------------------------------------------------------
replace_once(
    ".buildkite/run-unified-build-daily.sh",
    '''# PlatformIO 6.2.0 currently pulls SCons 4.11.1 on the Linux runners. That\n# combination aborts ESP32 builds before firmware compilation because the\n# bundled SCons package cannot import SCons.Tool.FortranCommon. Keep Unified\n# Core builds on the last stable 6.1.x release until that upstream regression\n# is resolved. PIP_CONSTRAINT also applies to the nested pip invocation in\n# run-unified-build.sh without duplicating its environment bootstrap.\nPLATFORMIO_CONSTRAINTS="$(mktemp)"\n''',
    '''# Self-hosted runners normally share ~/.platformio across repositories and\n# jobs. A damaged/stale package there caused the intermittent SCons\n# FortranCommon failures seen around Builds 140/141. Give every Unified matrix\n# environment a clean private PlatformIO core directory. The environment name\n# is part of the key so Tracker preflight and each board build are isolated even\n# when the same physical runner executes them sequentially.\nif [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then\n  PIO_TEMP_ROOT="${RUNNER_TEMP:-$PWD/.runner-temp}"\n  PIO_TEMP_KEY="${GITHUB_RUN_ID:-run}-${GITHUB_RUN_ATTEMPT:-1}-${JARNSEN_PIO_ENV:-board}"\n  export PLATFORMIO_CORE_DIR="$PIO_TEMP_ROOT/jarnsen-platformio-$PIO_TEMP_KEY"\n  rm -rf "$PLATFORMIO_CORE_DIR"\n  mkdir -p "$PLATFORMIO_CORE_DIR"\n  printf 'Isolated PlatformIO core: %s\\n' "$PLATFORMIO_CORE_DIR"\nfi\n\n# PlatformIO 6.2.0 currently pulls SCons 4.11.1 on the Linux runners. That\n# combination aborts ESP32 builds before firmware compilation because the\n# bundled SCons package cannot import SCons.Tool.FortranCommon. Keep Unified\n# Core builds on the last stable 6.1.x release until that upstream regression\n# is resolved. PIP_CONSTRAINT also applies to the nested pip invocation in\n# run-unified-build.sh without duplicating its environment bootstrap.\nPLATFORMIO_CONSTRAINTS="$(mktemp)"\n''',
)

# ---------------------------------------------------------------------------
# 4) Build #141 packaging failure. Never assume the ESP32 app starts at 0x10000.
#    Read the actual partition table and verify the update image against the app
#    partition that really contains it. This works across 8/16 MB layouts and is
#    consistent with the later WebFlasher partition-derived logic.
# ---------------------------------------------------------------------------
replace_once(
    ".github/workflows/build-jarn-mesh-unified-core.yml",
    '''          factory_path = Path(sys.argv[2])\n          factory = factory_path.read_bytes()\n          app_offset = 0x10000\n          if len(factory) < app_offset + len(app):\n              raise SystemExit(f"Factory image too small to contain application: {factory_path}")\n          if factory[0x8000:0x8002] != b'\\xaa\\x50':\n              raise SystemExit(f"Factory partition-table magic invalid: {factory_path}")\n          if factory[app_offset] != 0xE9:\n              raise SystemExit(f"Factory application header invalid at 0x{app_offset:x}: {factory_path}")\n          if factory[app_offset:app_offset + len(app)] != app:\n              raise SystemExit(f"Factory application payload does not match update image: {factory_path}")\n\n          print(f"Validated ESP32 application image: {len(app)} bytes")\n''',
    '''          factory_path = Path(sys.argv[2])\n          factory = factory_path.read_bytes()\n          table_offset = 0x8000\n          entry_size = 32\n          table_limit = min(len(factory), table_offset + 0x1000)\n          if factory[table_offset:table_offset + 2] != b'\\xaa\\x50':\n              raise SystemExit(f"Factory partition-table magic invalid: {factory_path}")\n\n          partitions = []\n          for pos in range(table_offset, table_limit, entry_size):\n              raw = factory[pos:pos + entry_size]\n              if len(raw) < entry_size:\n                  break\n              magic = int.from_bytes(raw[0:2], 'little')\n              if magic == 0xFFFF:\n                  break\n              if magic != 0x50AA:\n                  raise SystemExit(f"Invalid partition entry magic 0x{magic:04x} at 0x{pos:x}")\n              p_type = raw[2]\n              subtype = raw[3]\n              offset = int.from_bytes(raw[4:8], 'little')\n              size = int.from_bytes(raw[8:12], 'little')\n              label = raw[12:28].split(b'\\x00', 1)[0].decode('ascii', errors='replace')\n              partitions.append((p_type, subtype, offset, size, label))\n\n          candidates = [\n              p for p in partitions\n              if p[0] == 0x00 and p[3] >= len(app) and len(factory) >= p[2] + len(app)\n          ]\n          matches = [p for p in candidates if factory[p[2]:p[2] + len(app)] == app]\n          if not matches:\n              summary = ', '.join(\n                  f"{p[4] or '?'}:sub=0x{p[1]:02x}@0x{p[2]:x}+0x{p[3]:x}" for p in candidates\n              ) or 'none'\n              raise SystemExit(\n                  f"Factory application payload does not match update image in any app partition; candidates: {summary}"\n              )\n\n          app_part = matches[0]\n          app_offset = app_part[2]\n          if factory[app_offset] != 0xE9:\n              raise SystemExit(f"Factory application header invalid at 0x{app_offset:x}: {factory_path}")\n\n          print(\n              f"Validated ESP32 application image: {len(app)} bytes; "\n              f"partition={app_part[4] or '?'} offset=0x{app_offset:x} size=0x{app_part[3]:x}"\n          )\n''',
)

print("JARNSEN source migration applied successfully")
