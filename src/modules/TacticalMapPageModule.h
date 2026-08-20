#pragma once

#include "configuration.h"

#if defined(HAS_TACTICAL_MAP) && HAS_TACTICAL_MAP && HAS_SCREEN && !MESHTASTIC_EXCLUDE_GPS && !MESHTASTIC_EXCLUDE_POSITIONDB

#include "Observer.h"
#include "input/InputBroker.h"
#include "mesh/MeshModule.h"
#include "mesh/generated/meshtastic/deviceonly.pb.h"

class TacticalMapPageModule : public MeshModule, public Observable<const UIFrameEvent *>
{
  public:
    enum class CenterMode : uint8_t { OWN, MIDPOINT, TARGET };

    TacticalMapPageModule();

  protected:
    bool wantPacket(const meshtastic_MeshPacket *) override { return false; }
    bool wantUIFrame() override;
    Observable<const UIFrameEvent *> *getUIFrameObservable() override { return this; }
    // The map must never trap the tracker's normal page button. Tactical map
    // controls are observed in parallel, while the regular screen controller
    // remains responsible for moving to the next/previous page.
    bool interceptingKeyboardInput() override { return false; }
    void drawFrame(OLEDDisplay *display, OLEDDisplayUiState *state, int16_t x, int16_t y) override;

  private:
    bool active = false;
    int8_t manualZoom = -1;
    uint8_t lastZoom = 0;
    CenterMode centerMode = CenterMode::OWN;
    CallbackObserver<TacticalMapPageModule, const InputEvent *> inputObserver =
        CallbackObserver<TacticalMapPageModule, const InputEvent *>(this, &TacticalMapPageModule::handleInputEvent);

    int handleInputEvent(const InputEvent *event);
    void redraw();
};

#endif
