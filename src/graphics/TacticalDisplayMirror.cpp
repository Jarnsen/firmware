#include "TacticalDisplayMirror.h"

#if defined(HAS_TACTICAL_DISPLAY_MIRROR) && HAS_TACTICAL_DISPLAY_MIRROR && HAS_SCREEN

#include <Arduino.h>
#include <OLEDDisplay.h>
#include <algorithm>
#include <cstring>
#include <vector>

namespace graphics
{
namespace
{
constexpr uint32_t MIRROR_INTERVAL_MS = 250;

std::vector<uint8_t> previous;
uint16_t previousWidth = 0;
uint16_t previousHeight = 0;
bool havePrevious = false;
uint32_t lastEmit = 0;
} // namespace

void mirrorDisplayFrame(OLEDDisplay *display)
{
    if (!display || !display->buffer)
        return;

    const uint16_t width = display->getWidth();
    const uint16_t height = display->getHeight();
    if (width == 0 || height == 0 || (height % 8) != 0)
        return;

    const size_t frameBytes = static_cast<size_t>(width) * height / 8;
    const uint32_t now = millis();
    if (havePrevious && static_cast<uint32_t>(now - lastEmit) < MIRROR_INTERVAL_MS)
        return;

    const bool sameGeometry = havePrevious && previousWidth == width && previousHeight == height && previous.size() == frameBytes;
    if (sameGeometry && memcmp(previous.data(), display->buffer, frameBytes) == 0)
        return;

    static constexpr char HEX_DIGITS[] = "0123456789ABCDEF";
    char encoded[64];

    Serial.printf("@TMF %u %u ", static_cast<unsigned>(width), static_cast<unsigned>(height));
    for (size_t offset = 0; offset < frameBytes; offset += 32) {
        const size_t count = std::min<size_t>(32, frameBytes - offset);
        for (size_t i = 0; i < count; ++i) {
            const uint8_t value = display->buffer[offset + i];
            encoded[i * 2] = HEX_DIGITS[value >> 4];
            encoded[i * 2 + 1] = HEX_DIGITS[value & 0x0f];
        }
        Serial.write(reinterpret_cast<const uint8_t *>(encoded), count * 2);
    }
    Serial.write('\n');

    previous.assign(display->buffer, display->buffer + frameBytes);
    previousWidth = width;
    previousHeight = height;
    havePrevious = true;
    lastEmit = now;
}
} // namespace graphics

#endif