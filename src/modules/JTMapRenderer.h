#pragma once

#include "configuration.h"

#if defined(HAS_TACTICAL_MAP) && HAS_TACTICAL_MAP && HAS_SCREEN

#include <OLEDDisplay.h>
#include <cstdint>

class JTMapRenderer
{
  public:
    static constexpr const char *DEFAULT_MAP_PATH = "/maps/friesenheim-v1.jtmap";

    enum class Theme : uint8_t {
        TACTICAL_NIGHT,
        LIGHT,
        HIGH_CONTRAST,
    };

    struct Bounds {
        double south = 0.0;
        double west = 0.0;
        double north = 0.0;
        double east = 0.0;
        bool valid = false;
    };

    static bool draw(OLEDDisplay *display, const char *path, int16_t left, int16_t top, int16_t width, int16_t height,
                     Bounds *bounds = nullptr, Theme theme = Theme::TACTICAL_NIGHT);
    static bool drawViewport(OLEDDisplay *display, const char *path, int16_t left, int16_t top, int16_t width, int16_t height,
                             int32_t centerLatitudeI, int32_t centerLongitudeI, uint8_t zoomLevel,
                             Bounds *viewportBounds = nullptr, Theme theme = Theme::TACTICAL_NIGHT);
    static bool contains(const Bounds &bounds, int32_t latitude_i, int32_t longitude_i);
    static int16_t projectX(const Bounds &bounds, int32_t longitude_i, int16_t left, int16_t width);
    static int16_t projectY(const Bounds &bounds, int32_t latitude_i, int16_t top, int16_t height);
};

#endif