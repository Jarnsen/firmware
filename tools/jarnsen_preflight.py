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
    runtime_policy = read("src/jarnsen/core/runtime/JarnsenRuntimePolicy.cpp")
    runtime_header = read("src/jarnsen/core/runtime/JarnsenRuntimePolicy.h")
    modules = read("src/modules/Modules.cpp")
    button_thread = read("src/input/ButtonThread.cpp")
    sleep_impl = read("src/sleep.cpp")
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

    # One board-wide 20 s interaction deadline. Generic PowerFSM and the
    # Tracker service both consume config.display.screen_on_secs, while every
    # physical button action resets the deadline through the existing paths.
    require(runtime_header, "JARNSEN_DISPLAY_ON_MS = 20000U", "JARNSEN runtime: 20-second display deadline changed")
    require(runtime_policy, "config.display.screen_on_secs = JARNSEN_DISPLAY_ON_MS / 1000U;", "JARNSEN runtime: 20-second display policy is not applied before PowerFSM setup")
    require(modules, "jarnsen::runtimePolicyInit();", "Modules.cpp: common JARNSEN runtime policy is not initialized")
    require(common, "config.display.screen_on_secs", "TrackerCommonPolicy.cpp: display timeout no longer consumes shared screen_on_secs")
    require(common, "resetDisplayWindow(releaseNow);", "TrackerCommonPolicy.cpp: display timer is no longer reset from button release")
    require(button_thread, "JARNSEN_BUTTON_DEBOUNCE_MS = 20U", "ButtonThread.cpp: reliable JARNSEN hardware debounce is missing")
    require(button_thread, "powerFSM.trigger(EVENT_INPUT);", "ButtonThread.cpp: long-press release no longer restarts the display deadline")

    # Light sleep and deep sleep must both have a physical Userbutton wake path.
    require(sleep_impl, "gpio_wakeup_enable(pin, GPIO_INTR_LOW_LEVEL);", "sleep.cpp: ESP32 Userbutton light-sleep wake is missing")
    require(sleep_impl, "esp_sleep_enable_gpio_wakeup();", "sleep.cpp: ESP32 GPIO wake source is not enabled")
    require(runtime_policy, "deepSleepButtonObserver.observe(&preflightSleep);", "JARNSEN runtime: deep-sleep button wake is not armed from preflight")
    require(runtime_policy, "esp_sleep_enable_ext1_wakeup", "JARNSEN runtime: ESP32 deep-sleep EXT1 Userbutton wake is missing")
    require(runtime_policy, "normalizeDeepSleepUserButtonWake();", "JARNSEN runtime: post-deep-sleep RTC GPIO normalization is missing")
    require(button_thread, "esp_sleep_get_ext1_wakeup_status()", "ButtonThread.cpp: deep-sleep wake press is not identified")
    require(button_thread, "suppressJarnsenBootWakeEvent", "ButtonThread.cpp: first deep-sleep wake hold is not consumed as wake-only")
    require(common, "void armDeepSleepButtonWake()", "TrackerCommonPolicy.cpp: Tracker deep-sleep Userbutton wake helper is missing")
    require(common, "bool bootWasUserWake()", "TrackerCommonPolicy.cpp: Tracker deep-sleep wake boot handling is missing")

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

    # Generic compact displays, notably Heltec V3 128x64, fit every dynamic line
    # by actual rendered width and keep the page marker out of the bottom band.
    require(display_runtime, "defined(TBEAM_V10)", "Unified display runtime: classic T-Beam is not enabled")
    require(display_runtime, "void drawFittedCentered", "Unified display runtime: pixel-width fitting helper is missing")
    require(display_runtime, "display->getStringWidth(fitted)", "Unified display runtime: text fitting does not use rendered pixel width")
    require(display_runtime, "display->setTextAlignment(TEXT_ALIGN_LEFT);", "Unified display runtime: top-left page marker is missing")
    forbid(display_runtime, "display->getHeight() - 12", "Unified display runtime: page marker again overlaps the V3 bottom status band")
    require(display_runtime, "jarnsen::radioProfileSlotExists(profile)", "Unified PROFILE: slot existence is not checked")
    require(display_runtime, "jarnsen::radioProfileSelect(profile, true)", "Unified PROFILE: shared radioProfileSelect backend is not used")
    require(display_runtime, '"PROFIL NICHT GESPEICHERT"', "Unified PROFILE: missing-slot error text is absent")
    require(display_runtime, "jarnsen::radioProfileActive()", "Unified PROFILE: active profile is not displayed")

    require(radio_profiles, "staged.region = meshtastic_Config_LoRaConfig_RegionCode_US;", "JarnsenRadioProfiles: J1/J2 are no longer forced to US region")
    require(radio_profiles, "currentMatchesSlot", "JarnsenRadioProfiles: active marker is no longer validated against config.lora")
    require(radio_profiles, "const meshtastic_Config_LoRaConfig previousLora = config.lora;", "JarnsenRadioProfiles: LoRa rollback snapshot missing")
    require(radio_profiles, "const bool rollbackSaved = nodeDB->saveToDisk(SEGMENT_CONFIG);", "JarnsenRadioProfiles: failed marker write no longer rolls config back")

    # Defaults are provisioned once through the same backend. The migration
    # marker prevents later intentional slot deletion from being silently healed.
    require(runtime_policy, 'RADIO_DEFAULTS_MARKER = "/prefs/jarnsen-radio-defaults-v1"', "JARNSEN runtime: radio-default migration marker missing")
    require(runtime_policy, "JARNSEN_1_DEFAULT_MHZ = 915.625f", "JARNSEN runtime: JARNSEN 1 default frequency changed")
    require(runtime_policy, "JARNSEN_2_DEFAULT_MHZ = 917.375f", "JARNSEN runtime: JARNSEN 2 default frequency changed")
    require(runtime_policy, "!radioProfileSlotExists(RadioProfileSlot::STANDARD) && !radioProfileCaptureStandard()", "JARNSEN runtime: Standard is not captured once before default profiles")
    require(runtime_policy, "radioProfileConfigureJarnsen(RadioProfileSlot::JARNSEN_1", "JARNSEN runtime: J1 default does not use shared radio backend")
    require(runtime_policy, "radioProfileConfigureJarnsen(RadioProfileSlot::JARNSEN_2", "JARNSEN runtime: J2 default does not use shared radio backend")

    require(serial_console, "const bool ok = valid && jarnsen::radioProfileSelect(profile, true);", "SerialConsole: USB RADIO_SELECT no longer uses radioProfileSelect")

    # All boards expose one JARNSEN service contract. Tracker keeps its richer
    # logger internally, while every other board uses the shared persistent log.
    require(diag_header, "diagnosticLogRequestUsbExport", "Shared diagnostic log header is missing USB export")
    require(diag_impl, "#if defined(HELTEC_TRACKER_V1_1)", "Tracker diagnostic adapter is missing")
    require(diag_impl, 'constexpr const char *CURRENT_LOG = "/jarnsen_diag.log";', "Generic persistent diagnostic log is missing")
    require(diag_impl, "#if defined(ARCH_NRF52) || defined(ARCH_NRF54L15)", "Wio/nRF shared diagnostic append compatibility guard is missing")
    require(diag_impl, "FSCom.open(CURRENT_LOG, FILE_O_WRITE)", "Wio/nRF shared diagnostic logger no longer uses LittleFS numeric write mode")
    require(diag_impl, "===JARNSEN_DIAG_LOG_BEGIN===", "Generic diagnostic BEGIN marker is missing")
    require(diag_impl, "===JARNSEN_DIAG_LOG_END===", "Generic diagnostic END marker is missing")
    require(serial_console, 'const bool full = strncmp(command, "JARNSEN_TOOL_FULL ', "JARNSEN_TOOL_FULL is not available in the common SerialConsole")
    require(serial_console, "jarnsen::diagnosticLogRequestUsbExport(Port);", "SerialConsole does not route log export through the common backend")
    require(serial_console, "jarnsen::diagnosticLogPumpUsbExport();", "SerialConsole does not pump the common log export")
    require(serial_console, "radio_profiles=3 diag_log=1 service_version=2", "JARNSEN service capabilities are not advertised")

    print("JARNSEN preflight contracts: PASS")
    print("- 20s display deadline, debounced Userbutton and wake-only first press")
    print("- Userbutton wake covered for light sleep and ESP32 deep sleep")
    print("- compact display text is pixel-fitted for Heltec V3")
    print("- J1/J2 defaults migrate once through the shared radio backend")
    print("- local/USB radio profiles share one persistent backend with rollback")
    print("- Wio/nRF diagnostic append mode is compile-compatible")
    print("- common service advertises 3 radio slots and diagnostic log export")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PreflightFailure as exc:
        print(f"JARNSEN preflight contracts: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
