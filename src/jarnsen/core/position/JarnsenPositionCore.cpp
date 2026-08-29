#include "jarnsen/core/position/JarnsenPositionCore.h"

#include <algorithm>
#include <cmath>
#include <cstdio>

namespace
{
struct MgrsProjection {
    int zone = 0;
    char band = 0;
    char eLetter = 0;
    char nLetter = 0;
    double easting = 0.0;
    double northing = 0.0;
};

char latitudeBand(double latitude)
{
    static constexpr char bands[] = "CDEFGHJKLMNPQRSTUVWX";
    if (latitude < -80.0 || latitude > 84.0)
        return 0;
    int index = static_cast<int>(std::floor((latitude + 80.0) / 8.0));
    index = std::max(0, std::min(19, index));
    return bands[index];
}

int utmZone(double latitude, double longitude)
{
    int zone = static_cast<int>(std::floor((longitude + 180.0) / 6.0)) + 1;
    zone = std::max(1, std::min(60, zone));

    if (latitude >= 56.0 && latitude < 64.0 && longitude >= 3.0 && longitude < 12.0)
        zone = 32;
    if (latitude >= 72.0 && latitude < 84.0) {
        if (longitude >= 0.0 && longitude < 9.0)
            zone = 31;
        else if (longitude < 21.0)
            zone = 33;
        else if (longitude < 33.0)
            zone = 35;
        else if (longitude < 42.0)
            zone = 37;
    }
    return zone;
}

bool projectMgrs(int32_t latitudeI, int32_t longitudeI, MgrsProjection &result)
{
    if ((latitudeI == 0 && longitudeI == 0) || latitudeI < -900000000 || latitudeI > 900000000 ||
        longitudeI < -1800000000 || longitudeI > 1800000000)
        return false;

    const double latitude = latitudeI * 1e-7;
    const double longitude = longitudeI * 1e-7;
    const char band = latitudeBand(latitude);
    if (!band)
        return false;

    constexpr double a = 6378137.0;
    constexpr double eccSquared = 0.00669438;
    constexpr double k0 = 0.9996;
    constexpr double degToRad = 0.017453292519943295769;

    const int zone = utmZone(latitude, longitude);
    const double lonOrigin = (zone - 1) * 6.0 - 180.0 + 3.0;
    const double latRad = latitude * degToRad;
    const double lonRad = longitude * degToRad;
    const double lonOriginRad = lonOrigin * degToRad;
    const double eccPrimeSquared = eccSquared / (1.0 - eccSquared);
    const double sinLat = std::sin(latRad);
    const double cosLat = std::cos(latRad);
    const double tanLat = std::tan(latRad);
    const double n = a / std::sqrt(1.0 - eccSquared * sinLat * sinLat);
    const double t = tanLat * tanLat;
    const double c = eccPrimeSquared * cosLat * cosLat;
    const double aa = cosLat * (lonRad - lonOriginRad);

    const double m =
        a * ((1.0 - eccSquared / 4.0 - 3.0 * eccSquared * eccSquared / 64.0 -
              5.0 * eccSquared * eccSquared * eccSquared / 256.0) *
                 latRad -
             (3.0 * eccSquared / 8.0 + 3.0 * eccSquared * eccSquared / 32.0 +
              45.0 * eccSquared * eccSquared * eccSquared / 1024.0) *
                 std::sin(2.0 * latRad) +
             (15.0 * eccSquared * eccSquared / 256.0 + 45.0 * eccSquared * eccSquared * eccSquared / 1024.0) *
                 std::sin(4.0 * latRad) -
             (35.0 * eccSquared * eccSquared * eccSquared / 3072.0) * std::sin(6.0 * latRad));

    const double easting =
        k0 * n *
            (aa + (1.0 - t + c) * aa * aa * aa / 6.0 +
             (5.0 - 18.0 * t + t * t + 72.0 * c - 58.0 * eccPrimeSquared) * aa * aa * aa * aa * aa / 120.0) +
        500000.0;
    double northing =
        k0 * (m + n * tanLat *
                      (aa * aa / 2.0 + (5.0 - t + 9.0 * c + 4.0 * c * c) * aa * aa * aa * aa / 24.0 +
                       (61.0 - 58.0 * t + t * t + 600.0 * c - 330.0 * eccPrimeSquared) * aa * aa * aa * aa * aa * aa /
                           720.0));
    if (latitude < 0.0)
        northing += 10000000.0;

    static constexpr const char *eastingSets[] = {"ABCDEFGH", "JKLMNPQR", "STUVWXYZ"};
    static constexpr char northingLetters[] = "ABCDEFGHJKLMNPQRSTUV";
    const int e100k = static_cast<int>(std::floor(easting / 100000.0));
    if (e100k < 1 || e100k > 8)
        return false;
    const int n100k = static_cast<int>(std::floor(northing / 100000.0)) % 20;

    result.zone = zone;
    result.band = band;
    result.eLetter = eastingSets[(zone - 1) % 3][e100k - 1];
    result.nLetter = northingLetters[(n100k + (zone % 2 == 0 ? 5 : 0)) % 20];
    result.easting = easting;
    result.northing = northing;
    return true;
}
} // namespace

bool jarnsenPositionFormatMgrs8(int32_t latitudeI, int32_t longitudeI, char *out, size_t outSize)
{
    if (!out || outSize < 24)
        return false;
    MgrsProjection mgrs;
    if (!projectMgrs(latitudeI, longitudeI, mgrs))
        return false;

    int eMeters = static_cast<int>(std::floor(mgrs.easting)) % 100000;
    int nMeters = static_cast<int>(std::floor(mgrs.northing)) % 100000;
    if (eMeters < 0)
        eMeters += 100000;
    if (nMeters < 0)
        nMeters += 100000;
    std::snprintf(out, outSize, "%02d%c %c%c %04d %04d", mgrs.zone, mgrs.band, mgrs.eLetter, mgrs.nLetter, eMeters / 10,
                  nMeters / 10);
    return true;
}

bool jarnsenPositionFormatMgrs10(int32_t latitudeI, int32_t longitudeI, char *out, size_t outSize)
{
    if (!out || outSize < 24)
        return false;
    MgrsProjection mgrs;
    if (!projectMgrs(latitudeI, longitudeI, mgrs))
        return false;

    int eMeters = static_cast<int>(std::floor(mgrs.easting + 0.5)) % 100000;
    int nMeters = static_cast<int>(std::floor(mgrs.northing + 0.5)) % 100000;
    if (eMeters < 0)
        eMeters += 100000;
    if (nMeters < 0)
        nMeters += 100000;
    std::snprintf(out, outSize, "%02d%c %c%c %05d %05d", mgrs.zone, mgrs.band, mgrs.eLetter, mgrs.nLetter, eMeters, nMeters);
    return true;
}

double jarnsenPositionDistanceMeters(int32_t latitudeA, int32_t longitudeA, int32_t latitudeB, int32_t longitudeB)
{
    constexpr double degToRad = 0.017453292519943295769;
    constexpr double earthRadiusM = 6371000.0;
    const double latA = latitudeA * 1e-7 * degToRad;
    const double latB = latitudeB * 1e-7 * degToRad;
    const double dLat = latB - latA;
    const double dLon = (static_cast<double>(longitudeB) - static_cast<double>(longitudeA)) * 1e-7 * degToRad;
    const double x = dLon * std::cos((latA + latB) * 0.5);
    return std::sqrt(dLat * dLat + x * x) * earthRadiusM;
}

double jarnsenPositionBearingDegrees(int32_t latitudeA, int32_t longitudeA, int32_t latitudeB, int32_t longitudeB)
{
    constexpr double degToRad = 0.017453292519943295769;
    constexpr double radToDeg = 57.2957795130823208768;
    const double latA = latitudeA * 1e-7 * degToRad;
    const double latB = latitudeB * 1e-7 * degToRad;
    const double dLon = (static_cast<double>(longitudeB) - static_cast<double>(longitudeA)) * 1e-7 * degToRad;
    const double y = std::sin(dLon) * std::cos(latB);
    const double x = std::cos(latA) * std::sin(latB) - std::sin(latA) * std::cos(latB) * std::cos(dLon);
    if (x == 0.0 && y == 0.0)
        return 0.0;
    double bearing = std::atan2(y, x) * radToDeg;
    if (bearing < 0.0)
        bearing += 360.0;
    if (bearing >= 360.0)
        bearing = std::fmod(bearing, 360.0);
    return bearing;
}

uint16_t jarnsenPositionHeadingMils6400(double headingDegrees)
{
    if (!std::isfinite(headingDegrees))
        return 0;
    double normalized = std::fmod(headingDegrees, 360.0);
    if (normalized < 0.0)
        normalized += 360.0;
    const long mils = std::lround(normalized * (6400.0 / 360.0));
    return static_cast<uint16_t>(mils % 6400L);
}

uint16_t jarnsenPositionGroundTrackMils6400(uint32_t groundTrackCentiDegrees)
{
    return jarnsenPositionHeadingMils6400((groundTrackCentiDegrees % 36000U) / 100.0);
}
