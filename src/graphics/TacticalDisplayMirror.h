#pragma once

#include "configuration.h"

#if defined(HAS_TACTICAL_DISPLAY_MIRROR) && HAS_TACTICAL_DISPLAY_MIRROR && HAS_SCREEN

#include <cstddef>
#include <cstdint>

class OLEDDisplay;

namespace graphics
{
void mirrorDisplayFrame(OLEDDisplay *display);
void prioritizeMirrorInput();

// RGB565 tactical-frame helpers. The current USB transport uses short @TMF3
// chunks for both monochrome and colour frames; the PC viewer still accepts
// complete legacy @TMF/@TMF2 records from older firmware.
void beginTacticalColorFrame(uint16_t width, uint16_t height, uint16_t backgroundRgb565);
void setTacticalColorPixel(int16_t x, int16_t y, uint16_t rgb565);
void drawTacticalColorLine(int16_t x1, int16_t y1, int16_t x2, int16_t y2, uint16_t rgb565);
void drawTacticalColorCircle(int16_t centerX, int16_t centerY, int16_t radius, uint16_t rgb565);
void overlayTacticalMonoBuffer(OLEDDisplay *display, uint16_t foregroundRgb565, uint16_t onlyOverRgb565);
void publishTacticalColorFrame();

// The physical colour TFT consumes the same published RGB565 frame as the PC
// mirror. Row copies avoid allocating a second full-screen framebuffer.
bool getTacticalColorFrameInfo(const uint8_t *monoBuffer, size_t monoBytes, uint16_t &width, uint16_t &height,
                               uint32_t &sequence);
bool copyTacticalColorFrameRows(uint32_t sequence, uint16_t startRow, uint16_t rowCount, uint16_t *destination,
                                size_t destinationPixels);
} // namespace graphics

#endif
