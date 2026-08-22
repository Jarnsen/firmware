from pathlib import Path

STATUS = Path("src/vehicle/TrackerStatusModule.cpp")
text = STATUS.read_text()


def add_include(anchor: str, include: str, label: str):
    global text
    if include in text:
        print(f"{label}: already present")
        return
    if anchor not in text:
        raise SystemExit(f"{label}: anchor not found")
    text = text.replace(anchor, anchor + include, 1)
    print(f"{label}: applied")


# The Service module is rendered through FOCUS_MODULE. Unlike normal stock
# carousel frames, that focused path does not automatically draw the common
# Meshtastic header/navigation overlay. Use the exact stock helpers explicitly
# instead of imitating them by hand.
add_include(
    '#include "graphics/ScreenFonts.h"\n',
    '#include "graphics/SharedUIDisplay.h"\n',
    "stock Meshtastic common header/footer include",
)
add_include(
    '#include "graphics/draw/NotificationRenderer.h"\n',
    '#include "graphics/draw/UIRenderer.h"\n',
    "stock Meshtastic navigation renderer include",
)

if 'graphics::drawCommonHeader(display, x, y, "Service");' in text and \
   'graphics::UIRenderer::drawNavigationBar(display, state);' in text:
    print("Tracker Service stock frame: already applied")
else:
    start_marker = '        // Screen/MeshModule already supplies the same stock top status bar,'
    end_marker = '        display->drawString(left, 64 + y, line);\n'
    start = text.find(start_marker)
    if start < 0:
        raise SystemExit("Tracker Service stock frame: start marker not found")
    end = text.find(end_marker, start)
    if end < 0:
        raise SystemExit("Tracker Service stock frame: end marker not found")
    end += len(end_marker)

    body = r'''        // FOCUS_MODULE does not receive the normal stock frame chrome, so draw
        // the same shared Meshtastic header and navigation overlay explicitly.
        // This page still has no wake behavior of its own: it is only rendered
        // while TrackerCommon already has the display on after a GPIO0 press.
        display->clear();
        graphics::drawCommonHeader(display, x, y, "Service");

        display->setColor(WHITE);
        display->setFont(FONT_SMALL);
        const int *textPos = graphics::getTextPositions(display);
        const int left = x + 2;
        const int right = x + display->getWidth() - 2;
        char line[72] = {};

        // Row 1: role and live Tracker state, matching the compact two-column
        // layout used by stock Meshtastic status pages.
        const char *role = config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER ? "TAK-TRK" : "TAK";
        display->setTextAlignment(TEXT_ALIGN_LEFT);
        display->drawString(left, textPos[1], role);
        display->setTextAlignment(TEXT_ALIGN_RIGHT);
        display->drawString(right, textPos[1], trackerCommonRuntimeState());

        // Determine current GNSS state without waking GNSS just for the screen.
        const char *gpsState = "WAIT";
        if (trackerCommonParkGpsSearchPending())
            gpsState = "SEARCH";
        else if (trackerCommonIsParked() && config.device.role == meshtastic_Config_DeviceConfig_Role_TAK)
            gpsState = "SLEEP";
        else if (gpsStatus && gpsStatus->getHasLock())
            gpsState = "FIX";

        // Row 2: motion preset + GNSS state.
        display->setTextAlignment(TEXT_ALIGN_LEFT);
        snprintf(line, sizeof(line), "Motion:%s", trackerMotionSensitivityName());
        display->drawString(left, textPos[2], line);
        display->setTextAlignment(TEXT_ALIGN_RIGHT);
        snprintf(line, sizeof(line), "GPS:%s", gpsState);
        display->drawString(right, textPos[2], line);

        // Row 3: Smart Position + parked heartbeat interval.
        display->setTextAlignment(TEXT_ALIGN_LEFT);
        snprintf(line, sizeof(line), "Smart:%um/%us", (unsigned)trackerSmartDistanceM(),
                 (unsigned)trackerSmartIntervalSecs());
        display->drawString(left, textPos[3], line);
        char park[20] = {};
        trackerFormatParkInterval(park, sizeof(park));
        display->setTextAlignment(TEXT_ALIGN_RIGHT);
        snprintf(line, sizeof(line), "Park:%s", park);
        display->drawString(right, textPos[3], line);

        // Row 4: next parked TX (when meaningful), Bluetooth and diagnostic log.
        const uint32_t nextTx = trackerCommonParkNextTxSecs();
        char next[24] = {};
        if (nextTx == UINT32_MAX) {
            next[0] = '\0';
        } else if (nextTx == 0) {
            snprintf(next, sizeof(next), "Next:NOW ");
        } else if (nextTx < 60U) {
            snprintf(next, sizeof(next), "Next:%us ", (unsigned)nextTx);
        } else if (nextTx < 3600U) {
            snprintf(next, sizeof(next), "Next:%um ", (unsigned)((nextTx + 59U) / 60U));
        } else {
            const uint32_t hours = nextTx / 3600U;
            const uint32_t mins = (nextTx % 3600U) / 60U;
            snprintf(next, sizeof(next), "Next:%uh%02um ", (unsigned)hours, (unsigned)mins);
        }

        display->setTextAlignment(TEXT_ALIGN_LEFT);
        snprintf(line, sizeof(line), "%sBT:%s  Log:%s", next,
                 config.bluetooth.enabled ? "ON" : "OFF", trackerDiagEnabled() ? "ON" : "OFF");
        display->drawString(left, textPos[4], line);

        // Same stock footer/link indicator and temporary navigation-icon bar as
        // the user's original Messages/Hops/Position pages.
        graphics::drawCommonFooter(display, x, y);
        if (state)
            graphics::UIRenderer::drawNavigationBar(display, state);
'''
    text = text[:start] + body + text[end:]
    print("Tracker Service stock frame: applied")

for needle in [
    '#include "graphics/SharedUIDisplay.h"',
    '#include "graphics/draw/UIRenderer.h"',
    'graphics::drawCommonHeader(display, x, y, "Service");',
    'graphics::getTextPositions(display)',
    '"Motion:%s"',
    '"GPS:%s"',
    '"Smart:%um/%us"',
    '"Park:%s"',
    'graphics::drawCommonFooter(display, x, y);',
    'graphics::UIRenderer::drawNavigationBar(display, state);',
]:
    if needle not in text:
        raise SystemExit(f"Tracker Service stock frame verification failed: {needle}")

if 'Screen/MeshModule already supplies the same stock top status bar' in text:
    raise SystemExit("Tracker Service stock frame verification failed: old false header assumption remains")

STATUS.write_text(text)
