#pragma once

#include "configuration.h"

#if HAS_SCREEN
class OLEDDisplay;
struct OLEDDisplayUiState;
#endif

bool heltecV3MeshHealthPageEnabled();
bool heltecV3AntennaPageEnabled();
#if HAS_SCREEN
void heltecV3MeshHealthPageDrawFrame(OLEDDisplay *display, OLEDDisplayUiState *state, int16_t x, int16_t y);
void heltecV3AntennaPageDrawFrame(OLEDDisplay *display, OLEDDisplayUiState *state, int16_t x, int16_t y);
#endif
bool heltecV3MeshHealthPageRecentlyVisible();
bool heltecV3AntennaPageRecentlyVisible();
void heltecV3MeshPagesRefresh();
