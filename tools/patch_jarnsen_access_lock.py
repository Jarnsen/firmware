"""Jarnsen shared access/RF/full-lock integration for Tracker V1.1 and Heltec V3.

Runs after the existing mesh-sync patch.  The device branches remain isolated,
but both receive the same user-facing security model:
- fixed PIN 240180
- 15 minute admin session
- persistent full display lock
- double-short + third 3s hold emergency full lock
- encrypted-primary-channel LOCKED_FULL / UNLOCKED text alerts
- persistent STANDARD / AUTH_A / AUTH_B RF selector (A/B unavailable until
  exact authorised frequencies are compiled in)
- protected service menu and tool write commands

The existing JARNSEN_TOOL_HELLO delta-log path is intentionally preserved.
"""
from __future__ import annotations

from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
BRANCH = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True).strip()
TRACKER = "tracker-v11" in BRANCH
V3 = "v3-repeater" in BRANCH
if not (TRACKER or V3):
    raise SystemExit(f"unsupported Jarnsen access branch: {BRANCH}")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"{label}: expected one anchor, got {text.count(old)}")
    return text.replace(old, new, 1)


BASE = ROOT / ("src/vehicle" if TRACKER else "src/infrastructure")
HEADER = BASE / "JarnsenAccessPolicy.h"
CPP = BASE / "JarnsenAccessPolicy.cpp"

HEADER.write_text(r'''#pragma once
#include <stddef.h>
#include <stdint.h>

enum class JarnsenRfProfile : uint8_t { STANDARD = 0, AUTH_A = 1, AUTH_B = 2 };

static constexpr uint32_t JARNSEN_ACCESS_PIN = 240180U;
static constexpr uint32_t JARNSEN_ADMIN_SESSION_MS = 15UL * 60UL * 1000UL;

void jarnsenAccessInit();
void jarnsenAccessEnforce();
void jarnsenAccessTick();

bool jarnsenAccessUnlock(uint32_t pin);
void jarnsenAccessLockAdmin();
bool jarnsenAccessAdminUnlocked();
uint32_t jarnsenAccessRemainingSecs();

bool jarnsenFullLocked();
void jarnsenActivateFullLock();
bool jarnsenUnlockFull(uint32_t pin);

bool jarnsenLockAlertEnabled();
void jarnsenSetLockAlertEnabled(bool enabled);

JarnsenRfProfile jarnsenRfProfile();
const char *jarnsenRfProfileName();
bool jarnsenRfProfileAvailable(JarnsenRfProfile profile);
bool jarnsenSetRfProfile(JarnsenRfProfile profile);

// Observe the physical button without replacing the existing button handler.
// Returns true only while the emergency third press/release must suppress the
// normal short/long action.
bool jarnsenAccessButtonSample(bool pressed, uint32_t nowMs, bool serviceMenuActive);

// Shared command grammar used by USB now and BLE/tool control paths later.
// Read-only delta-log HELLO/FULL commands remain owned by DiagnosticLog.
bool jarnsenAccessHandleToolCommand(const char *command, char *response, size_t responseSize);
''', encoding="utf-8")

CPP.write_text(r'''#include "JarnsenAccessPolicy.h"

#if defined(HELTEC_TRACKER_V1_1) || defined(_VARIANT_HELTEC_V3)

#include "MeshService.h"
#include "NodeDB.h"
#include "configuration.h"
#include "gps/RTC.h"
#include "main.h"
#include "mesh/Channels.h"
#include "mesh/Router.h"
#if defined(HELTEC_TRACKER_V1_1)
#include "vehicle/TrackerDiagnosticLog.h"
#define JACCESS_LOG(event, fmt, ...) trackerDiagLog(event, fmt, ##__VA_ARGS__)
#else
#include "infrastructure/HeltecV3DiagnosticLog.h"
#define JACCESS_LOG(event, fmt, ...) heltecV3DiagLog(event, fmt, ##__VA_ARGS__)
#endif

#include <Arduino.h>
#include <Preferences.h>
#include <cstdio>
#include <cstring>

namespace
{
constexpr const char *PREF_NAMESPACE = "jarnsenAccess";
constexpr const char *PREF_FULL = "full";
constexpr const char *PREF_ALERT = "alert";
constexpr const char *PREF_RF = "rf";
constexpr uint32_t CLICK_MAX_MS = 500UL;
constexpr uint32_t CLICK_GAP_MS = 800UL;
constexpr uint32_t EMERGENCY_HOLD_MS = 3000UL;
constexpr uint32_t ALERT_RETRY_MS = 5000UL;

// Deliberately unavailable until the exact authorised values are supplied.
// Never replace these with guessed frequencies.
constexpr float JARNSEN_AUTH_FREQUENCY_A_MHZ = 0.0f;
constexpr float JARNSEN_AUTH_FREQUENCY_B_MHZ = 0.0f;
constexpr bool JARNSEN_AUTH_ALLOW_DUTY_OVERRIDE = false;

bool initialized = false;
bool fullLocked = false;
bool lockAlert = true;
JarnsenRfProfile rfProfile = JarnsenRfProfile::STANDARD;
uint32_t adminUnlockedUntilMs = 0;

bool buttonPrevPressed = false;
uint32_t buttonPressStartedMs = 0;
uint32_t lastShortReleaseMs = 0;
uint8_t shortClickCount = 0;
bool emergencyThirdPress = false;
bool emergencyTriggered = false;

uint8_t pendingAlertCount = 0;
bool pendingAlertLocked = false;
uint32_t nextAlertMs = 0;
static char alertText[220] = {};

bool deadlineActive(uint32_t deadline)
{
    return deadline != 0 && (int32_t)(deadline - millis()) > 0;
}

void persistBool(const char *key, bool value)
{
    Preferences prefs;
    if (prefs.begin(PREF_NAMESPACE, false)) {
        prefs.putBool(key, value);
        prefs.end();
    }
}

void persistRf()
{
    Preferences prefs;
    if (prefs.begin(PREF_NAMESPACE, false)) {
        prefs.putUChar(PREF_RF, (uint8_t)rfProfile);
        prefs.end();
    }
}

float rfFrequency(JarnsenRfProfile profile)
{
    if (profile == JarnsenRfProfile::AUTH_A)
        return JARNSEN_AUTH_FREQUENCY_A_MHZ;
    if (profile == JarnsenRfProfile::AUTH_B)
        return JARNSEN_AUTH_FREQUENCY_B_MHZ;
    return 0.0f;
}

void applyRfRuntime()
{
    if (rfProfile == JarnsenRfProfile::STANDARD) {
        // Standard mode must stay inside normal Meshtastic/region policy.
        config.lora.override_frequency = 0.0f;
        config.lora.override_duty_cycle = false;
        return;
    }

    const float frequency = rfFrequency(rfProfile);
    if (frequency <= 0.0f) {
        rfProfile = JarnsenRfProfile::STANDARD;
        config.lora.override_frequency = 0.0f;
        config.lora.override_duty_cycle = false;
        persistRf();
        JACCESS_LOG("RF_PROFILE", "invalid/unprovisioned profile forced STANDARD");
        return;
    }

    config.lora.override_frequency = frequency;
    config.lora.override_duty_cycle = JARNSEN_AUTH_ALLOW_DUTY_OVERRIDE;
}

void scheduleAlert(bool locked)
{
    if (!lockAlert)
        return;
    pendingAlertLocked = locked;
    pendingAlertCount = locked ? 3U : 2U;
    nextAlertMs = millis();
}

bool buildPositionText(char *out, size_t outSize)
{
    if (!out || outSize == 0 || !nodeDB)
        return false;
    meshtastic_PositionLite position;
    if (!nodeDB->copyNodePosition(nodeDB->getNodeNum(), position) ||
        (position.latitude_i == 0 && position.longitude_i == 0))
        return false;

    uint32_t age = UINT32_MAX;
    const uint32_t nowEpoch = getValidTime(RTCQualityDevice);
    if (position.time != 0 && nowEpoch != 0)
        age = nowEpoch >= position.time ? nowEpoch - position.time : position.time - nowEpoch;

    if (age == UINT32_MAX)
        snprintf(out, outSize, "pos=%.6f,%.6f age=?", position.latitude_i * 1e-7, position.longitude_i * 1e-7);
    else
        snprintf(out, outSize, "pos=%.6f,%.6f age=%us", position.latitude_i * 1e-7, position.longitude_i * 1e-7,
                 (unsigned)age);
    return true;
}

bool sendAccessAlert(bool locked)
{
    if (!router || !service || !nodeDB)
        return false;
    // Never leak recovery coordinates onto the public/default Meshtastic channel.
    if (channels.isDefaultChannel(0)) {
        JACCESS_LOG("LOCK_ALERT", "skipped public primary channel state=%s", locked ? "LOCKED_FULL" : "UNLOCKED");
        return false;
    }

    char position[72] = "pos=unknown";
    buildPositionText(position, sizeof(position));
    const uint32_t nowEpoch = getValidTime(RTCQualityDevice);
    const char *name = owner.long_name[0] ? owner.long_name : "--";
    snprintf(alertText, sizeof(alertText), "[JARNSEN:%s] %s !%08x t=%u %s", locked ? "LOCKED_FULL" : "UNLOCKED", name,
             (unsigned)nodeDB->getNodeNum(), (unsigned)nowEpoch, position);

    meshtastic_MeshPacket *packet = router->allocForSending();
    if (!packet)
        return false;
    packet->decoded.portnum = meshtastic_PortNum_TEXT_MESSAGE_APP;
    packet->to = NODENUM_BROADCAST;
    packet->channel = 0;
    packet->want_ack = false;
    packet->decoded.want_response = false;
    packet->priority = meshtastic_MeshPacket_Priority_DEFAULT;
    size_t length = strnlen(alertText, sizeof(alertText));
    if (length > sizeof(packet->decoded.payload.bytes))
        length = sizeof(packet->decoded.payload.bytes);
    packet->decoded.payload.size = length;
    memcpy(packet->decoded.payload.bytes, alertText, length);
    service->sendToMesh(packet);
    JACCESS_LOG("LOCK_ALERT", "mesh state=%s try-left=%u", locked ? "LOCKED_FULL" : "UNLOCKED",
                (unsigned)pendingAlertCount);
    return true;
}

void resetEmergencySequence()
{
    buttonPressStartedMs = 0;
    lastShortReleaseMs = 0;
    shortClickCount = 0;
    emergencyThirdPress = false;
    emergencyTriggered = false;
}
} // namespace

void jarnsenAccessInit()
{
    if (initialized)
        return;
    Preferences prefs;
    if (prefs.begin(PREF_NAMESPACE, true)) {
        fullLocked = prefs.getBool(PREF_FULL, false);
        lockAlert = prefs.getBool(PREF_ALERT, true);
        rfProfile = (JarnsenRfProfile)prefs.getUChar(PREF_RF, (uint8_t)JarnsenRfProfile::STANDARD);
        prefs.end();
    }
    initialized = true;
    if (!jarnsenRfProfileAvailable(rfProfile)) {
        rfProfile = JarnsenRfProfile::STANDARD;
        persistRf();
    }
    applyRfRuntime();
    JACCESS_LOG("ACCESS_INIT", "full=%u alert=%u rf=%s", fullLocked ? 1U : 0U, lockAlert ? 1U : 0U,
                jarnsenRfProfileName());
}

void jarnsenAccessEnforce()
{
    if (!initialized)
        jarnsenAccessInit();
    config.bluetooth.mode = meshtastic_Config_BluetoothConfig_PairingMode_FIXED_PIN;
    config.bluetooth.fixed_pin = JARNSEN_ACCESS_PIN;
    if (!jarnsenRfProfileAvailable(rfProfile))
        rfProfile = JarnsenRfProfile::STANDARD;
    applyRfRuntime();
    if (adminUnlockedUntilMs != 0 && !deadlineActive(adminUnlockedUntilMs))
        adminUnlockedUntilMs = 0;
}

void jarnsenAccessTick()
{
    jarnsenAccessEnforce();
    if (pendingAlertCount == 0)
        return;
    const uint32_t now = millis();
    if (nextAlertMs != 0 && (int32_t)(now - nextAlertMs) < 0)
        return;
    sendAccessAlert(pendingAlertLocked);
    --pendingAlertCount;
    nextAlertMs = pendingAlertCount ? now + ALERT_RETRY_MS : 0;
}

bool jarnsenAccessUnlock(uint32_t pin)
{
    if (pin != JARNSEN_ACCESS_PIN) {
        JACCESS_LOG("ACCESS_DENY", "bad PIN");
        return false;
    }
    const uint32_t now = millis();
    adminUnlockedUntilMs = now + JARNSEN_ADMIN_SESSION_MS;
    if (adminUnlockedUntilMs == 0)
        adminUnlockedUntilMs = 1;
    JACCESS_LOG("ACCESS_OK", "admin session 15min");
    return true;
}

void jarnsenAccessLockAdmin()
{
    adminUnlockedUntilMs = 0;
    JACCESS_LOG("ACCESS_LOCK", "admin session closed");
}

bool jarnsenAccessAdminUnlocked()
{
    if (!initialized)
        jarnsenAccessInit();
    if (!deadlineActive(adminUnlockedUntilMs)) {
        adminUnlockedUntilMs = 0;
        return false;
    }
    return true;
}

uint32_t jarnsenAccessRemainingSecs()
{
    if (!jarnsenAccessAdminUnlocked())
        return 0;
    return ((uint32_t)(adminUnlockedUntilMs - millis()) + 999U) / 1000U;
}

bool jarnsenFullLocked()
{
    if (!initialized)
        jarnsenAccessInit();
    return fullLocked;
}

void jarnsenActivateFullLock()
{
    if (!initialized)
        jarnsenAccessInit();
    if (fullLocked)
        return;
    fullLocked = true;
    adminUnlockedUntilMs = 0;
    persistBool(PREF_FULL, true);
    scheduleAlert(true);
    JACCESS_LOG("FULL_LOCK", "persistent full display lock activated");
}

bool jarnsenUnlockFull(uint32_t pin)
{
    if (!jarnsenAccessUnlock(pin))
        return false;
    if (fullLocked) {
        fullLocked = false;
        persistBool(PREF_FULL, false);
        scheduleAlert(false);
        JACCESS_LOG("FULL_UNLOCK", "persistent full display lock cleared");
    }
    return true;
}

bool jarnsenLockAlertEnabled()
{
    if (!initialized)
        jarnsenAccessInit();
    return lockAlert;
}

void jarnsenSetLockAlertEnabled(bool enabled)
{
    if (!initialized)
        jarnsenAccessInit();
    lockAlert = enabled;
    persistBool(PREF_ALERT, enabled);
    JACCESS_LOG("LOCK_ALERT", "enabled=%u", enabled ? 1U : 0U);
}

JarnsenRfProfile jarnsenRfProfile()
{
    if (!initialized)
        jarnsenAccessInit();
    return rfProfile;
}

const char *jarnsenRfProfileName()
{
    switch (rfProfile) {
    case JarnsenRfProfile::AUTH_A: return "JARNSEN A";
    case JarnsenRfProfile::AUTH_B: return "JARNSEN B";
    default: return "STANDARD";
    }
}

bool jarnsenRfProfileAvailable(JarnsenRfProfile profile)
{
    if (profile == JarnsenRfProfile::STANDARD)
        return true;
    return rfFrequency(profile) > 0.0f;
}

bool jarnsenSetRfProfile(JarnsenRfProfile profile)
{
    if (!jarnsenAccessAdminUnlocked())
        return false;
    if (!jarnsenRfProfileAvailable(profile)) {
        JACCESS_LOG("RF_PROFILE", "refused unprovisioned profile=%u", (unsigned)profile);
        return false;
    }
    rfProfile = profile;
    persistRf();
    applyRfRuntime();
    if (router && router->getRadioIface())
        router->getRadioIface()->reconfigure();
    JACCESS_LOG("RF_PROFILE", "active=%s", jarnsenRfProfileName());
    return true;
}

bool jarnsenAccessButtonSample(bool pressed, uint32_t nowMs, bool serviceMenuActive)
{
    if (!initialized)
        jarnsenAccessInit();

    if (serviceMenuActive) {
        buttonPrevPressed = pressed;
        resetEmergencySequence();
        return false;
    }

    bool suppress = emergencyThirdPress || emergencyTriggered;
    if (pressed && !buttonPrevPressed) {
        buttonPressStartedMs = nowMs ? nowMs : 1;
        if (shortClickCount == 2 && lastShortReleaseMs != 0 &&
            (uint32_t)(nowMs - lastShortReleaseMs) <= CLICK_GAP_MS) {
            emergencyThirdPress = true;
            emergencyTriggered = false;
            suppress = true;
        }
    }

    if (pressed && emergencyThirdPress && !emergencyTriggered && buttonPressStartedMs != 0 &&
        (uint32_t)(nowMs - buttonPressStartedMs) >= EMERGENCY_HOLD_MS) {
        jarnsenActivateFullLock();
        emergencyTriggered = true;
        suppress = true;
    }

    if (!pressed && buttonPrevPressed) {
        const uint32_t heldMs = buttonPressStartedMs != 0 ? (uint32_t)(nowMs - buttonPressStartedMs) : 0U;
        if (emergencyThirdPress) {
            suppress = true;
            resetEmergencySequence();
        } else if (heldMs >= 40UL && heldMs <= CLICK_MAX_MS) {
            if (shortClickCount != 0 && lastShortReleaseMs != 0 &&
                (uint32_t)(nowMs - lastShortReleaseMs) > CLICK_GAP_MS)
                shortClickCount = 0;
            if (shortClickCount < 2)
                ++shortClickCount;
            lastShortReleaseMs = nowMs ? nowMs : 1;
            buttonPressStartedMs = 0;
        } else {
            resetEmergencySequence();
        }
    } else if (!pressed && shortClickCount != 0 && lastShortReleaseMs != 0 &&
               (uint32_t)(nowMs - lastShortReleaseMs) > CLICK_GAP_MS) {
        resetEmergencySequence();
    }

    buttonPrevPressed = pressed;
    return suppress;
}

bool jarnsenAccessHandleToolCommand(const char *command, char *response, size_t responseSize)
{
    if (!command || !response || responseSize == 0)
        return false;
    response[0] = '\0';

    unsigned pin = 0;
    unsigned value = 0;
    char mode[16] = {};
    if (sscanf(command, "JARNSEN_AUTH %u", &pin) == 1) {
        snprintf(response, responseSize, "%s", jarnsenAccessUnlock(pin) ? "OK AUTH" : "ERR PIN");
        return true;
    }
    if (sscanf(command, "JARNSEN_UNLOCK_FULL %u", &pin) == 1) {
        snprintf(response, responseSize, "%s", jarnsenUnlockFull(pin) ? "OK UNLOCKED" : "ERR PIN");
        return true;
    }
    if (sscanf(command, "JARNSEN_LOCK_FULL %u", &pin) == 1) {
        if (!jarnsenAccessUnlock(pin))
            snprintf(response, responseSize, "ERR PIN");
        else {
            jarnsenActivateFullLock();
            snprintf(response, responseSize, "OK LOCKED_FULL");
        }
        return true;
    }
    if (sscanf(command, "JARNSEN_RF %u %15s", &pin, mode) == 2) {
        if (!jarnsenAccessUnlock(pin)) {
            snprintf(response, responseSize, "ERR PIN");
            return true;
        }
        JarnsenRfProfile requested = JarnsenRfProfile::STANDARD;
        if (strcmp(mode, "A") == 0 || strcmp(mode, "AUTH_A") == 0)
            requested = JarnsenRfProfile::AUTH_A;
        else if (strcmp(mode, "B") == 0 || strcmp(mode, "AUTH_B") == 0)
            requested = JarnsenRfProfile::AUTH_B;
        const bool ok = jarnsenSetRfProfile(requested);
        snprintf(response, responseSize, "%s %s", ok ? "OK" : "ERR UNAVAILABLE", jarnsenRfProfileName());
        return true;
    }
    if (sscanf(command, "JARNSEN_LOCK_ALERT %u %u", &pin, &value) == 2) {
        if (!jarnsenAccessUnlock(pin))
            snprintf(response, responseSize, "ERR PIN");
        else {
            jarnsenSetLockAlertEnabled(value != 0);
            snprintf(response, responseSize, "OK ALERT=%u", jarnsenLockAlertEnabled() ? 1U : 0U);
        }
        return true;
    }
    if (strcmp(command, "JARNSEN_ACCESS_STATUS") == 0) {
        snprintf(response, responseSize, "OK full=%u admin=%u rf=%s alert=%u", jarnsenFullLocked() ? 1U : 0U,
                 jarnsenAccessAdminUnlocked() ? 1U : 0U, jarnsenRfProfileName(), jarnsenLockAlertEnabled() ? 1U : 0U);
        return true;
    }
    return false;
}

#endif
''', encoding="utf-8")


def patch_screen() -> None:
    path = ROOT / "src/graphics/Screen.cpp"
    text = path.read_text(encoding="utf-8")
    include = '#include "vehicle/JarnsenAccessPolicy.h"\n' if TRACKER else '#include "infrastructure/JarnsenAccessPolicy.h"\n'
    if include.strip() not in text:
        text = replace_once(text, '#include "configuration.h"\n', '#include "configuration.h"\n' + include, "screen access include")

    marker = "drawJarnsenFullLockIntoBuffer"
    if marker not in text:
        anchor = "static inline void updateUiFrame(OLEDDisplayUi *ui)\n{\n"
        helper = r'''static void drawJarnsenFullLockIntoBuffer(OLEDDisplay *display)
{
    display->clear();
    const int w = display->getWidth();
    const int h = display->getHeight();
    display->setTextAlignment(TEXT_ALIGN_CENTER);
    display->setFont(FONT_LARGE);
    display->drawString(w / 2, h / 2 - FONT_HEIGHT_LARGE, "NODE GESPERRT");
    display->setFont(FONT_SMALL);
    display->drawString(w / 2, h / 2 + 4, "HOLD: PIN");
}

static inline void updateUiFrame(OLEDDisplayUi *ui)
{
#if defined(HELTEC_TRACKER_V1_1) || defined(_VARIANT_HELTEC_V3)
    if (jarnsenFullLocked() && screen != nullptr) {
        OLEDDisplay *display = screen->getDisplayDevice();
        drawJarnsenFullLockIntoBuffer(display);
        // Only the six-digit local PIN picker may be composited over the lock
        // screen. Normal message/status banners stay hidden.
        if (NotificationRenderer::current_notification_type == notificationTypeEnum::number_picker)
            NotificationRenderer::drawBannercallback(display, ui->getUiState());
        display->display();
        return;
    }
#endif
'''
        text = replace_once(text, anchor, helper, "screen full lock")
    path.write_text(text, encoding="utf-8")


def patch_diag_tool_command() -> None:
    path = ROOT / ("src/vehicle/TrackerDiagnosticLog.cpp" if TRACKER else "src/infrastructure/HeltecV3DiagnosticLog.cpp")
    text = path.read_text(encoding="utf-8")
    include = '#include "vehicle/JarnsenAccessPolicy.h"\n' if TRACKER else '#include "infrastructure/JarnsenAccessPolicy.h"\n'
    if include.strip() not in text:
        anchor = '#include "NodeDB.h"\n' if TRACKER else '#include "infrastructure/HeltecV3PowerMonitor.h"\n'
        if anchor not in text:
            # V3 source layout can move; fall back to the diagnostic header.
            anchor = '#include "HeltecV3DiagnosticLog.h"\n' if not TRACKER else '#include "TrackerDiagnosticLog.h"\n'
        text = replace_once(text, anchor, anchor + include, "diag access include")

    fn = "trackerDiagHandleToolSerialByte" if TRACKER else "heltecV3DiagHandleToolSerialByte"
    start = text.find(f"bool {fn}(uint8_t value)\n{{")
    if start < 0:
        raise SystemExit(f"{fn}: generated delta handler missing; access patch must run after mesh-sync")
    end = text.find("\n}\n", start) + 3
    block = text[start:end]
    if "jarnsenAccessHandleToolCommand" not in block:
        needle = "\n        toolCommandLength = 0;"
        if needle not in block:
            raise SystemExit(f"{fn}: reset anchor missing")
        extra = r'''
        else {
            char accessResponse[96] = {};
            if (jarnsenAccessHandleToolCommand(toolCommand, accessResponse, sizeof(accessResponse))) {
                Serial.print("JARNSEN_ACCESS ");
                Serial.print(accessResponse);
                Serial.print("\r\n");
            }
        }
'''
        block = block.replace(needle, extra + needle, 1)
        text = text[:start] + block + text[end:]
    path.write_text(text, encoding="utf-8")


def patch_tracker() -> None:
    common = ROOT / "src/vehicle/TrackerCommonPolicy.cpp"
    text = common.read_text(encoding="utf-8")
    if '#include "vehicle/JarnsenAccessPolicy.h"' not in text:
        text = replace_once(text, '#include "vehicle/JarnsenMeshPolicy.h"\n',
                            '#include "vehicle/JarnsenMeshPolicy.h"\n#include "vehicle/JarnsenAccessPolicy.h"\n', "tracker access include")
    if "jarnsenAccessTick();" not in text:
        text = replace_once(text, '        jarnsenMeshPolicyEnforce();\n        const uint32_t now = millis();\n',
                            '        jarnsenMeshPolicyEnforce();\n        jarnsenAccessTick();\n        const uint32_t now = millis();\n', "tracker access tick")
    pressed_anchor = '        const bool pressed = button != GPIO_NUM_NC && digitalRead(button) == LOW;\n'
    if "jarnsenButtonSuppress" not in text:
        text = replace_once(text, pressed_anchor, pressed_anchor +
                            '        const bool jarnsenButtonSuppress = jarnsenAccessButtonSample(pressed, now, trackerServiceMenuActive());\n',
                            "tracker button sample")
        text = replace_once(text,
                            '            if (serviceActive && !buttonLongHandled && buttonPressedSinceMs != 0 &&\n',
                            '            if (serviceActive && !buttonLongHandled && !jarnsenButtonSuppress && buttonPressedSinceMs != 0 &&\n',
                            "tracker long suppress")
        text = replace_once(text,
                            '                if (serviceActive && !openedServiceThisPress && !buttonLongHandled) {\n',
                            '                if (serviceActive && !openedServiceThisPress && !buttonLongHandled && !jarnsenButtonSuppress) {\n',
                            "tracker short suppress")
        text = replace_once(text,
                            '                if (trackerServiceMenuActive())\n                    trackerServiceMenuSelect();\n                else if (trackerServicePageVisible())\n                    trackerServiceMenuOpen();\n',
                            '                if (trackerServiceMenuActive())\n                    trackerServiceMenuSelect();\n                else if (jarnsenFullLocked())\n                    trackerServiceMenuOpen();\n                else if (trackerServicePageVisible())\n                    trackerServiceMenuOpen();\n',
                            "tracker locked PIN long")
    common.write_text(text, encoding="utf-8")

    menu = ROOT / "src/vehicle/TrackerStatusModule.cpp"
    text = menu.read_text(encoding="utf-8")
    if '#include "vehicle/JarnsenAccessPolicy.h"' not in text:
        text = replace_once(text, '#include "vehicle/JarnsenMeshPolicy.h"\n',
                            '#include "vehicle/JarnsenMeshPolicy.h"\n#include "vehicle/JarnsenAccessPolicy.h"\n', "tracker menu access include")
    if "RF_PROFILE" not in text:
        text = replace_once(text, '    ROOT,\n    POSITION,\n', '    ROOT,\n    ACCESS,\n    RF_PROFILE,\n    POSITION,\n', "tracker access enum")

    if "showTrackerAccessPin" not in text:
        anchor = "void showTrackerMenu(TrackerMenu menu, int initialSelection)\n"
        helper = r'''void showTrackerAccessPin()
{
    if (!screen || !trackerServiceMenuMode)
        return;
    trackerMenuCurrent = TrackerMenu::NONE;
    trackerMenuPending = TrackerMenu::NONE;
    screen->showNumberPicker("PIN", 0, 6, false, [](uint32_t pin) {
        const bool ok = jarnsenFullLocked() ? jarnsenUnlockFull(pin) : jarnsenAccessUnlock(pin);
        if (ok) {
            trackerRootSelection = 0;
            queueTrackerMenu(TrackerMenu::ROOT, 0);
        } else {
            showTrackerAccessPin();
        }
    });
}

void showTrackerMenu(TrackerMenu menu, int initialSelection)
'''
        text = replace_once(text, anchor, helper, "tracker PIN helper")

    old_root = '''        static const char *opts[] = {"Back", "Position", "Motion", "Parking", "Bluetooth", "Diagnostic Log", "System",
                                     "WLAN Service"};
        showTrackerOptions("Service Settings", opts, 8, initialSelection, [](int selected) {
'''
    new_root = '''        static const char *opts[] = {"Back", "Sicherheit / Funk", "Position", "Motion", "Parking", "Bluetooth", "Diagnostic Log", "System",
                                     "WLAN Service"};
        showTrackerOptions("Service Settings", opts, 9, initialSelection, [](int selected) {
'''
    if '"Sicherheit / Funk"' not in text:
        text = replace_once(text, old_root, new_root, "tracker root option")
        # Shift root switch cases and insert access at 1.
        old_cases = '''            case 1:
                queueTrackerMenu(TrackerMenu::POSITION, 0);
                break;
            case 2:
                queueTrackerMenu(TrackerMenu::MOTION, 0);
                break;
            case 3:
                queueTrackerMenu(TrackerMenu::PARK_POWER, 0);
                break;
            case 4:
                queueTrackerMenu(TrackerMenu::BLUETOOTH, 0);
                break;
            case 5:
                queueTrackerMenu(TrackerMenu::DIAG_LOG, 0);
                break;
            case 6:
                queueTrackerMenu(TrackerMenu::SYSTEM, 0);
                break;
            case 7:
                queueTrackerMenu(TrackerMenu::WLAN_SERVICE, 0);
                break;
'''
        new_cases = '''            case 1:
                queueTrackerMenu(TrackerMenu::ACCESS, 0);
                break;
            case 2:
                queueTrackerMenu(TrackerMenu::POSITION, 0);
                break;
            case 3:
                queueTrackerMenu(TrackerMenu::MOTION, 0);
                break;
            case 4:
                queueTrackerMenu(TrackerMenu::PARK_POWER, 0);
                break;
            case 5:
                queueTrackerMenu(TrackerMenu::BLUETOOTH, 0);
                break;
            case 6:
                queueTrackerMenu(TrackerMenu::DIAG_LOG, 0);
                break;
            case 7:
                queueTrackerMenu(TrackerMenu::SYSTEM, 0);
                break;
            case 8:
                queueTrackerMenu(TrackerMenu::WLAN_SERVICE, 0);
                break;
'''
        text = replace_once(text, old_cases, new_cases, "tracker root cases")

    if "case TrackerMenu::ACCESS" not in text:
        anchor = "    case TrackerMenu::POSITION: {\n"
        cases = r'''    case TrackerMenu::ACCESS: {
        static char rfLine[40], alertLine[40], sessionLine[40];
        static const char *opts[] = {"Back", rfLine, alertLine, sessionLine, "Admin jetzt sperren"};
        snprintf(rfLine, sizeof(rfLine), "Funkprofil: %s", jarnsenRfProfileName());
        snprintf(alertLine, sizeof(alertLine), "Vollsperren-Alarm: %s", jarnsenLockAlertEnabled() ? "ON" : "OFF");
        snprintf(sessionLine, sizeof(sessionLine), "Freigabe: %us", (unsigned)jarnsenAccessRemainingSecs());
        showTrackerOptions("Sicherheit / Funk", opts, 5, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::ROOT, trackerRootSelection);
            else if (selected == 1) queueTrackerMenu(TrackerMenu::RF_PROFILE, 0);
            else if (selected == 2) {
                jarnsenSetLockAlertEnabled(!jarnsenLockAlertEnabled());
                queueTrackerMenu(TrackerMenu::ACCESS, 2);
            } else if (selected == 3) queueTrackerMenu(TrackerMenu::ACCESS, 3);
            else if (selected == 4) {
                jarnsenAccessLockAdmin();
                showTrackerAccessPin();
            }
        });
        break;
    }

    case TrackerMenu::RF_PROFILE: {
        static char aLine[40], bLine[40];
        static const char *opts[] = {"Back", "Standard", aLine, bLine};
        snprintf(aLine, sizeof(aLine), "Jarnsen A: %s", jarnsenRfProfileAvailable(JarnsenRfProfile::AUTH_A) ? "BEREIT" : "NICHT FREIGEGEBEN");
        snprintf(bLine, sizeof(bLine), "Jarnsen B: %s", jarnsenRfProfileAvailable(JarnsenRfProfile::AUTH_B) ? "BEREIT" : "NICHT FREIGEGEBEN");
        showTrackerOptions("Funkprofil", opts, 4, initialSelection, [](int selected) {
            if (selected == 0) queueTrackerMenu(TrackerMenu::ACCESS, 1);
            else {
                const JarnsenRfProfile p = selected == 1 ? JarnsenRfProfile::STANDARD :
                                           (selected == 2 ? JarnsenRfProfile::AUTH_A : JarnsenRfProfile::AUTH_B);
                jarnsenSetRfProfile(p);
                queueTrackerMenu(TrackerMenu::RF_PROFILE, selected);
            }
        });
        break;
    }

'''
        text = replace_once(text, anchor, cases + anchor, "tracker access cases")

    old_open = '''void trackerServiceMenuOpen()
{
    if (!trackerUiRoleEnabled() || !trackerServicePageVisible())
        return;
    trackerServiceMenuMode = true;
    trackerRootSelection = 0;
    queueTrackerMenu(TrackerMenu::ROOT, trackerRootSelection);
}
'''
    new_open = '''void trackerServiceMenuOpen()
{
    if (!trackerUiRoleEnabled() || !screen)
        return;
    if (!jarnsenFullLocked() && !trackerServicePageVisible())
        return;
    trackerServiceMenuMode = true;
    trackerRootSelection = 0;
    if (!jarnsenAccessAdminUnlocked()) {
        showTrackerAccessPin();
        return;
    }
    queueTrackerMenu(TrackerMenu::ROOT, trackerRootSelection);
}
'''
    if "!jarnsenFullLocked() && !trackerServicePageVisible()" not in text:
        text = replace_once(text, old_open, new_open, "tracker protected open")

    pump_anchor = '''void trackerServiceMenuPump()
{
    if (!trackerServiceMenuMode)
        return;

'''
    if "notificationTypeEnum::number_picker" not in text[text.find("void trackerServiceMenuPump"):text.find("void trackerServiceMenuClose")]:
        pump_new = pump_anchor + '''    if (!jarnsenAccessAdminUnlocked()) {
        if (!screen || graphics::NotificationRenderer::current_notification_type != graphics::notificationTypeEnum::number_picker)
            showTrackerAccessPin();
        return;
    }

'''
        text = replace_once(text, pump_anchor, pump_new, "tracker PIN timeout")
    menu.write_text(text, encoding="utf-8")


def patch_v3() -> None:
    policy = ROOT / "src/infrastructure/HeltecV3RepeaterPolicy.cpp"
    text = policy.read_text(encoding="utf-8")
    if '#include "infrastructure/JarnsenAccessPolicy.h"' not in text:
        text = replace_once(text, '#include "infrastructure/JarnsenV3MeshPolicy.h"\n',
                            '#include "infrastructure/JarnsenV3MeshPolicy.h"\n#include "infrastructure/JarnsenAccessPolicy.h"\n', "v3 access include")
    if "jarnsenAccessTick();" not in text:
        text = replace_once(text, '        jarnsenV3MeshPolicyEnforce();\n        heltecV3PowerMonitorTick',
                            '        jarnsenV3MeshPolicyEnforce();\n        jarnsenAccessTick();\n        heltecV3PowerMonitorTick', "v3 access tick")
    if "jarnsenButtonSuppress" not in text:
        pressed_anchor = '        const bool pressed = digitalRead(BUTTON_PIN) == LOW;\n'
        text = replace_once(text, pressed_anchor, pressed_anchor +
                            '        const bool jarnsenButtonSuppress = jarnsenAccessButtonSample(pressed, now, heltecV3ServiceMenuActive());\n',
                            "v3 button sample")
        text = replace_once(text,
                            '        if (v3ButtonWasPressed && pressed && !v3OpenedServiceThisPress && !v3LongPressHandled &&\n',
                            '        if (v3ButtonWasPressed && pressed && !v3OpenedServiceThisPress && !v3LongPressHandled && !jarnsenButtonSuppress &&\n',
                            "v3 long suppress")
        text = replace_once(text,
                            '            if (!v3OpenedServiceThisPress && !v3LongPressHandled && validTap && actionGuardExpired) {\n',
                            '            if (!v3OpenedServiceThisPress && !v3LongPressHandled && !jarnsenButtonSuppress && validTap && actionGuardExpired) {\n',
                            "v3 short suppress")
        text = replace_once(text,
                            '            if (heltecV3ServiceMenuActive()) {\n                heltecV3ServiceMenuSelect();\n            } else if (heltecV3PositionPageRecentlyVisible()) {\n',
                            '            if (heltecV3ServiceMenuActive()) {\n                heltecV3ServiceMenuSelect();\n            } else if (jarnsenFullLocked()) {\n                heltecV3ServiceMenuOpen();\n            } else if (heltecV3PositionPageRecentlyVisible()) {\n',
                            "v3 locked PIN long")
    policy.write_text(text, encoding="utf-8")

    menu = ROOT / "src/infrastructure/HeltecV3ServicePage.cpp"
    text = menu.read_text(encoding="utf-8")
    if '#include "infrastructure/JarnsenAccessPolicy.h"' not in text:
        text = replace_once(text, '#include "infrastructure/JarnsenV3MeshPolicy.h"\n',
                            '#include "infrastructure/JarnsenV3MeshPolicy.h"\n#include "infrastructure/JarnsenAccessPolicy.h"\n', "v3 menu access include")
    if "RF_PROFILE" not in text:
        old = 'enum class V3ServiceMenu : uint8_t { NONE = 0, ROOT, MESH_SETTINGS, POWER_STATS, DIAG_LOG, EXPORT_CONFIRM, CLEAR_CONFIRM, WLAN_SERVICE };'
        new = 'enum class V3ServiceMenu : uint8_t { NONE = 0, ROOT, ACCESS, RF_PROFILE, MESH_SETTINGS, POWER_STATS, DIAG_LOG, EXPORT_CONFIRM, CLEAR_CONFIRM, WLAN_SERVICE };'
        text = replace_once(text, old, new, "v3 access enum")

    if "showV3AccessPin" not in text:
        anchor = "void showMenu(V3ServiceMenu menu)\n"
        helper = r'''void showV3AccessPin()
{
    if (!screen || !menuActive)
        return;
    currentMenu = V3ServiceMenu::NONE;
    pendingMenu = V3ServiceMenu::NONE;
    screen->showNumberPicker("PIN", 0, 6, false, [](uint32_t pin) {
        const bool ok = jarnsenFullLocked() ? jarnsenUnlockFull(pin) : jarnsenAccessUnlock(pin);
        if (ok)
            queueMenu(V3ServiceMenu::ROOT);
        else
            showV3AccessPin();
    });
}

void showMenu(V3ServiceMenu menu)
'''
        text = replace_once(text, anchor, helper, "v3 PIN helper")

    old_root = '''        static const char *options[] = {"Back", "Mesh Settings", "Power Statistics", "Diagnostic Log", "WLAN Service"};
        showOptions("V3 Service", options, 5, [](int selected) {
            switch (selected) {
            case 0: queueAction(V3MenuAction::CLOSE); break;
            case 1: queueMenu(V3ServiceMenu::MESH_SETTINGS); break;
            case 2: queueMenu(V3ServiceMenu::POWER_STATS); break;
            case 3: queueMenu(V3ServiceMenu::DIAG_LOG); break;
            case 4: queueMenu(V3ServiceMenu::WLAN_SERVICE); break;
            default: break;
            }
        });
'''
    new_root = '''        static const char *options[] = {"Back", "Sicherheit / Funk", "Mesh Settings", "Power Statistics", "Diagnostic Log", "WLAN Service"};
        showOptions("V3 Service", options, 6, [](int selected) {
            switch (selected) {
            case 0: queueAction(V3MenuAction::CLOSE); break;
            case 1: queueMenu(V3ServiceMenu::ACCESS); break;
            case 2: queueMenu(V3ServiceMenu::MESH_SETTINGS); break;
            case 3: queueMenu(V3ServiceMenu::POWER_STATS); break;
            case 4: queueMenu(V3ServiceMenu::DIAG_LOG); break;
            case 5: queueMenu(V3ServiceMenu::WLAN_SERVICE); break;
            default: break;
            }
        });
'''
    if '"Sicherheit / Funk"' not in text:
        text = replace_once(text, old_root, new_root, "v3 root access")

    if "case V3ServiceMenu::ACCESS" not in text:
        anchor = "    case V3ServiceMenu::MESH_SETTINGS: {\n"
        cases = r'''    case V3ServiceMenu::ACCESS: {
        static char rfLine[40], alertLine[40], sessionLine[40];
        static const char *options[] = {"Back", rfLine, alertLine, sessionLine, "Admin jetzt sperren"};
        snprintf(rfLine, sizeof(rfLine), "Funkprofil: %s", jarnsenRfProfileName());
        snprintf(alertLine, sizeof(alertLine), "Vollsperren-Alarm: %s", jarnsenLockAlertEnabled() ? "ON" : "OFF");
        snprintf(sessionLine, sizeof(sessionLine), "Freigabe: %us", (unsigned)jarnsenAccessRemainingSecs());
        showOptions("Sicherheit / Funk", options, 5, [](int selected) {
            if (selected == 0) queueMenu(V3ServiceMenu::ROOT);
            else if (selected == 1) queueMenu(V3ServiceMenu::RF_PROFILE);
            else if (selected == 2) {
                jarnsenSetLockAlertEnabled(!jarnsenLockAlertEnabled());
                queueMenu(V3ServiceMenu::ACCESS);
            } else if (selected == 3) queueMenu(V3ServiceMenu::ACCESS);
            else if (selected == 4) {
                jarnsenAccessLockAdmin();
                showV3AccessPin();
            }
        });
        break;
    }
    case V3ServiceMenu::RF_PROFILE: {
        static char aLine[40], bLine[40];
        static const char *options[] = {"Back", "Standard", aLine, bLine};
        snprintf(aLine, sizeof(aLine), "Jarnsen A: %s", jarnsenRfProfileAvailable(JarnsenRfProfile::AUTH_A) ? "BEREIT" : "NICHT FREIGEGEBEN");
        snprintf(bLine, sizeof(bLine), "Jarnsen B: %s", jarnsenRfProfileAvailable(JarnsenRfProfile::AUTH_B) ? "BEREIT" : "NICHT FREIGEGEBEN");
        showOptions("Funkprofil", options, 4, [](int selected) {
            if (selected == 0) queueMenu(V3ServiceMenu::ACCESS);
            else {
                const JarnsenRfProfile p = selected == 1 ? JarnsenRfProfile::STANDARD :
                                           (selected == 2 ? JarnsenRfProfile::AUTH_A : JarnsenRfProfile::AUTH_B);
                jarnsenSetRfProfile(p);
                queueMenu(V3ServiceMenu::RF_PROFILE);
            }
        });
        break;
    }
'''
        text = replace_once(text, anchor, cases + anchor, "v3 access cases")

    old_open = '''void heltecV3ServiceMenuOpen()
{
    if (!roleEnabled() || !screen)
        return;

    menuActive = true;
    currentMenu = V3ServiceMenu::ROOT;
'''
    new_open = '''void heltecV3ServiceMenuOpen()
{
    if (!roleEnabled() || !screen)
        return;

    menuActive = true;
    if (!jarnsenAccessAdminUnlocked()) {
        currentMenu = V3ServiceMenu::NONE;
        pendingMenu = V3ServiceMenu::NONE;
        pendingAction = V3MenuAction::NONE;
        overlayRequestPending = false;
        menuNeedsReopen = false;
        showV3AccessPin();
        return;
    }
    currentMenu = V3ServiceMenu::ROOT;
'''
    if "if (!jarnsenAccessAdminUnlocked())" not in text[text.find("void heltecV3ServiceMenuOpen"):text.find("void heltecV3ServiceMenuNext")]:
        text = replace_once(text, old_open, new_open, "v3 protected open")

    # Number picker receives the same one-button next/select events as selection picker.
    text = text.replace(
        'graphics::NotificationRenderer::current_notification_type != graphics::notificationTypeEnum::selection_picker)\n        return;',
        '(graphics::NotificationRenderer::current_notification_type != graphics::notificationTypeEnum::selection_picker &&\n         graphics::NotificationRenderer::current_notification_type != graphics::notificationTypeEnum::number_picker))\n        return;')

    pump_anchor = '''    const auto type = graphics::NotificationRenderer::current_notification_type;
    if (type == graphics::notificationTypeEnum::pairing_pin) {
'''
    if "type == graphics::notificationTypeEnum::number_picker" not in text[text.find("void heltecV3ServiceMenuPump"):text.find("void heltecV3ServiceMenuClose")]:
        pump_new = '''    const auto type = graphics::NotificationRenderer::current_notification_type;
    if (!jarnsenAccessAdminUnlocked()) {
        if (type != graphics::notificationTypeEnum::number_picker)
            showV3AccessPin();
        return;
    }
    if (type == graphics::notificationTypeEnum::pairing_pin) {
'''
        text = replace_once(text, pump_anchor, pump_new, "v3 PIN timeout")
    menu.write_text(text, encoding="utf-8")


patch_screen()
if TRACKER:
    patch_tracker()
else:
    patch_v3()
patch_diag_tool_command()

for required in (
    HEADER,
    CPP,
    ROOT / "src/graphics/Screen.cpp",
    ROOT / ("src/vehicle/TrackerCommonPolicy.cpp" if TRACKER else "src/infrastructure/HeltecV3RepeaterPolicy.cpp"),
):
    if not required.exists():
        raise SystemExit(f"missing access output: {required}")

print(f"Jarnsen access/full-lock/RF integration applied for {'Tracker V1.1' if TRACKER else 'Heltec V3'}")
