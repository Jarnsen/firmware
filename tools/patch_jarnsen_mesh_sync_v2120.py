"""V3 v2.1.20 integration: locked mesh policy, local Neighbor toggle and USB delta-log handshake."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"{label}: expected one anchor, got {text.count(old)}")
    return text.replace(old, new, 1)


def patch_repeater_policy() -> None:
    path = ROOT / "src/infrastructure/HeltecV3RepeaterPolicy.cpp"
    text = path.read_text(encoding="utf-8")
    if '#include "infrastructure/JarnsenV3MeshPolicy.h"' not in text:
        anchor = '#include "infrastructure/HeltecV3PowerMonitor.h"\n'
        text = replace_once(text, anchor, anchor + '#include "infrastructure/JarnsenV3MeshPolicy.h"\n', "policy include")
    pump_anchor = '''        heltecV3ServiceMenuPump();\n        heltecV3PowerMonitorTick(!v3ServiceActive, v3ServiceActive, v3BleConnected(),\n'''
    if "jarnsenV3MeshPolicyEnforce();" not in text:
        text = replace_once(text, pump_anchor, '''        heltecV3ServiceMenuPump();\n        jarnsenV3MeshPolicyEnforce();\n        heltecV3PowerMonitorTick(!v3ServiceActive, v3ServiceActive, v3BleConnected(),\n''', "policy enforce")
    setup_anchor = '''    heltecV3DiagInit();\n'''
    if "jarnsenV3MeshPolicyInit();" not in text:
        text = replace_once(text, setup_anchor, setup_anchor + "    jarnsenV3MeshPolicyInit();\n", "policy init")
    path.write_text(text, encoding="utf-8")


def patch_service_page() -> None:
    path = ROOT / "src/infrastructure/HeltecV3ServicePage.cpp"
    text = path.read_text(encoding="utf-8")
    if '#include "infrastructure/JarnsenV3MeshPolicy.h"' not in text:
        anchor = '#include "infrastructure/HeltecV3Runtime.h"\n'
        text = replace_once(text, anchor, anchor + '#include "infrastructure/JarnsenV3MeshPolicy.h"\n', "service include")
    old_enum = 'enum class V3ServiceMenu : uint8_t { NONE = 0, ROOT, POWER_STATS, DIAG_LOG, EXPORT_CONFIRM, CLEAR_CONFIRM, WLAN_SERVICE };'
    new_enum = 'enum class V3ServiceMenu : uint8_t { NONE = 0, ROOT, MESH_SETTINGS, POWER_STATS, DIAG_LOG, EXPORT_CONFIRM, CLEAR_CONFIRM, WLAN_SERVICE };'
    if "MESH_SETTINGS" not in text:
        text = replace_once(text, old_enum, new_enum, "service enum")
    old_root = '''        static const char *options[] = {"Back", "Power Statistics", "Diagnostic Log", "WLAN Service"};\n        showOptions("V3 Service", options, 4, [](int selected) {\n            switch (selected) {\n            case 0:\n                queueAction(V3MenuAction::CLOSE);\n                break;\n            case 1:\n                queueMenu(V3ServiceMenu::POWER_STATS);\n                break;\n            case 2:\n                queueMenu(V3ServiceMenu::DIAG_LOG);\n                break;\n            case 3:\n                queueMenu(V3ServiceMenu::WLAN_SERVICE);\n                break;\n            default:\n                break;\n            }\n        });\n        break;\n    }\n'''
    new_root = '''        static const char *options[] = {"Back", "Mesh Settings", "Power Statistics", "Diagnostic Log", "WLAN Service"};\n        showOptions("V3 Service", options, 5, [](int selected) {\n            switch (selected) {\n            case 0: queueAction(V3MenuAction::CLOSE); break;\n            case 1: queueMenu(V3ServiceMenu::MESH_SETTINGS); break;\n            case 2: queueMenu(V3ServiceMenu::POWER_STATS); break;\n            case 3: queueMenu(V3ServiceMenu::DIAG_LOG); break;\n            case 4: queueMenu(V3ServiceMenu::WLAN_SERVICE); break;\n            default: break;\n            }\n        });\n        break;\n    }\n    case V3ServiceMenu::MESH_SETTINGS: {\n        static char neighborLine[36];\n        static const char *options[] = {"Back", "Mesh Position TX: ON [LOCK]", neighborLine};\n        snprintf(neighborLine, sizeof(neighborLine), "Neighbor Info: %s", jarnsenV3NeighborInfoEnabled() ? "ON" : "OFF");\n        showOptions("Mesh Settings", options, 3, [](int selected) {\n            if (selected == 0) queueMenu(V3ServiceMenu::ROOT);\n            else if (selected == 1) queueMenu(V3ServiceMenu::MESH_SETTINGS);\n            else if (selected == 2) {\n                jarnsenV3SetNeighborInfoEnabled(!jarnsenV3NeighborInfoEnabled());\n                queueMenu(V3ServiceMenu::MESH_SETTINGS);\n            }\n        });\n        break;\n    }\n'''
    if "Mesh Position TX: ON [LOCK]" not in text:
        text = replace_once(text, old_root, new_root, "service root")
    path.write_text(text, encoding="utf-8")


def patch_diag_header() -> None:
    path = ROOT / "src/infrastructure/HeltecV3DiagnosticLog.h"
    text = path.read_text(encoding="utf-8")
    anchor = "void heltecV3DiagRequestUsbExport();\n"
    if "heltecV3DiagHandleToolSerialByte" not in text:
        text = replace_once(text, anchor, anchor + "void heltecV3DiagRequestUsbExportFrom(uint32_t generation, size_t cursor, bool forceFull);\nbool heltecV3DiagHandleToolSerialByte(uint8_t value);\n", "diag header")
    path.write_text(text, encoding="utf-8")


def patch_diag_cpp() -> None:
    path = ROOT / "src/infrastructure/HeltecV3DiagnosticLog.cpp"
    text = path.read_text(encoding="utf-8")
    vars_anchor = '''size_t exportPreviousRemaining = 0;\nsize_t exportCurrentRemaining = 0;\nuint8_t *usbTransferBuffer = nullptr;\n'''
    if "logGeneration" not in text:
        text = replace_once(text, vars_anchor, '''size_t exportPreviousRemaining = 0;\nsize_t exportCurrentRemaining = 0;\nsize_t exportPreviousOffset = 0;\nsize_t exportCurrentOffset = 0;\nuint32_t logGeneration = 1;\nuint32_t requestedGeneration = 0;\nsize_t requestedCursor = 0;\nbool requestedForceFull = true;\nsize_t exportCursorStart = 0;\nsize_t exportCursorEnd = 0;\nconst char *exportSyncMode = "full";\nchar toolCommand[96] = {};\nsize_t toolCommandLength = 0;\nuint8_t *usbTransferBuffer = nullptr;\n''', "diag vars")

    load_anchor = '''    stats.manualPositionSaveCount = prefs.getULong("posMan", 0);\n    prefs.end();\n'''
    if 'getULong("generation"' not in text:
        text = replace_once(text, load_anchor, '''    stats.manualPositionSaveCount = prefs.getULong("posMan", 0);\n    logGeneration = prefs.getULong("generation", 1);\n    if (logGeneration == 0) logGeneration = 1;\n    prefs.end();\n''', "generation load")
    save_anchor = '''    prefs.putULong("posMan", stats.manualPositionSaveCount);\n    prefs.end();\n'''
    if 'putULong("generation"' not in text:
        text = replace_once(text, save_anchor, '''    prefs.putULong("posMan", stats.manualPositionSaveCount);\n    prefs.putULong("generation", logGeneration);\n    prefs.end();\n''', "generation save")

    rotate_anchor = '''    if (FSCom.exists(CURRENT_LOG))\n        FSCom.rename(CURRENT_LOG, PREVIOUS_LOG);\n}\n'''
    if "generation advanced on rotation" not in text:
        text = replace_once(text, rotate_anchor, '''    if (FSCom.exists(CURRENT_LOG))\n        FSCom.rename(CURRENT_LOG, PREVIOUS_LOG);\n    ++logGeneration; if (logGeneration == 0) logGeneration = 1;\n    Preferences prefs; if (prefs.begin(PREF_NAMESPACE, false)) { prefs.putULong("generation", logGeneration); prefs.end(); }\n    // generation advanced on rotation: previous cursors require recovery.\n}\n''', "generation rotation")

    clear_anchor = '''    if (FSCom.exists(PREVIOUS_LOG))\n        FSCom.remove(PREVIOUS_LOG);\n    heltecV3DiagLog("LOGGER", "log cleared");\n'''
    if "log cleared generation" not in text:
        text = replace_once(text, clear_anchor, '''    if (FSCom.exists(PREVIOUS_LOG))\n        FSCom.remove(PREVIOUS_LOG);\n    ++logGeneration; if (logGeneration == 0) logGeneration = 1;\n    saveCounters();\n    heltecV3DiagLog("LOGGER", "log cleared generation=%u", (unsigned)logGeneration);\n''', "generation clear")

    open_anchor = '''bool openExportFile(const char *path)\n{\n    if (exportFile)\n        exportFile.close();\n    exportFile = FSCom.open(path, FILE_O_READ);\n    return (bool)exportFile;\n}\n'''
    if "openExportFileAt" not in text:
        text = replace_once(text, open_anchor, open_anchor + '''\nbool openExportFileAt(const char *path, size_t offset)\n{\n    if (!openExportFile(path)) return false;\n    return offset == 0 || exportFile.seek(offset);\n}\n''', "offset open")

    start = text.find("void heltecV3DiagRequestUsbExport()\n{")
    end = text.find("\nbool heltecV3DiagUsbExportPending()", start)
    if start < 0 or end < 0:
        raise SystemExit("request export range missing")
    request = r'''void heltecV3DiagRequestUsbExportFrom(uint32_t generation, size_t cursor, bool forceFull)
{
    if (bleUiState.load() == BleExportState::DOWNLOADING) {
        exportState = UsbExportState::ERROR;
        heltecV3DiagLog("LOG_EXPORT", "usb rejected: BLE export active");
        return;
    }
    if (!ensureUsbTransferBuffer()) {
        exportRequested = false; exportPhase = 0; exportState = UsbExportState::ERROR;
        heltecV3DiagLog("LOG_EXPORT", "usb rejected: transfer buffer allocation failed");
        return;
    }
    closeExportFile(); saveCounters();
    requestedGeneration = generation; requestedCursor = cursor; requestedForceFull = forceFull;
    exportRequested = true; exportPhase = 1; exportState = UsbExportState::WAIT_USB;
    serialConnectedSinceMs = 0; exportBytesSent = 0; usbBytesSinceFlush = 0;
    setRuntimeServiceHold(usbServiceHold, true);
    heltecV3DiagLog("LOG_EXPORT", "tool request gen=%u cursor=%u full=%u", (unsigned)generation, (unsigned)cursor, forceFull ? 1U : 0U);
}

void heltecV3DiagRequestUsbExport()
{
    heltecV3DiagRequestUsbExportFrom(0, 0, true);
}

bool heltecV3DiagHandleToolSerialByte(uint8_t value)
{
    if (toolCommandLength == 0 && value != 'J') return false;
    if (value == '\r') return true;
    if (value == '\n') {
        toolCommand[toolCommandLength] = '\0';
        unsigned generation = 0, cursor = 0;
        if (sscanf(toolCommand, "JARNSEN_TOOL_HELLO 1 %u %u", &generation, &cursor) == 2) {
            heltecV3DiagRequestUsbExportFrom(generation, cursor, false);
            heltecV3DiagLog("TOOL_LINK", "HELLO generation=%u cursor=%u", generation, cursor);
        } else if (strcmp(toolCommand, "JARNSEN_TOOL_FULL 1") == 0) {
            heltecV3DiagRequestUsbExportFrom(0, 0, true);
            heltecV3DiagLog("TOOL_LINK", "FULL requested");
        }
        toolCommandLength = 0; return true;
    }
    if (toolCommandLength + 1 >= sizeof(toolCommand)) { toolCommandLength = 0; return true; }
    toolCommand[toolCommandLength++] = (char)value;
    return true;
}
'''
    text = text[:start] + request + text[end:]

    phase1_old = '''        exportPreviousRemaining = fileSize(PREVIOUS_LOG);\n        exportCurrentRemaining = fileSize(CURRENT_LOG);\n        exportTotalBytes = exportPreviousRemaining + exportCurrentRemaining;\n        exportBytesSent = 0;\n'''
    phase1_new = '''        const size_t previousSize = fileSize(PREVIOUS_LOG);\n        const size_t currentSize = fileSize(CURRENT_LOG);\n        const size_t logicalEnd = previousSize + currentSize;\n        const bool sameGeneration = requestedGeneration != 0 && requestedGeneration == logGeneration;\n        const bool validCursor = sameGeneration && requestedCursor <= logicalEnd;\n        const bool delta = !requestedForceFull && validCursor;\n        const bool recovery = !requestedForceFull && requestedGeneration != 0 && !validCursor;\n        exportSyncMode = delta ? "delta" : (recovery ? "recovery" : "full");\n        exportCursorStart = delta ? requestedCursor : 0;\n        exportCursorEnd = logicalEnd;\n        exportPreviousOffset = delta ? std::min(requestedCursor, previousSize) : 0;\n        exportCurrentOffset = delta && requestedCursor > previousSize ? requestedCursor - previousSize : 0;\n        exportPreviousRemaining = previousSize - exportPreviousOffset;\n        exportCurrentRemaining = currentSize - exportCurrentOffset;\n        exportTotalBytes = exportPreviousRemaining + exportCurrentRemaining;\n        exportBytesSent = 0;\n'''
    text = replace_once(text, phase1_old, phase1_new, "phase1 cursor")

    # patch_jarnsen_diag_live_snapshot.py runs before this patch and has already
    # expanded the heap-backed USB header with LIVE BATTERY fields. Add delta
    # metadata inside only that USB snprintf block so the battery snapshot and
    # its complete argument list remain intact.
    header_start = text.find('        const int headerLength = snprintf((char *)usbTransferBuffer, USB_FILE_BUFFER_BYTES,')
    header_end = text.find('        if (headerLength <= 0', header_start)
    if header_start < 0 or header_end < 0:
        raise SystemExit("USB header block not found")
    header_block = text[header_start:header_end]
    fmt_old = '                                          "# log_format=%u\\r\\n# export=%s\\r\\n"\n'
    fmt_new = ('                                          "# log_format=%u\\r\\n# export=%s\\r\\n# transport=USB\\r\\n"\n'
               '                                          "# sync_mode=%s\\r\\n# log_generation=%u\\r\\n# cursor_start=%u\\r\\n# cursor_end=%u\\r\\n"\n')
    header_block = replace_once(header_block, fmt_old, fmt_new, "USB header format")
    args_old = '                                          exportTime, heltecV3PowerMonitorSourceText(),'
    args_new = ('                                          exportTime, exportSyncMode, (unsigned)logGeneration, '
                '(unsigned)exportCursorStart,\n'
                '                                          (unsigned)exportCursorEnd, heltecV3PowerMonitorSourceText(),')
    header_block = replace_once(header_block, args_old, args_new, "USB header args")
    text = text[:header_start] + header_block + text[header_end:]

    text = text.replace("if (!openExportFile(PREVIOUS_LOG))", "if (!openExportFileAt(PREVIOUS_LOG, exportPreviousOffset))", 1)
    text = text.replace("if (!exportFile && !openExportFile(CURRENT_LOG))", "if (!exportFile && !openExportFileAt(CURRENT_LOG, exportCurrentOffset))", 1)
    text = text.replace("        heltecV3MeshMonitorPrintSnapshot(Serial);\n", "", 1)

    stub_anchor = "void heltecV3DiagRequestUsbExport() {}\n"
    if "void heltecV3DiagRequestUsbExportFrom(uint32_t, size_t, bool)" not in text:
        text = replace_once(text, stub_anchor, stub_anchor + "void heltecV3DiagRequestUsbExportFrom(uint32_t, size_t, bool) {}\nbool heltecV3DiagHandleToolSerialByte(uint8_t) { return false; }\n", "stubs")
    path.write_text(text, encoding="utf-8")


def patch_stream_api() -> None:
    path = ROOT / "src/mesh/StreamAPI.cpp"
    text = path.read_text(encoding="utf-8")
    if '#include "infrastructure/HeltecV3DiagnosticLog.h"' not in text:
        text = replace_once(text, '#include "gps/RTC.h"\n', '#include "gps/RTC.h"\n#if defined(_VARIANT_HELTEC_V3)\n#include "infrastructure/HeltecV3DiagnosticLog.h"\n#endif\n', "stream include")
    anchor = '''        uint8_t c = (uint8_t)cInt;\n\n        // Use the read pointer for a little state machine'''
    replacement = '''        uint8_t c = (uint8_t)cInt;\n#if defined(_VARIANT_HELTEC_V3)\n        if (heltecV3DiagHandleToolSerialByte(c))\n            continue;\n#endif\n\n        // Use the read pointer for a little state machine'''
    count = text.count(anchor)
    if count not in (0, 2):
        raise SystemExit(f"stream byte hook anchors={count}")
    if count == 2:
        text = text.replace(anchor, replacement)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    patch_repeater_policy()
    patch_service_page()
    patch_diag_header()
    patch_diag_cpp()
    patch_stream_api()
    print("V3 v2.1.20 mesh policy + delta log sync applied")


if __name__ == "__main__":
    main()
