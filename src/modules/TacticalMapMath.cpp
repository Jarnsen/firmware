#include "TacticalMapMath.h"

#include "gps/GeoCoord.h"

#include <algorithm>
#include <cmath>
#include <cstdio>

namespace TacticalMapMath
{

bool isValidCoordinate(int32_t latitudeI, int32_t longitudeI)
{
    return latitudeI >= -800000000 && latitudeI <= 840000000 && longitudeI >= -1800000000 && longitudeI <= 1800000000;
}

bool formatMgrs10(int32_t latitudeI, int32_t longitudeI, char *out, size_t outSize)
{
    if (!out || outSize == 0)
        return false;

    out[0] = '\0';
    if (!isValidCoordinate(latitudeI, longitudeI))
        return false;

    GeoCoord coordinate(latitudeI, longitudeI, 0);
    const int written = snprintf(out, outSize, "%u%c %c%c %05lu %05lu", coordinate.getMGRSZone(), coordinate.getMGRSBand(),
                                 coordinate.getMGRSEast100k(), coordinate.getMGRSNorth100k(),
                                 static_cast<unsigned long>(coordinate.getMGRSEasting() % 100000U),
                                 static_cast<unsigned long>(coordinate.getMGRSNorthing() % 100000U));
    return written > 0 && static_cast<size_t>(written) < outSize;
}

float bearingDegrees(int32_t fromLatitudeI, int32_t fromLongitudeI, int32_t toLatitudeI, int32_t toLongitudeI)
{
    float degrees = GeoCoord::bearing(fromLatitudeI * 1e-7, fromLongitudeI * 1e-7, toLatitudeI * 1e-7,
                                      toLongitudeI * 1e-7) *
                    static_cast<float>(DEG_CONVERT);
    degrees = fmodf(degrees, 360.0f);
    if (degrees < 0.0f)
        degrees += 360.0f;
    return degrees;
}

uint16_t degreesToMil(float degrees)
{
    float normalized = fmodf(degrees, 360.0f);
    if (normalized < 0.0f)
        normalized += 360.0f;
    return static_cast<uint16_t>(lroundf(normalized * (6400.0f / 360.0f))) % 6400U;
}

float distanceMeters(int32_t fromLatitudeI, int32_t fromLongitudeI, int32_t toLatitudeI, int32_t toLongitudeI)
{
    return GeoCoord::latLongToMeter(fromLatitudeI * 1e-7, fromLongitudeI * 1e-7, toLatitudeI * 1e-7, toLongitudeI * 1e-7);
}

const char *formatDistance(float meters, char *out, size_t outSize)
{
    if (!out || outSize == 0)
        return "";

    meters = std::max(0.0f, meters);
    if (meters < 1000.0f)
        snprintf(out, outSize, "%.0f m", meters);
    else
        snprintf(out, outSize, "%.2f km", meters / 1000.0f);
    return out;
}

const char *formatPositionAge(uint32_t seconds, char *out, size_t outSize)
{
    if (!out || outSize == 0)
        return "";

    if (seconds < 120U)
        snprintf(out, outSize, "%lu s", static_cast<unsigned long>(seconds));
    else if (seconds < 7200U)
        snprintf(out, outSize, "%lu min", static_cast<unsigned long>(seconds / 60U));
    else if (seconds < 172800U)
        snprintf(out, outSize, "%lu h", static_cast<unsigned long>(seconds / 3600U));
    else
        snprintf(out, outSize, "%lu d", static_cast<unsigned long>(seconds / 86400U));
    return out;
}

float mapRangeMeters(float distance)
{
    static constexpr float ranges[] = {50.0f,    100.0f,   250.0f,   500.0f,   1000.0f,  2500.0f,
                                       5000.0f,  10000.0f, 25000.0f, 50000.0f, 100000.0f, 250000.0f};
    for (const float range : ranges) {
        if (distance <= range)
            return range;
    }
    return std::max(500000.0f, ceilf(distance / 500000.0f) * 500000.0f);
}

} // namespace TacticalMapMath
