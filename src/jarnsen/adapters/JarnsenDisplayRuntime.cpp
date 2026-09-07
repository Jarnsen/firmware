#include "jarnsen/adapters/JarnsenDisplayRuntime.h"

#include "configuration.h"

#if HAS_SCREEN && !defined(HELTEC_TRACKER_V1_1) && \
    (defined(HELTEC_V3) || defined(_VARIANT_HELTEC_V3) || defined(HELTEC_V4) || defined(SEEED_WIO_TRACKER_L1) || \
     defined(TBEAM_V10) || defined(LILYGO_TBEAM_S3_CORE))

#include "NodeDB.h"
#include "PowerStatus.h"
#include "graphics/Screen.h"
#include "graphics/ScreenFonts.h"
#include "jarnsen/core/display/JarnsenDisplayModel.h"
#include "jarnsen/core/mesh/JarnsenRadioProfiles.h"
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
    PROFILE,
    SYSTEM,
};

DisplayPage currentPage = DisplayPage::MGRS;
MenuView menuView = MenuView::NONE;
uint8_t menuSelection = 0;
bool stockUiActive = false;
const char *profileError = nullptr;

const char *boardLabel()
{
#if defined(HELTEC_V3) || defined(_VARIANT_HELTEC_V3)
    return "HELTEC V3";
#elif defined(HELTEC_V4)
    return "HELTEC V4";
#elif defined(SEEED_WIO_TRACKER_L1)
    return "WIO L1";
#elif defined(TBEAM_V10)
    return "T-BEAM";
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
    if (menuView == MenuView::PROFILE)
        return 4U;
    return menuView == MenuView::SYSTEM ? 3U : 6U;
}

const char *menuLabel(uint8_t index)
{
    if (menuView == MenuView::PROFILE) {
        static const char *items[] = {"STANDARD", "JARNSEN 1", "JARNSEN 2", "ZURUECK"};
        return items[index % 4U];
    }
    if (menuView == MenuView::SYSTEM) {
        static const char *items[] = {"SYSTEM INFO", "MESHTASTIC", "ZURUECK"};
        return items[index % 3U];
    }
    return jarnsen::mainMenuLabel(static_cast<jarnsen::MainMenuItem>(index % 6U));
}

void drawMenu(OLEDDisplay *display, int16_t x, int16_t y)
{
    const char *header = menuView == MenuView::PROFILE ? "FUNKPROFIL" : (menuView == MenuView::SYSTEM ? "SYSTEM MENUE" : "MENUE");
    drawHeader(display, x, y, header);
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
    if (menuView == MenuView::PROFILE && profileError)
        std::snprintf(next, sizeof(next), "%s", profileError);
    else if (menuView == MenuView::PROFILE)
        std::snprintf(next, sizeof(next), "aktiv: %s", jarnsen::radioProfileLabel(jarnsen::radioProfileActive()));
    else
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
    profileError = nullptr;
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
        if (menuView == MenuView::PROFILE)
            profileError = nullptr;
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
        profileError = nullptr;
        redraw();
        return true;
    }

    if (menuView == MenuView::ROOT) {
        switch (static_cast<jarnsen::MainMenuItem>(menuSelection % 6U)) {
        case jarnsen::MainMenuItem::NODES:
            closeMenuTo(DisplayPage::NETWORK);
            return true;
        case jarnsen::MainMenuItem::PROFILE:
            menuView = MenuView::PROFILE;
            menuSelection = static_cast<uint8_t>(jarnsen::radioProfileActive());
            profileError = nullptr;
            redraw();
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
            profileError = nullptr;
            redraw();
            return true;
        }
    }

    if (menuView == MenuView::PROFILE) {
        if (menuSelection < 3U) {
            const auto profile = static_cast<jarnsen::RadioProfileSlot>(menuSelection);
            const bool slotExists = jarnsen::radioProfileSlotExists(profile);
            if (jarnsen::radioProfileSelect(profile, true)) {
                closeMenuTo(DisplayPage::RADIO);
            } else {
                profileError = slotExists ? "PROFILWECHSEL FEHLER" : "PROFIL NICHT GESPEICHERT";
                redraw();
            }
        } else {
            menuView = MenuView::ROOT;
            menuSelection = 0;
            profileError = nullptr;
            redraw();
        }
        return true;
    }

    // SYSTEM INFO, MESHTASTIC, ZURUECK
    if (menuSelection == 0U) {
        closeMenuTo(DisplayPage::SYSTEM);
    } else if (menuSelection == 1U) {
        menuView = MenuView::NONE;
        menuSelection = 0;
        profileError = nullptr;
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
        profileError = nullptr;
        currentPage = DisplayPage::MGRS;
        jarnsenDisplayRequestFocus();
        return true;
    }
    if (menuView == MenuView::SYSTEM || menuView == MenuView::PROFILE) {
        menuView = MenuView::ROOT;
        menuSelection = 0;
        profileError = nullptr;
        redraw();
        return true;
    }
    if (menuView == MenuView::ROOT) {
        menuView = MenuView::NONE;
        menuSelection = 0;
        profileError = nullptr;
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
