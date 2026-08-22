from pathlib import Path

COMMON = Path("src/vehicle/TrackerCommonPolicy.cpp")
COMMON_H = Path("src/vehicle/TrackerCommonPolicy.h")
STATUS = Path("src/vehicle/TrackerStatusModule.cpp")

common = COMMON.read_text()
common_h = COMMON_H.read_text()
status = STATUS.read_text()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"{label}: already applied")
        return text
    if old not in text:
        raise SystemExit(f"{label}: anchor not found")
    print(f"{label}: applied")
    return text.replace(old, new, 1)


# Expose only read-only runtime state needed by the Service status page. These
# accessors do not wake the screen, GNSS, BLE or CPU; they simply report the
# state that already exists in TrackerCommonPolicy.
common_h = replace_once(
    common_h,
    '''void trackerCommonBleActivity();\n''',
    '''void trackerCommonBleActivity();\nconst char *trackerCommonRuntimeState();\nbool trackerCommonIsParked();\nbool trackerCommonParkGpsSearchPending();\nuint32_t trackerCommonParkNextTxSecs();\n''',
    "declare Tracker Service runtime-state accessors",
)

runtime_impl = r'''const char *trackerCommonRuntimeState()
{
    if (!trackerRoleEnabled())
        return "OFF";
    if (parkHeartbeatFixPending)
        return "GPS SEARCH";
    if (finalPositionWaitStartedMs != 0)
        return "FINAL GPS";
    if (finalPositionRequested)
        return "FINAL TX";
    if (motionActive)
        return "MOVING";
    if (parked)
        return "PARKED";
    if (motionCandidatePending)
        return "MOTION?";
    return "READY";
}

bool trackerCommonIsParked()
{
    return trackerRoleEnabled() && parked;
}

bool trackerCommonParkGpsSearchPending()
{
    return trackerRoleEnabled() && parkHeartbeatFixPending;
}

uint32_t trackerCommonParkNextTxSecs()
{
    if (!trackerRoleEnabled() || trackerUsesDeepSleep() || !parked)
        return UINT32_MAX;
    if (parkHeartbeatFixPending)
        return 0;

    const uint32_t interval = trackerEffectiveParkIntervalSecs();
    const uint32_t nowEpoch = getValidTime(RTCQualityDevice);
    if (lastPositionHeartbeatEpoch == 0 || nowEpoch == 0)
        return interval;
    if (nowEpoch < lastPositionHeartbeatEpoch)
        return interval;

    const uint32_t elapsed = nowEpoch - lastPositionHeartbeatEpoch;
    return elapsed >= interval ? 0U : interval - elapsed;
}

'''
common = replace_once(
    common,
    '''void trackerCommonBleActivity()\n{\n    if (trackerRoleEnabled())\n        rawBleActivitySequence.fetch_add(1);\n}\n\n''',
    '''void trackerCommonBleActivity()\n{\n    if (trackerRoleEnabled())\n        rawBleActivitySequence.fetch_add(1);\n}\n\n''' + runtime_impl,
    "implement Tracker Service runtime-state accessors",
)

# No-GPS/no-Tracker compile stubs keep the header safe in every build variant.
common = replace_once(
    common,
    '''bool trackerCommonScreenPowerAllowed(bool) { return true; }\nvoid trackerCommonBleActivity() {}\nvoid setupTrackerCommonPolicy() {}\n''',
    '''bool trackerCommonScreenPowerAllowed(bool) { return true; }\nvoid trackerCommonBleActivity() {}\nconst char *trackerCommonRuntimeState() { return "OFF"; }\nbool trackerCommonIsParked() { return false; }\nbool trackerCommonParkGpsSearchPending() { return false; }\nuint32_t trackerCommonParkNextTxSecs() { return UINT32_MAX; }\nvoid setupTrackerCommonPolicy() {}\n''',
    "Tracker Service runtime-state stubs",
)

# The previous visual pass intentionally reused drawDeviceFocused() as a quick
# approximation. The user's reference photos show that the correct result is a
# normal Meshtastic module page: stock header/title/navigation from Screen, with
# Service-specific content in the body. Replace only the body; no screen wake or
# timer behavior is introduced here.
status = replace_once(
    status,
    '#include "vehicle/TrackerStatusModule.h"\n',
    '#include "vehicle/TrackerStatusModule.h"\n#include "vehicle/TrackerCommonPolicy.h"\n',
    "Service page TrackerCommon runtime include",
)

old_body = '''        // Reuse the exact stock home renderer so the Service page visually\n        // matches the original Meshtastic page (status bar, spacing and font).\n        graphics::UIRenderer::drawDeviceFocused(display, state, x, y);\n\n        // Replace only the lowest content line with the Service affordance.\n        // The rest of the stock page is left untouched.\n        const int center = display->getWidth() / 2 + x;\n        const int16_t footerTop = (int16_t)display->getHeight() - 13 + y;\n        display->setColor(BLACK);\n        display->fillRect(x, footerTop, display->getWidth(), 13);\n        display->setColor(WHITE);\n        display->setTextAlignment(TEXT_ALIGN_CENTER);\n        display->setFont(FONT_SMALL);\n        display->drawString(center, footerTop + 1, "SERVICE  HOLD: SETTINGS");\n'''
new_body = r'''        // Screen/MeshModule already supplies the same stock top status bar,
        // centered page title ("Service") and bottom navigation indicator used
        // by Messages/Hops/Position. Draw only Tracker-specific body content.
        display->setColor(WHITE);
        display->setFont(FONT_SMALL);

        const int left = x + 2;
        const int right = x + display->getWidth() - 2;
        char line[72] = {};

        const char *role = config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER ? "TAK-TRK" : "TAK";
        display->setTextAlignment(TEXT_ALIGN_LEFT);
        display->drawString(left, 12 + y, role);
        display->setTextAlignment(TEXT_ALIGN_RIGHT);
        display->drawString(right, 12 + y, trackerCommonRuntimeState());

        display->setTextAlignment(TEXT_ALIGN_LEFT);
        snprintf(line, sizeof(line), "Motion: %s", trackerMotionSensitivityName());
        display->drawString(left, 25 + y, line);

        snprintf(line, sizeof(line), "Smart: %um / %us", (unsigned)trackerSmartDistanceM(),
                 (unsigned)trackerSmartIntervalSecs());
        display->drawString(left, 38 + y, line);

        char park[20] = {};
        trackerFormatParkInterval(park, sizeof(park));
        const char *gpsState = "WAIT";
        if (trackerCommonParkGpsSearchPending())
            gpsState = "SEARCH";
        else if (trackerCommonIsParked() && config.device.role == meshtastic_Config_DeviceConfig_Role_TAK)
            gpsState = "SLEEP";
        else if (gpsStatus && gpsStatus->getHasLock())
            gpsState = "FIX";
        snprintf(line, sizeof(line), "Park: %s   GPS:%s", park, gpsState);
        display->drawString(left, 51 + y, line);

        const uint32_t nextTx = trackerCommonParkNextTxSecs();
        char next[24] = {};
        if (nextTx == UINT32_MAX) {
            snprintf(next, sizeof(next), "BT:%s", config.bluetooth.enabled ? "ON" : "OFF");
        } else if (nextTx == 0) {
            snprintf(next, sizeof(next), "Next:NOW");
        } else if (nextTx < 60U) {
            snprintf(next, sizeof(next), "Next:%us", (unsigned)nextTx);
        } else if (nextTx < 3600U) {
            snprintf(next, sizeof(next), "Next:%um", (unsigned)((nextTx + 59U) / 60U));
        } else {
            const uint32_t hours = nextTx / 3600U;
            const uint32_t mins = (nextTx % 3600U) / 60U;
            snprintf(next, sizeof(next), "Next:%uh%02um", (unsigned)hours, (unsigned)mins);
        }

        snprintf(line, sizeof(line), "%s   BT:%s   Log:%s", next,
                 config.bluetooth.enabled ? "ON" : "OFF", trackerDiagEnabled() ? "ON" : "OFF");
        display->drawString(left, 64 + y, line);
'''
status = replace_once(status, old_body, new_body, "native Meshtastic-style Tracker Service status body")

# Remove the now-unused full start-page renderer include so the implementation
# clearly remains a module body and cannot accidentally clear/redraw the screen.
status = status.replace('#include "graphics/draw/UIRenderer.h"\n', '')

for text, needle in [
    (common_h, 'const char *trackerCommonRuntimeState();'),
    (common, 'return "GPS SEARCH";'),
    (common, 'uint32_t trackerCommonParkNextTxSecs()'),
    (status, 'display->drawString(right, 12 + y, trackerCommonRuntimeState());'),
    (status, '"Motion: %s"'),
    (status, '"Smart: %um / %us"'),
    (status, '"Park: %s   GPS:%s"'),
    (status, '"Next:NOW"'),
    (status, 'trackerDiagEnabled() ? "ON" : "OFF"'),
]:
    if needle not in text:
        raise SystemExit(f"Tracker Service status-page verification failed: {needle}")

if 'SERVICE  HOLD: SETTINGS' in status or 'drawDeviceFocused(display, state, x, y)' in status:
    raise SystemExit("Tracker Service status-page verification failed: old start-page approximation remains")

COMMON.write_text(common)
COMMON_H.write_text(common_h)
STATUS.write_text(status)
