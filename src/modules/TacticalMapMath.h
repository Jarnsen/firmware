#pragma once

#include <cstddef>
#include <cstdint>

namespace TacticalMapMath
{

bool isValidCoordinate(int32_t latitudeI, int32_t longitudeI);
bool formatMgrs10(int32_t latitudeI, int32_t longitudeI, char *out, size_t outSize);
bool parseMgrs10(const char *mgrs, int32_t &latitudeI, int32_t &longitudeI);
float bearingDegrees(int32_t fromLatitudeI, int32_t fromLongitudeI, int32_t toLatitudeI, int32_t toLongitudeI);
uint16_t degreesToMil(float degrees);
float distanceMeters(int32_t fromLatitudeI, int32_t fromLongitudeI, int32_t toLatitudeI, int32_t toLongitudeI);
const char *formatDistance(float meters, char *out, size_t outSize);
const char *formatPositionAge(uint32_t seconds, char *out, size_t outSize);
float mapRangeMeters(float distanceMeters);

} // namespace TacticalMapMath
