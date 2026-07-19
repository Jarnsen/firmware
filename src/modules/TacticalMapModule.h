#pragma once

#include "Observer.h"
#include "mesh/MeshModule.h"

#if HAS_SCREEN && !MESHTASTIC_EXCLUDE_GPS && !MESHTASTIC_EXCLUDE_POSITIONDB

class TacticalMapModule : public MeshModule, public Observable<const UIFrameEvent *>
{
  public:
    TacticalMapModule();

  protected:
    bool wantPacket(const meshtastic_MeshPacket *p) override { return false; }
    bool wantUIFrame() override { return true; }
    Observable<const UIFrameEvent *> *getUIFrameObservable() override { return this; }
    void drawFrame(OLEDDisplay *display, OLEDDisplayUiState *state, int16_t x, int16_t y) override;

  private:
    uint32_t selectedNode = 0;
    uint32_t lastSelectionAt = 0;

    uint32_t selectNextPositionedNode(uint32_t ownNode);
    const meshtastic_NodeInfoLite *findNode(uint32_t nodeNum) const;
    static void formatMgrs10(int32_t latitudeI, int32_t longitudeI, char *out, size_t outSize);
    static uint16_t degreesToMil(float degrees);
    static const char *formatDistance(float meters, char *out, size_t outSize);
    static uint32_t positionAgeSeconds(const meshtastic_PositionLite &position);
};

extern TacticalMapModule *tacticalMapModule;

#endif
