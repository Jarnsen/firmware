#include "TacticalDisplayMirror.h"

#if defined(HAS_TACTICAL_DISPLAY_MIRROR) && HAS_TACTICAL_DISPLAY_MIRROR && HAS_SCREEN

#include "concurrency/Lock.h"
#include "concurrency/LockGuard.h"

#include <Arduino.h>
#include <OLEDDisplay.h>
#include <algorithm>
#include <cmath>
#include <cstring>
#include <vector>

namespace graphics
{
namespace
{
constexpr uint32_t MIRROR_INTERVAL_MS = 250;

std::vector<uint8_t> previousMono;
uint16_t previousWidth = 0;
uint16_t previousHeight = 0;
bool havePreviousMono = false;
uint32_t lastEmit = 0;

concurrency::Lock colorLock;
std::vector<uint16_t> colorWorking;
std::vector<uint16_t> colorPublished;
uint16_t colorWidth = 0;
uint16_t colorHeight = 0;
uint32_t colorSequence = 0;
uint32_t emittedColorSequence = 0;
bool colorBuilding = false;

void emitHexByte(uint8_t value)
{
    static constexpr char HEX_DIGITS[] = "0123456789ABCDEF";
    char encoded[2] = {HEX_DIGITS[value >> 4], HEX_DIGITS[value & 0x0f]};
    Serial.write(reinterpret_cast<const uint8_t *>(encoded), sizeof(encoded));
}

void emitColorFrame(const std::vector<uint16_t> &pixels, uint16_t width, uint16_t height, uint32_t sequence)
{
    Serial.printf("@TMF2 %u %u %lu ", static_cast<unsigned>(width), static_cast<unsigned>(height),
                  static_cast<unsigned long>(sequence));

    // PackBits-style RGB565 RLE. Each run is: count, color-high, color-low.
    // A 160x80 flat map background becomes only three bytes, while complex
    // pages still remain substantially smaller than uncompressed RGB565 hex.
    size_t offset = 0;
    while (offset < pixels.size()) {
        const uint16_t color = pixels[offset];
        uint8_t count = 1;
        while (offset + count < pixels.size() && pixels[offset + count] == color && count < 255)
            ++count;

        emitHexByte(count);
        emitHexByte(static_cast<uint8_t>(color >> 8));
        emitHexByte(static_cast<uint8_t>(color & 0xff));
        offset += count;
    }
    Serial.write('\n');
}
} // namespace

void beginTacticalColorFrame(uint16_t width, uint16_t height, uint16_t backgroundRgb565)
{
    if (!width || !height)
        return;
    concurrency::LockGuard guard(&colorLock);
    colorWidth = width;
    colorHeight = height;
    colorWorking.assign(static_cast<size_t>(width) * height, backgroundRgb565);
    colorBuilding = true;
}

void setTacticalColorPixel(int16_t x, int16_t y, uint16_t rgb565)
{
    concurrency::LockGuard guard(&colorLock);
    if (!colorBuilding || x < 0 || y < 0 || x >= colorWidth || y >= colorHeight)
        return;
    colorWorking[static_cast<size_t>(y) * colorWidth + x] = rgb565;
}

void drawTacticalColorLine(int16_t x1, int16_t y1, int16_t x2, int16_t y2, uint16_t rgb565)
{
    concurrency::LockGuard guard(&colorLock);
    if (!colorBuilding)
        return;

    int dx = std::abs(x2 - x1);
    const int sx = x1 < x2 ? 1 : -1;
    int dy = -std::abs(y2 - y1);
    const int sy = y1 < y2 ? 1 : -1;
    int error = dx + dy;

    while (true) {
        if (x1 >= 0 && y1 >= 0 && x1 < colorWidth && y1 < colorHeight)
            colorWorking[static_cast<size_t>(y1) * colorWidth + x1] = rgb565;
        if (x1 == x2 && y1 == y2)
            break;
        const int doubled = error * 2;
        if (doubled >= dy) {
            error += dy;
            x1 += sx;
        }
        if (doubled <= dx) {
            error += dx;
            y1 += sy;
        }
    }
}

void drawTacticalColorCircle(int16_t centerX, int16_t centerY, int16_t radius, uint16_t rgb565)
{
    if (radius < 0)
        return;
    concurrency::LockGuard guard(&colorLock);
    if (!colorBuilding)
        return;

    int x = radius;
    int y = 0;
    int error = 1 - radius;
    auto pixel = [&](int16_t px, int16_t py) {
        if (px >= 0 && py >= 0 && px < colorWidth && py < colorHeight)
            colorWorking[static_cast<size_t>(py) * colorWidth + px] = rgb565;
    };

    while (x >= y) {
        pixel(centerX + x, centerY + y);
        pixel(centerX + y, centerY + x);
        pixel(centerX - y, centerY + x);
        pixel(centerX - x, centerY + y);
        pixel(centerX - x, centerY - y);
        pixel(centerX - y, centerY - x);
        pixel(centerX + y, centerY - x);
        pixel(centerX + x, centerY - y);
        ++y;
        if (error < 0) {
            error += 2 * y + 1;
        } else {
            --x;
            error += 2 * (y - x + 1);
        }
    }
}

void publishTacticalColorFrame()
{
    concurrency::LockGuard guard(&colorLock);
    if (!colorBuilding || colorWorking.empty())
        return;
    colorPublished = colorWorking;
    colorBuilding = false;
    ++colorSequence;
}

void mirrorDisplayFrame(OLEDDisplay *display)
{
    if (!display || !display->buffer)
        return;

    const uint32_t now = millis();
    if (static_cast<uint32_t>(now - lastEmit) < MIRROR_INTERVAL_MS)
        return;

    std::vector<uint16_t> colorCopy;
    uint16_t publishedWidth = 0;
    uint16_t publishedHeight = 0;
    uint32_t publishedSequence = 0;
    {
        concurrency::LockGuard guard(&colorLock);
        if (colorSequence != emittedColorSequence && !colorPublished.empty()) {
            colorCopy = colorPublished;
            publishedWidth = colorWidth;
            publishedHeight = colorHeight;
            publishedSequence = colorSequence;
        }
    }

    if (!colorCopy.empty()) {
        emitColorFrame(colorCopy, publishedWidth, publishedHeight, publishedSequence);
        emittedColorSequence = publishedSequence;
        lastEmit = now;
        return;
    }

    const uint16_t width = display->getWidth();
    const uint16_t height = display->getHeight();
    if (width == 0 || height == 0 || (height % 8) != 0)
        return;

    const size_t frameBytes = static_cast<size_t>(width) * height / 8;
    const bool sameGeometry = havePreviousMono && previousWidth == width && previousHeight == height &&
                              previousMono.size() == frameBytes;
    if (sameGeometry && memcmp(previousMono.data(), display->buffer, frameBytes) == 0)
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

    previousMono.assign(display->buffer, display->buffer + frameBytes);
    previousWidth = width;
    previousHeight = height;
    havePreviousMono = true;
    lastEmit = now;
}
} // namespace graphics

#endif
