#pragma once

#include "configuration.h"

#if defined(HAS_TACTICAL_MAP) && HAS_TACTICAL_MAP && HAS_SCREEN && !MESHTASTIC_EXCLUDE_GPS && !MESHTASTIC_EXCLUDE_POSITIONDB

#include "mesh/MeshModule.h"
#include "mesh/generated/meshtastic/deviceonly.pb.h"

class TacticalMapPageModule : public MeshModule
{
  public:
    TacticalMapPageModule() : MeshModule("tactical-map-page") {}

  protected:
    bool wantPacket(const meshtastic_MeshPacket *) override { return false; }
    bool wantUIFrame() override;
    void drawFrame(OLEDDisplay *display, OLEDDisplayUiState *state, int16_t x, int16_t y) override;

  private:
    NodeNum selectedNode = 0;

    bool copyTarget(meshtastic_PositionLite &position, char *name, size_t nameSize);
    NodeNum selectNewestPositionedNode() const;
};

#endif
