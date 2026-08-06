#pragma once

#include "configuration.h"

#if defined(HAS_TACTICAL_MAP) && HAS_TACTICAL_MAP && HAS_SCREEN && !MESHTASTIC_EXCLUDE_POSITIONDB

#include "Observer.h"
#include "input/InputBroker.h"
#include "mesh/MeshModule.h"

class TacticalMenuModule : public MeshModule, public Observable<const UIFrameEvent *>
{
  public:
    TacticalMenuModule();

  protected:
    bool wantPacket(const meshtastic_MeshPacket *) override { return false; }
    bool wantUIFrame() override;
    Observable<const UIFrameEvent *> *getUIFrameObservable() override { return this; }
    bool interceptingKeyboardInput() override { return active; }
    void drawFrame(OLEDDisplay *display, OLEDDisplayUiState *state, int16_t x, int16_t y) override;

  private:
    enum class Item : uint8_t { MODE, PREVIOUS, NEXT, ENTER_MGRS, COUNT };
    Item selected = Item::MODE;
    bool active = false;
    uint32_t lastUserPressAt = 0;
    CallbackObserver<TacticalMenuModule, const InputEvent *> inputObserver =
        CallbackObserver<TacticalMenuModule, const InputEvent *>(this, &TacticalMenuModule::handleInputEvent);

    int handleInputEvent(const InputEvent *event);
    void activateSelected();
    void redraw();
};

#endif
