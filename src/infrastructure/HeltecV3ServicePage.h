#pragma once

#include "configuration.h"

#if HAS_SCREEN
class OLEDDisplay;
struct OLEDDisplayUiState;
#endif

bool heltecV3ServicePageEnabled();
#if HAS_SCREEN
void heltecV3ServicePageDrawFrame(OLEDDisplay *display, OLEDDisplayUiState *state, int16_t x, int16_t y);
#endif
void heltecV3ServicePageRefresh();
bool heltecV3ServicePageRecentlyVisible();
