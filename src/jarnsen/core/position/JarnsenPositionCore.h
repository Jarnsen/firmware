#pragma once

#include <cstddef>
#include <cstdint>

// Pure, hardware-independent position helpers shared by display, service web
// and persistent track/history code.
bool jarnsenPositionFormatMgrs8(int32_t latitudeI, int32_t longitudeI, char *out, size_t outSize);
bool jarnsenPositionFormatMgrs10(int32_t latitudeI, int32_t longitudeI, char *out, size_t outSize);

double jarnsenPositionDistanceMeters(int32_t latitudeA, int32_t longitudeA, int32_t latitudeB, int32_t longitudeB);

// Initial true-north bearing from A to B, normalized to 0 <= degrees < 360.
// This is intentionally independent from a device's current heading so it can
// be reused for node navigation even when no compass/orientation source exists.
double jarnsenPositionBearingDegrees(int32_t latitudeA, int32_t longitudeA, int32_t latitudeB, int32_t longitudeB);

// Bundeswehr/NATO-style 6400 Strich full circle. Returned values are normalized
// to 0..6399. groundTrackCentiDegrees is Meshtastic's ground_track (1/100 degree).
uint16_t jarnsenPositionHeadingMils6400(double headingDegrees);
uint16_t jarnsenPositionGroundTrackMils6400(uint32_t groundTrackCentiDegrees);
