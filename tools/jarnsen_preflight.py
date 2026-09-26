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
    tracker_service_upgrade = read("src/vehicle/TrackerServiceUpgrade.cpp")
    tracker_service_upgrade_header = read("src/vehicle/TrackerServiceUpgrade.h")
    display_model = read("src/jarnsen/core/display/JarnsenDisplayModel.h")
    display_runtime = read("src/jarnsen/adapters/JarnsenDisplayRuntime.cpp")
    display_runtime_header = read("src/jarnsen/adapters/JarnsenDisplayRuntime.h")
    screen_impl = read("src/graphics/Screen.cpp")
    runtime_policy = read("src/jarnsen/core/runtime/JarnsenRuntimePolicy.cpp")
    runtime_header = read("src/jarnsen/core/runtime/JarnsenRuntimePolicy.h")
    modules = read("src/modules/Modules.cpp")
    button_thread = read("src/input/ButtonThread.cpp")
    input_broker = read("src/input/InputBroker.cpp")
    nimble = read("src/nimble/NimbleBluetooth.cpp")
    nrf52_bluetooth = read("src/platform/nrf52/NRF52Bluetooth.cpp")
    nrf54_bluetooth = read("src/platform/nrf54l15/NRF54L15Bluetooth.cpp")
    sleep_impl = read("src/sleep.cpp")
    radio_profiles = read("src/jarnsen/core/mesh/JarnsenRadioProfiles.cpp")
    serial_console = read("src/SerialConsole.cpp")
    power_status = read("src/PowerStatus.h")
    tracker_diag = read("src/vehicle/TrackerDiagnosticLog.cpp")
    tracker_power = read("src/vehicle/TrackerPowerMonitor.h")
    battery_learning_header = read("src/jarnsen/core/power/JarnsenBatteryLearning.h")
    battery_learning = read("src/jarnsen/core/power/JarnsenBatteryLearning.cpp")
    tak_repeater_header = read("src/jarnsen/core/runtime/JarnsenTakRepeaterPolicy.h")
    tak_repeater = read("src/jarnsen/core/runtime/JarnsenTakRepeaterPolicy.cpp")
    drone_repeater_header = read("src/jarnsen/core/runtime/JarnsenDroneRepeaterPolicy.h")
    drone_repeater = read("src/jarnsen/core/runtime/JarnsenDroneRepeaterPolicy.cpp")
    role_model = read("src/jarnsen/core/roles/JarnsenDeviceRole.h")
    hardware = read("src/jarnsen/hardware/JarnsenHardwareProfiles.h")
    service_platform = read("src/jarnsen/hardware/JarnsenServicePlatform.h")
    legacy_bridge = read("src/jarnsen/adapters/JarnsenLegacyStatusBridge.cpp")
    router_impl = read("src/mesh/Router.cpp")
    power_fsm = read("src/PowerFSM.cpp")
    service_web = read("src/mesh/http/JarnsenServiceWeb.cpp")
    supreme_wlan_patch = read("tools/patch_jarnsen_tbeam_supreme_wlan.py")
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
    require(button_thread, "JARNSEN_BUTTON_DEBOUNCE_MS = 25U",
            "ButtonThread.cpp: Tracker-matched 25 ms JARNSEN hardware debounce is missing")
    require(button_thread, "powerFSM.trigger(EVENT_INPUT);", "ButtonThread.cpp: long-press release no longer restarts the display deadline")
    require(button_thread, "JARNSEN_FULL_LOCK_HOLD_MS = 10000U", "ButtonThread.cpp: Full Lock hold is not exactly 10 seconds")
    require(button_thread, "JARNSEN_FULL_LOCK_COUNTDOWN_START_MS = 5000U", "ButtonThread.cpp: Full Lock countdown does not start at 5 seconds")
    require(button_thread, '"NODE WIRD GESPERRT\\nIN %u"', "ButtonThread.cpp: Full Lock countdown UI is missing")
    require(button_thread, "full_lock_countdown=cancelled", "ButtonThread.cpp: releasing before 10 seconds does not cancel countdown")
    require(common, "TRACKER_COMMON_LOCK_HOLD_MS 10000UL", "TrackerCommonPolicy.cpp: Tracker Full Lock hold is not exactly 10 seconds")
    require(common, "TRACKER_COMMON_LOCK_COUNTDOWN_START_MS 5000UL", "TrackerCommonPolicy.cpp: Tracker Full Lock countdown does not start at 5 seconds")
    forbid(common, "lockTapCount", "TrackerCommonPolicy.cpp: obsolete multi-tap Full Lock activation still exists")
    forbid(common, "lockGestureArmed", "TrackerCommonPolicy.cpp: obsolete armed multi-tap Full Lock activation still exists")

    # Light sleep and deep sleep must both have a physical Userbutton wake path.
    require(sleep_impl, "gpio_wakeup_enable(pin, GPIO_INTR_LOW_LEVEL);", "sleep.cpp: ESP32 Userbutton light-sleep wake is missing")
    require(sleep_impl, "esp_sleep_enable_gpio_wakeup();", "sleep.cpp: ESP32 GPIO wake source is not enabled")
    require(runtime_policy, "deepSleepButtonObserver.observe(&preflightSleep);", "JARNSEN runtime: deep-sleep button wake is not armed from preflight")
    require(runtime_policy, "esp_sleep_enable_ext1_wakeup", "JARNSEN runtime: ESP32 deep-sleep EXT1 Userbutton wake is missing")
    require(runtime_policy, "normalizeDeepSleepUserButtonWake();", "JARNSEN runtime: post-deep-sleep RTC GPIO normalization is missing")
    require(button_thread, "esp_sleep_get_ext1_wakeup_status()", "ButtonThread.cpp: deep-sleep wake press is not identified")
    require(button_thread, "suppressJarnsenBootWakeEvent", "ButtonThread.cpp: first deep-sleep wake hold is not consumed as wake-only")
    require(button_thread, "physicalButtonWake = cause == ESP_SLEEP_WAKEUP_GPIO",
            "ButtonThread.cpp: physical light-sleep Userbutton wake is not identified")
    require(button_thread, "jarnsenDisplayHandleLightSleepButtonWake();",
            "ButtonThread.cpp: light-sleep Userbutton wake does not restore the JARNSEN display")
    require(display_runtime, 'diagnosticLog("WAKE", "light_button display=on focus=jarnsen wake_only=1")',
            "Unified display: light-sleep wake does not explicitly restore display/focus as wake-only")
    require(display_runtime, "suppressNextOneButtonEvent = true;",
            "Unified display: first wake/service press is not consumed before navigation")
    require(common, "void armDeepSleepButtonWake()", "TrackerCommonPolicy.cpp: Tracker deep-sleep Userbutton wake helper is missing")
    require(common, "bool bootWasUserWake()", "TrackerCommonPolicy.cpp: Tracker deep-sleep wake boot handling is missing")

    expected_transitions = (
        "case DisplayPage::MGRS:\n        return DisplayPage::NODE_STATUS;",
        "case DisplayPage::NODE_STATUS:\n        return DisplayPage::RADIO;",
        "case DisplayPage::RADIO:\n        return DisplayPage::NETWORK;",
        "return repeaterStatusEnabled ? DisplayPage::REPEATER_STATUS : DisplayPage::SYSTEM;",
        "case DisplayPage::REPEATER_STATUS:\n        return DisplayPage::SYSTEM;",
    )
    for transition in expected_transitions:
        require(display_model, transition, f"JarnsenDisplayModel.h: missing page transition: {transition!r}")
    require(display_model, "constexpr uint8_t displayPageCount(bool repeaterStatusEnabled)",
            "JarnsenDisplayModel.h: role-aware operator page count is missing")
    require(display_model, "return repeaterStatusEnabled ? 6U : 5U;",
            "JarnsenDisplayModel.h: base five pages plus optional repeater page changed")
    require(display_model, 'case DisplayPage::REPEATER_STATUS:\n        return "REPEATER";',
            "JarnsenDisplayModel.h: repeater status page name is missing")

    node_page = between(status, "void drawOwnNodePage(", "void drawServicePage(", "drawOwnNodePage")
    require(node_page, "displayPageCount(repeaterStatusPageActive())",
            "Tracker page 2: page count does not expand to 6 for repeater roles")
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

    # Tracker V1.1 UI is hardware-wide. Meshtastic roles such as ROUTER_LATE
    # must not fall back to the stock-only carousel merely because they are not
    # one of the JARNSEN TAK roles.
    tracker_ui_gate = between(status, "bool trackerUiRoleEnabled()", "const char *trackerRoleText()", "Tracker UI role gate")
    require(tracker_ui_gate, "return true;", "Tracker UI is role-gated again; ROUTER_LATE would lose JARNSEN pages")
    require(screen_impl, "trackerStartsJarnsenUiAfterBoot()", "Screen.cpp: non-TAK Tracker roles do not start in JARNSEN UI")
    require(screen_impl, "trackerStatusRequestFocus();", "Screen.cpp: Tracker JARNSEN focus restore is missing")
    require(screen_impl, "event->inputEvent == INPUT_BROKER_USER_PRESS", "Screen.cpp: Tracker short press routing is missing")
    require(screen_impl, "trackerServiceMenuShortPress();", "Screen.cpp: Tracker short press is not routed to JARNSEN pages/menu")
    require(screen_impl, "trackerServiceMenuSelect();", "Screen.cpp: Tracker long press is not routed to JARNSEN select/open")

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

    # One-button boards deliberately mirror Tracker V1.1: short press advances
    # page/menu selection and long press (SELECT) opens/confirms. Wio keeps its
    # directional trackball semantics and is explicitly excluded from this map.
    require(display_runtime_header, "bool jarnsenDisplayHandlePrimaryPress();",
            "Unified display input: primary one-button press adapter is missing")
    primary_press = between(display_runtime, "bool jarnsenDisplayHandlePrimaryPress()",
                            "bool jarnsenDisplayHandleSelect()", "primary Userbutton handler")
    for target in ("HELTEC_V3", "HELTEC_V4", "TBEAM_V10", "LILYGO_TBEAM_S3_CORE"):
        require(primary_press, target, f"Unified display input: {target} is not mapped to Tracker-style one-button control")
    forbid(primary_press, "SEEED_WIO_TRACKER_L1",
           "Unified display input: Wio directional controls must not be collapsed into one-button semantics")
    require(primary_press, "return jarnsenDisplayHandleFrameStep(true);",
            "Unified display input: short press no longer advances page/menu selection")
    require(screen_impl,
            "event->inputEvent == INPUT_BROKER_USER_PRESS && jarnsenDisplayHandlePrimaryPress()",
            "Screen.cpp: Userbutton short press is not routed through the Unified one-button adapter")

    require(input_broker, "#define JARNSEN_ONE_BUTTON_UI 1",
            "InputBroker: Unified one-button target gate is missing")
    require(input_broker, "userConfig.longPressTime = 1200;",
            "InputBroker: V3/V4/T-Beam/Supreme long press no longer matches Tracker V1.1 1200 ms")
    require(input_broker, "config.longPressTime = 1200;",
            "InputBroker: alternate screened Userbutton path no longer uses Tracker V1.1 1200 ms")
    require(input_broker, "jarnsenDisplayHandlePhysicalPressStart();",
            "InputBroker: raw physical press no longer drives Tracker-style wake/service semantics")
    forbid(primary_press, "500", "Unified display input: 500 ms long-press semantics leaked back into the one-button UI")
    require(button_thread, "#define JARNSEN_FAST_ONE_BUTTON_TARGET 1",
            "ButtonThread: compile-time fast one-button target gate is missing")
    require(button_thread, "userButton.setClickMs(20);",
            "ButtonThread: one-button short tap no longer emits immediately after debounced release")
    no_screen_button = between(input_broker, "ButtonConfig userConfigNoScreen;", "UserButtonThread->initButton(userConfigNoScreen);",
                               "JARNSEN no-screen initialization fallback")
    require(no_screen_button, "#if JARNSEN_ONE_BUTTON_UI",
            "InputBroker: JARNSEN compile-time fallback is missing when Screen is not constructed")
    require(no_screen_button, "userConfigNoScreen.longPressTime = 1200;",
            "InputBroker: Screen construction order can regress one-button long press to 500 ms")
    require(no_screen_button, "userConfigNoScreen.longPress = INPUT_BROKER_SELECT;",
            "InputBroker: Screen construction order can drop long-press menu/select")


    # V1.1 is the visual/menu reference. Shared display boards keep the same
    # five base pages and operator menu hierarchy. Repeater roles add exactly
    # one sixth role-status page; unavailable hardware stays explicit N/A/OFF.
    for view in (
        "MAIN", "PROFILE", "TRACKER", "POSITION", "MOTION", "PARKING",
        "SERVICE", "BLUETOOTH", "WLAN", "DIAG_LOG", "SYSTEM",
        "DIAGNOSTICS", "POWER", "POWER_STATS", "INA226", "ANTENNA_TEST", "NODES",
    ):
        require(display_runtime, f"MenuView::{view}", f"Unified menu parity: missing {view} view")
    require(display_runtime, '"KURZ: WEITER   LANG: OK"',
            "Unified menu parity: Tracker V1.1 interaction hint is missing")
    require(display_runtime, '"2/%u"', "Unified page parity: NODE page no longer uses role-aware 2/5 or 2/6 numbering")
    require(display_runtime, "displayPageCount(repeaterStatusPageActive())",
            "Unified page parity: NODE count does not expand for repeater roles")
    require(display_runtime, '"TX%ddBm   RSSI--   SNR--"',
            "Unified page parity: RADIO bottom line no longer matches Tracker layout")
    require(display_runtime, '"DIRECT %u   ONLINE %u   %s"',
            "Unified page parity: NETWORK summary no longer matches Tracker layout")
    require(display_runtime, '"VOLL --             -- W"',
            "Unified page parity: SYSTEM layout no longer mirrors Tracker while keeping unsupported power explicit")
    require(display_runtime, "drawNodeNavigation(",
            "Unified menu parity: Tracker-style node navigation is missing")

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

    # Power snapshots must distinguish false from unknown and never invent
    # current, power, capacity-learning or sleep measurements on unsupported boards.
    require(power_status, "OptionalBool getHasBatteryState() const", "PowerStatus: battery diagnostics cannot distinguish false from unknown")
    require(power_status, "OptionalBool getHasUSBState() const", "PowerStatus: USB diagnostics cannot distinguish false from unknown")
    require(power_status, "OptionalBool getIsChargingState() const", "PowerStatus: charge diagnostics cannot distinguish false from unknown")
    require(diag_impl, '#include "PowerStatus.h"', "Generic diagnostics do not consume common PowerStatus")
    require(diag_impl, "powerStatus && powerStatus->isInitialized()", "Generic power diagnostics do not guard uninitialized PowerStatus")
    require(diag_impl, "LIVE | BATTERY | state=%s", "Generic live battery snapshot is missing")
    require(diag_impl, "LIVE | POWER | source=%s", "Generic live power snapshot is missing")
    require(diag_impl, "learn=unsupported", "Generic diagnostics do not mark unsupported battery learning")
    require(diag_impl, "current=unsupported power=unsupported", "Generic diagnostics invent unsupported current/power values")
    require(diag_impl, "# power_diag=1", "Generic diagnostic export does not advertise its power snapshot")
    require(tracker_diag, 'char remaining[32] = "learning";', "Tracker battery learning state is no longer exported")
    require(tracker_diag, "power.estimateReady", "Tracker remaining-time learning readiness is no longer checked")
    require(tracker_diag, "currentMilliAmpsX10", "Tracker current diagnostics are missing")
    require(tracker_power, "bool capacityReady;", "Tracker capacity learning readiness is missing from PowerMonitor")
    require(tracker_power, "uint8_t capacityConfidence;", "Tracker battery learning confidence is missing from PowerMonitor")

    # Every common non-Tracker board uses one SOC/time learner and the same
    # NODE/SYSTEM REST presentation. Current/power/mAh remain explicitly
    # unsupported until a real measurement source exists.
    require(battery_learning_header, "dischargeRateMilliPercentPerHour",
            "Shared battery learner stats are missing discharge rate")
    for target in ("HELTEC_V3", "HELTEC_V4", "SEEED_WIO_TRACKER_L1", "TBEAM_V10", "LILYGO_TBEAM_S3_CORE"):
        require(battery_learning, target, f"Shared battery learner is not enabled for {target}")
        require(runtime_policy, target, f"Shared battery learner runtime is not enabled for {target}")
    require(battery_learning, "LEARNING_MIN_SECS = 60UL * 60UL",
            "Shared battery learner no longer matches Tracker 1h minimum window")
    require(battery_learning, "RATE_REFRESH_SECS = 30UL * 60UL",
            "Shared battery learner no longer matches Tracker rate refresh")
    require(battery_learning, "(dischargeRateMilliPercentPerHour * 3UL + observedRate) / 4UL",
            "Shared battery learner no longer uses the Tracker smoothing rule")
    require(battery_learning, 'PERSIST_PATH = "/prefs/jarnsen-battery-learning-v1"',
            "Shared battery learner does not persist through the common filesystem")
    forbid(battery_learning, "#include <Preferences.h>",
           "Shared battery learner regressed to ESP32-only Preferences persistence")
    require(battery_learning, "capacity_mah=unsupported",
            "Shared battery learner must not invent mAh without a current sensor")
    require(runtime_policy, 'concurrency::OSThread("BatteryLearn")',
            "Shared battery learner thread is not installed")
    common_node_page = between(display_runtime, "void drawNode(", "void drawRadio(", "Unified NODE page")
    require(common_node_page, '"ON %s"', "Unified NODE page does not show uptime")
    require(common_node_page, '"REST %s"', "Unified NODE page does not show learned remaining runtime")
    require(common_node_page, "batteryLearningStats()", "Unified NODE page is not backed by the shared learner")
    common_system_page = between(display_runtime, "void drawSystem(", "void drawService(", "Unified SYSTEM page")
    require(common_system_page, '"REST %-8s', "Unified SYSTEM page does not show learned remaining runtime in Tracker V1.1 layout")
    require(common_system_page, "batteryLearningStats()", "Unified SYSTEM page is not backed by the shared learner")
    require(diag_impl, "learn=soc_time", "Common diagnostics do not expose battery learning state")
    require(diag_impl, "ina226=off", "Common diagnostics do not state that INA226 is currently absent")

    # TAK_REPEATER is a real Unified-Core runtime role, not just a label.
    require(tak_repeater_header, "struct TakRepeaterStats", "TAK Repeater health contract is missing")
    require(tak_repeater, "meshtastic_Config_DeviceConfig_Role_ROUTER_LATE",
            "TAK Repeater is not normalized to Router Late")
    require(tak_repeater, "meshtastic_Config_DeviceConfig_RebroadcastMode_ALL",
            "TAK Repeater rebroadcast policy is not ALL")
    require(tak_repeater, "TAK_LIGHT_SLEEP_CYCLE_SECS = 5UL * 60UL",
            "TAK Repeater light-sleep cycle changed")
    require(tak_repeater, "config.power.is_power_saving, false",
            "TAK Repeater must use router light sleep rather than tracker/deep-sleep power saving")
    require(role_model, "case DeviceRole::TAK_REPEATER:", "Core TAK_REPEATER role disappeared")
    require(role_model, "return {false, false, false, false, false, false, true, false",
            "TAK_REPEATER no longer requires light-sleep-capable hardware")
    require(legacy_bridge, "case meshtastic_Config_DeviceConfig_Role_REPEATER:",
            "Legacy stock REPEATER no longer maps to TAK_REPEATER")
    require(legacy_bridge, "role = DeviceRole::TAK_REPEATER;",
            "Legacy REPEATER mapping does not select TAK_REPEATER")
    require(runtime_policy, "takRepeaterApplyBaseConfig(true)",
            "TAK Repeater base config is not applied during Unified runtime bootstrap")
    require(runtime_policy, "takRepeaterRuntimeInit();",
            "TAK Repeater runtime is not started by Unified Core")
    require(power_fsm, "const bool isTakRepeater = jarnsen::activeDeviceRoleIs(jarnsen::DeviceRole::TAK_REPEATER);",
            "PowerFSM does not treat TAK_REPEATER as a router/light-sleep role")

    # Stationary and mobile behavior is automatic and preserves fixed_position.
    require(tak_repeater, "TAK_SMART_DISTANCE_M = 75U", "TAK Repeater smart-position distance changed")
    require(tak_repeater, "TAK_SMART_MIN_INTERVAL_SECS = 75U", "TAK Repeater smart-position minimum interval changed")
    require(tak_repeater, "TAK_STATIONARY_POSITION_SECS = 12UL * 60UL * 60UL",
            "TAK Repeater stationary heartbeat changed")
    require(tak_repeater, "mode == TakRepeaterPositionMode::MOBILE ? meshtastic_Config_PositionConfig_GpsMode_ENABLED",
            "TAK Repeater mobile mode no longer enables GPS")
    forbid(tak_repeater, "SET_CONFIG_IF_CHANGED(config.position.fixed_position",
           "TAK Repeater must preserve the user's fixed/mobile selection")
    require(tak_repeater, "position_broadcast_smart_enabled, mode == TakRepeaterPositionMode::MOBILE",
            "TAK Repeater smart position is not tied to mobile mode")

    # Service identity is derived from the normalized hardware profile for every
    # Unified-Core board. Board macros must not be duplicated in service code.
    require(service_platform, "currentHardwareRoleProfile().hardware.kind",
            "Service platform is not derived from the canonical hardware profile")
    for hardware_kind, descriptor in (
        ("BOARD_HELTEC_TRACKER_V11", "trackerV11ServiceDescriptor()"),
        ("BOARD_HELTEC_V3", "heltecV3ServiceDescriptor()"),
        ("BOARD_HELTEC_V4", "heltecV4ServiceDescriptor()"),
        ("BOARD_SEEED_WIO_TRACKER_L1", "seeedWioTrackerL1ServiceDescriptor()"),
        ("BOARD_LILYGO_TBEAM", "lilygoTBeamServiceDescriptor()"),
        ("BOARD_LILYGO_TBEAM_SUPREME", "lilygoTBeamSupremeServiceDescriptor()"),
    ):
        require(service_platform, hardware_kind,
                f"Service platform does not recognize {hardware_kind}")
        require(service_platform, descriptor,
                f"Service platform does not map {hardware_kind} to {descriptor}")
    forbid(service_platform, "#if defined(HELTEC",
           "Service platform duplicated board-macro selection instead of using HardwareKind")
    require(hardware, "defined(HELTEC_V3) || defined(_VARIANT_HELTEC_V3)",
            "Hardware profile does not recognize both Heltec V3 macro forms")
    require(hardware, "defined(HELTEC_V4) || defined(_VARIANT_HELTEC_V4)",
            "Hardware profile does not recognize both Heltec V4 macro forms")
    for target in ("HELTEC_TRACKER_V1_1", "SEEED_WIO_TRACKER_L1", "TBEAM_V10", "LILYGO_TBEAM_S3_CORE"):
        require(hardware, target, f"Hardware profile selector lost {target}")

    # Tracker V1.1 WLAN must use the existing BLE->WLAN handover. Direct
    # SoftAP startup from the menu races the active NimBLE backend on ESP32-S3.
    require(common, '#include "vehicle/TrackerServiceUpgrade.h"',
            "TrackerCommon: WLAN service-upgrade lifecycle is not included")
    require(common, "trackerServiceUpgradeInit();",
            "TrackerCommon: WLAN service-upgrade state is not initialized")
    require(common, "trackerServiceUpgradeTick();",
            "TrackerCommon: pending BLE->WLAN handover is never pumped")
    require(common, "trackerServiceUpgradeNoteServiceOpen();",
            "TrackerCommon: service-window health hook is missing")
    require(status, '#include "vehicle/TrackerServiceUpgrade.h"',
            "Tracker UI: WLAN handover interface is not included")
    require(status, "trackerServiceUpgradeRequestWlan();",
            "Tracker UI: WLAN STARTEN bypasses the safe BLE->WLAN handover")
    require(status, "trackerServiceUpgradeWlanPending()",
            "Tracker UI: WLAN pending state is not visible")
    forbid(status, "trackerWlanLastActionFailed = !jarnsenServiceWebStart();",
           "Tracker UI: direct SoftAP startup can race an active BLE controller")
    require(tracker_service_upgrade_header, "bool trackerServiceUpgradeWlanPending();",
            "Tracker WLAN handover pending contract is missing")
    require(tracker_service_upgrade, "bool localServiceWindowActive()",
            "Tracker WLAN handover does not model the active local service window")
    require(tracker_service_upgrade, "jarnsen::takRepeaterRoleActive()",
            "Tracker WLAN handover does not support TAK Repeater service windows")
    require(tracker_service_upgrade, "jarnsen::takRepeaterServiceOpen();",
            "Tracker WLAN handover cannot restore TAK Repeater BLE")
    require(nimble, 'memcmp(data, "WLANSTART", 9)',
            "Tracker BLE control lost WLANSTART")
    require(nimble, '"WLAN_ACK"',
            "Tracker BLE control lost WLANSTART acknowledgement")
    require(tak_repeater, "trackerServiceUpgradeTick();",
            "Tracker V1.1 TAK Repeater never pumps a pending WLAN handover")

    # Service transports are on demand, with a two-minute idle timeout and hard cap.
    require(tak_repeater, "TAK_SERVICE_IDLE_MS = 120UL * 1000UL", "TAK Repeater BLE service idle timeout changed")
    require(tak_repeater, "TAK_SERVICE_HARD_CAP_MS = 15UL * 60UL * 1000UL",
            "TAK Repeater service hard cap changed")
    require(tak_repeater, "class TakRepeaterServiceSleepObserver",
            "TAK Repeater provisioning: service-window sleep veto is missing")
    require(tak_repeater, "serviceSleepObserver.observe(&preflightSleep);",
            "TAK Repeater provisioning: service-window sleep veto is not installed")
    require(tak_repeater, 'diagnosticLog("TAK_REP_SLEEP", "veto=service_active")',
            "TAK Repeater provisioning: service sleep veto is not diagnosable")
    require(tak_repeater, "takRepeaterServiceOpen()", "TAK Repeater service window is missing")
    require(tak_repeater, "SET_CONFIG_IF_CHANGED(config.bluetooth.enabled, true);",
            "TAK Repeater provisioning: persistent Meshtastic Bluetooth must remain enabled across reconnect/reboot")
    forbid(tak_repeater, "SET_CONFIG_IF_CHANGED(config.bluetooth.enabled, false);",
           "TAK Repeater provisioning regressed to persisting Bluetooth OFF")
    bluetooth_off = between(tak_repeater, "void bluetoothOff()", "bool bluetoothConnected()", "TAK Repeater bluetoothOff")
    forbid(bluetooth_off, "config.bluetooth.enabled = false",
           "TAK Repeater provisioning: runtime BLE suspension must not persist/force config.enabled=false")
    require(bluetooth_off, "applyNimbleBluetoothLifecycle(nimbleBluetooth, caps, false);",
            "TAK Repeater provisioning: ESP32 service close no longer suspends the BLE backend")

    require(display_runtime, "jarnsen::takRepeaterServiceOpen();",
            "Shared SERVICE page does not activate TAK Repeater service")
    require(status, "jarnsen::takRepeaterServiceOpen();",
            "Tracker SERVICE menu does not activate TAK Repeater service")
    require(service_web, "jarnsen::takRepeaterServiceTouch();",
            "WLAN requests do not refresh TAK Repeater service activity")
    require(service_web, "defined(HELTEC_V3) || defined(_VARIANT_HELTEC_V3)",
            "ServiceWeb: Heltec V3 captive portal compile guard is missing")
    require(service_web, "CAPTIVE_DNS_GRACE_MS = 120UL * 1000UL",
            "ServiceWeb: captive DNS grace window is no longer long enough for phone portal detection")
    require(service_web, "if (portalAuthorized || !Throttle::isWithinTimespanMs(captiveDnsStartedMs, CAPTIVE_DNS_GRACE_MS))",
            "ServiceWeb: captive DNS no longer remains active until authorization/grace expiry")
    forbid(service_web, "if (client) {\n        stopCaptiveDns();",
           "ServiceWeb: first HTTP probe must not tear down captive DNS")

    require(nimble, 'meshtastic::BluetoothStatus newStatus("PAIRING");',
            "ESP32 BLE pairing status must not contain the numeric PIN")
    require(nimble, '"BT PIN"', "ESP32 pairing instruction title missing")
    require(nimble, '"EINGEBEN"', "ESP32 pairing instruction text missing")
    require(nrf52_bluetooth, 'const char *ble_message = "BT PIN\\nEINGEBEN";',
            "nRF52 pairing instruction must hide the numeric PIN")
    require(nrf54_bluetooth, 'meshtastic::BluetoothStatus pairingStatus("PAIRING");',
            "nRF54 pairing status must hide the numeric PIN")
    for pairing_source, label in (
        (nimble, "ESP32"),
        (nrf52_bluetooth, "nRF52"),
        (nrf54_bluetooth, "nRF54"),
    ):
        for forbidden_text in ("Enter passkey %06u", "Bluetooth pin set to", "BLE pairing PIN:", "BLE fixed PIN: %06u"):
            forbid(pairing_source, forbidden_text, f"{label} BLE pairing exposes numeric PIN")

    require(supreme_wlan_patch, "jarnsen::takRepeaterServiceOpen();",
            "Supreme shared WLAN transform drops TAK Repeater service activation")

    # Health/self-healing observes real radio events. Forwarding is counted but
    # never throttled by the metadata/position airtime brake.
    require(router_impl, "jarnsen::takRepeaterNoteRadioTx(forwarded);",
            "Router does not account TAK Repeater TX/forwarded packets")
    require(tak_repeater, "RadioInterface::loraRxPacketObservable",
            "TAK Repeater does not observe valid LoRa RX packets")
    require(tak_repeater, "forwarding=unchanged",
            "TAK Repeater airtime policy no longer documents forwarding as untouched")
    require(tak_repeater, "WATCH_CHANNEL_BUSY_PERCENT = 5.0f",
            "TAK Repeater watchdog busy-channel gate changed")
    require(tak_repeater, "radio->reconfigure()", "TAK Repeater watchdog cannot recover the radio")
    require(tak_repeater, "watchdogReconfigureFailures >= 2U",
            "TAK Repeater watchdog may reboot before two failed radio recoveries")
    require(tak_repeater, "rebootAtMsec = now + 5000UL",
            "TAK Repeater watchdog final reboot escalation is missing")
    require(tak_repeater, "TAK_REP_HEALTH", "TAK Repeater periodic health diagnostics are missing")
    require(tak_repeater, 'HEALTH_PATH = "/prefs/jarnsen-tak-repeater-health-v1"',
            "TAK Repeater boot/watchdog counters are not persistent")
    require(display_runtime, "void drawRepeaterStatus(", "Shared dedicated repeater status page is missing")
    require(display_runtime, '"TAK REP %s"', "Shared TAK Repeater status page title/mode is missing")
    require(display_runtime, '"RX%u  TX%u  FWD%u"', "Shared TAK Repeater page lacks RX/TX/FWD counters")
    require(display_runtime, '"CU%u%%  LAST %s"', "Shared TAK Repeater page lacks CU/last-radio status")
    require(status, "void drawRepeaterStatusPage(", "Tracker dedicated repeater status page is missing")
    require(status, '"TAK REP %s"', "Tracker TAK Repeater status page title/mode is missing")
    require(diag_impl, "LIVE | TAK_REPEATER |", "Generic diagnostic export lacks live TAK Repeater health")

    # DRONE_REPEATER is deliberately restricted to Tracker V1.1 and Heltec V4.
    tracker_profile = between(hardware, "constexpr HardwareRoleProfile trackerV11Profile()",
                              "constexpr HardwareRoleProfile heltecV3Profile()", "Tracker V1.1 hardware profile")
    v3_profile = between(hardware, "constexpr HardwareRoleProfile heltecV3Profile()",
                         "constexpr HardwareRoleProfile heltecV4Profile()", "Heltec V3 hardware profile")
    v4_profile = between(hardware, "constexpr HardwareRoleProfile heltecV4Profile()",
                         "constexpr HardwareRoleProfile seeedWioTrackerL1Profile()", "Heltec V4 hardware profile")
    wio_profile = between(hardware, "constexpr HardwareRoleProfile seeedWioTrackerL1Profile()",
                          "constexpr HardwareRoleProfile lilygoTBeamProfile()", "Wio hardware profile")
    tbeam_profile = between(hardware, "constexpr HardwareRoleProfile lilygoTBeamProfile()",
                            "constexpr HardwareRoleProfile lilygoTBeamSupremeProfile()", "T-Beam hardware profile")
    supreme_profile = between(hardware, "constexpr HardwareRoleProfile lilygoTBeamSupremeProfile()",
                              "constexpr HardwareRoleProfile currentHardwareRoleProfile()", "Supreme hardware profile")
    require(tracker_profile, "{true, true, true, true}", "Drone Repeater must remain enabled on Tracker V1.1")
    require(v4_profile, "{true, true, true, true}", "Drone Repeater must remain enabled on Heltec V4")
    for label, profile in (
        ("Heltec V3", v3_profile),
        ("Wio Tracker L1", wio_profile),
        ("T-Beam", tbeam_profile),
        ("T-Beam Supreme", supreme_profile),
    ):
        require(profile, "{true, true, true, false}", f"Drone Repeater must stay disabled on {label}")

    require(drone_repeater_header, "struct DroneRepeaterStats", "Drone Repeater live display stats are missing")
    require(drone_repeater, "#if defined(HELTEC_TRACKER_V1_1) || defined(HELTEC_V4) || defined(_VARIANT_HELTEC_V4)",
            "Drone Repeater runtime is not compile-limited to Tracker V1.1 / Heltec V4")
    forbid(drone_repeater, "defined(HELTEC_V3)", "Drone Repeater runtime leaked onto Heltec V3")
    forbid(drone_repeater, "defined(SEEED_WIO_TRACKER_L1)", "Drone Repeater runtime leaked onto Wio")
    forbid(drone_repeater, "defined(TBEAM_V10)", "Drone Repeater runtime leaked onto T-Beam")
    forbid(drone_repeater, "defined(LILYGO_TBEAM_S3_CORE)", "Drone Repeater runtime leaked onto Supreme")
    require(display_runtime, "#if defined(HELTEC_V4) || defined(_VARIANT_HELTEC_V4)",
            "Shared Drone Repeater display is not explicitly limited to Heltec V4")
    require(display_runtime, '"DRONE REPEATER"', "Heltec V4 Drone Repeater status page is missing")
    require(status, '"DRONE REPEATER"', "Tracker V1.1 Drone Repeater status page is missing")
    require(status, "jarnsen::droneRepeaterStats()", "Tracker Drone page is not backed by runtime stats")
    require(display_runtime, "jarnsen::droneRepeaterStats()", "V4 Drone page is not backed by runtime stats")

    require(serial_console, 'const bool full = strncmp(command, "JARNSEN_TOOL_FULL ', "JARNSEN_TOOL_FULL is not available in the common SerialConsole")
    require(serial_console, "jarnsen::diagnosticLogRequestUsbExport(Port);", "SerialConsole does not route log export through the common backend")
    require(serial_console, "jarnsen::diagnosticLogPumpUsbExport();", "SerialConsole does not pump the common log export")
    require(serial_console, "radio_profiles=3 diag_log=1 service_version=2", "JARNSEN service capabilities are not advertised")
    require(serial_console, "power_diag=1", "JARNSEN service does not advertise power diagnostics")

    print("JARNSEN preflight contracts: PASS")
    print("- 20s display deadline, debounced Userbutton and wake-only first press")
    print("- Userbutton wake covered for light sleep and ESP32 deep sleep")
    print("- compact display text is pixel-fitted for Heltec V3")
    print("- V3/V4/T-Beam/Supreme use Tracker-style 25ms debounce, 1200ms long press and wake-only first press")
    print("- V3/V4/Wio/T-Beam/Supreme mirror Tracker V1.1 pages/menu where hardware permits; unsupported sensors stay explicit N/A/OFF")
    print("- TAK_REPEATER keeps persistent BLE provisioning enabled while suspending the radio outside service windows")
    print("- Tracker V1.1 JARNSEN pages stay active for ROUTER_LATE and other Meshtastic roles")
    print("- J1/J2 defaults migrate once through the shared radio backend")
    print("- local/USB radio profiles share one persistent backend with rollback")
    print("- Wio/nRF diagnostic append mode is compile-compatible")
    print("- battery learning and power diagnostics are explicit on every target")
    print("- V3/V4/Wio/T-Beam/Supreme share Tracker-style SOC/time learning; INA226/mAh stay explicit unsupported")
    print("- all common display boards share NODE ON/REST and SYSTEM REST presentation")
    print("- TAK_REPEATER is unified for mobile/fixed position, light sleep, on-demand service and health monitoring")
    print("- TAK_REPEATER watchdog only escalates on a busy channel and never throttles forwarded mesh traffic")
    print("- TAK_REPEATER adds one dedicated 6th status page on display-capable boards")
    print("- DRONE_REPEATER adds the same dedicated status-page slot only on Tracker V1.1 and Heltec V4")
    print("- common service advertises 3 radio slots, diagnostic log and power snapshots")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PreflightFailure as exc:
        print(f"JARNSEN preflight contracts: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
