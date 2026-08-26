#pragma once

#include "configuration.h"

#if defined(_VARIANT_HELTEC_V3)
#define JARNSEN_SERVICE_WEB_DEFER_FROM_UI 1
#endif

#if HAS_SCREEN
class OLEDDisplay;
struct OLEDDisplayUiState;
#endif

bool heltecV3ServicePageEnabled();
#if HAS_SCREEN
void heltecV3ServicePageDrawFrame(OLEDDisplay *display, OLEDDisplayUiState *state, int16_t x, int16_t y);
void heltecV3ServiceSetupPageDrawFrame(OLEDDisplay *display, OLEDDisplayUiState *state, int16_t x, int16_t y);
#endif
void heltecV3ServicePageRefresh();
bool heltecV3ServicePageRecentlyVisible();

// GPIO0 is exclusively owned by the V3 policy, so the stock Meshtastic
// selection picker is driven explicitly from that one-button gesture path.
bool heltecV3ServiceMenuActive();
void heltecV3ServiceMenuOpen();
void heltecV3ServiceMenuNext();
void heltecV3ServiceMenuSelect();
void heltecV3ServiceMenuPump();
void heltecV3ServiceMenuClose();
