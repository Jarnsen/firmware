#include "TacticalMenuModule.h"

#if defined(HAS_TACTICAL_MAP) && HAS_TACTICAL_MAP && HAS_SCREEN && !MESHTASTIC_EXCLUDE_POSITIONDB

#include "TacticalTargetManager.h"
#include "graphics/Screen.h"
#include "graphics/ScreenFonts.h"
#include "graphics/SharedUIDisplay.h"

#include <cstdio>
#include <string>

TacticalMenuModule::TacticalMenuModule() : MeshModule("tactical-menu")
{
    if (inputBroker)
        inputObserver.observe(inputBroker);
}

bool TacticalMenuModule::wantUIFrame()
{
    return config.device.role == meshtastic_Config_DeviceConfig_Role_TRACKER ||
           config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER;
}

void TacticalMenuModule::redraw()
{
    UIFrameEvent event;
    event.action = UIFrameEvent::Action::REGENERATE_FRAMESET_BACKGROUND;
    notifyObservers(&event);
    if (screen)
        screen->forceDisplay();
}

void TacticalMenuModule::activateSelected()
{
    TacticalTargetManager &targets = TacticalTargetManager::instance();
    switch (selected) {
    case Item::MODE:
        if (targets.getMode() == TacticalTargetManager::Mode::AUTO)
            targets.lockCurrentNode();
        else
            targets.useAutoTarget();
        break;
    case Item::PREVIOUS:
        targets.cycleNode(-1);
        break;
    case Item::NEXT:
        targets.cycleNode(1);
        break;
    case Item::ENTER_MGRS:
        if (screen) {
            active = false;
            screen->showTextInput("10-digit MGRS", "32ULU1234567890", 300000, [this](const std::string &text) {
                TacticalTargetManager &manager = TacticalTargetManager::instance();
                char message[48];
                if (manager.setManualMgrs(text.c_str())) {
                    snprintf(message, sizeof(message), "TARGET\n%s", manager.getManualMgrs());
                    screen->showSimpleBanner(message, 5000);
                } else {
                    screen->showSimpleBanner("INVALID MGRS\nUse 32ULU1234567890", 5000);
                }
                redraw();
            });
        }
        return;
    default:
        break;
    }
    redraw();
}

int TacticalMenuModule::handleInputEvent(const InputEvent *event)
{
    if (!active || !event)
        return 0;

    const int count = static_cast<int>(Item::COUNT);
    const bool previous = event->inputEvent == INPUT_BROKER_UP || event->inputEvent == INPUT_BROKER_LEFT;
    const bool next = event->inputEvent == INPUT_BROKER_DOWN || event->inputEvent == INPUT_BROKER_RIGHT ||
                      event->inputEvent == INPUT_BROKER_USER_PRESS || event->inputEvent == INPUT_BROKER_SELECT;
    const bool activate = event->inputEvent == INPUT_BROKER_SELECT_LONG || event->inputEvent == INPUT_BROKER_ALT_PRESS ||
                          event->inputEvent == INPUT_BROKER_ALT_LONG;

    if (previous) {
        selected = static_cast<Item>((static_cast<int>(selected) + count - 1) % count);
        redraw();
    } else if (next) {
        selected = static_cast<Item>((static_cast<int>(selected) + 1) % count);
        redraw();
    } else if (activate) {
        activateSelected();
    } else if (event->inputEvent == INPUT_BROKER_BACK || event->inputEvent == INPUT_BROKER_CANCEL) {
        active = false;
        redraw();
    }
    return 0;
}

void TacticalMenuModule::drawFrame(OLEDDisplay *display, OLEDDisplayUiState *, int16_t x, int16_t y)
{
    if (!display)
        return;
    active = true;

    TacticalTargetManager &targets = TacticalTargetManager::instance();
    const char *items[] = {"TARGET MODE", "PREVIOUS TARGET", "NEXT TARGET", "ENTER MGRS"};

    display->clear();
    display->setTextAlignment(TEXT_ALIGN_LEFT);
    display->setFont(FONT_SMALL);
    graphics::drawCommonHeader(display, x, y, "TACTICAL MENU");
    for (int index = 0; index < static_cast<int>(Item::COUNT); ++index) {
        const int16_t rowY = y + 14 + index * 11;
        display->drawString(x + 2, rowY, index == static_cast<int>(selected) ? ">" : " ");
        display->drawString(x + 12, rowY, items[index]);
    }
    display->setTextAlignment(TEXT_ALIGN_RIGHT);
    display->drawString(x + display->getWidth() - 2, y + 14, targets.modeName());
    display->setTextAlignment(TEXT_ALIGN_LEFT);
    display->drawString(x + 2, y + display->getHeight() - FONT_HEIGHT_SMALL, "SHORT:NEXT LONG:OK");
}

#endif
