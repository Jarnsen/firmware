"""Tracker v2.1.20 integration: locked mesh policy, local Neighbor toggle and USB delta-log handshake."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"{label}: expected one anchor, got {text.count(old)}")
    return text.replace(old, new, 1)


def patch_common_policy() -> None:
    path = ROOT / "src/vehicle/TrackerCommonPolicy.cpp"
    text = path.read_text(encoding="utf-8")
    if '#include "vehicle/JarnsenMeshPolicy.h"' not in text:
        text = replace_once(text, '#include "vehicle/TrackerDiagnosticLog.h"\n', '#include "vehicle/TrackerDiagnosticLog.h"\n#include "vehicle/JarnsenMeshPolicy.h"\n', "common include")
    anchor = '''        if (!trackerRoleEnabled())\n            return 30000;\n\n        const uint32_t now = millis();\n'''
    if "jarnsenMeshPolicyEnforce();" not in text:
        text = replace_once(text, anchor, '''        if (!trackerRoleEnabled())\n            return 30000;\n\n        jarnsenMeshPolicyEnforce();\n        const uint32_t now = millis();\n''', "common enforce")
    setup_anchor = '''    trackerApplyPositionSettings();\n'''
    if "jarnsenMeshPolicyInit();" not in text:
        pos = text.rfind(setup_anchor)
        if pos < 0:
            raise SystemExit("common init anchor missing")
        end = pos + len(setup_anchor)
        text = text[:end] + "    jarnsenMeshPolicyInit();\n" + text[end:]
    sleep_anchor = '''        trackerDiagLog("PARK_SLEEP", "TAK_TRACKER reason=%s timer=%us", reason, (unsigned)(sleepMs / 1000UL));\n        LOG_INFO("Tracker V1.1: %s; TAK_TRACKER entering deep sleep for %us", reason, (unsigned)(sleepMs / 1000UL));\n        trackerRealDeepSleep(sleepMs, false, false);\n'''
    if "PARK_SLEEP_PREP" not in text:
        text = replace_once(text, sleep_anchor, '''        trackerDiagLog("PARK_SLEEP_PREP", "reason=%s timer=%us heap=%u motionPin=%u servicePin=%u", reason,\n                       (unsigned)(sleepMs / 1000UL), (unsigned)ESP.getFreeHeap(),\n                       (unsigned)digitalRead(VEHICLE_MOTION_WAKE_PIN), (unsigned)digitalRead(serviceButtonPin()));\n        trackerDiagLog("PARK_SLEEP", "TAK_TRACKER reason=%s timer=%us", reason, (unsigned)(sleepMs / 1000UL));\n        LOG_INFO("Tracker V1.1: %s; TAK_TRACKER entering deep sleep for %us", reason, (unsigned)(sleepMs / 1000UL));\n        trackerRealDeepSleep(sleepMs, false, false);\n''', "deep sleep diagnostics")
    path.write_text(text, encoding="utf-8")


def patch_service_menu() -> None:
    path = ROOT / "src/vehicle/TrackerStatusModule.cpp"
    text = path.read_text(encoding="utf-8")
    if '#include "vehicle/JarnsenMeshPolicy.h"' not in text:
        text = replace_once(text, '#include "vehicle/TrackerEnhancements.h"\n', '#include "vehicle/TrackerEnhancements.h"\n#include "vehicle/JarnsenMeshPolicy.h"\n', "menu include")
    old = '''    case TrackerMenu::POSITION: {\n        static const char *opts[] = {"Back", "Smart Distance", "Min TX Interval", "Moving GNSS"};\n        showTrackerOptions("Position", opts, 4, initialSelection, [](int selected) {\n            trackerPositionSelection = selected;\n            if (selected == 0)\n                queueTrackerMenu(TrackerMenu::ROOT, trackerRootSelection);\n            else if (selected == 1)\n                queueTrackerMenu(TrackerMenu::DISTANCE, 0);\n            else if (selected == 2)\n                queueTrackerMenu(TrackerMenu::INTERVAL, 0);\n            else if (selected == 3)\n                queueTrackerMenu(TrackerMenu::MOVING_GNSS, 0);\n        });\n        break;\n    }\n'''
    new = '''    case TrackerMenu::POSITION: {\n        static char neighborLine[32];\n        static const char *opts[] = {"Back", "Mesh Position TX: ON [LOCK]", neighborLine, "Smart Distance", "Min TX Interval", "Moving GNSS"};\n        snprintf(neighborLine, sizeof(neighborLine), "Neighbor Info: %s", jarnsenNeighborInfoEnabled() ? "ON" : "OFF");\n        showTrackerOptions("Position / Mesh", opts, 6, initialSelection, [](int selected) {\n            trackerPositionSelection = selected;\n            if (selected == 0)\n                queueTrackerMenu(TrackerMenu::ROOT, trackerRootSelection);\n            else if (selected == 1)\n                queueTrackerMenu(TrackerMenu::POSITION, 1);\n            else if (selected == 2) {\n                jarnsenSetNeighborInfoEnabled(!jarnsenNeighborInfoEnabled());\n                queueTrackerMenu(TrackerMenu::POSITION, 2);\n            } else if (selected == 3)\n                queueTrackerMenu(TrackerMenu::DISTANCE, 0);\n            else if (selected == 4)\n                queueTrackerMenu(TrackerMenu::INTERVAL, 0);\n            else if (selected == 5)\n                queueTrackerMenu(TrackerMenu::MOVING_GNSS, 0);\n        });\n        break;\n    }\n'''
    if "Mesh Position TX: ON [LOCK]" not in text:
        text = replace_once(text, old, new, "position menu")
    path.write_text(text, encoding="utf-8")


def patch_diag_header() -> None:
    path = ROOT / "src/vehicle/TrackerDiagnosticLog.h"
    text = path.read_text(encoding="utf-8")
    anchor = "void trackerDiagRequestUsbExport();\n"
    if "trackerDiagHandleToolSerialByte" not in text:
        text = replace_once(text, anchor, anchor + "void trackerDiagRequestUsbExportFrom(uint32_t generation, size_t cursor, bool forceFull);\nbool trackerDiagHandleToolSerialByte(uint8_t value);\n", "diag header")
    path.write_text(text, encoding="utf-8")


def patch_diag_cpp() -> None:
    path = ROOT / "src/vehicle/TrackerDiagnosticLog.cpp"
    text = path.read_text(encoding="utf-8")
    # Persistent generation increments whenever old cursor space can no longer be trusted.
    vars_anchor = '''size_t exportPreviousRemaining = 0;\nsize_t exportCurrentRemaining = 0;\nsize_t exportTotalBytes = 0;\nsize_t exportBytesSent = 0;\n'''
    if "logGeneration" not in text:
        text = replace_once(text, vars_anchor, '''size_t exportPreviousRemaining = 0;\nsize_t exportCurrentRemaining = 0;\nsize_t exportPreviousOffset = 0;\nsize_t exportCurrentOffset = 0;\nsize_t exportTotalBytes = 0;\nsize_t exportBytesSent = 0;\nuint32_t logGeneration = 1;\nsize_t exportCursorStart = 0;\nsize_t exportCursorEnd = 0;\nconst char *exportSyncMode = "full";\nchar toolCommand[96] = {};\nsize_t toolCommandLength = 0;\n''', "diag vars")

    init_anchor = '''        loggingEnabled = prefs.getBool("enabled", true);\n        prefs.end();\n'''
    if 'getULong("generation"' not in text:
        text = replace_once(text, init_anchor, '''        loggingEnabled = prefs.getBool("enabled", true);\n        logGeneration = prefs.getULong("generation", 1);\n        if (logGeneration == 0) logGeneration = 1;\n        prefs.end();\n''', "generation load")

    rotate_anchor = '''    if (FSCom.exists(CURRENT_LOG))\n        FSCom.rename(CURRENT_LOG, PREVIOUS_LOG);\n}\n'''
    if "generation advanced on rotation" not in text:
        text = replace_once(text, rotate_anchor, '''    if (FSCom.exists(CURRENT_LOG))\n        FSCom.rename(CURRENT_LOG, PREVIOUS_LOG);\n    ++logGeneration;\n    if (logGeneration == 0) logGeneration = 1;\n    Preferences prefs;\n    if (prefs.begin(PREF_NAMESPACE, false)) { prefs.putULong("generation", logGeneration); prefs.end(); }\n    // generation advanced on rotation: every earlier byte cursor is intentionally invalid.\n}\n''', "generation rotation")

    clear_anchor = '''    if (FSCom.exists(PREVIOUS_LOG))\n        FSCom.remove(PREVIOUS_LOG);\n    if (loggingEnabled)\n        trackerDiagLog("LOGGER", "log cleared");\n'''
    if "logGeneration++;" not in text:
        text = replace_once(text, clear_anchor, '''    if (FSCom.exists(PREVIOUS_LOG))\n        FSCom.remove(PREVIOUS_LOG);\n    logGeneration++; if (logGeneration == 0) logGeneration = 1;\n    Preferences prefs; if (prefs.begin(PREF_NAMESPACE, false)) { prefs.putULong("generation", logGeneration); prefs.end(); }\n    if (loggingEnabled)\n        trackerDiagLog("LOGGER", "log cleared generation=%u", (unsigned)logGeneration);\n''', "generation clear")

    open_anchor = '''bool openExportFile(const char *path)\n{\n    if (exportFile)\n        exportFile.close();\n    exportFile = FSCom.open(path, FILE_O_READ);\n    return (bool)exportFile;\n}\n'''
    if "openExportFileAt" not in text:
        text = replace_once(text, open_anchor, open_anchor + '''\nbool openExportFileAt(const char *path, size_t offset)\n{\n    if (!openExportFile(path)) return false;\n    return offset == 0 || exportFile.seek(offset);\n}\n''', "offset open")

    start = text.find("void trackerDiagRequestUsbExport()\n{")
    end = text.find("\nbool trackerDiagUsbExportPending()", start)
    if start < 0 or end < 0:
        raise SystemExit("request export method range missing")
    replacement = r'''void trackerDiagRequestUsbExportFrom(uint32_t generation, size_t cursor, bool forceFull)
{
    if (exportRequested || usbExportSessionActive())
        return;
    clearUsbTransferRuntime();
    exportRequested = true;
    exportState = UsbExportState::PREPARE;
    exportBytesSent = 0;
    usbHeaderLength = 0;
    usbFooterLength = 0;

    const size_t previousSize = fileSize(PREVIOUS_LOG);
    const size_t currentSize = fileSize(CURRENT_LOG);
    const size_t logicalEnd = previousSize + currentSize;
    const bool sameGeneration = generation != 0 && generation == logGeneration;
    const bool validCursor = sameGeneration && cursor <= logicalEnd;
    const bool delta = !forceFull && validCursor;
    const bool recovery = !forceFull && generation != 0 && !validCursor;
    exportSyncMode = delta ? "delta" : (recovery ? "recovery" : "full");
    exportCursorStart = delta ? cursor : 0;
    exportCursorEnd = logicalEnd;

    exportPreviousOffset = delta ? std::min(cursor, previousSize) : 0;
    exportCurrentOffset = delta && cursor > previousSize ? cursor - previousSize : 0;
    exportPreviousRemaining = previousSize - exportPreviousOffset;
    exportCurrentRemaining = currentSize - exportCurrentOffset;
    exportTotalBytes = exportPreviousRemaining + exportCurrentRemaining;

    trackerDiagLog("LOG_EXPORT", "requested usb=%u mode=%s gen=%u cursor=%u->%u bytes=%u", (bool)Serial ? 1U : 0U,
                   exportSyncMode, (unsigned)logGeneration, (unsigned)exportCursorStart, (unsigned)exportCursorEnd,
                   (unsigned)exportTotalBytes);

    char exportTime[32] = {};
    makeTimestamp(exportTime, sizeof(exportTime));
    const uint32_t nodeNum = nodeDB ? nodeDB->getNodeNum() : 0;
    const char *longName = owner.long_name[0] ? owner.long_name : "--";
    const char *shortName = owner.short_name[0] ? owner.short_name : "--";
    char usbLiveBattery[768] = {};
    formatTrackerLiveBattery(usbLiveBattery, sizeof(usbLiveBattery));
    usbHeaderLength = (size_t)snprintf(usbHeader, sizeof(usbHeader),
                                       "\r\n===JARNSEN_DIAG_LOG_BEGIN===\r\n"
                                       "# device=HELTEC_TRACKER_V1.1\r\n# firmware=%s\r\n# build=%s\r\n"
                                       "# node_id=!%08x\r\n# long_name=%s\r\n# short_name=%s\r\n"
                                       "# build_time=%s %s\r\n# role=%s\r\n# feature=%s\r\n"
                                       "# log_format=%u\r\n# export=%s\r\n# transport=USB\r\n"
                                       "# sync_mode=%s\r\n# log_generation=%u\r\n# cursor_start=%u\r\n# cursor_end=%u\r\n%s# bytes=%u\r\n",
                                       xstr(APP_VERSION), JARNSEN_BUILD_SHA, (unsigned)nodeNum, longName, shortName, __DATE__, __TIME__,
                                       trackerDiagRoleText(), JARNSEN_DIAG_FEATURE_VERSION, (unsigned)JARNSEN_DIAG_LOG_FORMAT, exportTime,
                                       exportSyncMode, (unsigned)logGeneration, (unsigned)exportCursorStart, (unsigned)exportCursorEnd,
                                       usbLiveBattery, (unsigned)exportTotalBytes);
    usbFooterLength = (size_t)snprintf(usbFooter, sizeof(usbFooter),
                                       "\r\n# payload_sent=%u\r\n===JARNSEN_DIAG_LOG_END===\r\n",
                                       (unsigned)exportTotalBytes);
    if (usbHeaderLength >= sizeof(usbHeader) || usbFooterLength >= sizeof(usbFooter)) {
        failUsbExport("metadata overflow");
        return;
    }
}

void trackerDiagRequestUsbExport()
{
    trackerDiagRequestUsbExportFrom(0, 0, true);
}

bool trackerDiagHandleToolSerialByte(uint8_t value)
{
    if (toolCommandLength == 0 && value != 'J')
        return false;
    if (value == '\r')
        return true;
    if (value == '\n') {
        toolCommand[toolCommandLength] = '\0';
        unsigned generation = 0, cursor = 0;
        if (sscanf(toolCommand, "JARNSEN_TOOL_HELLO 1 %u %u", &generation, &cursor) == 2) {
            trackerDiagRequestUsbExportFrom(generation, cursor, false);
            trackerDiagLog("TOOL_LINK", "HELLO generation=%u cursor=%u", generation, cursor);
        } else if (strcmp(toolCommand, "JARNSEN_TOOL_FULL 1") == 0) {
            trackerDiagRequestUsbExportFrom(0, 0, true);
            trackerDiagLog("TOOL_LINK", "FULL requested");
        }
        toolCommandLength = 0;
        return true;
    }
    if (toolCommandLength + 1 >= sizeof(toolCommand)) {
        toolCommandLength = 0;
        return true;
    }
    toolCommand[toolCommandLength++] = (char)value;
    return true;
}
'''
    text = text[:start] + replacement + text[end:]

    text = text.replace("if (!exportFile && !openExportFile(PREVIOUS_LOG))", "if (!exportFile && !openExportFileAt(PREVIOUS_LOG, exportPreviousOffset))")
    text = text.replace("if (!exportFile && !openExportFile(CURRENT_LOG))", "if (!exportFile && !openExportFileAt(CURRENT_LOG, exportCurrentOffset))")
    path.write_text(text, encoding="utf-8")


def patch_stream_api() -> None:
    path = ROOT / "src/mesh/StreamAPI.cpp"
    text = path.read_text(encoding="utf-8")
    if '#include "vehicle/TrackerDiagnosticLog.h"' not in text:
        text = replace_once(text, '#include "gps/RTC.h"\n', '#include "gps/RTC.h"\n#if defined(HELTEC_TRACKER_V1_1)\n#include "vehicle/TrackerDiagnosticLog.h"\n#endif\n', "stream include")
    anchor = '''        uint8_t c = (uint8_t)cInt;\n\n        // Use the read pointer for a little state machine'''
    replacement = '''        uint8_t c = (uint8_t)cInt;\n#if defined(HELTEC_TRACKER_V1_1)\n        if (trackerDiagHandleToolSerialByte(c))\n            continue;\n#endif\n\n        // Use the read pointer for a little state machine'''
    count = text.count(anchor)
    if count not in (0, 2):
        raise SystemExit(f"stream byte hook anchors={count}")
    if count == 2:
        text = text.replace(anchor, replacement)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    patch_common_policy()
    patch_service_menu()
    patch_diag_header()
    patch_diag_cpp()
    patch_stream_api()
    print("Tracker v2.1.20 mesh policy + delta log sync applied")


if __name__ == "__main__":
    main()
