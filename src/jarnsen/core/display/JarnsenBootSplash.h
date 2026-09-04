#pragma once

#include "configuration.h"

#if HAS_SCREEN
#include <OLEDDisplay.h>
#include "graphics/ScreenFonts.h"
#include "graphics/TFTColorRegions.h"
#include "graphics/TFTPalette.h"
#include "jarnsen/core/build/JarnsenBuildInfo.h"

#include <cstdio>

namespace jarnsen
{

// Shared JARNSEN-MESH boot splash for every supported board.
// The visual identity is fixed; version, build and hardware are injected from
// the common build metadata so each firmware shows exactly what is running.
inline void drawBootSplash(OLEDDisplay *display, int16_t x, int16_t y)
{
    const int16_t width = display->getWidth();
    const int16_t height = display->getHeight();
    const int16_t centerX = static_cast<int16_t>(x + width / 2);

    // Keep the three text lines readable even on 128x64. Larger displays use
    // the same layout rather than a board-specific splash.
    const int16_t titleY = static_cast<int16_t>(y + 18);
    const int16_t versionY = static_cast<int16_t>(height >= 80 ? y + 43 : y + 37);
    const int16_t hardwareY = static_cast<int16_t>(height >= 80 ? y + 58 : y + 50);

#if GRAPHICS_TFT_COLORING_ENABLED
    // Match the agreed design on color displays: black background, cyan mesh
    // and version, white product/hardware text.
    graphics::setAndRegisterTFTColorRole(graphics::TFTColorRole::BootSplash, graphics::TFTPalette::Cyan,
                                         graphics::TFTPalette::Black, x, y, width, height);
    graphics::registerTFTColorRegionDirect(x, titleY, width, FONT_HEIGHT_MEDIUM, graphics::TFTPalette::White,
                                           graphics::TFTPalette::Black);
    graphics::registerTFTColorRegionDirect(x, hardwareY, width, FONT_HEIGHT_SMALL, graphics::TFTPalette::White,
                                           graphics::TFTPalette::Black);
#endif

    display->setTextAlignment(TEXT_ALIGN_CENTER);

    // Scalable mesh emblem: deliberately geometric so the same logo remains
    // recognizable on 128x64 OLEDs and the wider Tracker display.
    const int16_t iconCenterY = static_cast<int16_t>(y + 9);
    const int16_t span = (width >= 150) ? 22 : 18;
    const int16_t halfSpan = static_cast<int16_t>(span / 2);

    const int16_t leftX = static_cast<int16_t>(centerX - span);
    const int16_t rightX = static_cast<int16_t>(centerX + span);
    const int16_t topX = centerX;
    const int16_t lowerLeftX = static_cast<int16_t>(centerX - halfSpan);
    const int16_t lowerRightX = static_cast<int16_t>(centerX + halfSpan);
    const int16_t topY = static_cast<int16_t>(iconCenterY - 6);
    const int16_t sideY = iconCenterY;
    const int16_t lowerY = static_cast<int16_t>(iconCenterY + 7);

    display->drawLine(leftX, sideY, topX, topY);
    display->drawLine(topX, topY, rightX, sideY);
    display->drawLine(leftX, sideY, lowerLeftX, lowerY);
    display->drawLine(lowerLeftX, lowerY, lowerRightX, lowerY);
    display->drawLine(lowerRightX, lowerY, rightX, sideY);
    display->drawLine(leftX, sideY, lowerRightX, lowerY);
    display->drawLine(rightX, sideY, lowerLeftX, lowerY);
    display->drawLine(topX, topY, lowerLeftX, lowerY);
    display->drawLine(topX, topY, lowerRightX, lowerY);

    display->fillCircle(leftX, sideY, 2);
    display->fillCircle(rightX, sideY, 2);
    display->fillCircle(topX, topY, 2);
    display->fillCircle(lowerLeftX, lowerY, 2);
    display->fillCircle(lowerRightX, lowerY, 2);

    display->setFont(FONT_MEDIUM);
    display->drawString(centerX, titleY, build::productName);

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
