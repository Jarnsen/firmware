#pragma once

#include "configuration.h"

#if defined(HAS_TACTICAL_DISPLAY_MIRROR) && HAS_TACTICAL_DISPLAY_MIRROR && HAS_SCREEN

class OLEDDisplay;

namespace graphics
{
void mirrorDisplayFrame(OLEDDisplay *display);
}

#endif
