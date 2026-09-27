#pragma once

#include "OLEDDisplay.h"
#include "graphics/ScreenFonts.h"

#include <cstdint>
#include <cstdio>

namespace jarnsen
{

// Tracker V1.1 is the visual reference for every transferable six-digit PIN UI.
// Display dimensions may scale the geometry, but controls and presentation stay identical.
inline void drawReferenceSixDigitPin(OLEDDisplay *display, int16_t x, int16_t y, const uint8_t values[6],
                                     uint8_t selected, uint32_t blockedMs, const char *title = "PIN EINGABE")
{
    if (!display || !values)
        return;

    const int16_t screenW = display->getWidth();
    const int16_t screenH = display->getHeight();
    display->clear();
    display->setTextAlignment(TEXT_ALIGN_CENTER);

    if (blockedMs != 0U) {
        display->setFont(FONT_MEDIUM);
        display->drawString(x + screenW / 2, y + 1, "PIN FALSCH");
        char waitText[20] = {};
        std::snprintf(waitText, sizeof(waitText), "NOCH %us", (unsigned)((blockedMs + 999U) / 1000U));
        display->setFont(FONT_SMALL);
        display->drawString(x + screenW / 2, y + 18, waitText);
    } else {
        display->setFont(FONT_SMALL);
        display->drawString(x + screenW / 2, y + 1, title ? title : "PIN EINGABE");
    }

    const int16_t digitW = screenW >= 150 ? 20 : 16;
    const int16_t digitH = screenH >= 72 ? 38 : 28;
    const int16_t thickness = screenW >= 150 ? 4 : 3;
    const int16_t gap = 2;
    const int16_t groupGap = screenW >= 150 ? 6 : 4;
    const int16_t totalW = 6 * digitW + 5 * gap + groupGap;
    const int16_t top = screenH >= 72 ? 29 : 22;
    int16_t left = (screenW - totalW) / 2;

    auto drawSegmentDigit = [display, digitW, digitH, thickness, x, y](uint8_t value, int16_t x0, int16_t y0) {
        static const uint8_t masks[10] = {0x3f, 0x06, 0x5b, 0x4f, 0x66, 0x6d, 0x7d, 0x07, 0x7f, 0x6f};
        if (value > 9U)
            return;
        const uint8_t mask = masks[value];
        const int16_t half = digitH / 2;
        auto segment = [display, x, y](int16_t sx, int16_t sy, int16_t sw, int16_t sh) {
            display->fillRect(x + sx, y + sy, sw, sh);
        };
        if (mask & 0x01) segment(x0 + thickness, y0, digitW - 2 * thickness, thickness);
        if (mask & 0x02) segment(x0 + digitW - thickness, y0 + thickness, thickness, half - thickness);
        if (mask & 0x04) segment(x0 + digitW - thickness, y0 + half, thickness, half - thickness);
        if (mask & 0x08) segment(x0 + thickness, y0 + digitH - thickness, digitW - 2 * thickness, thickness);
        if (mask & 0x10) segment(x0, y0 + half, thickness, half - thickness);
        if (mask & 0x20) segment(x0, y0 + thickness, thickness, half - thickness);
        if (mask & 0x40) segment(x0 + thickness, y0 + half - thickness / 2, digitW - 2 * thickness, thickness);
    };

    for (uint8_t digit = 0; digit < 6U; ++digit) {
        drawSegmentDigit(values[digit], left, top);
        if (blockedMs == 0U && selected == digit)
            display->drawRect(x + left - 2, y + top - 2, digitW + 4, digitH + 4);
        left += digitW;
        if (digit != 5U)
            left += gap;
        if (digit == 2U)
            left += groupGap;
    }
}

inline void splitSixDigitNumber(uint32_t value, uint8_t out[6])
{
    if (!out)
        return;
    value %= 1000000U;
    for (int i = 5; i >= 0; --i) {
        out[i] = (uint8_t)(value % 10U);
        value /= 10U;
    }
}

} // namespace jarnsen
