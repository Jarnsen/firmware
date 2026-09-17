#include "TacticalMapMath.h"

#include "gps/GeoCoord.h"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdio>
#include <cstring>

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

namespace
{
constexpr double WGS84_A = 6378137.0;
constexpr double WGS84_ECC_SQUARED = 0.00669438;
constexpr double UTM_SCALE = 0.9996;
constexpr double RADIANS_TO_DEGREES = 180.0 / 3.14159265358979323846;

int letterIndex(const char *letters, char value)
{
    const char *match = strchr(letters, value);
    return match ? static_cast<int>(match - letters) : -1;
}

bool utmToLatLon(uint8_t zone, bool northHemisphere, double easting, double northing, double &latitude, double &longitude)
{
    if (zone < 1 || zone > 60 || easting < 100000.0 || easting >= 1000000.0 || northing < 0.0 || northing > 10000000.0)
        return false;

    double x = easting - 500000.0;
    double y = northing;
    if (!northHemisphere)
        y -= 10000000.0;

    x /= UTM_SCALE;
    y /= UTM_SCALE;

    const double eccPrimeSquared = WGS84_ECC_SQUARED / (1.0 - WGS84_ECC_SQUARED);
    const double m = y;
    const double mu = m / (WGS84_A * (1.0 - WGS84_ECC_SQUARED / 4.0 - 3.0 * WGS84_ECC_SQUARED * WGS84_ECC_SQUARED / 64.0 -
                                      5.0 * WGS84_ECC_SQUARED * WGS84_ECC_SQUARED * WGS84_ECC_SQUARED / 256.0));
    const double e1 = (1.0 - sqrt(1.0 - WGS84_ECC_SQUARED)) / (1.0 + sqrt(1.0 - WGS84_ECC_SQUARED));
    const double phi1 = mu + (3.0 * e1 / 2.0 - 27.0 * pow(e1, 3) / 32.0) * sin(2.0 * mu) +
                        (21.0 * e1 * e1 / 16.0 - 55.0 * pow(e1, 4) / 32.0) * sin(4.0 * mu) +
                        (151.0 * pow(e1, 3) / 96.0) * sin(6.0 * mu);

    const double sinPhi = sin(phi1);
    const double cosPhi = cos(phi1);
    const double tanPhi = tan(phi1);
    const double n1 = WGS84_A / sqrt(1.0 - WGS84_ECC_SQUARED * sinPhi * sinPhi);
    const double t1 = tanPhi * tanPhi;
    const double c1 = eccPrimeSquared * cosPhi * cosPhi;
    const double r1 = WGS84_A * (1.0 - WGS84_ECC_SQUARED) / pow(1.0 - WGS84_ECC_SQUARED * sinPhi * sinPhi, 1.5);
    const double d = x / n1;

    const double latRad =
        phi1 -
        (n1 * tanPhi / r1) *
            (d * d / 2.0 - (5.0 + 3.0 * t1 + 10.0 * c1 - 4.0 * c1 * c1 - 9.0 * eccPrimeSquared) * pow(d, 4) / 24.0 +
             (61.0 + 90.0 * t1 + 298.0 * c1 + 45.0 * t1 * t1 - 252.0 * eccPrimeSquared - 3.0 * c1 * c1) * pow(d, 6) / 720.0);
    const double lonRad =
        (d - (1.0 + 2.0 * t1 + c1) * pow(d, 3) / 6.0 +
         (5.0 - 2.0 * c1 + 28.0 * t1 - 3.0 * c1 * c1 + 8.0 * eccPrimeSquared + 24.0 * t1 * t1) * pow(d, 5) / 120.0) /
        cosPhi;

    latitude = latRad * RADIANS_TO_DEGREES;
    longitude = (zone - 1) * 6.0 - 180.0 + 3.0 + lonRad * RADIANS_TO_DEGREES;
    return latitude >= -80.0 && latitude <= 84.0 && longitude >= -180.0 && longitude <= 180.0;
}
} // namespace

bool parseMgrs10(const char *mgrs, int32_t &latitudeI, int32_t &longitudeI)
{
    latitudeI = 0;
    longitudeI = 0;
    if (!mgrs)
        return false;

    char compact[24] = {0};
    size_t length = 0;
    for (const char *cursor = mgrs; *cursor && length < sizeof(compact) - 1; ++cursor) {
        if (!isspace(static_cast<unsigned char>(*cursor)))
            compact[length++] = static_cast<char>(toupper(static_cast<unsigned char>(*cursor)));
    }

    size_t zoneDigits = 0;
    while (zoneDigits < length && isdigit(static_cast<unsigned char>(compact[zoneDigits])))
        ++zoneDigits;
    if ((zoneDigits != 1 && zoneDigits != 2) || length != zoneDigits + 13)
        return false;

    unsigned zone = 0;
    for (size_t i = 0; i < zoneDigits; ++i)
        zone = zone * 10U + static_cast<unsigned>(compact[i] - '0');
    if (zone < 1 || zone > 60)
        return false;

    const char band = compact[zoneDigits];
    const char eastLetter = compact[zoneDigits + 1];
    const char northLetter = compact[zoneDigits + 2];
    const char *validBands = "CDEFGHJKLMNPQRSTUVWX";
    const int bandIndex = letterIndex(validBands, band);
    if (bandIndex < 0)
        return false;

    static const char *eastSets[] = {"ABCDEFGH", "JKLMNPQR", "STUVWXYZ"};
    static const char *northSets[] = {"ABCDEFGHJKLMNPQRSTUV", "FGHJKLMNPQRSTUVABCDE"};
    const int eastIndex = letterIndex(eastSets[(zone - 1U) % 3U], eastLetter);
    const int northIndex = letterIndex(northSets[(zone - 1U) % 2U], northLetter);
    if (eastIndex < 0 || northIndex < 0)
        return false;

    uint32_t eastDigits = 0;
    uint32_t northDigits = 0;
    for (size_t i = 0; i < 5; ++i) {
        const char eastDigit = compact[zoneDigits + 3 + i];
        const char northDigit = compact[zoneDigits + 8 + i];
        if (!isdigit(static_cast<unsigned char>(eastDigit)) || !isdigit(static_cast<unsigned char>(northDigit)))
            return false;
        eastDigits = eastDigits * 10U + static_cast<uint32_t>(eastDigit - '0');
        northDigits = northDigits * 10U + static_cast<uint32_t>(northDigit - '0');
    }

    static constexpr uint32_t bandMinimumNorthing[] = {1100000, 2000000, 2800000, 3700000, 4600000, 5500000, 6400000,
                                                       7300000, 8200000, 9100000, 0,       800000,  1700000, 2600000,
                                                       3500000, 4400000, 5300000, 6200000, 7000000, 7900000};
    const double easting = static_cast<double>((eastIndex + 1) * 100000U + eastDigits) + 0.5;
    uint32_t northing = static_cast<uint32_t>(northIndex) * 100000U + northDigits;
    while (northing < bandMinimumNorthing[bandIndex])
        northing += 2000000U;

    double latitude = 0.0;
    double longitude = 0.0;
    if (!utmToLatLon(static_cast<uint8_t>(zone), band >= 'N', easting, static_cast<double>(northing) + 0.5, latitude, longitude))
        return false;

    const double bandSouth = -80.0 + bandIndex * 8.0;
    const double bandNorth = band == 'X' ? 84.0 : bandSouth + 8.0;
    if (latitude < bandSouth - 0.01 || latitude > bandNorth + 0.01)
        return false;

    latitudeI = static_cast<int32_t>(lround(latitude * 1e7));
    longitudeI = static_cast<int32_t>(lround(longitude * 1e7));
    return isValidCoordinate(latitudeI, longitudeI);
}

float bearingDegrees(int32_t fromLatitudeI, int32_t fromLongitudeI, int32_t toLatitudeI, int32_t toLongitudeI)
{
    float degrees = GeoCoord::bearing(fromLatitudeI * 1e-7, fromLongitudeI * 1e-7, toLatitudeI * 1e-7, toLongitudeI * 1e-7) *
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
    static constexpr float ranges[] = {50.0f,   100.0f,   250.0f,   500.0f,   1000.0f,   2500.0f,
                                       5000.0f, 10000.0f, 25000.0f, 50000.0f, 100000.0f, 250000.0f};
    for (const float range : ranges) {
        if (distance <= range)
            return range;
    }
    return std::max(500000.0f, ceilf(distance / 500000.0f) * 500000.0f);
}

} // namespace TacticalMapMath
