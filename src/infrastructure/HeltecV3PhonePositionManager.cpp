#include "configuration.h"

#ifdef _VARIANT_HELTEC_V3

#include "NodeDB.h"
#include "PositionPrecision.h"
#include "ProtobufModule.h"
#include "Throttle.h"
#include "TypeConversions.h"
#include "concurrency/OSThread.h"
#include "gps/RTC.h"
#include "infrastructure/HeltecV3DiagnosticLog.h"
#include "infrastructure/HeltecV3PositionPage.h"
#include "infrastructure/HeltecV3PowerMonitor.h"
#include "infrastructure/HeltecV3Runtime.h"
#include "main.h"

#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
#include "nimble/NimbleBluetooth.h"
#endif

#include <cmath>
#include <driver/gpio.h>

namespace
{
constexpr uint32_t SERVICE_TAIL_MS = 20UL * 1000UL;
constexpr uint32_t PHONE_FIX_MAX_AGE_SECS = 60UL;
constexpr uint32_t PHONE_FIX_MAX_ACCURACY_MM = 20000UL;
constexpr uint32_t RELOCATION_MIN_DISTANCE_M = 50UL;
constexpr uint32_t RELOCATION_CLUSTER_M = 35UL;
constexpr uint32_t RELOCATION_CONFIRM_WINDOW_MS = 120UL * 1000UL;
constexpr uint32_t RELOCATION_CONFIRM_MIN_SPAN_MS = 25UL * 1000UL;
constexpr uint32_t RELOCATION_CONFIRM_SPACING_MS = 8UL * 1000UL;
constexpr uint8_t RELOCATION_CONFIRM_COUNT = 4U;
constexpr uint32_t MOBILE_STEP_M = 35UL;
constexpr uint32_t DEFAULT_LIVE_DISTANCE_M = 75UL;
constexpr uint32_t DEFAULT_LIVE_INTERVAL_SECS = 30UL;

portMUX_TYPE managerMux = portMUX_INITIALIZER_UNLOCKED;
meshtastic_Position pendingPhoneFix = meshtastic_Position_init_default;
volatile bool phoneFixPending = false;

bool serviceWasActive = false;
bool bleWasConnected = false;
bool serviceHoldOwned = false;
uint32_t serviceHoldLastActiveMs = 0;

bool sessionMobile = false;
bool relocationCandidateValid = false;
meshtastic_Position relocationAnchor = meshtastic_Position_init_default;
uint8_t relocationCandidateCount = 0;
uint32_t relocationCandidateStartedMs = 0;
uint32_t relocationCandidateLastMs = 0;

bool lastGoodFixValid = false;
meshtastic_Position lastGoodFix = meshtastic_Position_init_default;

bool lastLiveTxValid = false;
meshtastic_Position lastLiveTxPosition = meshtastic_Position_init_default;
uint32_t lastLiveTxMs = 0;

uint32_t distanceMeters(const meshtastic_Position &a, const meshtastic_Position &b)
{
    constexpr double DEG_TO_RAD = 0.017453292519943295;
    constexpr double EARTH_RADIUS_M = 6371000.0;
    const double lat1 = ((double)a.latitude_i / 10000000.0) * DEG_TO_RAD;
    const double lat2 = ((double)b.latitude_i / 10000000.0) * DEG_TO_RAD;
    const double dLat = lat2 - lat1;
    const double dLon = (((double)b.longitude_i - (double)a.longitude_i) / 10000000.0) * DEG_TO_RAD;
    const double x = dLon * std::cos((lat1 + lat2) * 0.5);
    const double d = std::sqrt(dLat * dLat + x * x) * EARTH_RADIUS_M;
    return d > 0.0 ? (uint32_t)d : 0U;
}

bool phoneFixHasCoordinates(const meshtastic_Position &position)
{
    return position.has_latitude_i && position.has_longitude_i && (position.latitude_i != 0 || position.longitude_i != 0);
}

bool phoneFixFresh(const meshtastic_Position &position)
{
    if (position.time == 0)
        return false;
    const uint32_t nowEpoch = getValidTime(RTCQualityFromNet);
    if (nowEpoch == 0)
        return true;
    const uint32_t age = nowEpoch >= position.time ? nowEpoch - position.time : position.time - nowEpoch;
    return age <= PHONE_FIX_MAX_AGE_SECS;
}

bool phoneFixAccurate(const meshtastic_Position &position)
{
    return position.gps_accuracy > 0 && position.gps_accuracy <= PHONE_FIX_MAX_ACCURACY_MM;
}

bool loadSavedPosition(meshtastic_Position &position)
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

uint32_t liveDistanceThresholdM()
{
    const uint32_t configured = config.position.broadcast_smart_minimum_distance;
    return configured != 0 ? configured : DEFAULT_LIVE_DISTANCE_M;
}

uint32_t liveIntervalMs()
{
    const uint32_t configured = config.position.broadcast_smart_minimum_interval_secs;
    const uint32_t secs = configured != 0 ? configured : DEFAULT_LIVE_INTERVAL_SECS;
    return secs * 1000UL;
}

bool bleConnected()
{
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
    return nimbleBluetooth && nimbleBluetooth->isConnected();
#else
    return false;
#endif
}

bool buttonPressed()
{
#ifdef BUTTON_PIN
    return digitalRead(BUTTON_PIN) == LOW;
#else
    return false;
#endif
}

void resetRelocationCandidate()
{
    relocationCandidateValid = false;
    relocationCandidateCount = 0;
    relocationCandidateStartedMs = 0;
    relocationCandidateLastMs = 0;
}

void resetServicePositionState()
{
    sessionMobile = false;
    resetRelocationCandidate();
    lastGoodFixValid = false;
    lastLiveTxValid = false;
    lastLiveTxMs = 0;
}

class V3PhonePositionManager;

class V3PhonePositionWorker : public concurrency::OSThread
{
  public:
    explicit V3PhonePositionWorker(V3PhonePositionManager *owner)
        : concurrency::OSThread("V3PhoneMgr"), owner(owner)
    {
    }

  protected:
    int32_t runOnce() override;

  private:
    V3PhonePositionManager *owner;
};

class V3PhonePositionManager : public ProtobufModule<meshtastic_Position>
{
  public:
    V3PhonePositionManager()
        : ProtobufModule("v3-phone-manager", meshtastic_PortNum_POSITION_APP, &meshtastic_Position_msg)
    {
        loopbackOk = true;
        isPromiscuous = true;
    }

    bool broadcastPosition(const meshtastic_Position &position, bool fixed)
    {
        const uint32_t precision = getPositionPrecisionForChannel(0);
        if (precision == 0) {
            heltecV3DiagLog("PHONE_POS_TX", "skipped precision=0 fixed=%u", fixed ? 1U : 0U);
            return false;
        }

        meshtastic_Position outgoing = position;
        if (fixed) {
            outgoing.location_source = meshtastic_Position_LocSource_LOC_MANUAL;
            outgoing.ground_speed = 0;
            outgoing.has_ground_speed = false;
            outgoing.ground_track = 0;
            outgoing.has_ground_track = false;
        }

        applyPositionPrecision(outgoing, precision);
        meshtastic_MeshPacket *packet = allocDataProtobuf(outgoing);
        if (!packet)
            return false;

        packet->to = NODENUM_BROADCAST;
        packet->channel = 0;
        service->sendToMesh(packet, RX_SRC_USER);
        heltecV3PowerMonitorNotePositionTx();
        return true;
    }

    bool saveFixedPosition(const meshtastic_Position &position, uint32_t previousDifferenceM)
    {
        if (!nodeDB || !phoneFixHasCoordinates(position))
            return false;

        meshtastic_Position fixed = position;
        fixed.location_source = meshtastic_Position_LocSource_LOC_MANUAL;
        fixed.ground_speed = 0;
        fixed.has_ground_speed = false;
        fixed.ground_track = 0;
        fixed.has_ground_track = false;

        config.position.fixed_position = true;
        nodeDB->setLocalPosition(fixed);
        nodeDB->updatePosition(nodeDB->getNodeNum(), fixed);
        nodeDB->saveToDisk(SEGMENT_CONFIG | SEGMENT_NODEDATABASE);

        const bool meshSent = broadcastPosition(fixed, true);
        heltecV3DiagNotePositionSave(true, previousDifferenceM);
        heltecV3DiagLog("PHONE_POS_FIXED", "auto lat=%d lon=%d diff=%um mesh=%u", fixed.latitude_i, fixed.longitude_i,
                        (unsigned)previousDifferenceM, meshSent ? 1U : 0U);
        LOG_INFO("Heltec V3 fixed position auto-updated after stationary confirmation: diff=%um mesh=%s",
                 (unsigned)previousDifferenceM, meshSent ? "sent" : "not-sent");
        heltecV3PositionPageRefresh();
        return true;
    }

    void processPhoneFix(const meshtastic_Position &position)
    {
        if (!heltecV3RuntimeServiceActive())
            return;

        const uint32_t now = millis();
        const uint32_t nowEpoch = getValidTime(RTCQualityFromNet);
        const uint32_t age =
            position.time != 0 && nowEpoch != 0
                ? (nowEpoch >= position.time ? nowEpoch - position.time : position.time - nowEpoch)
                : UINT32_MAX;

        heltecV3DiagLog("PHONE_POS_RX", "lat=%d lon=%d acc=%umm age=%us", position.latitude_i, position.longitude_i,
                        (unsigned)position.gps_accuracy, age == UINT32_MAX ? 9999U : (unsigned)age);

        if (!phoneFixHasCoordinates(position) || !phoneFixFresh(position) || !phoneFixAccurate(position)) {
            heltecV3DiagLog("PHONE_POS_REJECT", "coords=%u fresh=%u accurate=%u", phoneFixHasCoordinates(position) ? 1U : 0U,
                            phoneFixFresh(position) ? 1U : 0U, phoneFixAccurate(position) ? 1U : 0U);
            resetRelocationCandidate();
            return;
        }

        if (!config.position.fixed_position) {
            heltecV3DiagLog("PHONE_POS_REJECT", "fixed-position=off; custom repeater position manager disabled");
            return;
        }

        meshtastic_Position saved = meshtastic_Position_init_default;
        if (!loadSavedPosition(saved)) {
            heltecV3DiagLog("PHONE_POS_WAIT", "no saved fixed position; use long-press save once");
            lastGoodFix = position;
            lastGoodFixValid = true;
            return;
        }

        const uint32_t differenceFromSaved = distanceMeters(saved, position);
        const uint32_t stepFromLast = lastGoodFixValid ? distanceMeters(lastGoodFix, position) : 0U;

        if (differenceFromSaved <= RELOCATION_MIN_DISTANCE_M) {
            resetRelocationCandidate();
            lastGoodFix = position;
            lastGoodFixValid = true;
            return;
        }

        if (!sessionMobile) {
            if (lastGoodFixValid && stepFromLast >= MOBILE_STEP_M) {
                sessionMobile = true;
                resetRelocationCandidate();
                heltecV3DiagLog("PHONE_POS_MODE", "mobile step=%um saved-diff=%um", (unsigned)stepFromLast,
                                (unsigned)differenceFromSaved);
                LOG_INFO("Heltec V3 phone position: mobile session detected; fixed position will not be persisted this session");
            } else if (!relocationCandidateValid ||
                       (relocationCandidateStartedMs != 0 &&
                        !Throttle::isWithinTimespanMs(relocationCandidateStartedMs, RELOCATION_CONFIRM_WINDOW_MS))) {
                relocationAnchor = position;
                relocationCandidateValid = true;
                relocationCandidateCount = 1;
                relocationCandidateStartedMs = now ? now : 1;
                relocationCandidateLastMs = relocationCandidateStartedMs;
                heltecV3DiagLog("PHONE_POS_STABLE", "candidate=1/%u diff=%um", (unsigned)RELOCATION_CONFIRM_COUNT,
                                (unsigned)differenceFromSaved);
            } else {
                const uint32_t clusterDistance = distanceMeters(relocationAnchor, position);
                if (clusterDistance > RELOCATION_CLUSTER_M) {
                    sessionMobile = true;
                    resetRelocationCandidate();
                    heltecV3DiagLog("PHONE_POS_MODE", "mobile cluster-break=%um saved-diff=%um", (unsigned)clusterDistance,
                                    (unsigned)differenceFromSaved);
                    LOG_INFO("Heltec V3 phone position: mobile session detected by relocation cluster break");
                } else if (relocationCandidateLastMs == 0 ||
                           !Throttle::isWithinTimespanMs(relocationCandidateLastMs, RELOCATION_CONFIRM_SPACING_MS)) {
                    if (relocationCandidateCount < UINT8_MAX)
                        relocationCandidateCount++;
                    relocationCandidateLastMs = now ? now : 1;
                    heltecV3DiagLog("PHONE_POS_STABLE", "candidate=%u/%u cluster=%um diff=%um",
                                    (unsigned)relocationCandidateCount, (unsigned)RELOCATION_CONFIRM_COUNT,
                                    (unsigned)clusterDistance, (unsigned)differenceFromSaved);

                    const bool enoughSpan =
                        relocationCandidateStartedMs != 0 &&
                        !Throttle::isWithinTimespanMs(relocationCandidateStartedMs, RELOCATION_CONFIRM_MIN_SPAN_MS);
                    if (relocationCandidateCount >= RELOCATION_CONFIRM_COUNT && enoughSpan) {
                        saveFixedPosition(position, differenceFromSaved);
                        resetRelocationCandidate();
                        lastGoodFix = position;
                        lastGoodFixValid = true;
                        return;
                    }
                }
            }
        }

        if (sessionMobile && config.position.position_broadcast_smart_enabled) {
            const uint32_t distanceThreshold = liveDistanceThresholdM();
            const uint32_t referenceDistance =
                lastLiveTxValid ? distanceMeters(lastLiveTxPosition, position) : differenceFromSaved;
            const bool intervalReady =
                lastLiveTxMs == 0 || !Throttle::isWithinTimespanMs(lastLiveTxMs, liveIntervalMs());

            if (referenceDistance >= distanceThreshold && intervalReady) {
                const bool sent = broadcastPosition(position, false);
                heltecV3DiagLog("PHONE_POS_LIVE", "diff=%um step=%um tx=%u min=%um/%us", (unsigned)differenceFromSaved,
                                (unsigned)referenceDistance, sent ? 1U : 0U, (unsigned)distanceThreshold,
                                (unsigned)(liveIntervalMs() / 1000UL));
                if (sent) {
                    lastLiveTxPosition = position;
                    lastLiveTxValid = true;
                    lastLiveTxMs = now ? now : 1;
                }
            }
        }

        lastGoodFix = position;
        lastGoodFixValid = true;
    }

  protected:
    void setup() override
    {
        if (!worker)
            worker = new V3PhonePositionWorker(this);
    }

    bool handleReceivedProtobuf(const meshtastic_MeshPacket &mp, meshtastic_Position *position) override
    {
        if (!position || !heltecV3RuntimeServiceActive())
            return false;

        const bool phoneTransport =
            mp.transport_mechanism == meshtastic_MeshPacket_TransportMechanism_TRANSPORT_API ||
            (mp.transport_mechanism == meshtastic_MeshPacket_TransportMechanism_TRANSPORT_INTERNAL && mp.from == 0);
        const bool phoneSource = isFromUs(&mp) || mp.from == 0;
        if (!phoneSource || !phoneTransport)
            return false;

        portENTER_CRITICAL(&managerMux);
        pendingPhoneFix = *position;
        phoneFixPending = true;
        portEXIT_CRITICAL(&managerMux);
        return false;
    }

  private:
    V3PhonePositionWorker *worker = nullptr;
};

int32_t V3PhonePositionWorker::runOnce()
{
    const bool serviceActive = heltecV3RuntimeServiceActive();
    const uint32_t now = millis();

    if (!serviceActive) {
        if (serviceWasActive)
            heltecV3DiagLog("PHONE_SERVICE", "closed");
        serviceWasActive = false;
        bleWasConnected = false;
        serviceHoldOwned = false;
        serviceHoldLastActiveMs = 0;
        resetServicePositionState();
        return 1000;
    }

    if (!serviceWasActive) {
        serviceWasActive = true;
        serviceHoldOwned = true;
        serviceHoldLastActiveMs = now ? now : 1;
        heltecV3RuntimeSetBleQueueHold(true);
        resetServicePositionState();
        heltecV3DiagLog("PHONE_SERVICE", "opened tail=%us", (unsigned)(SERVICE_TAIL_MS / 1000UL));
    }

    const bool connected = bleConnected();
    const bool pressed = buttonPressed();

    if (connected != bleWasConnected) {
        bleWasConnected = connected;
        serviceHoldLastActiveMs = now ? now : 1;
        serviceHoldOwned = true;
        heltecV3RuntimeSetBleQueueHold(true);
        heltecV3DiagLog("PHONE_BT", "%s tail=%us", connected ? "connected" : "disconnected",
                        (unsigned)(SERVICE_TAIL_MS / 1000UL));
        LOG_INFO("Heltec V3 service: BLE %s; service hold %s", connected ? "connected" : "disconnected",
                 connected ? "latched while connected" : "kept for 20s");
    }

    if (connected || pressed) {
        serviceHoldLastActiveMs = now ? now : 1;
        if (!serviceHoldOwned) {
            serviceHoldOwned = true;
            heltecV3RuntimeSetBleQueueHold(true);
        }
    } else if (serviceHoldOwned && serviceHoldLastActiveMs != 0 &&
               !Throttle::isWithinTimespanMs(serviceHoldLastActiveMs, SERVICE_TAIL_MS)) {
        serviceHoldOwned = false;
        heltecV3RuntimeSetBleQueueHold(false);
        heltecV3DiagLog("PHONE_SERVICE", "20s tail expired; BLE may park");
    }

    meshtastic_Position pending = meshtastic_Position_init_default;
    bool havePending = false;
    portENTER_CRITICAL(&managerMux);
    if (phoneFixPending) {
        pending = pendingPhoneFix;
        phoneFixPending = false;
        havePending = true;
    }
    portEXIT_CRITICAL(&managerMux);

    if (havePending && owner)
        owner->processPhoneFix(pending);

    return 100;
}

static V3PhonePositionManager v3PhonePositionManager;

} // namespace

#endif // _VARIANT_HELTEC_V3
