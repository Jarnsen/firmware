"""Render the local six-digit Jarnsen PIN picker large on Tracker V1.1 / Heltec V3.

Input semantics stay in NotificationRenderer::drawNumberPicker; this patch only
replaces the final generic notification-box drawing for the dedicated "PIN"
six-digit picker. The digits use a compact seven-segment renderer sized from
the actual display dimensions, so Tracker 160x80 and V3 128x64 both use most
of their available panel area.
"""
from pathlib import Path

TARGET = Path("src/graphics/draw/NotificationRenderer.cpp")
source = TARGET.read_text(encoding="utf-8")

anchor = '''    if (alertBannerMessage[0] == '\\0')
        return;

    uint16_t totalLines = lineCount + 2;
'''

replacement = r'''    if (alertBannerMessage[0] == '\0')
        return;

#if defined(HELTEC_TRACKER_V1_1) || defined(_VARIANT_HELTEC_V3)
    // The local Jarnsen service/full-lock PIN is always six decimal digits.
    // Give it a dedicated full-panel renderer instead of squeezing it into the
    // generic notification box. Input handling above remains unchanged.
    if (numDigits == 6 && strcmp(alertBannerMessage, "PIN") == 0) {
        display->clear();
        const int16_t screenW = display->getWidth();
        const int16_t screenH = display->getHeight();
        const bool wideTracker = screenW >= 150 && screenH >= 72;
        const int16_t digitW = wideTracker ? 20 : 16;
        const int16_t digitH = wideTracker ? 42 : 30;
        const int16_t thickness = wideTracker ? 4 : 3;
        const int16_t gap = 2;
        const int16_t groupGap = wideTracker ? 6 : 4;
        const int16_t totalW = 6 * digitW + 5 * gap + groupGap;
        const int16_t top = wideTracker ? 28 : 21;
        int16_t left = (screenW - totalW) / 2;

        display->setTextAlignment(TEXT_ALIGN_CENTER);
        display->setFont(FONT_SMALL);
        display->drawString(screenW / 2, 1, "PIN EINGABE");

        auto drawSegmentDigit = [display, digitW, digitH, thickness](uint8_t value, int16_t x0, int16_t y0) {
            static const uint8_t masks[10] = {0x3f, 0x06, 0x5b, 0x4f, 0x66, 0x6d, 0x7d, 0x07, 0x7f, 0x6f};
            if (value > 9)
                return;
            const uint8_t mask = masks[value];
            const int16_t half = digitH / 2;
            auto segment = [display](int16_t sx, int16_t sy, int16_t sw, int16_t sh) {
                display->fillRect(sx, sy, sw, sh);
            };
            if (mask & 0x01) segment(x0 + thickness, y0, digitW - 2 * thickness, thickness);
            if (mask & 0x02) segment(x0 + digitW - thickness, y0 + thickness, thickness, half - thickness);
            if (mask & 0x04) segment(x0 + digitW - thickness, y0 + half, thickness, half - thickness);
            if (mask & 0x08) segment(x0 + thickness, y0 + digitH - thickness, digitW - 2 * thickness, thickness);
            if (mask & 0x10) segment(x0, y0 + half, thickness, half - thickness);
            if (mask & 0x20) segment(x0, y0 + thickness, thickness, half - thickness);
            if (mask & 0x40) segment(x0 + thickness, y0 + half - thickness / 2, digitW - 2 * thickness, thickness);
        };

        for (uint8_t digit = 0; digit < 6; ++digit) {
            const uint8_t value = (currentNumber % pow_of_10(6 - digit)) / pow_of_10(5 - digit);
            drawSegmentDigit(value, left, top);
            if (curSelected == static_cast<int8_t>(digit)) {
                display->drawRect(left - 2, top - 2, digitW + 4, digitH + 4);
                display->setFont(FONT_SMALL);
                display->drawString(left + digitW / 2, screenH - FONT_HEIGHT_SMALL + 2, "^");
            }
            left += digitW;
            if (digit != 5)
                left += gap;
            if (digit == 2)
                left += groupGap;
        }
        return;
    }
#endif

    uint16_t totalLines = lineCount + 2;
'''

if "PIN EINGABE" not in source:
    # The generic notification-box tail appears in number, hex and alphanumeric
    # pickers. Restrict the replacement to drawNumberPicker instead of requiring
    # the anchor to be globally unique in NotificationRenderer.cpp.
    function_start = source.find("void NotificationRenderer::drawNumberPicker(")
    function_end = source.find("\nvoid NotificationRenderer::drawHexPicker(", function_start)
    if function_start < 0 or function_end < 0:
        raise SystemExit("drawNumberPicker function boundaries not found")
    number_picker = source[function_start:function_end]
    anchor_count = number_picker.count(anchor)
    if anchor_count != 1:
        raise SystemExit(f"large PIN picker anchor expected once in drawNumberPicker, got {anchor_count}")
    number_picker = number_picker.replace(anchor, replacement, 1)
    source = source[:function_start] + number_picker + source[function_end:]

for marker in (
    'numDigits == 6 && strcmp(alertBannerMessage, "PIN") == 0',
    'const bool wideTracker = screenW >= 150 && screenH >= 72;',
    'display->drawString(screenW / 2, 1, "PIN EINGABE");',
    'display->drawRect(left - 2, top - 2, digitW + 4, digitH + 4);',
):
    if marker not in source:
        raise SystemExit(f"missing large PIN picker marker: {marker}")

TARGET.write_text(source, encoding="utf-8")
print("Large six-digit Jarnsen local PIN picker enabled")
