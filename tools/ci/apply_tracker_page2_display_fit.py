from pathlib import Path

path = Path("src/vehicle/TrackerStatusModule.cpp")
text = path.read_text()

start = text.index("void drawOwnNodePage(OLEDDisplay *display, int16_t x, int16_t y)\n{")
end = text.index("\nvoid drawServicePage(OLEDDisplay *display, int16_t x, int16_t y)", start)
old = text[start:end]
if old.count("AKKU ") != 2 or "voltage" not in old or "nameLength" not in old:
    raise SystemExit("unexpected drawOwnNodePage baseline")

new = r'''void drawOwnNodePage(OLEDDisplay *display, int16_t x, int16_t y)
{
    const int w = display->getWidth();
    const int h = display->getHeight();
    const auto bands = jarnsen::displayBands(h);
    const TrackerPowerStats p = trackerPowerMonitorStats();

    // Page 2 uses the same compact status header as the other pages:
    // page index on the left, battery indicator on the right, center intentionally empty.
    display->setFont(FONT_SMALL);
    display->setTextAlignment(TEXT_ALIGN_LEFT);
    display->drawString(x + 2, y + 1, "2/5");
    drawBattery(display, x, y);

    char name[32] = {};
    ownLongName(name, sizeof(name));
    const int maxNameWidth = std::max(1, w - 8);
    int nameHeight = FONT_HEIGHT_LARGE;

    // Fit by actual rendered pixel width, not character count. This matters on
    // the Tracker's 160x80 TFT because glyphs are variable-width.
    display->setFont(FONT_LARGE);
    if (display->getStringWidth(name) > maxNameWidth) {
        display->setFont(FONT_MEDIUM);
        nameHeight = FONT_HEIGHT_MEDIUM;
    }
    if (display->getStringWidth(name) > maxNameWidth) {
        display->setFont(FONT_SMALL);
        nameHeight = FONT_HEIGHT_SMALL;
    }
    if (display->getStringWidth(name) > maxNameWidth) {
        constexpr char ellipsis[] = "...";
        const int ellipsisWidth = display->getStringWidth(ellipsis);
        size_t len = std::strlen(name);
        while (len > 0 && display->getStringWidth(name) + ellipsisWidth > maxNameWidth)
            name[--len] = '\0';
        if (len + 3 < sizeof(name))
            std::strcat(name, ellipsis);
    }

    display->setTextAlignment(TEXT_ALIGN_CENTER);
    display->drawString(x + w / 2,
                        y + bands.middleY +
                            std::max(0, (static_cast<int>(bands.middleHeight) - nameHeight) / 2),
                        name);

    char ontime[16] = {};
    char remaining[16] = "LERNT";
    formatCompactDuration(millis() / 1000UL, ontime, sizeof(ontime));
    if (p.usbPowered)
        std::snprintf(remaining, sizeof(remaining), "USB");
    else if (p.charging)
        std::snprintf(remaining, sizeof(remaining), "LAEDT");
    else if (p.estimateReady)
        formatCompactDuration(p.remainingSecs, remaining, sizeof(remaining));

    char onText[24] = {};
    char restText[24] = {};
    std::snprintf(onText, sizeof(onText), "ON %s", ontime);
    std::snprintf(restText, sizeof(restText), "REST %s", remaining);
    display->setFont(FONT_SMALL);
    display->setTextAlignment(TEXT_ALIGN_LEFT);
    display->drawString(x + 2, y + bands.bottomY + 2, onText);
    display->setTextAlignment(TEXT_ALIGN_RIGHT);
    display->drawString(x + w - 2, y + bands.bottomY + 2, restText);
}
'''
text = text[:start] + new + text[end:]

old_count = '''    case MenuView::SYSTEM_INFO:
        return 4;
'''
new_count = '''    case MenuView::SYSTEM_INFO:
        return 5;
'''
if text.count(old_count) != 1:
    raise SystemExit(f"SYSTEM_INFO count baseline mismatch: {text.count(old_count)}")
text = text.replace(old_count, new_count, 1)

old_info = '''    case MenuView::SYSTEM_INFO:
        if (index == 0)
            return "ZURUECK";
        if (index == 1) {
            std::snprintf(buffer, size, "FW: %s", JARNSEN_FIRMWARE_VERSION);
            return buffer;
        }
        if (index == 2) {
            std::snprintf(buffer, size, "Build: %.8s", JARNSEN_BUILD_SHA);
            return buffer;
        }
        std::snprintf(buffer, size, "Role: %s", trackerRoleText());
        return buffer;
'''
new_info = '''    case MenuView::SYSTEM_INFO:
        if (index == 0)
            return "ZURUECK";
        if (index == 1) {
            std::snprintf(buffer, size, "FW: %s", JARNSEN_FIRMWARE_VERSION);
            return buffer;
        }
        if (index == 2) {
            std::snprintf(buffer, size, "Build: %.8s", JARNSEN_BUILD_SHA);
            return buffer;
        }
        if (index == 3) {
            std::snprintf(buffer, size, "Role: %s", trackerRoleText());
            return buffer;
        }
        const int displayWidth = screen ? screen->getWidth() : 0;
        const int displayHeight = screen ? screen->getHeight() : 0;
        std::snprintf(buffer, size, "Display: %dx%d", displayWidth, displayHeight);
        return buffer;
'''
if text.count(old_info) != 1:
    raise SystemExit(f"SYSTEM_INFO label baseline mismatch: {text.count(old_info)}")
text = text.replace(old_info, new_info, 1)

required = [
    'display->drawString(x + 2, y + 1, "2/5")',
    'display->getStringWidth(name)',
    'display->drawString(x + w - 2, y + bands.bottomY + 2, restText);',
    'Display: %dx%d',
]
for marker in required:
    if marker not in text:
        raise SystemExit(f"missing transformed marker: {marker}")

page2 = text[start:text.index("\nvoid drawServicePage", start)]
if "AKKU %s%u%%" in page2 or "char voltage" in page2:
    raise SystemExit("old page2 battery/voltage header remains")

path.write_text(text)
