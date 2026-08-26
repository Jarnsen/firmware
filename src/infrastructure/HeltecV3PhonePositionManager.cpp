#include "configuration.h"

#ifdef _VARIANT_HELTEC_V3

#include "MeshService.h"
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
#include "mesh/http/JarnsenPositionTrack.h"

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
constexpr uint32_t STATIONARY_CLUSTER_M = 35UL;
constexpr uint32_t MOBILE_STEP_M = 35UL;
constexpr uint8_t STATIONARY_CONFIRM_COUNT = 3U;
constexpr uint32_t STATIONARY_CONFIRM_SPACING_MS = 30UL * 1000UL;
constexpr uint32_t STATIONARY_DWELL_MS = 3UL * 60UL * 1000UL;
constexpr uint32_t DEFAULT_LIVE_DISTANCE_M = 75UL;
constexpr uint32_t DEFAULT_LIVE_INTERVAL_SECS = 30UL;

portMUX_TYPE managerMux = portMUX_INITIALIZER_UNLOCKED;
meshtastic_Position pendingPhoneFix = meshtastic_Position_init_default;
volatile bool phoneFixPending = false;

portMUX_TYPE motionMux = portMUX_INITIALIZER_UNLOCKED;
HeltecV3PhoneMotionState motionState;
meshtastic_Position motionLastFix = meshtastic_Position_init_default;
bool motionLastFixValid = false;
meshtastic_Position stabilizingAnchor = meshtastic_Position_init_default;
bool stabilizingAnchorValid = false;
uint32_t stabilizingStartedMs = 0;
uint32_t lastStabilizingEvidenceMs = 0;

bool sessionBaselineValid = false;
meshtastic_Position sessionBaseline = meshtastic_Position_init_default;

bool lastLiveTxValid = false;
meshtastic_Position lastLiveTxPosition = meshtastic_Position_init_default;
uint32_t lastLiveTxMs = 0;

bool serviceWasActive = false;
bool bleWasConnected = false;
bool serviceHoldOwned = false;
uint32_t serviceHoldLastActiveMs = 0;

uint32_t distanceMeters(const meshtastic_Position &a, const meshtastic_Position &b)
{
    constexpr double DEG_TO_RAD_LOCAL = 0.017453292519943295;
    constexpr double EARTH_RADIUS_M = 6371000.0;
    const double lat1 = ((double)a.latitude_i / 10000000.0) * DEG_TO_RAD_LOCAL;
    const double lat2 = ((double)b.latitude_i / 10000000.0) * DEG_TO_RAD_LOCAL;
    const double dLat = lat2 - lat1;
    const double dLon = (((double)b.longitude_i - (double)a.longitude_i) / 10000000.0) * DEG_TO_RAD_LOCAL;
    const double x = dLon * std::cos((lat1 + lat2) * 0.5);
    const double d = std::sqrt(dLat * dLat + x * x) * EARTH_RADIUS_M;
    return d > 0.0 ? (uint32_t)std::lround(d) : 0U;
}

bool sameCoordinates(const meshtastic_Position &a, const meshtastic_Position &b)
{
    return a.latitude_i == b.latitude_i && a.longitude_i == b.longitude_i;
}

bool phoneFixHasCoordinates(const meshtastic_Position &position)
{
    return position.has_latitude_i && position.has_longitude_i && (position.latitude_i != 0 || position.longitude_i != 0);
}

uint32_t phoneFixAgeSecs(const meshtastic_Position &position)
{
    if (position.time == 0)
        return UINT32_MAX;
    const uint32_t nowEpoch = getValidTime(RTCQualityFromNet);
    if (nowEpoch == 0)
        return UINT32_MAX;
    return nowEpoch >= position.time ? nowEpoch - position.time : position.time - nowEpoch;
}

bool phoneFixFresh(const meshtastic_Position &position)
{
    const uint32_t age = phoneFixAgeSecs(position);
    return age != UINT32_MAX && age <= PHONE_FIX_MAX_AGE_SECS;
}

bool phoneFixAccurate(const meshtastic_Position &position)
{
    return position.gps_accuracy == 0 || position.gps_accuracy <= PHONE_FIX_MAX_ACCURACY_MM;
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

void resetMotionStateLocked()
{
    motionState = HeltecV3PhoneMotionState{};
    motionState.stabilizingRequired = STATIONARY_CONFIRM_COUNT;
    motionLastFix = meshtastic_Position_init_default;
    motionLastFixValid = false;
    stabilizingAnchor = meshtastic_Position_init_default;
    stabilizingAnchorValid = false;
    stabilizingStartedMs = 0;
    lastStabilizingEvidenceMs = 0;
}

void startMovingLocked(uint32_t stepM)
{
    motionState.available = true;
    motionState.moving = true;
    motionState.stabilizing = false;
    motionState.stationaryConfirmed = false;
    motionState.stabilizingCount = 0;
    motionState.stabilizingRequired = STATIONARY_CONFIRM_COUNT;
    motionState.movementStepM = stepM;
    motionState.stabilizingElapsedSecs = 0;
    motionState.stabilizingRemainingSecs = 0;
    stabilizingAnchorValid = false;
    stabilizingStartedMs = 0;
    lastStabilizingEvidenceMs = 0;
}

void beginStabilizingLocked(const meshtastic_Position &position, uint32_t now)
{
    motionState.available = true;
    motionState.moving = false;
    motionState.stabilizing = true;
    motionState.stationaryConfirmed = false;
    motionState.stabilizingCount = 1;
    motionState.stabilizingRequired = STATIONARY_CONFIRM_COUNT;
    motionState.stabilizingElapsedSecs = 0;
    motionState.stabilizingRemainingSecs = STATIONARY_DWELL_MS / 1000UL;
    stabilizingAnchor = position;
    stabilizingAnchorValid = true;
    stabilizingStartedMs = now ? now : 1;
    lastStabilizingEvidenceMs = stabilizingStartedMs;
}

void finishStabilizingLocked(uint32_t now)
{
    motionState.available = true;
    motionState.moving = false;
    motionState.stabilizing = false;
    motionState.stationaryConfirmed = true;
    motionState.stabilizingCount = STATIONARY_CONFIRM_COUNT;
    motionState.stabilizingRequired = STATIONARY_CONFIRM_COUNT;
    motionState.stabilizingElapsedSecs = STATIONARY_DWELL_MS / 1000UL;
    motionState.stabilizingRemainingSecs = 0;
    motionState.movementStepM = 0;
    stabilizingStartedMs = now ? now : stabilizingStartedMs;
}

void updateStabilizingClockLocked(uint32_t now)
{
    if (!motionState.stabilizing || stabilizingStartedMs == 0)
        return;

    uint32_t elapsedMs = 0;
    if (!Throttle::isWithinTimespanMs(stabilizingStartedMs, STATIONARY_DWELL_MS))
        elapsedMs = STATIONARY_DWELL_MS;
    else
        elapsedMs = (uint32_t)(now - stabilizingStartedMs);

    motionState.stabilizingElapsedSecs = elapsedMs / 1000UL;
    const uint32_t remainingMs = elapsedMs >= STATIONARY_DWELL_MS ? 0U : STATIONARY_DWELL_MS - elapsedMs;
    motionState.stabilizingRemainingSecs = (remainingMs + 999UL) / 1000UL;
}

void observeMotionInternal(const meshtastic_Position &position, bool requireStationaryConfirmation)
{
    if (!phoneFixHasCoordinates(position))
        return;

    const uint32_t now = millis() ? millis() : 1;
    bool logMovingBreak = false;
    bool logMovingStart = false;
    bool logStabilizingStart = false;
    bool logStationary = false;
    uint32_t logStep = 0;
    uint32_t logCluster = 0;
    uint8_t logCount = 0;
    uint32_t logRemaining = 0;
    bool logDuplicate = false;

    portENTER_CRITICAL(&motionMux);
    const bool hadLast = motionLastFixValid;
    const bool duplicate = hadLast && sameCoordinates(motionLastFix, position);
    const uint32_t stepM = hadLast ? distanceMeters(motionLastFix, position) : 0U;
    motionState.available = true;
    motionState.stabilizingRequired = STATIONARY_CONFIRM_COUNT;
    motionState.movementStepM = duplicate ? 0U : stepM;

    if (!hadLast) {
        motionLastFix = position;
        motionLastFixValid = true;
        if (requireStationaryConfirmation) {
            beginStabilizingLocked(position, now);
            logStabilizingStart = true;
        }
        portEXIT_CRITICAL(&motionMux);
        if (logStabilizingStart)
            heltecV3DiagLog("PHONE_POS_MODE", "relocation candidate; require %us stationary dwell",
                            (unsigned)(STATIONARY_DWELL_MS / 1000UL));
        return;
    }

    if (!duplicate)
        motionLastFix = position;

    if (motionState.stabilizing) {
        const uint32_t clusterM = stabilizingAnchorValid ? distanceMeters(stabilizingAnchor, position) : UINT32_MAX;
        if ((!duplicate && stepM >= MOBILE_STEP_M) || !stabilizingAnchorValid || clusterM > STATIONARY_CLUSTER_M) {
            startMovingLocked(stepM >= MOBILE_STEP_M ? stepM : clusterM);
            logMovingBreak = true;
            logStep = stepM;
            logCluster = clusterM;
        } else {
            if (lastStabilizingEvidenceMs == 0 ||
                !Throttle::isWithinTimespanMs(lastStabilizingEvidenceMs, STATIONARY_CONFIRM_SPACING_MS)) {
                if (motionState.stabilizingCount < STATIONARY_CONFIRM_COUNT)
                    motionState.stabilizingCount++;
                lastStabilizingEvidenceMs = now;
            }
            updateStabilizingClockLocked(now);
            const bool dwellReady = stabilizingStartedMs != 0 &&
                                    !Throttle::isWithinTimespanMs(stabilizingStartedMs, STATIONARY_DWELL_MS);
            if (motionState.stabilizingCount >= STATIONARY_CONFIRM_COUNT && dwellReady) {
                finishStabilizingLocked(now);
                logStationary = true;
            } else {
                logCount = motionState.stabilizingCount;
                logRemaining = motionState.stabilizingRemainingSecs;
                logDuplicate = duplicate;
            }
        }
        portEXIT_CRITICAL(&motionMux);

        if (logMovingBreak) {
            heltecV3DiagLog("PHONE_POS_MODE", "moving; stabilization broken step=%um cluster=%um", (unsigned)logStep,
                            logCluster == UINT32_MAX ? 9999U : (unsigned)logCluster);
        } else if (logStationary) {
            heltecV3DiagLog("PHONE_POS_MODE", "stationary confirmed after %us and %u evidence fixes",
                            (unsigned)(STATIONARY_DWELL_MS / 1000UL), (unsigned)STATIONARY_CONFIRM_COUNT);
        } else {
            heltecV3DiagLog("PHONE_POS_STABLE", "stabilizing=%u/%u remaining=%us duplicate=%u", (unsigned)logCount,
                            (unsigned)STATIONARY_CONFIRM_COUNT, (unsigned)logRemaining, logDuplicate ? 1U : 0U);
        }
        return;
    }

    if (motionState.moving) {
        if (!duplicate && stepM >= MOBILE_STEP_M) {
            portEXIT_CRITICAL(&motionMux);
            return;
        }
        beginStabilizingLocked(position, now);
        portEXIT_CRITICAL(&motionMux);
        heltecV3DiagLog("PHONE_POS_MODE", "stabilizing after movement; dwell=%us",
                        (unsigned)(STATIONARY_DWELL_MS / 1000UL));
        return;
    }

    if (!duplicate && stepM >= MOBILE_STEP_M) {
        startMovingLocked(stepM);
        logMovingStart = true;
        logStep = stepM;
    } else if (requireStationaryConfirmation && !motionState.stationaryConfirmed) {
        beginStabilizingLocked(position, now);
        logStabilizingStart = true;
    }
    portEXIT_CRITICAL(&motionMux);

    if (logMovingStart)
        heltecV3DiagLog("PHONE_POS_MODE", "moving step=%um", (unsigned)logStep);
    else if (logStabilizingStart)
        heltecV3DiagLog("PHONE_POS_MODE", "relocation candidate; require %us stationary dwell",
                        (unsigned)(STATIONARY_DWELL_MS / 1000UL));
}

void acceptFixedInternal(const meshtastic_Position &position)
{
    portENTER_CRITICAL(&motionMux);
    sessionBaseline = position;
    sessionBaselineValid = phoneFixHasCoordinates(position);
    lastLiveTxValid = false;
    lastLiveTxPosition = meshtastic_Position_init_default;
    lastLiveTxMs = 0;
    resetMotionStateLocked();
    if (sessionBaselineValid) {
        motionState.available = true;
        motionState.stationaryConfirmed = true;
        motionState.stabilizingRequired = STATIONARY_CONFIRM_COUNT;
        motionLastFix = position;
        motionLastFixValid = true;
        stabilizingAnchor = position;
        stabilizingAnchorValid = true;
    }
    portEXIT_CRITICAL(&motionMux);
}

void resetServicePositionState()
{
    portENTER_CRITICAL(&motionMux);
    sessionBaselineValid = false;
    sessionBaseline = meshtastic_Position_init_default;
    lastLiveTxValid = false;
    lastLiveTxPosition = meshtastic_Position_init_default;
    lastLiveTxMs = 0;
    resetMotionStateLocked();
    portEXIT_CRITICAL(&motionMux);
}

void setSessionBaseline(const meshtastic_Position &position, bool valid)
{
    portENTER_CRITICAL(&motionMux);
    sessionBaseline = position;
    sessionBaselineValid = valid;
    portEXIT_CRITICAL(&motionMux);
}

bool getSessionBaseline(meshtastic_Position &position)
{
    portENTER_CRITICAL(&motionMux);
    const bool valid = sessionBaselineValid;
    position = sessionBaseline;
    portEXIT_CRITICAL(&motionMux);
    return valid;
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

    bool sendPositionToPhone(const meshtastic_Position &position, bool fresh)
    {
        if (!service || !nodeDB || !bleConnected())
            return false;

        meshtastic_Position outgoing = position;
        outgoing.location_source = meshtastic_Position_LocSource_LOC_EXTERNAL;
        meshtastic_MeshPacket *packet = allocDataProtobuf(outgoing);
        if (!packet)
            return false;

        packet->from = nodeDB->getNodeNum();
        packet->to = NODENUM_BROADCAST;
        packet->channel = 0;
        packet->rx_time = getValidTime(RTCQualityFromNet);
        service->sendToPhone(packet);
        heltecV3DiagLog("PHONE_POS_CLIENT", "lat=%d lon=%d fresh=%u", outgoing.latitude_i, outgoing.longitude_i,
                        fresh ? 1U : 0U);
        return true;
    }

    bool broadcastPosition(const meshtastic_Position &position, bool fixed)
    {
        if (!service)
            return false;

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
        } else {
            outgoing.location_source = meshtastic_Position_LocSource_LOC_EXTERNAL;
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
        const uint32_t nowEpoch = getValidTime(RTCQualityFromNet);
        if (nowEpoch != 0) {
            fixed.time = nowEpoch;
            fixed.timestamp = nowEpoch;
        }

        config.position.fixed_position = true;
        nodeDB->setLocalPosition(fixed);
        nodeDB->updatePosition(nodeDB->getNodeNum(), fixed);
        nodeDB->saveToDisk(SEGMENT_CONFIG | SEGMENT_NODEDATABASE);
        heltecV3PhonePositionAcceptFixed(fixed);

        const bool meshSent = broadcastPosition(fixed, true);
        heltecV3DiagNotePositionSave(true, previousDifferenceM);
        heltecV3DiagLog("PHONE_POS_FIXED", "auto lat=%d lon=%d diff=%um mesh=%u phone-time-normalized=%u", fixed.latitude_i,
                        fixed.longitude_i, (unsigned)previousDifferenceM, meshSent ? 1U : 0U, nowEpoch != 0 ? 1U : 0U);
        LOG_INFO("Heltec V3 fixed position auto-updated after stationary dwell: diff=%um mesh=%s",
                 (unsigned)previousDifferenceM, meshSent ? "sent" : "not-sent");
        heltecV3PositionPageRefresh();
        return true;
    }

    void processPhoneFix(const meshtastic_Position &position)
    {
        if (!heltecV3RuntimeServiceActive())
            return;

        const uint32_t now = millis() ? millis() : 1;
        const uint32_t nowEpoch = getValidTime(RTCQualityFromNet);
        const uint32_t age = phoneFixAgeSecs(position);
        const bool coordsOk = phoneFixHasCoordinates(position);
        const bool freshOk = phoneFixFresh(position);
        const bool accuracyOk = phoneFixAccurate(position);

        heltecV3DiagLog("PHONE_POS_RX", "lat=%d lon=%d acc=%umm age=%us local-rx=1", position.latitude_i, position.longitude_i,
                        (unsigned)position.gps_accuracy, age == UINT32_MAX ? 9999U : (unsigned)age);
        LOG_INFO("Heltec V3 phone position: lat=%d lon=%d acc=%umm age=%us coords=%u accurate=%u embedded-time-fresh=%u",
                 position.latitude_i, position.longitude_i, (unsigned)position.gps_accuracy,
                 age == UINT32_MAX ? 9999U : (unsigned)age, coordsOk ? 1U : 0U, accuracyOk ? 1U : 0U, freshOk ? 1U : 0U);

        if (coordsOk) {
            // Keep the phone candidate separate from NodeDB until it is accepted.
            // The client still receives it immediately for map preview/live use.
            sendPositionToPhone(position, freshOk && accuracyOk);
            if (!freshOk)
                heltecV3DiagLog("PHONE_POS_PREVIEW", "embedded phone time old; local receipt still valid for motion/live policy");
        }

        if (!coordsOk || !accuracyOk) {
            heltecV3DiagLog("PHONE_POS_REJECT", "coords=%u accurate=%u", coordsOk ? 1U : 0U, accuracyOk ? 1U : 0U);
            return;
        }

        const uint32_t trackEpoch = nowEpoch != 0 ? nowEpoch : position.time;
        jarnsenPositionTrackNote(position.latitude_i, position.longitude_i, trackEpoch, position.gps_accuracy,
                                 JarnsenTrackSource::PHONE);

        if (!config.position.fixed_position) {
            heltecV3DiagLog("PHONE_POS_REJECT", "fixed-position=off; custom repeater position manager disabled");
            return;
        }

        meshtastic_Position baseline = meshtastic_Position_init_default;
        if (!getSessionBaseline(baseline)) {
            const bool loaded = loadSavedPosition(baseline);
            setSessionBaseline(baseline, loaded);
            if (!loaded) {
                heltecV3PhoneMotionObserve(position, false);
                heltecV3DiagLog("PHONE_POS_WAIT", "no saved fixed position; use 1.2s hold save once");
                return;
            }
        }

        const uint32_t differenceFromSaved = distanceMeters(baseline, position);
        const bool requireStationaryConfirmation = differenceFromSaved > RELOCATION_MIN_DISTANCE_M;
        heltecV3PhoneMotionObserve(position, requireStationaryConfirmation);

        HeltecV3PhoneMotionState motion;
        heltecV3GetPhoneMotionState(motion);

        if (motion.moving) {
            const uint32_t distanceThreshold = liveDistanceThresholdM();
            meshtastic_Position previousLive = meshtastic_Position_init_default;
            bool previousLiveValid = false;
            uint32_t previousLiveMs = 0;
            portENTER_CRITICAL(&motionMux);
            previousLive = lastLiveTxPosition;
            previousLiveValid = lastLiveTxValid;
            previousLiveMs = lastLiveTxMs;
            portEXIT_CRITICAL(&motionMux);

            const uint32_t referenceDistance =
                previousLiveValid ? distanceMeters(previousLive, position) : differenceFromSaved;
            const bool intervalReady =
                previousLiveMs == 0 || !Throttle::isWithinTimespanMs(previousLiveMs, liveIntervalMs());

            if (referenceDistance >= distanceThreshold && intervalReady) {
                meshtastic_Position live = position;
                if (nowEpoch != 0) {
                    live.time = nowEpoch;
                    live.timestamp = nowEpoch;
                }
                const bool sent = broadcastPosition(live, false);
                heltecV3DiagLog("PHONE_POS_LIVE", "saved-diff=%um step=%um tx=%u min=%um/%us smart=%u stale-embedded=%u",
                                (unsigned)differenceFromSaved, (unsigned)referenceDistance, sent ? 1U : 0U,
                                (unsigned)distanceThreshold, (unsigned)(liveIntervalMs() / 1000UL),
                                config.position.position_broadcast_smart_enabled ? 1U : 0U, freshOk ? 0U : 1U);
                if (sent) {
                    portENTER_CRITICAL(&motionMux);
                    lastLiveTxPosition = live;
                    lastLiveTxValid = true;
                    lastLiveTxMs = now;
                    portEXIT_CRITICAL(&motionMux);
                }
            }
            return;
        }

        if (motion.stabilizing) {
            heltecV3DiagLog("PHONE_POS_STABLE", "candidate=%u/%u remaining=%us diff=%um", (unsigned)motion.stabilizingCount,
                            (unsigned)motion.stabilizingRequired, (unsigned)motion.stabilizingRemainingSecs,
                            (unsigned)differenceFromSaved);
            return;
        }

        if (requireStationaryConfirmation && motion.stationaryConfirmed) {
            saveFixedPosition(position, differenceFromSaved);
            return;
        }

        if (motion.stationaryConfirmed) {
            portENTER_CRITICAL(&motionMux);
            lastLiveTxValid = false;
            lastLiveTxMs = 0;
            portEXIT_CRITICAL(&motionMux);
        }
    }

  protected:
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

        if (!worker)
            worker = new V3PhonePositionWorker(this);

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
    const uint32_t now = millis() ? millis() : 1;

    if (!serviceActive) {
        if (serviceWasActive) {
            heltecV3DiagLog("PHONE_SERVICE", "closed");
            LOG_INFO("Heltec V3 phone service closed");
        }
        serviceWasActive = false;
        bleWasConnected = false;
        serviceHoldOwned = false;
        serviceHoldLastActiveMs = 0;
        resetServicePositionState();
        return 500;
    }

    if (!serviceWasActive) {
        serviceWasActive = true;
        serviceHoldOwned = true;
        serviceHoldLastActiveMs = now;
        heltecV3RuntimeSetBleQueueHold(true);
        resetServicePositionState();
        meshtastic_Position baseline = meshtastic_Position_init_default;
        const bool baselineValid = loadSavedPosition(baseline);
        setSessionBaseline(baseline, baselineValid);
        heltecV3DiagLog("PHONE_SERVICE", "opened tail=%us baseline=%u stationary-dwell=%us",
                        (unsigned)(SERVICE_TAIL_MS / 1000UL), baselineValid ? 1U : 0U,
                        (unsigned)(STATIONARY_DWELL_MS / 1000UL));
        LOG_INFO("Heltec V3 phone service opened; BLE hold tail=%us", (unsigned)(SERVICE_TAIL_MS / 1000UL));
    }

    const bool connected = bleConnected();
    const bool pressed = buttonPressed();

    if (connected != bleWasConnected) {
        bleWasConnected = connected;
        serviceHoldLastActiveMs = now;
        serviceHoldOwned = true;
        heltecV3RuntimeSetBleQueueHold(true);
        heltecV3DiagLog("PHONE_BT", "%s tail=%us", connected ? "connected" : "disconnected",
                        (unsigned)(SERVICE_TAIL_MS / 1000UL));
        LOG_INFO("Heltec V3 service: BLE %s; %s", connected ? "connected" : "disconnected",
                 connected ? "hold latched while connected" : "20s disconnect tail started");
    }

    if (connected || pressed) {
        serviceHoldLastActiveMs = now;
        if (!serviceHoldOwned) {
            serviceHoldOwned = true;
            heltecV3RuntimeSetBleQueueHold(true);
        }
    } else if (serviceHoldOwned && serviceHoldLastActiveMs != 0 &&
               !Throttle::isWithinTimespanMs(serviceHoldLastActiveMs, SERVICE_TAIL_MS)) {
        serviceHoldOwned = false;
        heltecV3RuntimeSetBleQueueHold(false);
        heltecV3DiagLog("PHONE_SERVICE", "20s tail expired; BLE may park");
        LOG_INFO("Heltec V3 service: 20s BLE tail expired");
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

void heltecV3PhoneMotionObserve(const meshtastic_Position &position, bool requireStationaryConfirmation)
{
    observeMotionInternal(position, requireStationaryConfirmation);
}

bool heltecV3GetPhoneMotionState(HeltecV3PhoneMotionState &out)
{
    const uint32_t now = millis() ? millis() : 1;
    portENTER_CRITICAL(&motionMux);
    updateStabilizingClockLocked(now);
    out = motionState;
    portEXIT_CRITICAL(&motionMux);
    return out.available;
}

void heltecV3PhonePositionAcceptFixed(const meshtastic_Position &position)
{
    if (!phoneFixHasCoordinates(position))
        return;
    acceptFixedInternal(position);
}

#endif // _VARIANT_HELTEC_V3
