#include "JTMapRenderer.h"

#if defined(HAS_TACTICAL_MAP) && HAS_TACTICAL_MAP && HAS_SCREEN

#include "FSCommon.h"

#include <Arduino.h>
#include <algorithm>
#include <array>
#include <cstdlib>
#include <cstring>

namespace
{
constexpr size_t MAX_LINE_LENGTH = 768;
constexpr size_t MAX_FEATURES_PER_MAP = 96;
constexpr size_t MAX_SEGMENTS_PER_MAP = 512;
constexpr size_t YIELD_EVERY_FEATURES = 12;
constexpr size_t YIELD_EVERY_SEGMENTS = 64;
constexpr size_t MAP_PATH_LENGTH = 96;

enum class FeatureKind : uint8_t {
    OTHER,
    PATH,
    TRACK,
    RAIL,
    MOTORWAY,
    TRUNK,
    PRIMARY,
};

struct CachedSegment {
    uint16_t x1 = 0;
    uint16_t y1 = 0;
    uint16_t x2 = 0;
    uint16_t y2 = 0;
    uint8_t level = 0;
    FeatureKind kind = FeatureKind::OTHER;
    uint16_t featureSegment = 0;
};

struct MapCache {
    JTMapRenderer::Bounds bounds;
    std::array<CachedSegment, MAX_SEGMENTS_PER_MAP> segments{};
    size_t segmentCount = 0;
    char path[MAP_PATH_LENGTH]{};
    bool loaded = false;
    bool valid = false;
};

MapCache mapCache;

FeatureKind parseKind(const char *kind)
{
    if (!kind)
        return FeatureKind::OTHER;
    if (strcmp(kind, "path") == 0 || strcmp(kind, "footway") == 0)
        return FeatureKind::PATH;
    if (strcmp(kind, "track") == 0)
        return FeatureKind::TRACK;
    if (strcmp(kind, "rail") == 0)
        return FeatureKind::RAIL;
    if (strcmp(kind, "motorway") == 0)
        return FeatureKind::MOTORWAY;
    if (strcmp(kind, "trunk") == 0)
        return FeatureKind::TRUNK;
    if (strcmp(kind, "primary") == 0)
        return FeatureKind::PRIMARY;
    return FeatureKind::OTHER;
}

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

bool appendFeatureToCache(char *line)
{
    char *save = nullptr;
    char *record = strtok_r(line, "|", &save);
    char *kindText = strtok_r(nullptr, "|", &save);
    char *levelText = strtok_r(nullptr, "|", &save);
    strtok_r(nullptr, "|", &save);
    char *points = strtok_r(nullptr, "|", &save);
    if (!record || strcmp(record, "F") != 0 || !kindText || !levelText || !points)
        return false;

    const int parsedLevel = atoi(levelText);
    if (parsedLevel < 0 || parsedLevel > 255)
        return false;

    const FeatureKind kind = parseKind(kindText);
    bool havePrevious = false;
    uint16_t previousX = 0;
    uint16_t previousY = 0;
    uint16_t featureSegment = 0;
    char *pointSave = nullptr;
    for (char *point = strtok_r(points, ";", &pointSave); point; point = strtok_r(nullptr, ";", &pointSave)) {
        char *comma = strchr(point, ',');
        if (!comma)
            continue;
        *comma = '\0';
        const unsigned long parsedX = strtoul(point, nullptr, 10);
        const unsigned long parsedY = strtoul(comma + 1, nullptr, 10);
        if (parsedX > 65535UL || parsedY > 65535UL)
            continue;

        const uint16_t x = static_cast<uint16_t>(parsedX);
        const uint16_t y = static_cast<uint16_t>(parsedY);
        if (havePrevious && mapCache.segmentCount < mapCache.segments.size()) {
            CachedSegment &segment = mapCache.segments[mapCache.segmentCount++];
            segment.x1 = previousX;
            segment.y1 = previousY;
            segment.x2 = x;
            segment.y2 = y;
            segment.level = static_cast<uint8_t>(parsedLevel);
            segment.kind = kind;
            segment.featureSegment = featureSegment++;
        }
        previousX = x;
        previousY = y;
        havePrevious = true;

        if (mapCache.segmentCount >= mapCache.segments.size())
            break;
    }
    return true;
}

bool loadMapCache(const char *path)
{
    if (mapCache.loaded && strncmp(mapCache.path, path, sizeof(mapCache.path)) == 0)
        return mapCache.valid;

    mapCache = MapCache{};
    strncpy(mapCache.path, path, sizeof(mapCache.path) - 1);
    mapCache.loaded = true;

    File file = FSCom.open(path, FILE_O_READ);
    if (!file)
        return false;

    bool validHeader = false;
    size_t featureCount = 0;
    char line[MAX_LINE_LENGTH];
    while (file.available() && featureCount < MAX_FEATURES_PER_MAP && mapCache.segmentCount < mapCache.segments.size()) {
        const size_t read = file.readBytesUntil('\n', line, sizeof(line) - 1);
        line[read] = '\0';
        if (read && line[read - 1] == '\r')
            line[read - 1] = '\0';

        if (strncmp(line, "JTMAP|1", 7) == 0) {
            validHeader = true;
            continue;
        }
        if (strncmp(line, "BBOX|", 5) == 0) {
            parseBounds(line, mapCache.bounds);
            continue;
        }
        if (strncmp(line, "F|", 2) == 0) {
            appendFeatureToCache(line);
            ++featureCount;
            if ((featureCount % YIELD_EVERY_FEATURES) == 0)
                delay(0);
        }
    }
    file.close();

    mapCache.valid = validHeader && mapCache.bounds.valid && mapCache.segmentCount > 0;
    return mapCache.valid;
}

bool shouldDrawSegment(const CachedSegment &segment, JTMapRenderer::Theme theme)
{
    if (theme == JTMapRenderer::Theme::HIGH_CONTRAST)
        return segment.level <= 3 || (segment.featureSegment % 2U) == 0U;

    if (segment.kind == FeatureKind::PATH || segment.kind == FeatureKind::TRACK)
        return (segment.featureSegment % 2U) == 0U;
    if (segment.kind == FeatureKind::RAIL)
        return (segment.featureSegment % 3U) != 1U;
    if (theme == JTMapRenderer::Theme::TACTICAL_NIGHT && segment.level >= 4)
        return (segment.featureSegment % 3U) == 0U;
    return true;
}

int16_t projectNormalized(uint16_t value, int16_t origin, int16_t extent)
{
    return origin + static_cast<int16_t>((static_cast<uint32_t>(value) * static_cast<uint32_t>(extent - 1)) / 65535U);
}

void drawCachedSegment(OLEDDisplay *display, const CachedSegment &segment, int16_t left, int16_t top, int16_t width,
                       int16_t height, JTMapRenderer::Theme theme)
{
    if (!shouldDrawSegment(segment, theme))
        return;

    const int16_t x1 = projectNormalized(segment.x1, left, width);
    const int16_t y1 = projectNormalized(segment.y1, top, height);
    const int16_t x2 = projectNormalized(segment.x2, left, width);
    const int16_t y2 = projectNormalized(segment.y2, top, height);
    display->drawLine(x1, y1, x2, y2);

    const bool majorRoad = segment.kind == FeatureKind::MOTORWAY || segment.kind == FeatureKind::TRUNK ||
                           segment.kind == FeatureKind::PRIMARY;
    if (majorRoad && segment.level <= 2) {
        display->drawLine(x1, y1 + 1, x2, y2 + 1);
    } else if (segment.kind == FeatureKind::RAIL && segment.level <= 2) {
        display->setPixel((x1 + x2) / 2, (y1 + y2) / 2);
    }
}
} // namespace

bool JTMapRenderer::draw(OLEDDisplay *display, const char *path, int16_t left, int16_t top, int16_t width, int16_t height,
                         Bounds *bounds, Theme theme)
{
    if (!display || !path || width < 2 || height < 2 || !loadMapCache(path))
        return false;

    for (size_t index = 0; index < mapCache.segmentCount; ++index) {
        drawCachedSegment(display, mapCache.segments[index], left, top, width, height, theme);
        if ((index % YIELD_EVERY_SEGMENTS) == 0)
            delay(0);
    }

    if (bounds)
        *bounds = mapCache.bounds;
    return true;
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