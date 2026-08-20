#pragma once

#include "configuration.h"

#if defined(HAS_TACTICAL_MAP) && HAS_TACTICAL_MAP && HAS_SCREEN && !MESHTASTIC_EXCLUDE_GPS && !MESHTASTIC_EXCLUDE_POSITIONDB

#include "mesh/MeshModule.h"

class TacticalMapModule : public MeshModule
{
  public:
    TacticalMapModule();

  protected:
    bool wantPacket(const meshtastic_MeshPacket *) override { return false; }
    bool wantUIFrame() override;
    void drawFrame(OLEDDisplay *display, OLEDDisplayUiState *state, int16_t x, int16_t y) override;
};

#endif
