"""Render the local six-digit Jarnsen PIN picker large and wire native USB auto-log.

The PIN renderer uses most of the available Tracker/V3 panel. The native USB
part intercepts only JARNSEN_TOOL_* ASCII control lines in SerialConsole before
Meshtastic's protobuf state machine can consume them. HELLO is parsed with its
generation/cursor, logged on the node, ACKed to the PC, then starts delta export.
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

# Native ESP32-S3 USB-CDC control path. Capture the dedicated ASCII command
# before StreamAPI sees it. Normal Meshtastic serial frames remain untouched.
SERIAL = Path("src/SerialConsole.cpp")
serial = SERIAL.read_text(encoding="utf-8")

include_anchor = '#include "time.h"\n'
include_block = '''#include "time.h"\n\n#if defined(HELTEC_TRACKER_V1_1)\n#include "vehicle/TrackerDiagnosticLog.h"\n#elif defined(_VARIANT_HELTEC_V3)\n#include "infrastructure/HeltecV3DiagnosticLog.h"\n#endif\n'''
if "JARNSEN_NATIVE_USB_TOOL_LINK" not in serial:
    if serial.count(include_anchor) != 1:
        raise SystemExit("native USB tool-link include anchor missing")
    serial = serial.replace(include_anchor, include_block, 1)

    run_anchor = '''    int32_t delay = runOncePart();\n'''
    run_block = r'''#if defined(HELTEC_TRACKER_V1_1) || defined(_VARIANT_HELTEC_V3)
    // JARNSEN_NATIVE_USB_TOOL_LINK: own only a line beginning with 'J'.
    static char jarnsenToolLine[96] = {};
    static size_t jarnsenToolLineLength = 0;
    static bool jarnsenToolLineActive = false;
    while (Port.available() > 0) {
        const int next = Port.peek();
        if (!jarnsenToolLineActive && next != 'J')
            break;
        const int raw = Port.read();
        if (raw < 0)
            break;
        const char c = static_cast<char>(raw);
        jarnsenToolLineActive = true;
        if (c == '\r')
            continue;
        if (c == '\n') {
            jarnsenToolLine[jarnsenToolLineLength] = '\0';
            unsigned generation = 0;
            unsigned cursor = 0;
            const bool hello = sscanf(jarnsenToolLine, "JARNSEN_TOOL_HELLO 1 %u %u", &generation, &cursor) == 2;
            const bool full = strcmp(jarnsenToolLine, "JARNSEN_TOOL_FULL 1") == 0;
            if (hello) {
#if defined(HELTEC_TRACKER_V1_1)
                trackerDiagLog("TOOL_USB", "hello received generation=%u cursor=%u", generation, cursor);
#elif defined(_VARIANT_HELTEC_V3)
                heltecV3DiagLog("TOOL_USB", "hello received generation=%u cursor=%u", generation, cursor);
#endif
                char ack[96] = {};
                const int ackLen = snprintf(ack, sizeof(ack), "JARNSEN_TOOL_ACK 1 HELLO %u %u\r\n", generation, cursor);
                if (ackLen > 0) {
                    Port.write((const uint8_t *)ack, (size_t)ackLen);
                    Port.flush();
                }
#if defined(HELTEC_TRACKER_V1_1)
                trackerDiagRequestUsbExportFrom(generation, cursor, false);
#elif defined(_VARIANT_HELTEC_V3)
                heltecV3DiagRequestUsbExportFrom(generation, cursor, false);
#endif
            } else if (full) {
#if defined(HELTEC_TRACKER_V1_1)
                trackerDiagLog("TOOL_USB", "full request received");
#elif defined(_VARIANT_HELTEC_V3)
                heltecV3DiagLog("TOOL_USB", "full request received");
#endif
                static const char ack[] = "JARNSEN_TOOL_ACK 1 FULL\r\n";
                Port.write((const uint8_t *)ack, sizeof(ack) - 1U);
                Port.flush();
#if defined(HELTEC_TRACKER_V1_1)
                trackerDiagRequestUsbExportFrom(0, 0, true);
#elif defined(_VARIANT_HELTEC_V3)
                heltecV3DiagRequestUsbExportFrom(0, 0, true);
#endif
            }
            jarnsenToolLineLength = 0;
            jarnsenToolLineActive = false;
            continue;
        }
        if (jarnsenToolLineLength + 1 < sizeof(jarnsenToolLine)) {
            jarnsenToolLine[jarnsenToolLineLength++] = c;
        } else {
            jarnsenToolLineLength = 0;
            jarnsenToolLineActive = false;
        }
    }
    if (jarnsenToolLineActive)
        return 2;
#endif

    int32_t delay = runOncePart();
'''
    if serial.count(run_anchor) != 1:
        raise SystemExit(f"native USB tool-link run anchor expected once, got {serial.count(run_anchor)}")
    serial = serial.replace(run_anchor, run_block, 1)

for marker in (
    "JARNSEN_NATIVE_USB_TOOL_LINK",
    "JARNSEN_TOOL_ACK 1 HELLO",
    "TOOL_USB",
    "trackerDiagRequestUsbExportFrom(generation, cursor, false);",
    "heltecV3DiagRequestUsbExportFrom(generation, cursor, false);",
):
    if marker not in serial:
        raise SystemExit(f"native USB tool-link validation failed: {marker}")
SERIAL.write_text(serial, encoding="utf-8")
print("Jarnsen native USB HELLO now logs RX, ACKs the PC and preserves delta cursor")
