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

enum class FeatureKind : uint8_t { OTHER, PATH, TRACK, RAIL, MOTORWAY, TRUNK, PRIMARY };

struct CachedSegment {
    uint16_t x1 = 0, y1 = 0, x2 = 0, y2 = 0;
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
    if (!strtok_r(line, "|", &save))
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

    bool havePrevious = false;
    uint16_t previousX = 0, previousY = 0, featureSegment = 0;
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
            segment = {previousX, previousY, x, y, static_cast<uint8_t>(parsedLevel), parseKind(kindText), featureSegment++};
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
        } else if (strncmp(line, "BBOX|", 5) == 0) {
            parseBounds(line, mapCache.bounds);
        } else if (strncmp(line, "F|", 2) == 0) {
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

void drawCachedSegment(OLEDDisplay *display, const CachedSegment &segment, const JTMapRenderer::Bounds &view, int16_t left,
                       int16_t top, int16_t width, int16_t height, JTMapRenderer::Theme theme)
{
    if (!shouldDrawSegment(segment, theme))
        return;
    const double lon1 = mapCache.bounds.west + (mapCache.bounds.east - mapCache.bounds.west) * segment.x1 / 65535.0;
    const double lat1 = mapCache.bounds.north - (mapCache.bounds.north - mapCache.bounds.south) * segment.y1 / 65535.0;
    const double lon2 = mapCache.bounds.west + (mapCache.bounds.east - mapCache.bounds.west) * segment.x2 / 65535.0;
    const double lat2 = mapCache.bounds.north - (mapCache.bounds.north - mapCache.bounds.south) * segment.y2 / 65535.0;
    if ((lon1 < view.west && lon2 < view.west) || (lon1 > view.east && lon2 > view.east) ||
        (lat1 < view.south && lat2 < view.south) || (lat1 > view.north && lat2 > view.north))
        return;

    auto px = [&](double lon) {
        const double n = std::max(0.0, std::min(1.0, (lon - view.west) / (view.east - view.west)));
        return left + static_cast<int16_t>(n * (width - 1));
    };
    auto py = [&](double lat) {
        const double n = std::max(0.0, std::min(1.0, (view.north - lat) / (view.north - view.south)));
        return top + static_cast<int16_t>(n * (height - 1));
    };
    const int16_t x1 = px(lon1), y1 = py(lat1), x2 = px(lon2), y2 = py(lat2);
    display->drawLine(x1, y1, x2, y2);
    const bool majorRoad = segment.kind == FeatureKind::MOTORWAY || segment.kind == FeatureKind::TRUNK ||
                           segment.kind == FeatureKind::PRIMARY;
    if (majorRoad && segment.level <= 2)
        display->drawLine(x1, y1 + 1, x2, y2 + 1);
    else if (segment.kind == FeatureKind::RAIL && segment.level <= 2)
        display->setPixel((x1 + x2) / 2, (y1 + y2) / 2);
}

JTMapRenderer::Bounds makeViewport(int32_t centerLatitudeI, int32_t centerLongitudeI, uint8_t zoomLevel)
{
    JTMapRenderer::Bounds view = mapCache.bounds;
    const double factor = zoomLevel == 0 ? 1.0 : zoomLevel == 1 ? 0.5 : zoomLevel == 2 ? 0.25 : 0.125;
    const double latSpan = (mapCache.bounds.north - mapCache.bounds.south) * factor;
    const double lonSpan = (mapCache.bounds.east - mapCache.bounds.west) * factor;
    const double centerLat = centerLatitudeI * 1e-7;
    const double centerLon = centerLongitudeI * 1e-7;
    view.south = centerLat - latSpan / 2.0;
    view.north = centerLat + latSpan / 2.0;
    view.west = centerLon - lonSpan / 2.0;
    view.east = centerLon + lonSpan / 2.0;
    if (view.south < mapCache.bounds.south) { view.north += mapCache.bounds.south - view.south; view.south = mapCache.bounds.south; }
    if (view.north > mapCache.bounds.north) { view.south -= view.north - mapCache.bounds.north; view.north = mapCache.bounds.north; }
    if (view.west < mapCache.bounds.west) { view.east += mapCache.bounds.west - view.west; view.west = mapCache.bounds.west; }
    if (view.east > mapCache.bounds.east) { view.west -= view.east - mapCache.bounds.east; view.east = mapCache.bounds.east; }
    view.valid = true;
    return view;
}
} // namespace

bool JTMapRenderer::draw(OLEDDisplay *display, const char *path, int16_t left, int16_t top, int16_t width, int16_t height,
                         Bounds *bounds, Theme theme)
{
    if (!display || !path || width < 2 || height < 2 || !loadMapCache(path))
        return false;
    for (size_t i = 0; i < mapCache.segmentCount; ++i) {
        drawCachedSegment(display, mapCache.segments[i], mapCache.bounds, left, top, width, height, theme);
        if ((i % YIELD_EVERY_SEGMENTS) == 0)
            delay(0);
    }
    if (bounds)
        *bounds = mapCache.bounds;
    return true;
}

bool JTMapRenderer::drawViewport(OLEDDisplay *display, const char *path, int16_t left, int16_t top, int16_t width, int16_t height,
                                 int32_t centerLatitudeI, int32_t centerLongitudeI, uint8_t zoomLevel,
                                 Bounds *viewportBounds, Theme theme)
{
    if (!display || !path || width < 2 || height < 2 || !loadMapCache(path))
        return false;
    const Bounds view = makeViewport(centerLatitudeI, centerLongitudeI, std::min<uint8_t>(zoomLevel, 3));
    for (size_t i = 0; i < mapCache.segmentCount; ++i)
        drawCachedSegment(display, mapCache.segments[i], view, left, top, width, height, theme);
    if (viewportBounds)
        *viewportBounds = view;
    return true;
}

bool JTMapRenderer::contains(const Bounds &bounds, int32_t latitude_i, int32_t longitude_i)
{
    if (!bounds.valid)
        return false;
    const double latitude = latitude_i * 1e-7, longitude = longitude_i * 1e-7;
    return latitude >= bounds.south && latitude <= bounds.north && longitude >= bounds.west && longitude <= bounds.east;
}

int16_t JTMapRenderer::projectX(const Bounds &bounds, int32_t longitude_i, int16_t left, int16_t width)
{
    if (!bounds.valid || width < 2)
        return left;
    const double n = std::max(0.0, std::min(1.0, ((longitude_i * 1e-7) - bounds.west) / (bounds.east - bounds.west)));
    return left + static_cast<int16_t>(n * (width - 1));
}

int16_t JTMapRenderer::projectY(const Bounds &bounds, int32_t latitude_i, int16_t top, int16_t height)
{
    if (!bounds.valid || height < 2)
        return top;
    const double n = std::max(0.0, std::min(1.0, (bounds.north - latitude_i * 1e-7) / (bounds.north - bounds.south)));
    return top + static_cast<int16_t>(n * (height - 1));
}

#endif