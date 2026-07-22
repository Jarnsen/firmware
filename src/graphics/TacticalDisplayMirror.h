#pragma once

#include "configuration.h"

#if defined(HAS_TACTICAL_DISPLAY_MIRROR) && HAS_TACTICAL_DISPLAY_MIRROR && HAS_SCREEN

#include <cstdint>

class OLEDDisplay;

namespace graphics
{
void mirrorDisplayFrame(OLEDDisplay *display);

// RGB565 tactical-frame helpers. The normal Meshtastic UI remains compatible
// with the legacy monochrome @TMF protocol; tactical pages can publish an
// exact colour frame through @TMF2.
void beginTacticalColorFrame(uint16_t width, uint16_t height, uint16_t backgroundRgb565);
void setTacticalColorPixel(int16_t x, int16_t y, uint16_t rgb565);
void drawTacticalColorLine(int16_t x1, int16_t y1, int16_t x2, int16_t y2, uint16_t rgb565);
void drawTacticalColorCircle(int16_t centerX, int16_t centerY, int16_t radius, uint16_t rgb565);
void overlayTacticalMonoBuffer(OLEDDisplay *display, uint16_t foregroundRgb565, uint16_t onlyOverRgb565);
void publishTacticalColorFrame();
}

#endif
