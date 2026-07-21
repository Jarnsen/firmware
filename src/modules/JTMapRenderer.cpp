#include "JTMapRenderer.h"

#if defined(HAS_TACTICAL_MAP) && HAS_TACTICAL_MAP && HAS_SCREEN

#include "FSCommon.h"

#include <Arduino.h>
#include <algorithm>
#include <cstdlib>
#include <cstring>

namespace
{
constexpr size_t MAX_LINE_LENGTH = 768;
constexpr size_t MAX_FEATURES_PER_FRAME = 220;

bool parseBounds(char *line, JTMapRenderer::Bounds &bounds)
{
    char *save = nullptr;
    char *token = strtok_r(line, "|", &save);
    if (!token || strcmp(token, "BBOX") != 0)
        return false;

    const char *south = strtok_r(nullptr, "|", &save);
    const char *west = strtok_r(nullptr, "|", &save);
    const char *north = strtok_r(nullptr, "|", &save);
    const char *east = strtok_r(nullptr, "|", &save);
    if (!south || !west || !north || !east)
        return false;

    bounds.south = strtod(south, nullptr);
    bounds.west = strtod(west, nullptr);
    bounds.north = strtod(north, nullptr);
    bounds.east = strtod(east, nullptr);
    bounds.valid = bounds.north > bounds.south && bounds.east > bounds.west;
    return bounds.valid;
}

bool drawFeature(OLEDDisplay *display, char *line, int16_t left, int16_t top, int16_t width, int16_t height)
{
    char *save = nullptr;
    char *record = strtok_r(line, "|", &save);
    char *kind = strtok_r(nullptr, "|", &save);
    char *levelText = strtok_r(nullptr, "|", &save);
    strtok_r(nullptr, "|", &save); // name is reserved for later labels
    char *points = strtok_r(nullptr, "|", &save);
    if (!record || strcmp(record, "F") != 0 || !kind || !levelText || !points)
        return false;

    const int level = atoi(levelText);
    if (level > 4)
        return true; // omit the smallest paths on the first 128x64 implementation

    bool havePrevious = false;
    int16_t previousX = 0;
    int16_t previousY = 0;
    char *pointSave = nullptr;
    for (char *point = strtok_r(points, ";", &pointSave); point; point = strtok_r(nullptr, ";", &pointSave)) {
        char *comma = strchr(point, ',');
        if (!comma)
            continue;
        *comma = '\0';
        const uint32_t normalizedX = static_cast<uint32_t>(strtoul(point, nullptr, 10));
        const uint32_t normalizedY = static_cast<uint32_t>(strtoul(comma + 1, nullptr, 10));
        const int16_t x = left + static_cast<int16_t>((normalizedX * static_cast<uint32_t>(width - 1)) / 65535U);
        const int16_t y = top + static_cast<int16_t>((normalizedY * static_cast<uint32_t>(height - 1)) / 65535U);

        if (havePrevious) {
            display->drawLine(previousX, previousY, x, y);
            if (strcmp(kind, "rail") == 0 && level <= 2)
                display->setPixel((previousX + x) / 2, (previousY + y) / 2);
        }
        previousX = x;
        previousY = y;
        havePrevious = true;
    }
    return true;
}
} // namespace

bool JTMapRenderer::draw(OLEDDisplay *display, const char *path, int16_t left, int16_t top, int16_t width, int16_t height,
                         Bounds *bounds)
{
    if (!display || !path || width < 2 || height < 2)
        return false;

    File file = FSCom.open(path, FILE_O_READ);
    if (!file)
        return false;

    Bounds parsedBounds;
    bool validHeader = false;
    size_t featureCount = 0;
    char line[MAX_LINE_LENGTH];

    while (file.available()) {
        const size_t read = file.readBytesUntil('\n', line, sizeof(line) - 1);
        line[read] = '\0';
        if (read && line[read - 1] == '\r')
            line[read - 1] = '\0';

        if (strncmp(line, "JTMAP|1", 7) == 0) {
            validHeader = true;
            continue;
        }
        if (strncmp(line, "BBOX|", 5) == 0) {
            parseBounds(line, parsedBounds);
            continue;
        }
        if (strncmp(line, "F|", 2) == 0 && featureCount < MAX_FEATURES_PER_FRAME) {
            drawFeature(display, line, left, top, width, height);
            ++featureCount;
        }
    }
    file.close();

    if (bounds)
        *bounds = parsedBounds;
    return validHeader && parsedBounds.valid && featureCount > 0;
}

bool JTMapRenderer::contains(const Bounds &bounds, int32_t latitude_i, int32_t longitude_i)
{
    if (!bounds.valid)
        return false;
    const double latitude = latitude_i * 1e-7;
    const double longitude = longitude_i * 1e-7;
    return latitude >= bounds.south && latitude <= bounds.north && longitude >= bounds.west && longitude <= bounds.east;
}

int16_t JTMapRenderer::projectX(const Bounds &bounds, int32_t longitude_i, int16_t left, int16_t width)
{
    if (!bounds.valid || width < 2)
        return left;
    const double normalized = ((longitude_i * 1e-7) - bounds.west) / (bounds.east - bounds.west);
    const double clipped = std::max(0.0, std::min(1.0, normalized));
    return left + static_cast<int16_t>(clipped * (width - 1));
}

int16_t JTMapRenderer::projectY(const Bounds &bounds, int32_t latitude_i, int16_t top, int16_t height)
{
    if (!bounds.valid || height < 2)
        return top;
    const double normalized = (bounds.north - (latitude_i * 1e-7)) / (bounds.north - bounds.south);
    const double clipped = std::max(0.0, std::min(1.0, normalized));
    return top + static_cast<int16_t>(clipped * (height - 1));
}

#endif
