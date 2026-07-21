#include "TacticalDisplayMirror.h"

#if defined(HAS_TACTICAL_DISPLAY_MIRROR) && HAS_TACTICAL_DISPLAY_MIRROR && HAS_SCREEN

#include <Arduino.h>
#include <OLEDDisplay.h>
#include <algorithm>
#include <cstring>

namespace graphics
{
namespace
{
constexpr uint16_t MIRROR_WIDTH = 128;
constexpr uint16_t MIRROR_HEIGHT = 64;
constexpr size_t MIRROR_BYTES = MIRROR_WIDTH * MIRROR_HEIGHT / 8;
constexpr uint32_t MIRROR_INTERVAL_MS = 250;

uint8_t previous[MIRROR_BYTES] = {};
bool havePrevious = false;
uint32_t lastEmit = 0;
} // namespace

void mirrorDisplayFrame(OLEDDisplay *display)
{
    if (!display || !display->buffer || display->getWidth() != MIRROR_WIDTH || display->getHeight() != MIRROR_HEIGHT)
        return;

    const uint32_t now = millis();
    if (havePrevious && static_cast<uint32_t>(now - lastEmit) < MIRROR_INTERVAL_MS)
        return;
    if (havePrevious && memcmp(previous, display->buffer, MIRROR_BYTES) == 0)
        return;

    static constexpr char HEX_DIGITS[] = "0123456789ABCDEF";
    char encoded[64];

    Serial.printf("@TMF %u %u ", static_cast<unsigned>(MIRROR_WIDTH), static_cast<unsigned>(MIRROR_HEIGHT));
    for (size_t offset = 0; offset < MIRROR_BYTES; offset += 32) {
        const size_t count = std::min<size_t>(32, MIRROR_BYTES - offset);
        for (size_t i = 0; i < count; ++i) {
            const uint8_t value = display->buffer[offset + i];
            encoded[i * 2] = HEX_DIGITS[value >> 4];
            encoded[i * 2 + 1] = HEX_DIGITS[value & 0x0f];
        }
        Serial.write(reinterpret_cast<const uint8_t *>(encoded), count * 2);
    }
    Serial.write('\n');

    memcpy(previous, display->buffer, MIRROR_BYTES);
    havePrevious = true;
    lastEmit = now;
}
} // namespace graphics

#endif
