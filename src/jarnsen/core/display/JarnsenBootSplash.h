#pragma once

#include "configuration.h"

#if HAS_SCREEN
#include <OLEDDisplay.h>
#include "graphics/ScreenFonts.h"
#include "graphics/TFTColorRegions.h"
#include "graphics/TFTPalette.h"
#include "jarnsen/core/build/JarnsenBuildInfo.h"
#include "jarnsen/core/display/JarnsenBootLogo.h"

#include <cstdio>

namespace jarnsen
{

// Shared JARNSEN-MESH boot splash for every supported board.
// The approved mountain mark and its original JARNSEN MESH wordmark form one
// visual block. Version/build and hardware remain dynamic and keep the exact
// metadata positions that were already used before this logo change.
inline void drawBootSplash(OLEDDisplay *display, int16_t x, int16_t y)
{
    const int16_t width = display->getWidth();
    const int16_t height = display->getHeight();
    const int16_t centerX = static_cast<int16_t>(x + width / 2);

    // Stable boot metadata contract: intentionally unchanged.
    const int16_t versionY = static_cast<int16_t>(height >= 80 ? y + 43 : y + 37);
    const int16_t hardwareY = static_cast<int16_t>(height >= 80 ? y + 58 : y + 50);

    const bool wide = width >= 150;
    const int16_t wordmarkWidth = static_cast<int16_t>(wide ? bootlogo::wideWordmarkWidth : bootlogo::narrowWordmarkWidth);
    const int16_t wordmarkHeight = static_cast<int16_t>(wide ? bootlogo::wideWordmarkHeight : bootlogo::narrowWordmarkHeight);
    const int16_t wordmarkY = static_cast<int16_t>(y + (wide ? 28 : 25));
    const int16_t wordmarkX = static_cast<int16_t>(centerX - wordmarkWidth / 2);
    const uint8_t *wordmark = wide ? bootlogo::wideWordmark : bootlogo::narrowWordmark;

#if GRAPHICS_TFT_COLORING_ENABLED
    // Color TFTs: cyan mountain field/version, white approved wordmark and
    // hardware name, all on black. Monochrome displays use the same geometry.
    graphics::setAndRegisterTFTColorRole(graphics::TFTColorRole::BootSplash, graphics::TFTPalette::Cyan,
                                         graphics::TFTPalette::Black, x, y, width, height);
    graphics::registerTFTColorRegionDirect(x, wordmarkY, width, wordmarkHeight, graphics::TFTPalette::White,
                                           graphics::TFTPalette::Black);
    graphics::registerTFTColorRegionDirect(x, hardwareY, width, FONT_HEIGHT_SMALL, graphics::TFTPalette::White,
                                           graphics::TFTPalette::Black);
#endif

    display->setTextAlignment(TEXT_ALIGN_CENTER);

    // Flattened mountain mark derived from the approved logo. Keeping it as
    // vector strokes makes the peaks crisp on 160x80 and 128x64 displays while
    // the exact wordmark lettering below remains a raster mask from the logo.
    const int16_t span = static_cast<int16_t>(wide ? 72 : 56);
    const int16_t left = static_cast<int16_t>(centerX - span);
    const int16_t right = static_cast<int16_t>(centerX + span);
    const int16_t baseY = static_cast<int16_t>(wordmarkY - 2);
    const int16_t mainPeakY = static_cast<int16_t>(y + 2);
    const int16_t sidePeakY = static_cast<int16_t>(y + (wide ? 12 : 10));

    // Outer silhouette: small-left -> main peak -> small-right.
    display->drawLine(left, baseY, static_cast<int16_t>(centerX - span * 2 / 3), sidePeakY);
    display->drawLine(static_cast<int16_t>(centerX - span * 2 / 3), sidePeakY,
                      static_cast<int16_t>(centerX - span / 2), baseY);
    display->drawLine(static_cast<int16_t>(centerX - span / 2), baseY, centerX, mainPeakY);
    display->drawLine(centerX, mainPeakY, static_cast<int16_t>(centerX + span / 2), baseY);
    display->drawLine(static_cast<int16_t>(centerX + span / 2), baseY,
                      static_cast<int16_t>(centerX + span * 2 / 3), sidePeakY);
    display->drawLine(static_cast<int16_t>(centerX + span * 2 / 3), sidePeakY, right, baseY);

    // Facets/notches preserve the angular character of the original mark.
    display->drawLine(static_cast<int16_t>(centerX - span / 2), baseY,
                      static_cast<int16_t>(centerX - span / 5), static_cast<int16_t>(y + (wide ? 14 : 12)));
    display->drawLine(static_cast<int16_t>(centerX - span / 5), static_cast<int16_t>(y + (wide ? 14 : 12)),
                      static_cast<int16_t>(centerX - span / 8), baseY);
    display->drawLine(static_cast<int16_t>(centerX + span / 8), baseY,
                      static_cast<int16_t>(centerX + span / 5), static_cast<int16_t>(y + (wide ? 15 : 13)));
    display->drawLine(static_cast<int16_t>(centerX + span / 5), static_cast<int16_t>(y + (wide ? 15 : 13)),
                      static_cast<int16_t>(centerX + span / 2), baseY);
    display->drawLine(centerX, mainPeakY, centerX, static_cast<int16_t>(y + (wide ? 17 : 15)));

    // Approved JARNSEN MESH lettering is part of the logo, not re-typeset.
    display->drawXbm(wordmarkX, wordmarkY, wordmarkWidth, wordmarkHeight, wordmark);

    char versionBuild[48] = {};
    if (build::buildNumber > 0) {
        if (width >= 150)
            std::snprintf(versionBuild, sizeof(versionBuild), "%s Build %lu", build::version, build::buildNumber);
        else
            std::snprintf(versionBuild, sizeof(versionBuild), "%s B%lu", build::version, build::buildNumber);
    } else {
        std::snprintf(versionBuild, sizeof(versionBuild), "%s", build::version);
    }

    display->setFont(FONT_SMALL);
    display->drawString(centerX, versionY, versionBuild);
    display->drawString(centerX, hardwareY, build::hardwareName);

    display->setTextAlignment(TEXT_ALIGN_LEFT);
}

} // namespace jarnsen
#endif // HAS_SCREEN
