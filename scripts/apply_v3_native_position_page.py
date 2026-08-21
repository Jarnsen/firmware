from pathlib import Path

POLICY_PATH = Path("src/infrastructure/HeltecV3RepeaterPolicy.cpp")
PHONE_API_PATH = Path("src/mesh/PhoneAPI.cpp")

policy = POLICY_PATH.read_text()
phone_api = PHONE_API_PATH.read_text()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"{label}: already applied")
        return text
    if old not in text:
        raise SystemExit(f"{label}: anchor not found")
    print(f"{label}: applied")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# PhoneAPI: capture POSITION_APP while it is still the untouched phone payload.
# This runs after the normal authorization gate but before handleToRadioPacket(),
# Router and PositionModule. No transport/from heuristics are needed here.
# ---------------------------------------------------------------------------
phone_api = replace_once(
    phone_api,
    '#include "TypeConversions.h"\n#include "concurrency/LockGuard.h"\n',
    '#include "TypeConversions.h"\n#ifdef _VARIANT_HELTEC_V3\n#include "infrastructure/HeltecV3PositionPage.h"\n#endif\n#include "concurrency/LockGuard.h"\n',
    "include V3 native position interface in PhoneAPI",
)

phone_api = replace_once(
    phone_api,
    """#endif\n            return handleToRadioPacket(toRadioScratch.packet);\n        case meshtastic_ToRadio_want_config_id_tag:\n""",
    """#endif\n#ifdef _VARIANT_HELTEC_V3\n            // At this point the BLE/API client has passed the same authorization\n            // gate as every other ToRadio packet. Copy the phone GPS fix before\n            // Router/PositionModule fixed-position handling can strip/replace it.\n            if (toRadioScratch.packet.which_payload_variant == meshtastic_MeshPacket_decoded_tag &&\n                toRadioScratch.packet.decoded.portnum == meshtastic_PortNum_POSITION_APP) {\n                meshtastic_Position v3PhonePosition = meshtastic_Position_init_default;\n                if (pb_decode_from_bytes(toRadioScratch.packet.decoded.payload.bytes,\n                                         toRadioScratch.packet.decoded.payload.size,\n                                         &meshtastic_Position_msg, &v3PhonePosition)) {\n                    heltecV3CapturePhonePosition(v3PhonePosition);\n                } else {\n                    LOG_WARN(\"Heltec V3 phone GPS: malformed POSITION_APP payload ignored\");\n                }\n            }\n#endif\n            return handleToRadioPacket(toRadioScratch.packet);\n        case meshtastic_ToRadio_want_config_id_tag:\n""",
    "capture authorized V3 phone GPS before Router",
)

# ---------------------------------------------------------------------------
# V3 policy: retain all distance/quality/auto-save policy here. The native
# MeshModule page is only a renderer/navigation target and never owns GPS logic.
# ---------------------------------------------------------------------------
policy = replace_once(
    policy,
    '#include "graphics/draw/NotificationRenderer.h"\n#include "main.h"\n',
    '#include "graphics/draw/NotificationRenderer.h"\n#include "infrastructure/HeltecV3PositionPage.h"\n#include "main.h"\n',
    "include V3 native position page interface",
)

policy = replace_once(
    policy,
    "static bool v3LastPositionBroadcastSent = false;\n",
    "static bool v3LastPositionBroadcastSent = false;\nstatic uint32_t v3LastSavedAtMs = 0;\n",
    "track V3 position save timestamp",
)

policy = replace_once(
    policy,
    """    v3LastSaveWasAutomatic = automatic;\n    v3LastPositionBroadcastSent = meshSent;\n    v3ResetAutoConfirmation();\n""",
    """    v3LastSaveWasAutomatic = automatic;\n    v3LastPositionBroadcastSent = meshSent;\n    v3LastSavedAtMs = millis() ? millis() : 1;\n    v3ResetAutoConfirmation();\n""",
    "timestamp manual/automatic V3 position save",
)

policy = replace_once(
    policy,
    """    showV3PositionSaved(automatic, differenceM, meshSent);\n    return true;\n}\n\nstatic void v3ProcessPhonePosition\n""",
    """    // The native Meshtastic position page redraws from policy state; do\n    // not open an alert/exclusive screen when a position is saved.\n    heltecV3PositionPageRefresh();\n    return true;\n}\n\nstatic void v3ProcessPhonePosition\n""",
    "stop using exclusive saved-position alert",
)

# Refresh the native page at every normal early-return point in the position
# policy. These replacements are deliberately narrow to the repeated legacy UI
# tail used inside v3ProcessPhonePosition().
legacy_return = """        if (v3ServicePage == V3_PAGE_POSITION)\n            showV3ServicePage();\n        return;\n"""
native_return = """        heltecV3PositionPageRefresh();\n        return;\n"""
return_count = policy.count(legacy_return)
if return_count < 3:
    raise SystemExit(f"native V3 position refresh: expected >=3 legacy return anchors, found {return_count}")
policy = policy.replace(legacy_return, native_return)
print(f"native V3 position refresh: replaced {return_count} early-return UI tails")

policy = replace_once(
    policy,
    """    if (v3ServicePage == V3_PAGE_POSITION)\n        showV3ServicePage();\n}\n\nstatic void startV3ServiceMode()\n""",
    """    heltecV3PositionPageRefresh();\n}\n\nvoid heltecV3CapturePhonePosition(const meshtastic_Position &position)\n{\n    if (!v3RepeaterRoleEnabled() || !v3ServiceActive)\n        return;\n\n    portENTER_CRITICAL(&v3PositionMux);\n    v3PendingPhonePosition = position;\n    v3PhonePositionPending = true;\n    portEXIT_CRITICAL(&v3PositionMux);\n\n    LOG_INFO(\"Heltec V3 phone GPS captured pre-router: lat=%d lon=%d acc=%umm time=%u\",\n             position.latitude_i, position.longitude_i, (unsigned)position.gps_accuracy,\n             (unsigned)position.time);\n\n    if (v3ServiceTaskHandle)\n        xTaskNotifyGive(v3ServiceTaskHandle);\n}\n\nbool heltecV3GetPositionUiState(HeltecV3PositionUiState &out)\n{\n    out = HeltecV3PositionUiState{};\n    if (!v3RepeaterRoleEnabled())\n        return false;\n\n    out.serviceActive = v3ServiceActive;\n    out.phoneFresh = v3LatestPhoneFixFresh;\n    out.phoneAccurate = v3LatestPhoneFixAccurate;\n    out.differenceM = v3LatestPhoneDifferenceM;\n    out.accuracyMm = v3LatestPhoneAccuracyMm;\n    out.autoConfirmCount = v3AutoConfirmCount;\n    out.autoConfirmRequired = V3_POSITION_CONFIRM_COUNT;\n    out.ignoreDistanceM = V3_POSITION_IGNORE_METERS;\n    out.autoDistanceM = V3_POSITION_AUTO_METERS;\n\n    meshtastic_Position saved = meshtastic_Position_init_default;\n    out.haveSavedPosition = v3LoadSavedPosition(saved);\n    if (out.haveSavedPosition) {\n        out.savedLatitudeI = saved.latitude_i;\n        out.savedLongitudeI = saved.longitude_i;\n    }\n\n    meshtastic_Position phone = meshtastic_Position_init_default;\n    portENTER_CRITICAL(&v3PositionMux);\n    phone = v3PendingPhonePosition;\n    portEXIT_CRITICAL(&v3PositionMux);\n\n    out.havePhonePosition = v3LatestPhonePositionReceivedMs != 0 && v3PhoneFixHasCoordinates(phone);\n    if (out.havePhonePosition) {\n        out.phoneLatitudeI = phone.latitude_i;\n        out.phoneLongitudeI = phone.longitude_i;\n\n        const uint32_t nowEpoch = getValidTime(RTCQualityFromNet);\n        if (phone.time != 0 && nowEpoch != 0)\n            out.phoneAgeSecs = nowEpoch >= phone.time ? nowEpoch - phone.time : phone.time - nowEpoch;\n        else if (millis() >= v3LatestPhonePositionReceivedMs)\n            out.phoneAgeSecs = (millis() - v3LatestPhonePositionReceivedMs) / 1000UL;\n    }\n\n    out.lastSaveValid = v3LastSavedAtMs != 0;\n    out.lastSaveAutomatic = v3LastSaveWasAutomatic;\n    out.lastSaveMeshSent = v3LastPositionBroadcastSent;\n    out.lastSavedDifferenceM = v3LastSavedDifferenceM;\n    if (out.lastSaveValid)\n        out.lastSaveAgeMs = (uint32_t)(millis() - v3LastSavedAtMs);\n\n    return true;\n}\n\nbool heltecV3ManualSaveLatestPosition()\n{\n    if (!v3RepeaterRoleEnabled() || !v3ServiceActive || !v3LatestGoodPhonePositionValid)\n        return false;\n\n    meshtastic_Position saved = meshtastic_Position_init_default;\n    const uint32_t differenceM =\n        v3LoadSavedPosition(saved) ? v3DistanceMeters(saved, v3LatestGoodPhonePosition) : 0U;\n    return v3SavePosition(v3LatestGoodPhonePosition, false, differenceM);\n}\n\nstatic void startV3ServiceMode()\n""",
    "export V3 phone capture and native UI policy state",
)

# The first GPIO0 press opens BT/display and focuses our normal MeshModule frame.
# No startAlert(), no exclusive frame reassertion, no custom two-page UI.
policy = replace_once(
    policy,
    """    v3ServiceLastActivityMs = now;\n    showV3ServicePage();\n}\n\nstatic void stopV3ServiceMode()\n""",
    """    v3ServiceLastActivityMs = now;\n    v3DisplayStartedMs = now;\n    v3DisplayVisible = true;\n    if (screen && !screen->isScreenOn())\n        screen->setOn(true);\n    heltecV3PositionPageRequestFocus();\n}\n\nstatic void stopV3ServiceMode()\n""",
    "focus native V3 position page when service opens",
)

# If the display timed out while the 120s BLE service remains alive, the first
# next press only wakes/focuses the position page. Its release must not advance.
policy = replace_once(
    policy,
    """            v3LongPressHandled = false;\n        }\n#endif\n\n        if (!v3ServiceActive) {\n""",
    """            v3LongPressHandled = false;\n\n            if (!v3DisplayVisible || (screen && !screen->isScreenOn())) {\n                v3DisplayStartedMs = now;\n                v3DisplayVisible = true;\n                if (screen && !screen->isScreenOn())\n                    screen->setOn(true);\n                heltecV3PositionPageRequestFocus();\n                v3OpenedServiceThisPress = true;\n            }\n        }\n#endif\n\n        if (!v3ServiceActive) {\n""",
    "wake native V3 position page after display timeout",
)

policy = replace_once(
    policy,
    """            v3HandleLongPress();\n            v3LongPressHandled = true;\n            v3ServiceLastActivityMs = now;\n""",
    """            if (heltecV3PositionPageRecentlyVisible()) {\n                heltecV3ManualSaveLatestPosition();\n                heltecV3PositionPageRefresh();\n            }\n            v3LongPressHandled = true;\n            v3ServiceLastActivityMs = now;\n""",
    "long press saves only from native V3 position page",
)

policy = replace_once(
    policy,
    """                v3ServicePage = (uint8_t)((v3ServicePage + 1U) % V3_PAGE_COUNT);\n                showV3ServicePage();\n                v3ServiceLastActivityMs = now;\n""",
    """                if (screen) {\n                    screen->showNextFrame();\n                    screen->runNow();\n                }\n                v3DisplayStartedMs = now;\n                v3DisplayVisible = true;\n                v3ServiceLastActivityMs = now;\n""",
    "short press navigates normal Meshtastic pages",
)

policy = replace_once(
    policy,
    """        const uint32_t frameNow = millis();\n        if (v3DisplayVisible &&\n            (v3LastFrameAssertMs == 0 ||\n             (uint32_t)(frameNow - v3LastFrameAssertMs) >= (uint32_t)V3_SERVICE_FRAME_REASSERT_MS))\n            v3AssertExclusiveServiceFrame();\n\n        const uint32_t displayNow = millis();\n""",
    """        // Native MeshModule frames are owned/redrawn by Screen itself. Do not\n        // reassert an alert frame from this service task.\n        const uint32_t displayNow = millis();\n""",
    "remove exclusive V3 frame reassertion",
)

POLICY_PATH.write_text(policy)
PHONE_API_PATH.write_text(phone_api)
print("V3 native MGRS position page ready: normal MeshModule frame + pre-router phone GPS + 25/50m save policy")
