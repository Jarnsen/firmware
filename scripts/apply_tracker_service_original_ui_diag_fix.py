from pathlib import Path

COMMON = Path("src/vehicle/TrackerCommonPolicy.cpp")
STATUS = Path("src/vehicle/TrackerStatusModule.cpp")
STATUS_H = Path("src/vehicle/TrackerStatusModule.h")
NIMBLE = Path("src/nimble/NimbleBluetooth.cpp")
SCREEN_H = Path("src/graphics/Screen.h")
POWER = Path("src/PowerFSM.cpp")
POSITION = Path("src/modules/PositionModule.cpp")

common = COMMON.read_text()
status = STATUS.read_text()
status_h = STATUS_H.read_text()
nimble = NIMBLE.read_text()
screen_h = SCREEN_H.read_text()
power = POWER.read_text()
position = POSITION.read_text()


def replace_once(text, old, new, label):
    if new in text:
        print(f"{label}: already applied")
        return text
    if old not in text:
        raise SystemExit(f"{label}: anchor not found")
    print(f"{label}: applied")
    return text.replace(old, new, 1)


def replace_span(text, start_marker, end_marker, replacement, label, include_end=False):
    start = text.find(start_marker)
    if start < 0:
        raise SystemExit(f"{label}: start marker not found")
    end = text.find(end_marker, start)
    if end < 0:
        raise SystemExit(f"{label}: end marker not found")
    if include_end:
        end += len(end_marker)
    print(f"{label}: applied")
    return text[:start] + replacement + text[end:]


# ---------------------------------------------------------------------------
# BLE: suspend is intentionally resumable, so make it idempotent. The previous
# service loop called bluetoothOff() every 10ms while parked; because isActive()
# stays true in suspended mode this caused thousands of PhoneAPI::close() calls.
# ---------------------------------------------------------------------------
nimble = replace_once(
    nimble,
    '''void NimbleBluetooth::suspend()\n{\n#ifdef ARCH_ESP32\n    if (!isActive())\n        return;\n\n    LOG_INFO("Suspend bluetooth service; keep NimBLE host resumeable");\n    bleSuspended = true;\n''',
    '''void NimbleBluetooth::suspend()\n{\n#ifdef ARCH_ESP32\n    if (!isActive())\n        return;\n    if (bleSuspended.exchange(true))\n        return;\n\n    LOG_INFO("Suspend bluetooth service; keep NimBLE host resumeable");\n''',
    "idempotent resumable BLE suspend",
)

# ---------------------------------------------------------------------------
# Screen helper: identify whether the dedicated Service module is the current
# normal carousel page. Long press only opens settings from that page.
# ---------------------------------------------------------------------------
screen_h = replace_once(
    screen_h,
    '''    bool isScreenOn() { return screenOn; }\n''',
    '''    bool isScreenOn() { return screenOn; }\n    uint8_t currentFrameIndex() { return ui ? ui->getUiState()->currentFrame : 255; }\n''',
    "expose current native frame index to Tracker service",
)

# Native serial monitor / downloader should veto sleep, but charging/external
# power must not. The old OR with getHasUSB() prevented a vehicle-powered
# TAK_TRACKER from ever entering the timed deep-sleep cycle.
power = replace_once(
    power,
    '''    return trackerOwnsInteractiveOutputs() &&\n           (nativeSerialConnected || (powerStatus && powerStatus->getHasUSB()));\n''',
    '''    return trackerOwnsInteractiveOutputs() && nativeSerialConnected;\n''',
    "only an open native USB serial session vetoes Tracker sleep",
)

# ---------------------------------------------------------------------------
# Replace the hand-drawn Tracker service sub-pages with the stock Meshtastic
# selection-picker renderer. This gives the same white list, border, arrows and
# scrollbar as the original menu shown by the user, while GPIO0 remains solely
# owned by TrackerCommon (no generic UserButton ISR ownership collision).
# ---------------------------------------------------------------------------
status = replace_once(
    status,
    '#include "graphics/ScreenFonts.h"\n',
    '#include "graphics/ScreenFonts.h"\n#include "graphics/draw/NotificationRenderer.h"\n',
    "Tracker service original menu renderer include",
)
status = replace_once(
    status,
    '#include "vehicle/TrackerEnhancements.h"\n',
    '#include "vehicle/TrackerEnhancements.h"\n#include "vehicle/TrackerDiagnosticLog.h"\n',
    "Tracker service diagnostic log include",
)

new_state = r'''enum class TrackerMenu : uint8_t {
    NONE = 0,
    ROOT,
    POSITION,
    DISTANCE,
    INTERVAL,
    MOTION,
    MOTION_SENS,
    PARK_POWER,
    PARK_INTERVAL,
    BLUETOOTH,
    DIAG_LOG,
    LOGGING,
    LOG_STATUS,
    LOG_CLEAR,
    SYSTEM_INFO,
};

bool trackerServiceMenuMode = false;
TrackerMenu trackerMenuCurrent = TrackerMenu::NONE;
TrackerMenu trackerMenuPending = TrackerMenu::NONE;
int8_t trackerMenuPendingSelection = 0;
int8_t trackerRootSelection = 0;
int8_t trackerPositionSelection = 0;
int8_t trackerMotionSelection = 0;
int8_t trackerParkSelection = 0;
int8_t trackerBluetoothSelection = 0;
int8_t trackerDiagSelection = 0;
volatile uint8_t trackerServiceFrameIndex = 255;

'''
status = replace_span(status, 'enum TrackerServicePage : uint8_t {', 'bool trackerUiRoleEnabled()', new_state,
                      "replace old Tracker service page state")

new_service_impl = r'''class TrackerServiceModule : public MeshModule
{
  public:
    TrackerServiceModule() : MeshModule("Service") {}

    bool wantPacket(const meshtastic_MeshPacket *) override { return false; }
    bool wantUIFrame() override { return trackerUiRoleEnabled(); }
    void requestServiceFocus() { requestFocus(); }

    void drawFrame(OLEDDisplay *display, OLEDDisplayUiState *state, int16_t x, int16_t y) override
    {
        if (!display)
            return;

        if (state) {
            if (state->frameState == IN_TRANSITION &&
                state->transitionFrameRelationship == TransitionRelationship_INCOMING)
                trackerServiceFrameIndex = state->transitionFrameTarget;
            else
                trackerServiceFrameIndex = state->currentFrame;
        }

        const int center = display->getWidth() / 2 + x;
        display->setTextAlignment(TEXT_ALIGN_CENTER);
        display->setFont(FONT_SMALL);

        const char *role = config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER ? "TAK_TRACKER" : "TAK";
        char line[72] = {};
        snprintf(line, sizeof(line), "Mode: %s   Log:%s", role, trackerDiagEnabled() ? "ON" : "OFF");
        display->drawString(center, 11 + y, line);
        snprintf(line, sizeof(line), "Motion: %s", trackerMotionSensitivityName());
        display->drawString(center, 24 + y, line);
        snprintf(line, sizeof(line), "Smart: %um / %us", (unsigned)trackerSmartDistanceM(),
                 (unsigned)trackerSmartIntervalSecs());
        display->drawString(center, 37 + y, line);
        char park[20] = {};
        trackerFormatParkInterval(park, sizeof(park));
        snprintf(line, sizeof(line), "Park: %s   GPS:%s", park,
                 trackerLastFixAgeSecs() == UINT32_MAX ? "WAIT" : "FIX");
        display->drawString(center, 50 + y, line);
        display->drawString(center, 64 + y, "HOLD: SETTINGS");
    }
};

TrackerServiceModule trackerServiceModule;

void queueTrackerMenu(TrackerMenu menu, int selection)
{
    trackerMenuPending = menu;
    trackerMenuPendingSelection = selection < 0 ? 0 : (int8_t)selection;
}

void showTrackerOptions(const char *title, const char **options, uint8_t count, int selected,
                        std::function<void(int)> callback)
{
    if (!screen)
        return;
    graphics::BannerOverlayOptions banner;
    banner.message = title;
    banner.optionsArrayPtr = options;
    banner.optionsCount = count;
    banner.bannerCallback = callback;
    banner.InitialSelected = selected;
    banner.durationMs = 0; // Tracker's own 20s display timer owns visibility.
    banner.notificationType = graphics::notificationTypeEnum::selection_picker;
    screen->showOverlayBanner(banner);
}

int distanceSelection()
{
    switch (trackerSmartDistanceM()) {
    case 50: return 1;
    case 75: return 2;
    case 100: return 3;
    case 150: return 4;
    default: return 1;
    }
}

int intervalSelection()
{
    switch (trackerSmartIntervalSecs()) {
    case 30: return 1;
    case 45: return 2;
    case 60: return 3;
    case 90: return 4;
    default: return 1;
    }
}

int parkIntervalSelection()
{
    switch (trackerParkIntervalMinutes()) {
    case 20: return 1;
    case 30: return 2;
    case 60: return 3;
    case 120: return 4;
    case 240: return 5;
    case 360: return 6;
    case 540: return 7;
    case 720: return 8;
    default: return 3;
    }
}

void markOption(char *out, size_t outSize, bool selected, const char *label)
{
    snprintf(out, outSize, "[%c] %s", selected ? 'x' : ' ', label);
}

void showTrackerMenu(TrackerMenu menu, int initialSelection)
{
    trackerMenuCurrent = menu;
    trackerMenuPending = TrackerMenu::NONE;

    switch (menu) {
    case TrackerMenu::ROOT: {
        static const char *opts[] = {"Back", "Position", "Motion", "Park / Power", "Bluetooth", "Diagnostic Log", "System Info"};
        showTrackerOptions("Service Settings", opts, 7, initialSelection, [](int selected) {
            trackerRootSelection = selected;
            switch (selected) {
            case 0: trackerServiceMenuMode = false; trackerMenuCurrent = TrackerMenu::NONE; trackerServiceModule.requestServiceFocus(); if (screen) { screen->setFrames(graphics::Screen::FOCUS_MODULE); screen->runNow(); } break;
            case 1: queueTrackerMenu(TrackerMenu::POSITION, trackerPositionSelection); break;
            case 2: queueTrackerMenu(TrackerMenu::MOTION, trackerMotionSelection); break;
            case 3: queueTrackerMenu(TrackerMenu::PARK_POWER, trackerParkSelection); break;
            case 4: queueTrackerMenu(TrackerMenu::BLUETOOTH, trackerBluetoothSelection); break;
            case 5: queueTrackerMenu(TrackerMenu::DIAG_LOG, trackerDiagSelection); break;
            case 6: queueTrackerMenu(TrackerMenu::SYSTEM_INFO, 0); break;
            }
        });
        break;
    }
    case TrackerMenu::POSITION: {
        static const char *opts[] = {"Back", "Smart Distance", "Smart Interval", "Local GNSS: 5 s"};
        showTrackerOptions("Position Settings", opts, 4, initialSelection, [](int selected) {
            trackerPositionSelection = selected;
            if (selected == 0) queueTrackerMenu(TrackerMenu::ROOT, trackerRootSelection);
            else if (selected == 1) queueTrackerMenu(TrackerMenu::DISTANCE, distanceSelection());
            else if (selected == 2) queueTrackerMenu(TrackerMenu::INTERVAL, intervalSelection());
            else queueTrackerMenu(TrackerMenu::POSITION, selected);
        });
        break;
    }
    case TrackerMenu::DISTANCE: {
        static char labels[5][24];
        static const char *opts[5] = {labels[0], labels[1], labels[2], labels[3], labels[4]};
        snprintf(labels[0], sizeof(labels[0]), "Back");
        const uint16_t vals[] = {50, 75, 100, 150};
        for (int i = 0; i < 4; ++i) { char raw[12]; snprintf(raw, sizeof(raw), "%u m", (unsigned)vals[i]); markOption(labels[i + 1], sizeof(labels[i + 1]), trackerSmartDistanceM() == vals[i], raw); }
        showTrackerOptions("Smart Distance", opts, 5, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::POSITION, trackerPositionSelection);
            else { const uint16_t vals[] = {50, 75, 100, 150}; trackerSetSmartDistanceM(vals[selected - 1]); queueTrackerMenu(TrackerMenu::DISTANCE, selected); }
        });
        break;
    }
    case TrackerMenu::INTERVAL: {
        static char labels[5][24];
        static const char *opts[5] = {labels[0], labels[1], labels[2], labels[3], labels[4]};
        snprintf(labels[0], sizeof(labels[0]), "Back");
        const uint16_t vals[] = {30, 45, 60, 90};
        for (int i = 0; i < 4; ++i) { char raw[12]; snprintf(raw, sizeof(raw), "%u s", (unsigned)vals[i]); markOption(labels[i + 1], sizeof(labels[i + 1]), trackerSmartIntervalSecs() == vals[i], raw); }
        showTrackerOptions("Smart Interval", opts, 5, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::POSITION, trackerPositionSelection);
            else { const uint16_t vals[] = {30, 45, 60, 90}; trackerSetSmartIntervalSecs(vals[selected - 1]); queueTrackerMenu(TrackerMenu::INTERVAL, selected); }
        });
        break;
    }
    case TrackerMenu::MOTION: {
        static char sensor[40];
        static char confirm[40];
        static const char *opts[] = {"Back", "Sensitivity", sensor, confirm};
        snprintf(sensor, sizeof(sensor), "Sensor: %s", trackerMotionSensorStatus());
        snprintf(confirm, sizeof(confirm), "Confirm: %u / %us", (unsigned)trackerMotionConfirmCount(), (unsigned)(trackerMotionConfirmWindowMs() / 1000UL));
        showTrackerOptions("Motion Settings", opts, 4, initialSelection, [](int selected) {
            trackerMotionSelection = selected;
            if (selected == 0) queueTrackerMenu(TrackerMenu::ROOT, trackerRootSelection);
            else if (selected == 1) queueTrackerMenu(TrackerMenu::MOTION_SENS, trackerMotionSensitivityIndex() + 1);
            else queueTrackerMenu(TrackerMenu::MOTION, selected);
        });
        break;
    }
    case TrackerMenu::MOTION_SENS: {
        static char labels[5][28];
        static const char *opts[5] = {labels[0], labels[1], labels[2], labels[3], labels[4]};
        snprintf(labels[0], sizeof(labels[0]), "Back");
        const char *names[] = {"VERY SENS", "SENSITIVE", "NORMAL", "ROBUST"};
        for (int i = 0; i < 4; ++i) markOption(labels[i + 1], sizeof(labels[i + 1]), trackerMotionSensitivityIndex() == i, names[i]);
        showTrackerOptions("Motion Sensitivity", opts, 5, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::MOTION, trackerMotionSelection);
            else { trackerSetMotionSensitivityIndex((uint8_t)(selected - 1)); queueTrackerMenu(TrackerMenu::MOTION_SENS, selected); }
        });
        break;
    }
    case TrackerMenu::PARK_POWER: {
        static char mode[40];
        static const char *opts[] = {"Back", "Park Interval", "GPS Wake Wait: 30 s", mode};
        snprintf(mode, sizeof(mode), "Mode: %s", config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER ? "Deep sleep" : "Light sleep");
        showTrackerOptions("Park / Power", opts, 4, initialSelection, [](int selected) {
            trackerParkSelection = selected;
            if (selected == 0) queueTrackerMenu(TrackerMenu::ROOT, trackerRootSelection);
            else if (selected == 1) queueTrackerMenu(TrackerMenu::PARK_INTERVAL, parkIntervalSelection());
            else queueTrackerMenu(TrackerMenu::PARK_POWER, selected);
        });
        break;
    }
    case TrackerMenu::PARK_INTERVAL: {
        static char labels[9][24];
        static const char *opts[9] = {labels[0], labels[1], labels[2], labels[3], labels[4], labels[5], labels[6], labels[7], labels[8]};
        const uint16_t vals[] = {20, 30, 60, 120, 240, 360, 540, 720};
        const char *names[] = {"20 min", "30 min", "60 min", "2 h", "4 h", "6 h", "9 h", "12 h"};
        snprintf(labels[0], sizeof(labels[0]), "Back");
        for (int i = 0; i < 8; ++i) markOption(labels[i + 1], sizeof(labels[i + 1]), trackerParkIntervalMinutes() == vals[i], names[i]);
        showTrackerOptions("Park Interval", opts, 9, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::PARK_POWER, trackerParkSelection);
            else { const uint16_t vals[] = {20, 30, 60, 120, 240, 360, 540, 720}; trackerSetParkIntervalMinutes(vals[selected - 1]); queueTrackerMenu(TrackerMenu::PARK_INTERVAL, selected); }
        });
        break;
    }
    case TrackerMenu::BLUETOOTH: {
        static char state[32];
        static const char *opts[] = {"Back", state, "Idle timeout: 120 s", "Hard cap: 15 min"};
        snprintf(state, sizeof(state), "Service: %s", config.bluetooth.enabled ? "ON" : "OFF");
        showTrackerOptions("Bluetooth", opts, 4, initialSelection, [](int selected) {
            trackerBluetoothSelection = selected;
            if (selected == 0) queueTrackerMenu(TrackerMenu::ROOT, trackerRootSelection);
            else queueTrackerMenu(TrackerMenu::BLUETOOTH, selected);
        });
        break;
    }
    case TrackerMenu::DIAG_LOG: {
        static char state[32];
        static const char *opts[] = {"Back", "Logging", state, "Export via USB", "Clear Log"};
        snprintf(state, sizeof(state), "Status: %s", trackerDiagEnabled() ? "ON" : "OFF");
        showTrackerOptions("Diagnostic Log", opts, 5, initialSelection, [](int selected) {
            trackerDiagSelection = selected;
            if (selected == 0) queueTrackerMenu(TrackerMenu::ROOT, trackerRootSelection);
            else if (selected == 1) queueTrackerMenu(TrackerMenu::LOGGING, trackerDiagEnabled() ? 2 : 1);
            else if (selected == 2) queueTrackerMenu(TrackerMenu::LOG_STATUS, 0);
            else if (selected == 3) { trackerDiagRequestUsbExport(); queueTrackerMenu(TrackerMenu::DIAG_LOG, selected); }
            else if (selected == 4) queueTrackerMenu(TrackerMenu::LOG_CLEAR, 0);
        });
        break;
    }
    case TrackerMenu::LOGGING: {
        static char off[24], on[24];
        static const char *opts[] = {"Back", off, on};
        markOption(off, sizeof(off), !trackerDiagEnabled(), "Off");
        markOption(on, sizeof(on), trackerDiagEnabled(), "On");
        showTrackerOptions("Diagnostic Logging", opts, 3, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::DIAG_LOG, trackerDiagSelection);
            else { trackerDiagSetEnabled(selected == 2); queueTrackerMenu(TrackerMenu::LOGGING, selected); }
        });
        break;
    }
    case TrackerMenu::LOG_STATUS: {
        static char sizeLine[40], exportLine[40];
        static const char *opts[] = {"Back", sizeLine, exportLine};
        snprintf(sizeLine, sizeof(sizeLine), "Size: %u KB", (unsigned)((trackerDiagLogSize() + 1023U) / 1024U));
        snprintf(exportLine, sizeof(exportLine), "USB export: %s", trackerDiagUsbExportPending() ? "WAIT/RUN" : "READY");
        showTrackerOptions("Log Status", opts, 3, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::DIAG_LOG, trackerDiagSelection);
            else queueTrackerMenu(TrackerMenu::LOG_STATUS, selected);
        });
        break;
    }
    case TrackerMenu::LOG_CLEAR: {
        static const char *opts[] = {"Back", "CLEAR LOG NOW"};
        showTrackerOptions("Clear Diagnostic Log?", opts, 2, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::DIAG_LOG, trackerDiagSelection);
            else { trackerDiagClear(); queueTrackerMenu(TrackerMenu::LOG_CLEAR, selected); }
        });
        break;
    }
    case TrackerMenu::SYSTEM_INFO: {
        static char version[48], build[40], wake[48], role[40];
        static const char *opts[] = {"Back", version, build, wake, role};
        snprintf(version, sizeof(version), "FW: %s", JARNSEN_FIRMWARE_VERSION);
        snprintf(build, sizeof(build), "Build: %.8s", JARNSEN_BUILD_SHA);
        snprintf(wake, sizeof(wake), "Wake: %s", trackerBootWakeReason());
        snprintf(role, sizeof(role), "Role: %s", config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER ? "TAK_TRACKER" : "TAK");
        showTrackerOptions("System Info", opts, 5, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::ROOT, trackerRootSelection);
            else queueTrackerMenu(TrackerMenu::SYSTEM_INFO, selected);
        });
        break;
    }
    default:
        break;
    }
}
'''
status = replace_span(status, 'class TrackerServiceModule : public MeshModule', 'TrackerServiceModule trackerServiceModule;',
                      new_service_impl, "replace Tracker service class with stock original-style menu", include_end=True)

new_public = r'''bool trackerServiceMenuActive()
{
    return trackerServiceMenuMode;
}

bool trackerServicePageVisible()
{
    return !trackerServiceMenuMode && screen && trackerServiceFrameIndex != 255 &&
           screen->currentFrameIndex() == trackerServiceFrameIndex;
}

void trackerServiceMenuOpen()
{
    if (!trackerUiRoleEnabled() || !trackerServicePageVisible())
        return;
    trackerServiceMenuMode = true;
    trackerRootSelection = 0;
    queueTrackerMenu(TrackerMenu::ROOT, trackerRootSelection);
}

void trackerServiceMenuShortPress()
{
    if (!trackerServiceMenuMode || !screen)
        return;
    graphics::NotificationRenderer::inEvent.inputEvent = INPUT_BROKER_USER_PRESS;
    screen->runNow();
}

void trackerServiceMenuSelect()
{
    if (!trackerServiceMenuMode || !screen)
        return;
    graphics::NotificationRenderer::inEvent.inputEvent = INPUT_BROKER_SELECT;
    screen->runNow();
}

void trackerServiceMenuPump()
{
    if (!trackerServiceMenuMode || trackerMenuPending == TrackerMenu::NONE)
        return;
    const TrackerMenu menu = trackerMenuPending;
    const int selection = trackerMenuPendingSelection;
    showTrackerMenu(menu, selection);
}

void trackerServiceMenuClose()
{
    trackerServiceMenuMode = false;
    trackerMenuCurrent = TrackerMenu::NONE;
    trackerMenuPending = TrackerMenu::NONE;
    graphics::NotificationRenderer::resetBanner();
    trackerServiceModule.requestServiceFocus();
    if (screen) {
        screen->setFrames(graphics::Screen::FOCUS_MODULE);
        screen->runNow();
    }
}

void trackerServiceMenuForceClose()
{
    trackerServiceMenuMode = false;
    trackerMenuCurrent = TrackerMenu::NONE;
    trackerMenuPending = TrackerMenu::NONE;
    graphics::NotificationRenderer::resetBanner();
}

'''
status = replace_span(status, 'bool trackerServiceMenuActive()', '#else', new_public + '#else',
                      "replace old Tracker service public actions")

# Replace declarations produced by the earlier service patch.
status_h = replace_span(
    status_h,
    'bool trackerServiceMenuActive();',
    'void trackerServiceMenuClose();',
    '''bool trackerServiceMenuActive();\nbool trackerServicePageVisible();\nvoid trackerServiceMenuOpen();\nvoid trackerServiceMenuShortPress();\nvoid trackerServiceMenuSelect();\nvoid trackerServiceMenuPump();\nvoid trackerServiceMenuClose();\nvoid trackerServiceMenuForceClose();''',
    "Tracker service original-menu declarations",
    include_end=True,
)

# No-screen stubs were created by the earlier service patch. Replace them too.
status = status.replace(
    '''bool trackerServiceMenuActive() { return false; }\nvoid trackerServiceMenuOpen() {}\nvoid trackerServiceMenuNext() {}\nvoid trackerServiceMenuLongAction() {}\nvoid trackerServiceMenuClose() {}\n''',
    '''bool trackerServiceMenuActive() { return false; }\nbool trackerServicePageVisible() { return false; }\nvoid trackerServiceMenuOpen() {}\nvoid trackerServiceMenuShortPress() {}\nvoid trackerServiceMenuSelect() {}\nvoid trackerServiceMenuPump() {}\nvoid trackerServiceMenuClose() {}\nvoid trackerServiceMenuForceClose() {}\n''')

# ---------------------------------------------------------------------------
# TrackerCommon: menu gesture ownership, 20s timer on EVERY button press,
# persistent diagnostics, and parked wake fixes.
# ---------------------------------------------------------------------------
common = replace_once(common, '#include "TrackerEnhancements.h"\n',
                      '#include "TrackerEnhancements.h"\n#include "TrackerDiagnosticLog.h"\n#include "GPSStatus.h"\n',
                      "Tracker common diagnostic includes")

common = replace_once(
    common,
    '''    if (screen) {\n        screen->setOn(true);\n        trackerStatusRequestFocus();\n        screen->runNow();\n    }\n''',
    '''    if (screen) {\n        screen->setOn(true);\n        if (!trackerServiceMenuActive())\n            trackerStatusRequestFocus();\n        screen->runNow();\n    }\n''',
    "preserve Tracker menu when display is restored",
)

common = replace_once(
    common,
    '''    serviceActive = false;\n    bluetoothOff();\n    closeDisplay();\n''',
    '''    serviceActive = false;\n    trackerServiceMenuForceClose();\n    bluetoothOff();\n    trackerDiagLog("BT_SERVICE", "closed/suspended");\n    closeDisplay();\n''',
    "close Tracker menu and log BLE service shutdown",
)

common = replace_once(
    common,
    '''    bluetoothOn();\n    showTrackerScreen();\n''',
    '''    bluetoothOn();\n    trackerDiagLog("BT_SERVICE", "opened/resumed");\n    showTrackerScreen();\n''',
    "log Tracker BLE service startup",
)

# Deep-sleep Tracker may be connected to vehicle power. Only a real open native
# serial session is a maintenance veto; VBUS/charging alone must still sleep.
common = replace_once(
    common,
    '''        if (usbPowered())\n            return; // USB is a test/maintenance veto only.\n''',
    '''#if defined(ARDUINO_USB_CDC_ON_BOOT) && ARDUINO_USB_CDC_ON_BOOT\n        if ((bool)Serial) {\n            trackerDiagLog("PARK_SLEEP", "deep sleep veto: native serial connected");\n            return;\n        }\n#endif\n''',
    "allow externally powered TAK_TRACKER timed deep sleep",
)

# Long press only opens the service menu when the dedicated Service page is on
# screen. In a menu it selects the highlighted row. Long press on all other
# normal pages has no side effect.
common = replace_once(common, 'trackerServiceMenuLongAction();', 'trackerServiceMenuSelect();',
                      "long press selects original Tracker menu row")
common = replace_once(common, 'else\n                    trackerServiceMenuOpen();',
                      'else if (trackerServicePageVisible())\n                    trackerServiceMenuOpen();',
                      "long press opens settings only from Service page")
common = replace_once(common, 'trackerServiceMenuNext();', 'trackerServiceMenuShortPress();',
                      "short press advances original Tracker menu row")

# Reset the 20s display window immediately at the physical press edge, not only
# after release. A long press resets it again when the long gesture fires.
press_anchor = '''                buttonPressedSinceMs = now ? now : 1;\n                openedServiceThisPress = false;\n                buttonLongHandled = false;\n\n                if (!serviceActive) {\n'''
press_new = '''                buttonPressedSinceMs = now ? now : 1;\n                openedServiceThisPress = false;\n                buttonLongHandled = false;\n\n                if (serviceActive) {\n                    serviceLastActivityMs = now;\n                    displayStartedMs = now ? now : 1;\n                    displayWindowMs = lowBattery() ? TRACKER_COMMON_LOW_BATTERY_DISPLAY_MS : TRACKER_COMMON_DISPLAY_MS;\n                    displayVisible = true;\n                }\n\n                if (!serviceActive) {\n'''
common = replace_once(common, press_anchor, press_new, "reset display timer on every GPIO0 press")

# Pump deferred original menus after NotificationRenderer has reset the previous
# picker, and stream requested diagnostic exports in small chunks.
common = replace_once(
    common,
    '''        processBleActivity(now);\n        rememberCurrentPosition();\n''',
    '''        processBleActivity(now);\n        trackerServiceMenuPump();\n        trackerDiagPumpUsbExport();\n        rememberCurrentPosition();\n''',
    "pump Tracker menus and USB log export",
)

# Persistent event breadcrumbs for autonomous, no-serial testing.
common = replace_once(
    common,
    '''    trackerStatusSetMotionActive(true);\n    LOG_INFO("Tracker V1.1: movement confirmed''',
    '''    trackerStatusSetMotionActive(true);\n    trackerDiagLog("MOTION", "confirmed pulses=%u window=%ums", (unsigned)trackerMotionConfirmCount(),\n                   (unsigned)trackerMotionConfirmWindowMs());\n    LOG_INFO("Tracker V1.1: movement confirmed''',
    "log confirmed Tracker motion",
)

common = replace_once(
    common,
    '''        const uint32_t sleepMs = trackerEffectiveParkIntervalSecs() * 1000UL;\n        LOG_INFO("Tracker V1.1: %s; TAK_TRACKER entering deep sleep for %us", reason,\n''',
    '''        const uint32_t sleepMs = trackerEffectiveParkIntervalSecs() * 1000UL;\n        trackerDiagLog("PARK_SLEEP", "TAK_TRACKER reason=%s timer=%us", reason, (unsigned)(sleepMs / 1000UL));\n        LOG_INFO("Tracker V1.1: %s; TAK_TRACKER entering deep sleep for %us", reason,\n''',
    "log TAK_TRACKER timed deep sleep",
)

# Service/power script has already added GNSS parking to this log line.
common = replace_once(
    common,
    '''        useParkedGnssPolicy();\n        LOG_INFO("Tracker V1.1: %s; TAK returning to always-listening light sleep; GNSS parked at %us interval",\n''',
    '''        useParkedGnssPolicy();\n        trackerDiagLog("PARK_ENTER", "TAK reason=%s heartbeat=%us GNSS=sleep", reason,\n                       (unsigned)trackerEffectiveParkIntervalSecs());\n        LOG_INFO("Tracker V1.1: %s; TAK returning to always-listening light sleep; GNSS parked at %us interval",\n''',
    "log TAK parked entry",
)

common = replace_once(
    common,
    '''        LOG_INFO("Tracker V1.1: parked heartbeat due; waking GNSS for fresh fix");\n''',
    '''        trackerDiagLog("PARK_HEARTBEAT", "due; GNSS wake requested");\n        LOG_INFO("Tracker V1.1: parked heartbeat due; waking GNSS for fresh fix");\n''',
    "log parked GNSS heartbeat wake",
)
common = replace_once(
    common,
    '''        LOG_INFO("Tracker V1.1: TAK parked heartbeat sent with fresh GNSS fix after %us", (unsigned)heartbeatSecs);\n''',
    '''        trackerDiagLog("PARK_HEARTBEAT", "fresh fix TX after %us", (unsigned)heartbeatSecs);\n        LOG_INFO("Tracker V1.1: TAK parked heartbeat sent with fresh GNSS fix after %us", (unsigned)heartbeatSecs);\n''',
    "log parked fresh heartbeat TX",
)
common = replace_once(
    common,
    '''        LOG_WARN("Tracker V1.1: parked heartbeat GNSS wait expired; sent best stored position");\n''',
    '''        trackerDiagLog("PARK_HEARTBEAT", "GNSS timeout; best stored TX");\n        LOG_WARN("Tracker V1.1: parked heartbeat GNSS wait expired; sent best stored position");\n''',
    "log parked heartbeat fallback",
)

common = replace_once(
    common,
    '''            LOG_INFO("Tracker V1.1: 120s motion quiet; fresh final position sent");\n''',
    '''            trackerDiagLog("FINAL_POS", "120s quiet; fresh TX");\n            LOG_INFO("Tracker V1.1: 120s motion quiet; fresh final position sent");\n''',
    "log fresh final position",
)
common = replace_once(
    common,
    '''            LOG_INFO("Tracker V1.1: 120s motion quiet; waiting up to %us for fresh final GNSS fix",\n''',
    '''            trackerDiagLog("FINAL_POS", "120s quiet; waiting GNSS up to %us",\n                           (unsigned)(TRACKER_COMMON_FINAL_GPS_WAIT_MS / 1000UL));\n            LOG_INFO("Tracker V1.1: 120s motion quiet; waiting up to %us for fresh final GNSS fix",\n''',
    "log final GNSS wait",
)
common = replace_once(
    common,
    '''        LOG_WARN("Tracker V1.1: final GNSS wait expired; sending best available position");\n''',
    '''        trackerDiagLog("FINAL_POS", "GNSS timeout; best stored TX");\n        LOG_WARN("Tracker V1.1: final GNSS wait expired; sending best available position");\n''',
    "log final GNSS fallback",
)

common = replace_once(
    common,
    '''            LOG_INFO("Tracker V1.1: parked timer wake acquired fresh GNSS position");\n''',
    '''            trackerDiagLog("TIMER_WAKE", "TAK_TRACKER fresh GNSS TX");\n            LOG_INFO("Tracker V1.1: parked timer wake acquired fresh GNSS position");\n''',
    "log deep-sleep timer fresh fix",
)
common = replace_once(
    common,
    '''        LOG_WARN("Tracker V1.1: parked timer wake has no fresh GNSS fix; using best stored position");\n''',
    '''        trackerDiagLog("TIMER_WAKE", "TAK_TRACKER GNSS timeout; best stored TX");\n        LOG_WARN("Tracker V1.1: parked timer wake has no fresh GNSS fix; using best stored position");\n''',
    "log deep-sleep timer fallback",
)

common = replace_once(
    common,
    '''        LOG_DEBUG("Tracker service: active BLE burst detected; 120s idle timer reset");\n''',
    '''        trackerDiagLog("BT_ACTIVITY", "meaningful burst; idle timer reset");\n        LOG_DEBUG("Tracker service: active BLE burst detected; 120s idle timer reset");\n''',
    "log meaningful BLE activity",
)

common = replace_once(
    common,
    '''    trackerServiceSettingsInit();\n    setupTrackerEnhancements();\n''',
    '''    trackerServiceSettingsInit();\n    trackerDiagInit();\n    trackerDiagLog("BOOT", "role=%s wake=%s park=%umin effective=%us",\n                   config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER ? "TAK_TRACKER" : "TAK",\n                   trackerBootWakeReason(), (unsigned)trackerParkIntervalMinutes(),\n                   (unsigned)trackerEffectiveParkIntervalSecs());\n    setupTrackerEnhancements();\n''',
    "initialize persistent Tracker diagnostics",
)

# PositionModule is the single authoritative point after a packet has actually
# been handed to the mesh service. This catches Smart Position, final position,
# TAK parked heartbeat and TAK_TRACKER timer sends without logging every 5s fix.
position = replace_once(
    position,
    '#include "target_specific.h"\n',
    '#include "target_specific.h"\n#if defined(HELTEC_TRACKER_V1_1)\n#include "vehicle/TrackerDiagnosticLog.h"\n#endif\n',
    "PositionModule Tracker diagnostic include",
)
position = replace_once(
    position,
    '''    service->sendToMesh(p, RX_SRC_LOCAL, true);\n\n    if (IS_ONE_OF(config.device.role,''',
    '''    service->sendToMesh(p, RX_SRC_LOCAL, true);\n#if defined(HELTEC_TRACKER_V1_1)\n    if (config.device.role == meshtastic_Config_DeviceConfig_Role_TAK ||\n        config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER) {\n        uint32_t age = UINT32_MAX;\n        const uint32_t nowEpoch = getValidTime(RTCQualityDevice);\n        if (localPosition.time != 0 && nowEpoch != 0 && nowEpoch >= localPosition.time)\n            age = nowEpoch - localPosition.time;\n        trackerDiagLogPosition("POSITION_TX", localPosition.latitude_i, localPosition.longitude_i,\n                               age == UINT32_MAX ? 9999U : age, (uint8_t)localPosition.sats_in_view,\n                               age != UINT32_MAX && age <= 60U);\n    }\n#endif\n\n    if (IS_ONE_OF(config.device.role,''',
    "log actual Tracker mesh position transmissions",
)

# Verify final intent before writing.
checks = [
    (nimble, 'bleSuspended.exchange(true)'),
    (screen_h, 'uint8_t currentFrameIndex()'),
    (power, 'trackerOwnsInteractiveOutputs() && nativeSerialConnected'),
    (status, 'MeshModule("Service")'),
    (status, 'showOverlayBanner(banner)'),
    (status, '"20 min", "30 min", "60 min", "2 h", "4 h", "6 h", "9 h", "12 h"'),
    (status, 'trackerServicePageVisible()'),
    (status, 'INPUT_BROKER_USER_PRESS'),
    (status, 'INPUT_BROKER_SELECT'),
    (status, 'trackerDiagRequestUsbExport()'),
    (common, 'trackerDiagPumpUsbExport();'),
    (common, 'else if (trackerServicePageVisible())'),
    (common, 'PARK_HEARTBEAT'),
    (position, 'trackerDiagLogPosition("POSITION_TX"'),
]
for text, needle in checks:
    if needle not in text:
        raise SystemExit(f"Tracker original UI/diag verification failed: {needle}")

COMMON.write_text(common)
STATUS.write_text(status)
STATUS_H.write_text(status_h)
NIMBLE.write_text(nimble)
SCREEN_H.write_text(screen_h)
POWER.write_text(power)
POSITION.write_text(position)
