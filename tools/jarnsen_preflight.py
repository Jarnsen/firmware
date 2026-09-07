#!/usr/bin/env python3
"""Static contract checks for JARNSEN-MESH Unified Core invariants."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


class PreflightFailure(RuntimeError):
    pass


def read(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        raise PreflightFailure(f"required file missing: {rel}")
    return path.read_text(encoding="utf-8")


def require(text: str, needle: str, message: str) -> None:
    if needle not in text:
        raise PreflightFailure(message)


def forbid(text: str, needle: str, message: str) -> None:
    if needle in text:
        raise PreflightFailure(message)


def between(text: str, start: str, end: str, label: str) -> str:
    start_pos = text.find(start)
    if start_pos < 0:
        raise PreflightFailure(f"cannot find start of {label}: {start}")
    end_pos = text.find(end, start_pos + len(start))
    if end_pos < 0:
        raise PreflightFailure(f"cannot find end of {label}: {end}")
    return text[start_pos:end_pos]


def main() -> int:
    common = read("src/vehicle/TrackerCommonPolicy.cpp")
    enhancements = read("src/vehicle/TrackerEnhancements.cpp")
    status = read("src/vehicle/TrackerStatusModule.cpp")
    display_model = read("src/jarnsen/core/display/JarnsenDisplayModel.h")
    display_runtime = read("src/jarnsen/adapters/JarnsenDisplayRuntime.cpp")
    radio_profiles = read("src/jarnsen/core/mesh/JarnsenRadioProfiles.cpp")
    serial_console = read("src/SerialConsole.cpp")
    diag_header = read("src/jarnsen/core/service/JarnsenDiagnosticLog.h")
    diag_impl = read("src/jarnsen/core/service/JarnsenDiagnosticLog.cpp")

    for rel, text in (
        ("TrackerCommonPolicy.cpp", common),
        ("TrackerEnhancements.cpp", enhancements),
        ("TrackerStatusModule.cpp", status),
    ):
        forbid(text, "config.device.role", f"{rel}: direct config.device.role read reintroduced; use normalized Core role")

    require(common, "config.display.screen_on_secs", "TrackerCommonPolicy.cpp: display timeout no longer reads config.display.screen_on_secs")
    require(common, "seconds == 0 ? TRACKER_COMMON_DEFAULT_DISPLAY_SECS : seconds", "TrackerCommonPolicy.cpp: screen_on_secs default semantics changed unexpectedly")
    require(common, "resetDisplayWindow(releaseNow);", "TrackerCommonPolicy.cpp: display timer is no longer reset from button release")
    forbid(common, "TRACKER_COMMON_DISPLAY_MS", "TrackerCommonPolicy.cpp: fixed TRACKER_COMMON_DISPLAY_MS timeout reintroduced")
    forbid(common, "TRACKER_COMMON_LOW_BATTERY_DISPLAY_MS", "TrackerCommonPolicy.cpp: low-battery display timeout override reintroduced")

    expected_transitions = (
        "case DisplayPage::MGRS:\n        return DisplayPage::NODE_STATUS;",
        "case DisplayPage::NODE_STATUS:\n        return DisplayPage::RADIO;",
        "case DisplayPage::RADIO:\n        return DisplayPage::NETWORK;",
        "case DisplayPage::NETWORK:\n        return DisplayPage::SYSTEM;",
    )
    for transition in expected_transitions:
        require(display_model, transition, f"JarnsenDisplayModel.h: missing page transition: {transition!r}")
    require(display_model, "constexpr uint8_t displayPageCount()\n{\n    return 5U;\n}", "JarnsenDisplayModel.h: operator display page count is no longer 5")

    node_page = between(status, "void drawOwnNodePage(", "void drawServicePage(", "drawOwnNodePage")
    require(node_page, 'display->drawString(x + 2, y + 1, "2/5");', "Tracker page 2: missing 2/5 label at top-left")
    require(node_page, "drawBattery(display, x, y);", "Tracker page 2: missing shared battery indicator")
    require(node_page, "display->getStringWidth(name)", "Tracker page 2: long name is not fitted by rendered pixel width")
    require(node_page, "const int w = display->getWidth();", "Tracker page 2: runtime display width is not used")
    require(node_page, "const int h = display->getHeight();", "Tracker page 2: runtime display height is not used")

    forbid(status, '"Display: 160x80"', "TrackerStatusModule.cpp: hard-coded display geometry reintroduced")
    require(status, 'std::snprintf(buffer, size, "Display: %dx%d", screen ? screen->getWidth() : 0, screen ? screen->getHeight() : 0);', "Tracker SYSTEM INFO: runtime display geometry readout missing")

    require(status, 'static const char *items[] = {"Standard", "Jarnsen 1", "Jarnsen 2", "ZURUECK"};', "Tracker PROFILE menu changed; Standard/Jarnsen 1/Jarnsen 2 must remain radio profiles")
    select_menu = between(status, "void selectMenuItem()", "void selectNextNavigationNode()", "selectMenuItem")
    select_profile = between(select_menu, "    case MenuView::PROFILE:\n", "    case MenuView::TRACKER:\n", "PROFILE selection block")
    forbid(select_profile, "Role", "Tracker PROFILE selection block must not expose role changes")
    forbid(select_profile, "role", "Tracker PROFILE selection block must not expose role changes")
    require(select_profile, "jarnsen::radioProfileSlotExists(profile)", "Tracker PROFILE: slot existence is not checked")
    require(select_profile, "jarnsen::radioProfileSelect(profile, true)", "Tracker PROFILE: shared radioProfileSelect backend is not used")
    require(select_profile, '"PROFIL NICHT GESPEICHERT"', "Tracker PROFILE: missing-slot error text is absent")
    require(status, "jarnsen::radioProfileActive()", "Tracker PROFILE: active profile is not displayed")
    require(status, "jarnsen::radioProfileLabel", "Tracker PROFILE: active profile label is not displayed")

    require(display_runtime, "defined(TBEAM_V10)", "Unified display runtime: classic T-Beam is not enabled")
    require(display_runtime, "jarnsen::radioProfileSlotExists(profile)", "Unified PROFILE: slot existence is not checked")
    require(display_runtime, "jarnsen::radioProfileSelect(profile, true)", "Unified PROFILE: shared radioProfileSelect backend is not used")
    require(display_runtime, '"PROFIL NICHT GESPEICHERT"', "Unified PROFILE: missing-slot error text is absent")
    require(display_runtime, "jarnsen::radioProfileActive()", "Unified PROFILE: active profile is not displayed")

    require(radio_profiles, "staged.region = meshtastic_Config_LoRaConfig_RegionCode_US;", "JarnsenRadioProfiles: J1/J2 are no longer forced to US region")
    require(radio_profiles, "currentMatchesSlot", "JarnsenRadioProfiles: active marker is no longer validated against config.lora")
    require(radio_profiles, "const meshtastic_Config_LoRaConfig previousLora = config.lora;", "JarnsenRadioProfiles: LoRa rollback snapshot missing")
    require(radio_profiles, "const bool rollbackSaved = nodeDB->saveToDisk(SEGMENT_CONFIG);", "JarnsenRadioProfiles: failed marker write no longer rolls config back")

    require(serial_console, "const bool ok = valid && jarnsen::radioProfileSelect(profile, true);", "SerialConsole: USB RADIO_SELECT no longer uses radioProfileSelect")

    # All boards expose one JARNSEN service contract. Tracker keeps its richer
    # logger internally, while every other board uses the shared persistent log.
    require(diag_header, "diagnosticLogRequestUsbExport", "Shared diagnostic log header is missing USB export")
    require(diag_impl, "#if defined(HELTEC_TRACKER_V1_1)", "Tracker diagnostic adapter is missing")
    require(diag_impl, 'constexpr const char *CURRENT_LOG = "/jarnsen_diag.log";', "Generic persistent diagnostic log is missing")
    require(diag_impl, "===JARNSEN_DIAG_LOG_BEGIN===", "Generic diagnostic BEGIN marker is missing")
    require(diag_impl, "===JARNSEN_DIAG_LOG_END===", "Generic diagnostic END marker is missing")
    require(serial_console, 'const bool full = strncmp(command, "JARNSEN_TOOL_FULL ', "JARNSEN_TOOL_FULL is not available in the common SerialConsole")
    require(serial_console, "jarnsen::diagnosticLogRequestUsbExport(Port);", "SerialConsole does not route log export through the common backend")
    require(serial_console, "jarnsen::diagnosticLogPumpUsbExport();", "SerialConsole does not pump the common log export")
    require(serial_console, "radio_profiles=3 diag_log=1 service_version=2", "JARNSEN service capabilities are not advertised")

    print("JARNSEN preflight contracts: PASS")
    print("- normalized Tracker role ownership")
    print("- configured display timeout and 5-page operator cycle")
    print("- local/USB radio profiles share one persistent backend with rollback")
    print("- common service advertises 3 radio slots and diagnostic log export")
    print("- Tracker and generic boards share one USB log protocol")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PreflightFailure as exc:
        print(f"JARNSEN preflight contracts: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
