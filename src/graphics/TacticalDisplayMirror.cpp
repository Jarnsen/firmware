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
constexpr uint32_t MIRROR_FRAME_INTERVAL_MS = 50;
constexpr uint32_t MIRROR_ACTIVE_FRAME_INTERVAL_MS = 160;
constexpr uint32_t MIRROR_INPUT_PRIORITY_MS = 180;
constexpr uint32_t MIRROR_INPUT_BURST_MS = 420;
constexpr uint32_t COLOR_FRAME_VALID_MS = 2000;
constexpr size_t COLOR_MONO_DIFFERENCE_BITS = 512;
constexpr size_t CHUNK_PAYLOAD_BYTES = 60;
constexpr size_t COLOR_RUNS_PER_CHUNK = CHUNK_PAYLOAD_BYTES / 3;
constexpr size_t MIRROR_LINE_BUFFER_SIZE = 192;

enum class PendingFrameKind : uint8_t { NONE, MONO, COLOR };

struct PendingFrame {
    PendingFrameKind kind = PendingFrameKind::NONE;
    uint16_t width = 0;
    uint16_t height = 0;
    uint32_t sequence = 0;
    uint16_t chunkIndex = 0;
    uint16_t chunkCount = 0;
    size_t sourceOffset = 0;
};

std::vector<uint8_t> previousMono;
std::vector<uint8_t> pendingMono;
uint16_t previousWidth = 0;
uint16_t previousHeight = 0;
bool havePreviousMono = false;
uint32_t monoSequence = 0;
uint32_t lastFrameCompletedAt = 0;
uint32_t inputPriorityUntil = 0;
uint32_t lastInputAt = 0;
PendingFrame pendingFrame;

concurrency::Lock colorLock;
std::vector<uint16_t> colorWorking;
std::vector<uint16_t> colorPublished;
std::vector<uint8_t> colorWorkingMono;
std::vector<uint8_t> colorPublishedMono;
uint16_t colorWidth = 0;
uint16_t colorHeight = 0;
uint32_t colorSequence = 0;
uint32_t emittedColorSequence = 0;
uint32_t colorPublishedAt = 0;
bool colorBuilding = false;

bool beforeDeadline(uint32_t now, uint32_t deadline)
{
    return static_cast<int32_t>(now - deadline) < 0;
}

bool colorMonoMatchesDisplay(const uint8_t *displayBuffer, size_t monoBytes)
{
    if (!displayBuffer || colorPublishedMono.size() != monoBytes)
        return false;

    size_t differentBits = 0;
    for (size_t i = 0; i < monoBytes; ++i) {
        differentBits += static_cast<size_t>(__builtin_popcount(static_cast<unsigned>(colorPublishedMono[i] ^ displayBuffer[i])));
        if (differentBits > COLOR_MONO_DIFFERENCE_BITS)
            return false;
    }
    return true;
}

void mergeDisplayMonoOverlay(const uint8_t *displayBuffer)
{
    if (!displayBuffer || colorPublishedMono.empty() || colorPublished.empty())
        return;

    for (uint16_t y = 0; y < colorHeight; ++y) {
        const size_t pageOffset = static_cast<size_t>(y / 8U) * colorWidth;
        const uint8_t mask = static_cast<uint8_t>(1U << (y & 7U));
        for (uint16_t x = 0; x < colorWidth; ++x) {
            const size_t monoIndex = pageOffset + x;
            const bool finalPixel = (displayBuffer[monoIndex] & mask) != 0;
            const bool capturedPixel = (colorPublishedMono[monoIndex] & mask) != 0;
            const size_t pixelIndex = static_cast<size_t>(y) * colorWidth + x;
            if (finalPixel && !capturedPixel && colorPublished[pixelIndex] == 0x0000)
                colorPublished[pixelIndex] = 0xffff;
        }
    }
}

void clearPendingFrame()
{
    pendingFrame = PendingFrame{};
    pendingMono.clear();
}

size_t countColorRuns(const std::vector<uint16_t> &pixels)
{
    size_t runs = 0;
    for (size_t offset = 0; offset < pixels.size();) {
        const uint16_t color = pixels[offset];
        size_t count = 1;
        while (offset + count < pixels.size() && pixels[offset + count] == color && count < 255)
            ++count;
        offset += count;
        ++runs;
    }
    return runs;
}

bool emitChunk(char mode, uint16_t width, uint16_t height, uint32_t sequence, uint16_t chunkIndex, uint16_t chunkCount,
               const uint8_t *payload, size_t payloadSize)
{
    static constexpr char HEX_DIGITS[] = "0123456789ABCDEF";
    char line[MIRROR_LINE_BUFFER_SIZE];
    const int headerLength = snprintf(line, sizeof(line), "@TMF3 %c %u %u %lu %u %u ", mode, static_cast<unsigned>(width),
                                      static_cast<unsigned>(height), static_cast<unsigned long>(sequence),
                                      static_cast<unsigned>(chunkIndex), static_cast<unsigned>(chunkCount));
    if (headerLength < 0)
        return false;

    size_t lineLength = static_cast<size_t>(headerLength);
    if (lineLength + payloadSize * 2 + 1 > sizeof(line))
        return false;

    for (size_t i = 0; i < payloadSize; ++i) {
        line[lineLength++] = HEX_DIGITS[payload[i] >> 4];
        line[lineLength++] = HEX_DIGITS[payload[i] & 0x0f];
    }
    line[lineLength++] = '\n';

    // Never wait for a whole image to drain. A single short line is emitted
    // only when the USB TX queue can accept it, leaving the next scheduler
    // slice free to read keyboard commands.
    if (Serial.availableForWrite() < static_cast<int>(lineLength))
        return false;
    return Serial.write(reinterpret_cast<const uint8_t *>(line), lineLength) == lineLength;
}

bool startPendingColorFrame(OLEDDisplay *display)
{
    concurrency::LockGuard guard(&colorLock);
    const uint32_t now = millis();
    if (colorSequence == emittedColorSequence || colorPublished.empty() || colorPublishedMono.empty() || !colorPublishedAt ||
        static_cast<uint32_t>(now - colorPublishedAt) > COLOR_FRAME_VALID_MS || display->getWidth() != colorWidth ||
        display->getHeight() != colorHeight)
        return false;

    const size_t monoBytes = static_cast<size_t>(colorWidth) * colorHeight / 8;
    if (!colorMonoMatchesDisplay(display->buffer, monoBytes))
        return false;

    mergeDisplayMonoOverlay(display->buffer);

    const size_t runCount = countColorRuns(colorPublished);
    if (!runCount)
        return false;

    const size_t chunkCount = (runCount + COLOR_RUNS_PER_CHUNK - 1) / COLOR_RUNS_PER_CHUNK;
    if (chunkCount > UINT16_MAX)
        return false;

    pendingFrame.kind = PendingFrameKind::COLOR;
    pendingFrame.width = colorWidth;
    pendingFrame.height = colorHeight;
    pendingFrame.sequence = colorSequence;
    pendingFrame.chunkIndex = 0;
    pendingFrame.chunkCount = static_cast<uint16_t>(chunkCount);
    pendingFrame.sourceOffset = 0;
    return true;
}

bool startPendingMonoFrame(OLEDDisplay *display)
{
    const uint16_t width = display->getWidth();
    const uint16_t height = display->getHeight();
    if (!width || !height || (height % 8) != 0)
        return false;

    const size_t frameBytes = static_cast<size_t>(width) * height / 8;
    const bool sameGeometry =
        havePreviousMono && previousWidth == width && previousHeight == height && previousMono.size() == frameBytes;
    if (sameGeometry && memcmp(previousMono.data(), display->buffer, frameBytes) == 0)
        return false;

    pendingMono.assign(display->buffer, display->buffer + frameBytes);
    const size_t chunkCount = (frameBytes + CHUNK_PAYLOAD_BYTES - 1) / CHUNK_PAYLOAD_BYTES;
    if (chunkCount > UINT16_MAX) {
        pendingMono.clear();
        return false;
    }

    pendingFrame.kind = PendingFrameKind::MONO;
    pendingFrame.width = width;
    pendingFrame.height = height;
    pendingFrame.sequence = ++monoSequence;
    pendingFrame.chunkIndex = 0;
    pendingFrame.chunkCount = static_cast<uint16_t>(chunkCount);
    pendingFrame.sourceOffset = 0;
    return true;
}

bool emitPendingColorChunk()
{
    uint8_t payload[CHUNK_PAYLOAD_BYTES];
    size_t payloadSize = 0;
    size_t nextOffset = pendingFrame.sourceOffset;
    {
        concurrency::LockGuard guard(&colorLock);
        if (pendingFrame.sequence != colorSequence || colorPublished.empty()) {
            clearPendingFrame();
            return false;
        }

        size_t runs = 0;
        while (nextOffset < colorPublished.size() && runs < COLOR_RUNS_PER_CHUNK) {
            const uint16_t color = colorPublished[nextOffset];
            uint8_t count = 1;
            while (nextOffset + count < colorPublished.size() && colorPublished[nextOffset + count] == color && count < 255)
                ++count;
            payload[payloadSize++] = count;
            payload[payloadSize++] = static_cast<uint8_t>(color >> 8);
            payload[payloadSize++] = static_cast<uint8_t>(color & 0xff);
            nextOffset += count;
            ++runs;
        }
    }

    if (!payloadSize || !emitChunk('C', pendingFrame.width, pendingFrame.height, pendingFrame.sequence, pendingFrame.chunkIndex,
                                   pendingFrame.chunkCount, payload, payloadSize))
        return false;

    pendingFrame.sourceOffset = nextOffset;
    ++pendingFrame.chunkIndex;
    if (pendingFrame.chunkIndex >= pendingFrame.chunkCount) {
        emittedColorSequence = pendingFrame.sequence;
        lastFrameCompletedAt = millis();
        clearPendingFrame();
    }
    return true;
}

bool emitPendingMonoChunk()
{
    const size_t remaining = pendingMono.size() - pendingFrame.sourceOffset;
    const size_t payloadSize = std::min(CHUNK_PAYLOAD_BYTES, remaining);
    if (!payloadSize || !emitChunk('M', pendingFrame.width, pendingFrame.height, pendingFrame.sequence, pendingFrame.chunkIndex,
                                   pendingFrame.chunkCount, pendingMono.data() + pendingFrame.sourceOffset, payloadSize))
        return false;

    pendingFrame.sourceOffset += payloadSize;
    ++pendingFrame.chunkIndex;
    if (pendingFrame.chunkIndex >= pendingFrame.chunkCount) {
        previousMono = pendingMono;
        previousWidth = pendingFrame.width;
        previousHeight = pendingFrame.height;
        havePreviousMono = true;
        emittedColorSequence = 0;
        lastFrameCompletedAt = millis();
        clearPendingFrame();
    }
    return true;
}
} // namespace

void beginTacticalColorFrame(uint16_t width, uint16_t height, uint16_t backgroundRgb565)
{
    if (!width || !height)
        return;
    concurrency::LockGuard guard(&colorLock);
    colorWidth = width;
    colorHeight = height;
    const size_t pixelCount = static_cast<size_t>(width) * height;
    if (colorWorking.size() != pixelCount)
        colorWorking.resize(pixelCount);
    std::fill(colorWorking.begin(), colorWorking.end(), backgroundRgb565);
    colorWorkingMono.clear();
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

void overlayTacticalMonoBuffer(OLEDDisplay *display, uint16_t foregroundRgb565, uint16_t onlyOverRgb565)
{
    if (!display || !display->buffer)
        return;
    concurrency::LockGuard guard(&colorLock);
    if (!colorBuilding || display->getWidth() != colorWidth || display->getHeight() != colorHeight)
        return;

    const size_t monoBytes = static_cast<size_t>(colorWidth) * colorHeight / 8;
    colorWorkingMono.assign(display->buffer, display->buffer + monoBytes);

    for (uint16_t y = 0; y < colorHeight; ++y) {
        const size_t pageOffset = static_cast<size_t>(y / 8U) * colorWidth;
        const uint8_t mask = static_cast<uint8_t>(1U << (y & 7U));
        for (uint16_t x = 0; x < colorWidth; ++x) {
            const size_t pixelIndex = static_cast<size_t>(y) * colorWidth + x;
            if ((display->buffer[pageOffset + x] & mask) && colorWorking[pixelIndex] == onlyOverRgb565)
                colorWorking[pixelIndex] = foregroundRgb565;
        }
    }
}

void publishTacticalColorFrame()
{
    concurrency::LockGuard guard(&colorLock);
    if (!colorBuilding || colorWorking.empty())
        return;

    colorPublishedAt = millis();
    if (colorPublished == colorWorking && colorPublishedMono == colorWorkingMono) {
        colorBuilding = false;
        return;
    }

    colorPublished = colorWorking;
    colorPublishedMono = colorWorkingMono;
    colorBuilding = false;
    ++colorSequence;
}

bool getTacticalColorFrameInfo(const uint8_t *monoBuffer, size_t monoBytes, uint16_t &width, uint16_t &height, uint32_t &sequence)
{
    concurrency::LockGuard guard(&colorLock);
    const uint32_t now = millis();
    if (!monoBuffer || colorPublished.empty() || !colorWidth || !colorHeight || !colorSequence || !colorPublishedAt ||
        static_cast<uint32_t>(now - colorPublishedAt) > COLOR_FRAME_VALID_MS || !colorMonoMatchesDisplay(monoBuffer, monoBytes))
        return false;
    mergeDisplayMonoOverlay(monoBuffer);
    width = colorWidth;
    height = colorHeight;
    sequence = colorSequence;
    return true;
}

bool copyTacticalColorFrameRows(uint32_t sequence, uint16_t startRow, uint16_t rowCount, uint16_t *destination,
                                size_t destinationPixels)
{
    if (!destination || !rowCount)
        return false;
    concurrency::LockGuard guard(&colorLock);
    if (sequence != colorSequence || colorPublished.empty() || startRow >= colorHeight || rowCount > colorHeight - startRow)
        return false;

    const size_t pixelCount = static_cast<size_t>(colorWidth) * rowCount;
    if (destinationPixels < pixelCount)
        return false;
    memcpy(destination, colorPublished.data() + static_cast<size_t>(startRow) * colorWidth, pixelCount * sizeof(uint16_t));
    return true;
}

void prioritizeMirrorInput()
{
    const uint32_t now = millis();
    lastInputAt = now;
    inputPriorityUntil = now + MIRROR_INPUT_PRIORITY_MS;
    lastFrameCompletedAt = now;

    // Every accepted control event cancels the old partial image. This keeps
    // stale USB chunks and page transitions away from the normal UI input path.
    clearPendingFrame();
    havePreviousMono = false;
    {
        concurrency::LockGuard guard(&colorLock);
        emittedColorSequence = colorSequence;
    }
}

void mirrorDisplayFrame(OLEDDisplay *display)
{
    if (!display || !display->buffer)
        return;

    const uint32_t now = millis();
    if (beforeDeadline(now, inputPriorityUntil))
        return;

    if (pendingFrame.kind == PendingFrameKind::COLOR) {
        emitPendingColorChunk();
        return;
    }
    if (pendingFrame.kind == PendingFrameKind::MONO) {
        emitPendingMonoChunk();
        return;
    }

    const bool inputActive = lastInputAt && static_cast<uint32_t>(now - lastInputAt) <= MIRROR_INPUT_BURST_MS;
    const uint32_t frameInterval = inputActive ? MIRROR_ACTIVE_FRAME_INTERVAL_MS : MIRROR_FRAME_INTERVAL_MS;
    if (static_cast<uint32_t>(now - lastFrameCompletedAt) < frameInterval)
        return;

    if (!startPendingColorFrame(display))
        startPendingMonoFrame(display);
}
} // namespace graphics

#endif
