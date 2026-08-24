#include "configuration.h"

#ifdef _VARIANT_HELTEC_V3

#include "MeshService.h"
#include "NodeDB.h"
#include "PositionPrecision.h"
#include "PowerFSM.h"
#include "PowerStatus.h"
#include "ProtobufModule.h"
#include "TypeConversions.h"
#include "gps/RTC.h"
#include "graphics/Screen.h"
#include "graphics/ScreenFonts.h"
#include "graphics/draw/NotificationRenderer.h"
#include "infrastructure/HeltecV3DiagnosticLog.h"
#include "infrastructure/HeltecV3MeshMonitor.h"
#include "infrastructure/HeltecV3MeshPages.h"
#include "infrastructure/HeltecV3PositionPage.h"
#include "infrastructure/HeltecV3PowerMonitor.h"
#include "infrastructure/HeltecV3Runtime.h"
#include "infrastructure/HeltecV3ServicePage.h"
#include "main.h"
#include "sleep.h"
#include "target_specific.h"

#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
#include "nimble/NimbleBluetooth.h"
#endif

#include <cmath>
#include <cstdio>
#include <cstring>
#include <driver/gpio.h>
#include <esp_sleep.h>
#include <esp_system.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

#ifndef V3_SERVICE_IDLE_MS
#define V3_SERVICE_IDLE_MS (120UL * 1000UL)
#endif
#ifndef V3_SERVICE_MAX_MS
#define V3_SERVICE_MAX_MS (15UL * 60UL * 1000UL)
#endif
#ifndef V3_SERVICE_CONNECT_GRACE_MS
#define V3_SERVICE_CONNECT_GRACE_MS (60UL * 1000UL)
#endif
#ifndef V3_SERVICE_ACTIVITY_WINDOW_MS
#define V3_SERVICE_ACTIVITY_WINDOW_MS (10UL * 1000UL)
#endif
#ifndef V3_SERVICE_ACTIVITY_THRESHOLD
#define V3_SERVICE_ACTIVITY_THRESHOLD 3U
#endif
#ifndef V3_SERVICE_DISPLAY_MS
#define V3_SERVICE_DISPLAY_MS (20UL * 1000UL)
#endif
#ifndef V3_SERVICE_DEBOUNCE_MS
#define V3_SERVICE_DEBOUNCE_MS 250UL
#endif
#ifndef V3_SERVICE_LONG_PRESS_MS
#define V3_SERVICE_LONG_PRESS_MS 1200UL
#endif
#ifndef V3_SERVICE_FRAME_REASSERT_MS
#define V3_SERVICE_FRAME_REASSERT_MS 1000UL
#endif
#ifndef V3_POSITION_GOOD_ACCURACY_MM
#define V3_POSITION_GOOD_ACCURACY_MM 20000UL
#endif
#ifndef V3_POSITION_FRESH_SECS
#define V3_POSITION_FRESH_SECS 180UL
#endif
#ifndef V3_POSITION_IGNORE_METERS
#define V3_POSITION_IGNORE_METERS 25U
#endif
#ifndef V3_POSITION_AUTO_METERS
#define V3_POSITION_AUTO_METERS 50U
#endif
#ifndef V3_POSITION_CONFIRM_COUNT
#define V3_POSITION_CONFIRM_COUNT 3U
#endif
#ifndef V3_POSITION_CONFIRM_WINDOW_MS
#define V3_POSITION_CONFIRM_WINDOW_MS (15UL * 1000UL)
#endif
#ifndef V3_POSITION_CONFIRM_SPACING_MS
#define V3_POSITION_CONFIRM_SPACING_MS 1000UL
#endif
#ifndef V3_POSITION_CONFIRM_CLUSTER_METERS
#define V3_POSITION_CONFIRM_CLUSTER_METERS 25U
#endif

enum V3ServicePage : uint8_t {
    V3_PAGE_STATUS = 0,
    V3_PAGE_POSITION,
    V3_PAGE_COUNT,
};

static TaskHandle_t v3ServiceTaskHandle = nullptr;
static volatile bool v3ServiceButtonEvent = false;
static bool v3ServiceActive = false;
static uint32_t v3ServiceStartedMs = 0;
static uint32_t v3ServiceLastActivityMs = 0;
static uint32_t v3DisplayStartedMs = 0;
static uint32_t v3LastFrameAssertMs = 0;
static uint32_t v3LastAcceptedButtonMs = 0;
static uint32_t v3ButtonPressedSinceMs = 0;
static bool v3ButtonWasPressed = false;
static bool v3ButtonPrevPressed = false;
static bool v3OpenedServiceThisPress = false;
static bool v3LongPressHandled = false;
static bool v3RequireButtonRelease = false;
static uint32_t v3LastPageAdvanceMs = 0;
static uint32_t v3LastBleAdvertisingCheckMs = 0;
static uint32_t v3ConsumedBleDiagUiSequence = 0;
static bool v3UsbMaintenanceActive = false;
static bool v3DisplayVisible = false;
static bool v3PairingDisplayActive = false;
static uint8_t v3ServicePage = V3_PAGE_STATUS;
static char v3ServiceBanner[160];
static bool v3ServiceEverConnected = false;
static uint32_t v3BleTrafficLast = 0;
static uint32_t v3BleActivityWindowStartedMs = 0;
static uint8_t v3BleActivityWindowCount = 0;

static portMUX_TYPE v3PositionMux = portMUX_INITIALIZER_UNLOCKED;
static meshtastic_Position v3PendingPhonePosition = meshtastic_Position_init_default;
static volatile bool v3PhonePositionPending = false;
static meshtastic_Position v3LatestGoodPhonePosition = meshtastic_Position_init_default;
static bool v3LatestGoodPhonePositionValid = false;
static uint32_t v3LatestPhonePositionReceivedMs = 0;
static uint32_t v3LatestPhoneAccuracyMm = 0;
static uint32_t v3LatestPhoneDifferenceM = 0;
static bool v3LatestPhoneFixFresh = false;
static bool v3LatestPhoneFixAccurate = false;
static uint8_t v3AutoConfirmCount = 0;
static uint32_t v3AutoConfirmStartedMs = 0;
static uint32_t v3AutoConfirmLastMs = 0;
static meshtastic_Position v3AutoConfirmAnchor = meshtastic_Position_init_default;
static bool v3AutoConfirmAnchorValid = false;
static uint32_t v3LastSavedDifferenceM = 0;
static bool v3LastSaveWasAutomatic = false;
static bool v3LastPositionBroadcastSent = false;
static uint32_t v3LastSavedAtMs = 0;

static bool v3RepeaterRoleEnabled()
{
    return config.device.role == meshtastic_Config_DeviceConfig_Role_ROUTER_LATE ||
           config.device.role == meshtastic_Config_DeviceConfig_Role_REPEATER;
}

// The V3 repeater policy owns BLE/display for the entire lifetime of this role,
// not only while service is open. This prevents the generic PowerFSM from
// briefly showing the stock Meshtastic UI or starting BLE between our
// idle-policy events.
bool heltecV3ServiceOwnsPeripherals()
{
    return v3RepeaterRoleEnabled();
}

static uint32_t repeaterHealthIntervalSecs()
{
    if (!nodeDB)
        return 3600UL;
    uint32_t x = nodeDB->getNodeNum();
    x ^= x >> 16;
    x *= 0x7feb352dU;
    x ^= x >> 15;
    return 3300UL + (x % 301U);
}

static bool v3BleConnected()
{
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
    return nimbleBluetooth && nimbleBluetooth->isConnected();
#else
    return false;
#endif
}

static bool v3BleAdvertisingActive()
{
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
    return nimbleBluetooth && nimbleBluetooth->isAdvertisingActive();
#else
    return false;
#endif
}

static uint32_t v3BleMeaningfulTrafficCount()
{
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
    return nimbleBluetooth ? nimbleBluetooth->getMeaningfulTrafficCount() : 0U;
#else
    return 0U;
#endif
}

static bool v3NativeSerialConnected()
{
#if defined(ARDUINO_USB_CDC_ON_BOOT) && ARDUINO_USB_CDC_ON_BOOT
    return (bool)Serial;
#else
    return false;
#endif
}

static void v3UpdateUsbMaintenance()
{
    const bool connected = v3NativeSerialConnected();
    if (connected == v3UsbMaintenanceActive)
        return;
    v3UsbMaintenanceActive = connected;
    heltecV3DiagLog("USB_MAINT", "active=%u", connected ? 1U : 0U);
    LOG_INFO("Heltec V3 USB maintenance: %s", connected ? "active; light sleep vetoed" : "closed; normal light sleep restored");
}

bool heltecV3RuntimeRoleEnabled()
{
    return v3RepeaterRoleEnabled();
}

bool heltecV3RuntimeServiceActive()
{
    return v3RepeaterRoleEnabled() && v3ServiceActive;
}

void heltecV3RuntimeSetPairingDisplay(bool active)
{
    v3PairingDisplayActive = active;
    if (active && v3ServiceActive) {
        v3DisplayStartedMs = millis() ? millis() : 1;
        v3DisplayVisible = true;
        if (screen && !screen->isScreenOn())
            screen->setOn(true);
        if (screen)
            screen->runNow();
    }
}

bool heltecV3RuntimeUsbMaintenanceActive()
{
    return v3RepeaterRoleEnabled() && v3UsbMaintenanceActive;
}

const char *heltecV3RuntimeStateText()
{
    if (!v3RepeaterRoleEnabled())
        return "OFF";
    if (v3ServiceActive)
        return "SERVICE";
    if (v3UsbMaintenanceActive)
        return "MAINT";
    return "LISTEN";
}

const char *heltecV3RuntimeBleStateText()
{
    if (!v3RepeaterRoleEnabled())
        return "OFF";
    if (v3BleConnected())
        return "CONNECTED";
    if (v3BleAdvertisingActive())
        return "ADV";
    return "OFF";
}

uint32_t heltecV3RuntimeServiceRemainingSecs()
{
    if (!v3ServiceActive)
        return 0;
    const uint32_t now = millis();
    const uint32_t elapsed = (uint32_t)(now - v3ServiceLastActivityMs);
    return elapsed >= V3_SERVICE_IDLE_MS ? 0U : (V3_SERVICE_IDLE_MS - elapsed + 999U) / 1000U;
}

static void v3BluetoothOnNow()
{
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
    if (!nimbleBluetooth || !nimbleBluetooth->isActive()) {
        LOG_INFO("Heltec V3 service: initialize BLE");
        setBluetoothEnable(true);
    } else if (nimbleBluetooth->isAdvertisingSuppressed()) {
        LOG_INFO("Heltec V3 service: resume BLE advertising");
        nimbleBluetooth->startAdvertising();
    }
#endif
}

static void v3BluetoothOffNow()
{
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
    if (nimbleBluetooth && nimbleBluetooth->isActive() && !nimbleBluetooth->isAdvertisingSuppressed()) {
        LOG_DEBUG("Heltec V3 service: park BLE advertising outside service window");
        nimbleBluetooth->stopAdvertisingForService();
    }
#endif
}

static void v3ForceIdlePeripheralsOff()
{
    if (v3ServiceActive)
        return;
    if (screen && screen->isScreenOn())
        screen->setOn(false);
    v3BluetoothOffNow();
}

static uint32_t v3DistanceMeters(const meshtastic_Position &a, const meshtastic_Position &b)
{
    constexpr double DEG_TO_RAD_LOCAL = 0.017453292519943295;
    constexpr double EARTH_RADIUS_M = 6371000.0;
    const double lat1 = ((double)a.latitude_i / 10000000.0) * DEG_TO_RAD_LOCAL;
    const double lat2 = ((double)b.latitude_i / 10000000.0) * DEG_TO_RAD_LOCAL;
    const double dLat = lat2 - lat1;
    const double dLon = (((double)b.longitude_i - (double)a.longitude_i) / 10000000.0) * DEG_TO_RAD_LOCAL;
    const double x = dLon * std::cos((lat1 + lat2) * 0.5);
    const double d = std::sqrt(dLat * dLat + x * x) * EARTH_RADIUS_M;
    return d > 0.0 ? (uint32_t)d : 0U;
}

static bool v3LoadSavedPosition(meshtastic_Position &position)
{
    if (!nodeDB)
        return false;
    meshtastic_PositionLite lite;
    if (nodeDB->copyNodePosition(nodeDB->getNodeNum(), lite) && (lite.latitude_i != 0 || lite.longitude_i != 0)) {
        position = TypeConversions::ConvertToPosition(lite);
        return true;
    }
    if (localPosition.latitude_i != 0 || localPosition.longitude_i != 0) {
        position = localPosition;
        return true;
    }
    return false;
}

static bool v3PhoneFixFresh(const meshtastic_Position &position)
{
    if (position.time == 0)
        return false;
    const uint32_t nowEpoch = getValidTime(RTCQualityFromNet);
    if (nowEpoch == 0)
        return true;
    const uint32_t age = nowEpoch >= position.time ? nowEpoch - position.time : position.time - nowEpoch;
    return age <= V3_POSITION_FRESH_SECS;
}

static bool v3PhoneFixAccurate(const meshtastic_Position &position)
{
    return position.gps_accuracy > 0 && position.gps_accuracy <= V3_POSITION_GOOD_ACCURACY_MM;
}

static bool v3PhoneFixHasCoordinates(const meshtastic_Position &position)
{
    return position.has_latitude_i && position.has_longitude_i && (position.latitude_i != 0 || position.longitude_i != 0);
}

class V3PhonePositionCaptureModule : public ProtobufModule<meshtastic_Position>
{
  public:
    V3PhonePositionCaptureModule()
        : ProtobufModule("v3-phone-position", meshtastic_PortNum_POSITION_APP, &meshtastic_Position_msg)
    {
        loopbackOk = true;
        isPromiscuous = true;
    }

    bool broadcastFixedPosition(const meshtastic_Position &position)
    {
        const uint32_t precision = getPositionPrecisionForChannel(0);
        if (precision == 0) {
            LOG_WARN("Heltec V3 position saved, but primary channel position "
                     "precision is 0; mesh broadcast skipped");
            return false;
        }

        meshtastic_Position outgoing = position;
        outgoing.location_source = meshtastic_Position_LocSource_LOC_MANUAL;
        applyPositionPrecision(outgoing, precision);
        meshtastic_MeshPacket *packet = allocDataProtobuf(outgoing);
        if (!packet)
            return false;
        packet->to = NODENUM_BROADCAST;
        packet->channel = 0;
        service->sendToMesh(packet, RX_SRC_USER);
        return true;
    }

  protected:
    bool handleReceivedProtobuf(const meshtastic_MeshPacket &mp, meshtastic_Position *position) override
    {
        if (!position || !v3ServiceActive)
            return false;
        // Real Meshtastic phone positions are inserted into Router as from=0 +
        // TRANSPORT_INTERNAL on this firmware. Keep TRANSPORT_API as a
        // compatibility path for clients/builds that preserve the API transport
        // marker.
        const bool phoneTransport =
            mp.transport_mechanism == meshtastic_MeshPacket_TransportMechanism_TRANSPORT_API ||
            (mp.transport_mechanism == meshtastic_MeshPacket_TransportMechanism_TRANSPORT_INTERNAL && mp.from == 0);
        const bool phoneSource = isFromUs(&mp) || mp.from == 0;
        if (!phoneSource || !phoneTransport)
            return false;

        // This module is statically constructed before the normal PositionModule
        // is created. Therefore this copy still contains the raw phone GPS fix,
        // before fixed_position handling and channel precision can strip lat/lon.
        portENTER_CRITICAL(&v3PositionMux);
        v3PendingPhonePosition = *position;
        v3PhonePositionPending = true;
        portEXIT_CRITICAL(&v3PositionMux);

        LOG_DEBUG("Heltec V3 raw phone GPS captured: lat=%d lon=%d acc=%umm "
                  "time=%u payload=%u",
                  position->latitude_i, position->longitude_i, (unsigned)position->gps_accuracy, (unsigned)position->time,
                  (unsigned)mp.decoded.payload.size);

        if (v3ServiceTaskHandle)
            xTaskNotifyGive(v3ServiceTaskHandle);
        return false;
    }
};

// Deliberately static/early: MeshModule dispatch is construction-order based.
// PositionModule later mutates local phone packets when fixed_position=true.
// Registering this listener before setup() preserves the original phone fix.
static V3PhonePositionCaptureModule v3PhonePositionCaptureModuleInstance;
static V3PhonePositionCaptureModule *v3PhonePositionCaptureModule = &v3PhonePositionCaptureModuleInstance;

static void v3ResetAutoConfirmation()
{
    v3AutoConfirmCount = 0;
    v3AutoConfirmStartedMs = 0;
    v3AutoConfirmLastMs = 0;
    v3AutoConfirmAnchorValid = false;
}

static void drawV3ServiceFrame(OLEDDisplay *display, OLEDDisplayUiState *state, int16_t, int16_t)
{
    if (!display)
        return;
    display->clear();
    display->setTextAlignment(TEXT_ALIGN_CENTER);

    char text[sizeof(v3ServiceBanner)];
    strncpy(text, v3ServiceBanner, sizeof(text) - 1);
    text[sizeof(text) - 1] = '\0';
    const int16_t centerX = display->getWidth() / 2;
    const char *cursor = text;
    uint8_t lineNo = 0;
    int16_t y = 0;
    while (*cursor && lineNo < 4) {
        const char *newline = strchr(cursor, '\n');
        const size_t len = newline ? (size_t)(newline - cursor) : strlen(cursor);
        char line[64];
        const size_t copyLen = len < sizeof(line) - 1 ? len : sizeof(line) - 1;
        memcpy(line, cursor, copyLen);
        line[copyLen] = '\0';
        if (lineNo == 0) {
            display->setFont(FONT_MEDIUM);
            y = 0;
        } else {
            display->setFont(FONT_SMALL);
            y = 19 + (lineNo - 1) * 13;
        }
        display->drawString(centerX, y, line);
        lineNo++;
        if (!newline)
            break;
        cursor = newline + 1;
    }

    if (graphics::NotificationRenderer::current_notification_type == graphics::notificationTypeEnum::pairing_pin)
        graphics::NotificationRenderer::drawBannercallback(display, state);
}

static void v3AssertExclusiveServiceFrame()
{
    if (!screen || !v3ServiceActive || !v3DisplayVisible)
        return;
    screen->startAlert(drawV3ServiceFrame);
    screen->runNow();
    v3LastFrameAssertMs = millis();
}

static void showV3ServiceFrame()
{
    if (!screen || !v3ServiceActive)
        return;
    v3DisplayStartedMs = millis();
    v3DisplayVisible = true;
    v3LastFrameAssertMs = 0;
    v3AssertExclusiveServiceFrame();
    if (!screen->isScreenOn())
        screen->setOn(true);
    LOG_DEBUG("Heltec V3 service: display window opened");
}

static void showV3ServicePage()
{
    if (!screen || !v3ServiceActive)
        return;

    unsigned battery = 0;
    if (powerStatus && powerStatus->getHasBattery())
        battery = powerStatus->getBatteryChargePercent();
    const char *role = config.device.role == meshtastic_Config_DeviceConfig_Role_ROUTER_LATE ? "ROUTER_LATE" : "REPEATER";
    const uint32_t elapsed = (uint32_t)(millis() - v3ServiceLastActivityMs);
    const uint32_t remainingMs = elapsed >= V3_SERVICE_IDLE_MS ? 0U : V3_SERVICE_IDLE_MS - elapsed;
    const unsigned remaining = (unsigned)(remainingMs / 1000UL);

    if (v3ServicePage == V3_PAGE_STATUS) {
        snprintf(v3ServiceBanner, sizeof(v3ServiceBanner), "V3 SERVICE\n%s BAT %u%%\nBT %us A%u/%u\nSHORT: NEXT", role, battery,
                 remaining, (unsigned)v3BleActivityWindowCount, (unsigned)V3_SERVICE_ACTIVITY_THRESHOLD);
    } else {
        meshtastic_Position saved;
        const bool savedValid = v3LoadSavedPosition(saved);
        if (!v3LatestGoodPhonePositionValid) {
            if (v3LatestPhonePositionReceivedMs == 0)
                snprintf(v3ServiceBanner, sizeof(v3ServiceBanner), "POSITION\nPHONE GPS WAIT\nLONG: SAVE POS");
            else if (!v3LatestPhoneFixFresh)
                snprintf(v3ServiceBanner, sizeof(v3ServiceBanner), "POSITION\nGPS FIX TOO OLD\nLONG: SAVE POS");
            else if (!v3LatestPhoneFixAccurate)
                snprintf(v3ServiceBanner, sizeof(v3ServiceBanner), "POSITION\nGPS ACC %um BAD\nLONG: SAVE POS",
                         (unsigned)(v3LatestPhoneAccuracyMm / 1000UL));
            else
                snprintf(v3ServiceBanner, sizeof(v3ServiceBanner), "POSITION\nGPS WAIT\nLONG: SAVE POS");
        } else if (!savedValid) {
            snprintf(v3ServiceBanner, sizeof(v3ServiceBanner), "POSITION NEW\nGPS OK  ACC %um\nLONG: SAVE POS",
                     (unsigned)(v3LatestPhoneAccuracyMm / 1000UL));
        } else if (v3LatestPhoneDifferenceM <= V3_POSITION_IGNORE_METERS) {
            snprintf(v3ServiceBanner, sizeof(v3ServiceBanner), "POSITION OK\nDIFF %um  ACC %um\nLONG: SAVE POS",
                     (unsigned)v3LatestPhoneDifferenceM, (unsigned)(v3LatestPhoneAccuracyMm / 1000UL));
        } else if (v3LatestPhoneDifferenceM <= V3_POSITION_AUTO_METERS) {
            snprintf(v3ServiceBanner, sizeof(v3ServiceBanner), "POSITION CHECK\nDIFF %um  ACC %um\nLONG: SAVE POS",
                     (unsigned)v3LatestPhoneDifferenceM, (unsigned)(v3LatestPhoneAccuracyMm / 1000UL));
        } else {
            snprintf(v3ServiceBanner, sizeof(v3ServiceBanner), "AUTO UPDATE\nDIFF %um  %u/%u\nLONG: SAVE POS",
                     (unsigned)v3LatestPhoneDifferenceM, (unsigned)v3AutoConfirmCount, (unsigned)V3_POSITION_CONFIRM_COUNT);
        }
    }
    showV3ServiceFrame();
}

static void showV3PositionSaved(bool automatic, uint32_t differenceM, bool meshSent)
{
    if (!screen)
        return;
    snprintf(v3ServiceBanner, sizeof(v3ServiceBanner), "POSITION SAVED\n%s %um\n%s", automatic ? "AUTO" : "MANUAL",
             (unsigned)differenceM, meshSent ? "SENT TO MESH" : "MESH POS OFF");
    showV3ServiceFrame();
}

static bool v3SavePosition(const meshtastic_Position &phonePosition, bool automatic, uint32_t differenceM)
{
    if (!nodeDB || !v3PhoneFixHasCoordinates(phonePosition) || !v3PhoneFixFresh(phonePosition) ||
        !v3PhoneFixAccurate(phonePosition))
        return false;

    meshtastic_Position fixed = phonePosition;
    fixed.location_source = meshtastic_Position_LocSource_LOC_MANUAL;
    fixed.ground_speed = 0;
    fixed.has_ground_speed = false;
    fixed.ground_track = 0;
    fixed.has_ground_track = false;

    config.position.fixed_position = true;
    nodeDB->setLocalPosition(fixed);
    nodeDB->updatePosition(nodeDB->getNodeNum(), fixed);
    nodeDB->saveToDisk(SEGMENT_CONFIG | SEGMENT_NODEDATABASE);

    bool meshSent = false;
    if (v3PhonePositionCaptureModule)
        meshSent = v3PhonePositionCaptureModule->broadcastFixedPosition(fixed);

    v3LatestGoodPhonePosition = fixed;
    v3LatestGoodPhonePositionValid = true;
    v3LatestPhoneDifferenceM = 0;
    v3LastSavedDifferenceM = differenceM;
    v3LastSaveWasAutomatic = automatic;
    v3LastPositionBroadcastSent = meshSent;
    v3LastSavedAtMs = millis() ? millis() : 1;
    v3ResetAutoConfirmation();

    LOG_INFO("Heltec V3 position %s: lat=%d lon=%d acc=%umm previous-diff=%um mesh=%s",
             automatic ? "auto-updated" : "manually saved", fixed.latitude_i, fixed.longitude_i, (unsigned)fixed.gps_accuracy,
             (unsigned)differenceM, meshSent ? "sent" : "not-sent");
    heltecV3DiagNotePositionSave(automatic, differenceM);
    if (meshSent)
        heltecV3PowerMonitorNotePositionTx();
    // Native MeshModule page redraws from policy state; never switch to
    // an exclusive alert just because a position was saved.
    heltecV3PositionPageRefresh();
    return true;
}

static void v3ProcessPhonePosition(const meshtastic_Position &position)
{
    const uint32_t now = millis();
    v3LatestPhonePositionReceivedMs = now;
    v3LatestPhoneAccuracyMm = position.gps_accuracy;
    v3LatestPhoneFixFresh = v3PhoneFixFresh(position);
    v3LatestPhoneFixAccurate = v3PhoneFixAccurate(position);

    const uint32_t nowEpoch = getValidTime(RTCQualityFromNet);
    const uint32_t fixAge = (position.time != 0 && nowEpoch != 0)
                                ? (nowEpoch >= position.time ? nowEpoch - position.time : position.time - nowEpoch)
                                : UINT32_MAX;
    LOG_INFO("Heltec V3 phone GPS: lat=%d lon=%d acc=%umm age=%us coords=%s "
             "fresh=%s accurate=%s",
             position.latitude_i, position.longitude_i, (unsigned)position.gps_accuracy,
             fixAge == UINT32_MAX ? 9999U : (unsigned)fixAge, v3PhoneFixHasCoordinates(position) ? "yes" : "no",
             v3LatestPhoneFixFresh ? "yes" : "no", v3LatestPhoneFixAccurate ? "yes" : "no");

    if (!v3PhoneFixHasCoordinates(position) || !v3LatestPhoneFixFresh || !v3LatestPhoneFixAccurate) {
        v3LatestGoodPhonePositionValid = false;
        v3LatestPhoneDifferenceM = 0;
        v3ResetAutoConfirmation();
        heltecV3PositionPageRefresh();
        return;
    }

    v3LatestGoodPhonePosition = position;
    v3LatestGoodPhonePositionValid = true;
    meshtastic_Position saved;
    if (!v3LoadSavedPosition(saved)) {
        v3LatestPhoneDifferenceM = 0;
        v3ResetAutoConfirmation();
        heltecV3PositionPageRefresh();
        return;
    }

    v3LatestPhoneDifferenceM = v3DistanceMeters(saved, position);
    if (v3LatestPhoneDifferenceM <= V3_POSITION_AUTO_METERS) {
        v3ResetAutoConfirmation();
        heltecV3PositionPageRefresh();
        return;
    }

    if (!v3AutoConfirmAnchorValid || (uint32_t)(now - v3AutoConfirmStartedMs) > V3_POSITION_CONFIRM_WINDOW_MS ||
        v3DistanceMeters(v3AutoConfirmAnchor, position) > V3_POSITION_CONFIRM_CLUSTER_METERS) {
        v3AutoConfirmAnchor = position;
        v3AutoConfirmAnchorValid = true;
        v3AutoConfirmCount = 1;
        v3AutoConfirmStartedMs = now;
        v3AutoConfirmLastMs = now;
    } else if ((uint32_t)(now - v3AutoConfirmLastMs) >= V3_POSITION_CONFIRM_SPACING_MS) {
        v3AutoConfirmCount++;
        v3AutoConfirmLastMs = now;
    }

    if (v3AutoConfirmCount >= V3_POSITION_CONFIRM_COUNT) {
        const uint32_t differenceM = v3LatestPhoneDifferenceM;
        v3SavePosition(position, true, differenceM);
        return;
    }
    heltecV3PositionPageRefresh();
}

void heltecV3CapturePhonePosition(const meshtastic_Position &position)
{
    if (!v3RepeaterRoleEnabled() || !v3ServiceActive)
        return;

    portENTER_CRITICAL(&v3PositionMux);
    v3PendingPhonePosition = position;
    v3PhonePositionPending = true;
    portEXIT_CRITICAL(&v3PositionMux);

    LOG_INFO("Heltec V3 phone GPS captured pre-router: lat=%d lon=%d acc=%umm time=%u", position.latitude_i, position.longitude_i,
             (unsigned)position.gps_accuracy, (unsigned)position.time);

    if (v3ServiceTaskHandle)
        xTaskNotifyGive(v3ServiceTaskHandle);
}

bool heltecV3GetPositionUiState(HeltecV3PositionUiState &out)
{
    out = HeltecV3PositionUiState{};
    if (!v3RepeaterRoleEnabled())
        return false;

    out.serviceActive = v3ServiceActive;
    out.phoneFresh = v3LatestPhoneFixFresh;
    out.phoneAccurate = v3LatestPhoneFixAccurate;
    out.differenceM = v3LatestPhoneDifferenceM;
    out.accuracyMm = v3LatestPhoneAccuracyMm;
    out.autoConfirmCount = v3AutoConfirmCount;
    out.autoConfirmRequired = V3_POSITION_CONFIRM_COUNT;
    out.ignoreDistanceM = V3_POSITION_IGNORE_METERS;
    out.autoDistanceM = V3_POSITION_AUTO_METERS;

    meshtastic_Position saved = meshtastic_Position_init_default;
    out.haveSavedPosition = v3LoadSavedPosition(saved);
    if (out.haveSavedPosition) {
        out.savedLatitudeI = saved.latitude_i;
        out.savedLongitudeI = saved.longitude_i;
    }

    meshtastic_Position phone = meshtastic_Position_init_default;
    portENTER_CRITICAL(&v3PositionMux);
    phone = v3PendingPhonePosition;
    portEXIT_CRITICAL(&v3PositionMux);

    out.havePhonePosition = v3LatestPhonePositionReceivedMs != 0 && v3PhoneFixHasCoordinates(phone);
    if (out.havePhonePosition) {
        out.phoneLatitudeI = phone.latitude_i;
        out.phoneLongitudeI = phone.longitude_i;
        const uint32_t nowEpoch = getValidTime(RTCQualityFromNet);
        if (phone.time != 0 && nowEpoch != 0)
            out.phoneAgeSecs = nowEpoch >= phone.time ? nowEpoch - phone.time : phone.time - nowEpoch;
        else if (millis() >= v3LatestPhonePositionReceivedMs)
            out.phoneAgeSecs = (millis() - v3LatestPhonePositionReceivedMs) / 1000UL;
    }

    out.lastSaveValid = v3LastSavedAtMs != 0;
    out.lastSaveAutomatic = v3LastSaveWasAutomatic;
    out.lastSaveMeshSent = v3LastPositionBroadcastSent;
    out.lastSavedDifferenceM = v3LastSavedDifferenceM;
    if (out.lastSaveValid)
        out.lastSaveAgeMs = (uint32_t)(millis() - v3LastSavedAtMs);
    return true;
}

bool heltecV3ManualSaveLatestPosition()
{
    if (!v3RepeaterRoleEnabled() || !v3ServiceActive || !v3LatestGoodPhonePositionValid)
        return false;
    meshtastic_Position saved = meshtastic_Position_init_default;
    const uint32_t differenceM = v3LoadSavedPosition(saved) ? v3DistanceMeters(saved, v3LatestGoodPhonePosition) : 0U;
    return v3SavePosition(v3LatestGoodPhonePosition, false, differenceM);
}

static void startV3ServiceMode()
{
    const uint32_t now = millis();
    if (!v3ServiceActive) {
        v3ServiceActive = true;
        v3ServiceStartedMs = now;
        v3ServicePage = V3_PAGE_STATUS;
        v3LatestPhonePositionReceivedMs = 0;
        v3LatestGoodPhonePositionValid = false;
        v3DisplayVisible = false;
        v3LastFrameAssertMs = 0;
        v3ServiceEverConnected = false;
        v3BleActivityWindowStartedMs = 0;
        v3BleActivityWindowCount = 0;
        v3ResetAutoConfirmation();

        config.power.is_power_saving = true;
        config.bluetooth.enabled = true;
        v3BluetoothOnNow();
        v3LastBleAdvertisingCheckMs = now;
        v3BleTrafficLast = v3BleMeaningfulTrafficCount();
        heltecV3DiagNoteServiceOpen();
        LOG_INFO("Heltec V3 service: GPIO0 opened display/Bluetooth; idle=%us "
                 "connect-grace=%us activity=%u/%us hard-cap=%us power-save=%s",
                 (unsigned)(V3_SERVICE_IDLE_MS / 1000UL), (unsigned)(V3_SERVICE_CONNECT_GRACE_MS / 1000UL),
                 (unsigned)V3_SERVICE_ACTIVITY_THRESHOLD, (unsigned)(V3_SERVICE_ACTIVITY_WINDOW_MS / 1000UL),
                 (unsigned)(V3_SERVICE_MAX_MS / 1000UL), config.power.is_power_saving ? "on" : "off");
    }
    v3ServiceLastActivityMs = now;
    v3DisplayStartedMs = now;
    v3DisplayVisible = true;
    if (screen && !screen->isScreenOn())
        screen->setOn(true);
    heltecV3PositionPageRequestFocus();
}

static void stopV3ServiceMode()
{
    if (!v3ServiceActive)
        return;
    heltecV3ServiceMenuClose();
    v3BluetoothOffNow();
#ifdef BUTTON_PIN
    v3ServiceButtonEvent = false;
    v3RequireButtonRelease = digitalRead(BUTTON_PIN) == LOW;
    v3ButtonPrevPressed = v3RequireButtonRelease;
#endif
    config.bluetooth.enabled = false;
    config.power.is_power_saving = true;
    v3ResetAutoConfirmation();
    v3DisplayVisible = false;
    v3LastFrameAssertMs = 0;
    if (screen && screen->isScreenOn())
        screen->setOn(false);
    v3ServiceActive = false;
    heltecV3DiagLog("SERVICE_CLOSE", "BLE/display parked; repeater policy restored");
    LOG_INFO("Heltec V3 service: window complete; Bluetooth/display off, "
             "repeater power policy restored");
}

static void v3HandleLongPress()
{
    if (v3ServicePage != V3_PAGE_POSITION)
        return;
    if (!v3LatestGoodPhonePositionValid) {
        showV3ServicePage();
        return;
    }
    meshtastic_Position saved;
    const uint32_t differenceM = v3LoadSavedPosition(saved) ? v3DistanceMeters(saved, v3LatestGoodPhonePosition) : 0U;
    v3SavePosition(v3LatestGoodPhonePosition, false, differenceM);
}

static void v3QueueButtonEvent()
{
    v3ServiceButtonEvent = true;
    if (v3ServiceTaskHandle)
        xTaskNotifyGive(v3ServiceTaskHandle);
}

class V3LightSleepEndObserver : public Observer<esp_sleep_wakeup_cause_t>
{
  protected:
    int onNotify(esp_sleep_wakeup_cause_t cause) override
    {
        if (!v3RepeaterRoleEnabled())
            return 0;
#ifdef BUTTON_PIN
        if (cause == ESP_SLEEP_WAKEUP_GPIO && digitalRead(BUTTON_PIN) == LOW)
            v3QueueButtonEvent();
#endif
        return 0;
    }
};

class V3PreflightSleepObserver : public Observer<void *>
{
  protected:
    int onNotify(void *) override
    {
        if (!v3RepeaterRoleEnabled())
            return 0;
        if (v3ServiceActive || v3NativeSerialConnected())
            return 1;
        v3ForceIdlePeripheralsOff();
        return 0;
    }
};

static V3LightSleepEndObserver v3LightSleepEndObserver;
static V3PreflightSleepObserver v3PreflightSleepObserver;
static bool v3SleepObserversInstalled = false;

static void v3ServiceTask(void *)
{
    for (;;) {
        // GPIO0 still wakes this task immediately. The idle timeout only services
        // power accounting: one-second samples with INA226, otherwise the next
        // 30-second probe. This removes the old permanent 100 ms wake-up without
        // starving battery learning and persistence.
        const TickType_t waitTicks = v3ServiceActive ? pdMS_TO_TICKS(50UL) : pdMS_TO_TICKS(heltecV3PowerMonitorIdleWakeMs());
        ulTaskNotifyTake(pdTRUE, waitTicks);
        const uint32_t now = millis();
        v3UpdateUsbMaintenance();
        heltecV3DiagPumpUsbExport();
        heltecV3MeshMonitorTick();
        heltecV3ServiceMenuPump();
        heltecV3PowerMonitorTick(!v3ServiceActive, v3ServiceActive, v3BleConnected(),
                                 v3DisplayVisible && screen && screen->isScreenOn());

#ifdef BUTTON_PIN
        const bool pressed = digitalRead(BUTTON_PIN) == LOW;
        const bool pressEdge = pressed && !v3ButtonPrevPressed;
        v3ButtonPrevPressed = pressed;

        if (!v3ServiceActive && v3RequireButtonRelease) {
            if (!pressed) {
                v3RequireButtonRelease = false;
                v3ServiceButtonEvent = false;
                v3ButtonPrevPressed = false;
                v3LastAcceptedButtonMs = now;
                LOG_DEBUG("Heltec V3 service: GPIO0 released; next press armed");
            }
            v3ForceIdlePeripheralsOff();
            continue;
        }

        if (!v3ServiceActive && (v3ServiceButtonEvent || pressEdge)) {
            if ((uint32_t)(now - v3LastAcceptedButtonMs) >= (uint32_t)V3_SERVICE_DEBOUNCE_MS) {
                v3ServiceButtonEvent = false;
                v3LastAcceptedButtonMs = now ? now : 1;
                startV3ServiceMode();
                v3OpenedServiceThisPress = true;
                v3ButtonPressedSinceMs = now ? now : 1;
                v3ButtonWasPressed = pressed;
                v3LongPressHandled = false;
            }
        } else if (v3ServiceActive && !v3ButtonWasPressed && pressEdge &&
                   (uint32_t)(now - v3LastAcceptedButtonMs) >= (uint32_t)V3_SERVICE_DEBOUNCE_MS) {
            v3LastAcceptedButtonMs = now ? now : 1;
            v3ButtonPressedSinceMs = now ? now : 1;
            v3ButtonWasPressed = true;
            v3OpenedServiceThisPress = false;
            v3LongPressHandled = false;

            if (!v3DisplayVisible || (screen && !screen->isScreenOn())) {
                v3DisplayStartedMs = now;
                v3DisplayVisible = true;
                if (screen && !screen->isScreenOn())
                    screen->setOn(true);
                // Preserve current page/menu. This wake press is consumed; its
                // release must not navigate. Initial service open still focuses
                // Position.
                if (screen)
                    screen->runNow();
                v3OpenedServiceThisPress = true;
            }
        }
#endif

        if (!v3ServiceActive) {
            v3ForceIdlePeripheralsOff();
            continue;
        }

        meshtastic_Position pending = meshtastic_Position_init_default;
        bool havePending = false;
        portENTER_CRITICAL(&v3PositionMux);
        if (v3PhonePositionPending) {
            pending = v3PendingPhonePosition;
            v3PhonePositionPending = false;
            havePending = true;
        }
        portEXIT_CRITICAL(&v3PositionMux);
        if (havePending)
            v3ProcessPhonePosition(pending);

#ifdef BUTTON_PIN
        if (v3ButtonWasPressed && pressed && !v3OpenedServiceThisPress && !v3LongPressHandled &&
            (uint32_t)(now - v3ButtonPressedSinceMs) >= V3_SERVICE_LONG_PRESS_MS) {
            if (heltecV3ServiceMenuActive()) {
                heltecV3ServiceMenuSelect();
            } else if (heltecV3PositionPageRecentlyVisible()) {
                heltecV3ManualSaveLatestPosition();
                heltecV3PositionPageRefresh();
            } else if (heltecV3ServicePageRecentlyVisible()) {
                heltecV3ServiceMenuOpen();
            } else if (heltecV3AntennaPageRecentlyVisible()) {
                heltecV3AntennaHandleLongPress();
                heltecV3MeshPagesRefresh();
            }
            // Mesh Health and stock Meshtastic pages are read-only on long press.
            // The gesture is still consumed so release cannot become a short tap.
            v3LongPressHandled = true;
            v3DisplayStartedMs = now;
            v3DisplayVisible = true;
            v3ServiceLastActivityMs = now;
        }
        if (v3ButtonWasPressed && !pressed) {
            const uint32_t heldMs = v3ButtonPressedSinceMs != 0 ? (uint32_t)(now - v3ButtonPressedSinceMs) : 0U;
            const bool validTap = heldMs >= 40UL;
            const bool actionGuardExpired = v3LastPageAdvanceMs == 0 || (uint32_t)(now - v3LastPageAdvanceMs) >= 120UL;

            if (!v3OpenedServiceThisPress && !v3LongPressHandled && validTap && actionGuardExpired) {
                if (heltecV3ServiceMenuActive()) {
                    heltecV3ServiceMenuNext();
                    LOG_DEBUG("Heltec V3 button: one tap -> next service-menu item (held=%ums)", (unsigned)heldMs);
                } else if (screen) {
                    screen->showNextFrame();
                    screen->runNow();
                    LOG_DEBUG("Heltec V3 button: one tap -> one next frame (held=%ums)", (unsigned)heldMs);
                }
                v3LastPageAdvanceMs = now ? now : 1;
                v3DisplayStartedMs = now;
                v3DisplayVisible = true;
                v3ServiceLastActivityMs = now;
            } else if (!v3OpenedServiceThisPress && !v3LongPressHandled && !validTap) {
                LOG_DEBUG("Heltec V3 button: ignored bounce pulse (%ums)", (unsigned)heldMs);
            } else if (!v3OpenedServiceThisPress && !v3LongPressHandled && !actionGuardExpired) {
                LOG_DEBUG("Heltec V3 button: ignored duplicate tap inside 120ms guard");
            }
            v3ButtonWasPressed = false;
            v3OpenedServiceThisPress = false;
            v3LongPressHandled = false;
            v3ButtonPressedSinceMs = 0;
        }
#endif

        const bool bleConnected = v3BleConnected();
        if (bleConnected && !v3ServiceEverConnected) {
            v3ServiceEverConnected = true;
            heltecV3DiagNoteBleConnection();
            LOG_INFO("Heltec V3 service: BLE connected; activity burst detector "
                     "armed (%u transactions/%us)",
                     (unsigned)V3_SERVICE_ACTIVITY_THRESHOLD, (unsigned)(V3_SERVICE_ACTIVITY_WINDOW_MS / 1000UL));
        }

        if (!bleConnected && (uint32_t)(now - v3LastBleAdvertisingCheckMs) >= 2000UL) {
            v3LastBleAdvertisingCheckMs = now;
            if (!v3BleAdvertisingActive()) {
                LOG_WARN("Heltec V3 service: GAP advertising inactive; restarting "
                         "without BLE reinit");
                heltecV3DiagNoteBleRecovery();
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
                if (nimbleBluetooth && nimbleBluetooth->isActive())
                    nimbleBluetooth->startAdvertising();
#endif
            }
        }

        const uint32_t trafficNow = v3BleMeaningfulTrafficCount();
        if (trafficNow < v3BleTrafficLast) {
            // NimBLE resets its per-session counter on disconnect/reconnect.
            v3BleTrafficLast = trafficNow;
            v3BleActivityWindowStartedMs = 0;
            v3BleActivityWindowCount = 0;
        } else if (trafficNow > v3BleTrafficLast) {
            uint32_t delta = trafficNow - v3BleTrafficLast;
            v3BleTrafficLast = trafficNow;

            if (v3BleActivityWindowStartedMs == 0 ||
                (uint32_t)(now - v3BleActivityWindowStartedMs) > (uint32_t)V3_SERVICE_ACTIVITY_WINDOW_MS) {
                v3BleActivityWindowStartedMs = now ? now : 1;
                v3BleActivityWindowCount = 0;
            }

            if (delta > (uint32_t)V3_SERVICE_ACTIVITY_THRESHOLD)
                delta = (uint32_t)V3_SERVICE_ACTIVITY_THRESHOLD;
            uint32_t activityCount = (uint32_t)v3BleActivityWindowCount + delta;
            v3BleActivityWindowCount = activityCount > (uint32_t)V3_SERVICE_ACTIVITY_THRESHOLD
                                           ? (uint8_t)V3_SERVICE_ACTIVITY_THRESHOLD
                                           : (uint8_t)activityCount;

            if (v3BleActivityWindowCount >= (uint8_t)V3_SERVICE_ACTIVITY_THRESHOLD) {
                v3ServiceLastActivityMs = now;
                LOG_DEBUG("Heltec V3 service: active BLE burst detected; 120s idle "
                          "timer reset");
                v3BleActivityWindowStartedMs = now ? now : 1;
                v3BleActivityWindowCount = 0;
            }
        }

        const uint32_t bleDiagSequence = heltecV3DiagBleExportStatusSequence();
        if (bleDiagSequence != v3ConsumedBleDiagUiSequence) {
            v3ConsumedBleDiagUiSequence = bleDiagSequence;
            if (heltecV3DiagBleExportStatusVisible() && screen) {
                char banner[48] = {};
                if (heltecV3DiagBleExportActive())
                    snprintf(banner, sizeof(banner), "%s\n%u%%", heltecV3DiagBleExportStatusText(),
                             (unsigned)heltecV3DiagBleExportProgress());
                else
                    snprintf(banner, sizeof(banner), "%s", heltecV3DiagBleExportStatusText());
                v3ServiceLastActivityMs = now;
                v3DisplayStartedMs = now;
                v3DisplayVisible = true;
                if (!screen->isScreenOn())
                    screen->setOn(true);
                screen->showSimpleBanner(banner, heltecV3DiagBleExportActive() ? 1200U : 2500U);
            }
        }

        // Do not close the complete local service UI merely because no phone
        // connected during the BLE discovery grace. The agreed user-visible
        // behavior is 20 s OLED inactivity plus a 120 s service inactivity
        // window. Local button actions and meaningful BLE bursts reset that
        // service timer; GPS/LoRa/background polling do not.
        const bool hardCapReached = (uint32_t)(now - v3ServiceStartedMs) >= (uint32_t)V3_SERVICE_MAX_MS;
        const bool idleExpired = (uint32_t)(now - v3ServiceLastActivityMs) >= (uint32_t)V3_SERVICE_IDLE_MS;
        if (!heltecV3DiagUsbExportPending() && (hardCapReached || idleExpired)) {
            heltecV3DiagLog("SERVICE_TIMEOUT", "reason=%s idleAge=%us sessionAge=%us", hardCapReached ? "hard-cap" : "idle",
                            (unsigned)((now - v3ServiceLastActivityMs) / 1000UL),
                            (unsigned)((now - v3ServiceStartedMs) / 1000UL));
            stopV3ServiceMode();
            continue;
        }

        // Native MeshModule frames are owned/redrawn by Screen itself. Do not
        // reassert an alert frame from this service task.
        const uint32_t displayNow = millis();
        const bool serviceUiActive = heltecV3ServiceMenuActive();
        (void)serviceUiActive;
        if (!heltecV3DiagUsbExportPending() && !v3PairingDisplayActive && v3DisplayVisible &&
            (uint32_t)(displayNow - v3DisplayStartedMs) >= (uint32_t)V3_SERVICE_DISPLAY_MS) {
            v3DisplayVisible = false;
            if (screen && screen->isScreenOn())
                screen->setOn(false);
            LOG_DEBUG("Heltec V3 service: display window closed");
        }
    }
}

static void setupV3ServiceButton()
{
#ifdef BUTTON_PIN
    pinMode(BUTTON_PIN, INPUT_PULLUP);
    v3ButtonPrevPressed = digitalRead(BUTTON_PIN) == LOW;
    if (!v3ServiceTaskHandle)
        xTaskCreate(v3ServiceTask, "V3Service", 6144, nullptr, 1, &v3ServiceTaskHandle);
    if (!v3SleepObserversInstalled) {
        v3LightSleepEndObserver.observe(&notifyLightSleepEnd);
        v3PreflightSleepObserver.observe(&preflightSleep);
        v3SleepObserversInstalled = true;
    }
#if defined(ARCH_ESP32)
    gpio_wakeup_enable((gpio_num_t)BUTTON_PIN, GPIO_INTR_LOW_LEVEL);
    esp_sleep_enable_gpio_wakeup();
#endif
#endif
}

void lateInitVariant()
{
    if (!v3RepeaterRoleEnabled()) {
        LOG_INFO("Heltec V3 repeater policy inactive (role=%d); use ROUTER_LATE "
                 "(recommended) or REPEATER",
                 (int)config.device.role);
        return;
    }

    config.position.fixed_position = true;
    config.bluetooth.enabled = false;
    config.power.wait_bluetooth_secs = 1;
    config.network.wifi_enabled = false;
    config.display.screen_on_secs = 1;
    config.device.led_heartbeat_disabled = true;
    config.power.is_power_saving = true;
    config.power.min_wake_secs = 1;
    config.power.ls_secs = 3600;

    moduleConfig.telemetry.device_telemetry_enabled = true;
    moduleConfig.telemetry.device_update_interval = repeaterHealthIntervalSecs();
    if (config.device.role == meshtastic_Config_DeviceConfig_Role_REPEATER)
        config.device.rebroadcast_mode = meshtastic_Config_DeviceConfig_RebroadcastMode_ALL_SKIP_DECODING;

    config.bluetooth.enabled = true;
    LOG_INFO("Heltec V3 BLE: pre-initialize NimBLE once before first light sleep");
    v3BluetoothOnNow();
    v3BluetoothOffNow();
    config.bluetooth.enabled = false;
    LOG_INFO("Heltec V3 BLE: boot initialization complete; advertising parked "
             "until GPIO0");

    if (screen)
        screen->setOn(false);
    heltecV3DiagInit();
    heltecV3PowerMonitorInit();
    heltecV3MeshMonitorTick();
    setupV3ServiceButton();

    LOG_INFO("Heltec V3 %s duty: LS + LoRa wake, BLE/WiFi/display/LED off, GPIO0 "
             "service + raw-phone-GPS fixed-position capture, health=%us, "
             "resetReason=%d",
             config.device.role == meshtastic_Config_DeviceConfig_Role_ROUTER_LATE ? "ROUTER_LATE repeater" : "legacy REPEATER",
             (unsigned)moduleConfig.telemetry.device_update_interval, (int)esp_reset_reason());
}

#endif // _VARIANT_HELTEC_V3
