#include "jarnsen/core/runtime/JarnsenTakRepeaterPolicy.h"

#include "configuration.h"
#include "jarnsen/core/roles/JarnsenRolePersistence.h"
#include "jarnsen/core/service/JarnsenDiagnosticLog.h"
#include "jarnsen/core/status/JarnsenStatusProvider.h"
#include "jarnsen/hardware/JarnsenHardwareProfiles.h"

#if defined(HELTEC_TRACKER_V1_1) || defined(HELTEC_V3) || defined(_VARIANT_HELTEC_V3) || defined(HELTEC_V4) || \
    defined(_VARIANT_HELTEC_V4) || defined(SEEED_WIO_TRACKER_L1) || defined(TBEAM_V10) || \
    defined(LILYGO_TBEAM_S3_CORE)
#define JARNSEN_TAK_REPEATER_TARGET 1
#else
#define JARNSEN_TAK_REPEATER_TARGET 0
#endif

#if JARNSEN_TAK_REPEATER_TARGET

#include "FSCommon.h"
#include "NodeDB.h"
#include "PowerStatus.h"
#include "SPILock.h"
#include "airtime.h"
#include "concurrency/LockGuard.h"
#include "concurrency/OSThread.h"
#include "jarnsen/core/bluetooth/JarnsenBluetoothPolicy.h"
#include "main.h"
#include "mesh/RadioInterface.h"
#include "mesh/Router.h"
#include "mesh/http/JarnsenServiceWeb.h"
#include "modules/PositionModule.h"
#include "sleep.h"

#if !MESHTASTIC_EXCLUDE_GPS
#include "GPS.h"
#endif

#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
#include "nimble/NimbleBluetooth.h"
#endif

#if defined(HELTEC_TRACKER_V1_1)
#include "vehicle/TrackerPowerMonitor.h"
#endif

#include <Arduino.h>
#include <atomic>
#include <cstdio>

#ifdef ARCH_ESP32
#include <esp_sleep.h>
#include <esp_system.h>
#endif

#if (defined(ARCH_NRF52) || defined(ARCH_NRF54L15)) && !MESHTASTIC_EXCLUDE_BLUETOOTH
void setBluetoothEnable(bool enable);
#endif

namespace jarnsen
{
namespace
{

constexpr uint32_t TAK_SMART_DISTANCE_M = 75U;
constexpr uint32_t TAK_SMART_MIN_INTERVAL_SECS = 75U;
constexpr uint32_t TAK_MOBILE_POSITION_SECS = 60UL * 60UL;
constexpr uint32_t TAK_STATIONARY_POSITION_SECS = 12UL * 60UL * 60UL;
constexpr uint32_t TAK_GPS_UPDATE_SECS = 5U;
constexpr uint32_t TAK_LIGHT_SLEEP_CYCLE_SECS = 5UL * 60UL;
constexpr uint32_t TAK_NODEINFO_BASE_SECS = 3UL * 60UL * 60UL;
constexpr uint32_t TAK_TELEMETRY_BASE_SECS = 30UL * 60UL;
constexpr uint32_t TAK_SERVICE_IDLE_MS = 120UL * 1000UL;
constexpr uint32_t TAK_SERVICE_HARD_CAP_MS = 15UL * 60UL * 1000UL;
constexpr uint32_t TAK_SERVICE_BUTTON_HOLD_MS = 2000UL;
constexpr uint32_t TAK_HEALTH_LOG_MS = 60UL * 1000UL;
constexpr uint32_t TAK_DYNAMIC_POLICY_MS = 5000UL;
constexpr uint32_t WATCH_SILENCE_MS = 30UL * 60UL * 1000UL;
constexpr uint32_t WATCH_CONFIRM_MS = 10UL * 60UL * 1000UL;
constexpr float WATCH_CHANNEL_BUSY_PERCENT = 5.0f;

constexpr const char *HEALTH_PATH = "/prefs/jarnsen-tak-repeater-health-v1";
constexpr uint32_t HEALTH_MAGIC = 0x4A545231U;
constexpr uint8_t HEALTH_VERSION = 1U;

struct HealthRecord {
    uint32_t magic;
    uint8_t version;
    uint8_t reserved[3];
    uint32_t bootCount;
    uint32_t watchdogReboots;
    uint32_t checksum;
};

std::atomic<bool> serviceWindowActive{false};
std::atomic<uint32_t> serviceStartedMs{0};
std::atomic<uint32_t> serviceLastActivityMs{0};
std::atomic<uint32_t> rxPackets{0};
std::atomic<uint32_t> txPackets{0};
std::atomic<uint32_t> forwardedPackets{0};
std::atomic<uint32_t> lastRxMs{0};
std::atomic<uint32_t> lastTxMs{0};
std::atomic<uint32_t> lightSleepEntries{0};
std::atomic<uint32_t> lightSleepWakes{0};
std::atomic<uint8_t> lastLightSleepWakeCause{0};

bool runtimeInitialized = false;
bool fixedModeKnown = false;
bool previousFixedMode = false;
bool previousUsbKnown = false;
bool previousUsb = false;
bool previousGpsConnected = false;
bool noDisplayButtonWasPressed = false;
bool noDisplayButtonHandled = false;
uint32_t noDisplayButtonPressedMs = 0;
uint32_t lastHealthLogMs = 0;
uint32_t lastDynamicPolicyMs = 0;
uint32_t lastObservedPositionTxMs = 0;
uint32_t positionTxCount = 0;
uint32_t usbDropCount = 0;
uint32_t usbRestoreCount = 0;
uint32_t minFreeHeap = 0;
uint8_t airtimeTier = 0xffU;
uint8_t watchdogStage = 0;
uint8_t watchdogReconfigureFailures = 0;
uint32_t watchdogStageStartedMs = 0;
uint32_t bootCount = 0;
uint32_t watchdogReboots = 0;
uint32_t resetReason = 0;
uint32_t observedBleTraffic = 0;

uint32_t healthChecksum(const HealthRecord &record)
{
    return record.magic ^ ((uint32_t)record.version << 24) ^ record.bootCount ^ (record.watchdogReboots << 1U) ^
           0x6B9214D3U;
}

void loadHealthRecord()
{
#ifdef FSCom
    concurrency::LockGuard guard(spiLock);
    File file = FSCom.open(HEALTH_PATH, FILE_O_READ);
    if (!file)
        return;
    HealthRecord record{};
    const size_t got = file.read(reinterpret_cast<uint8_t *>(&record), sizeof(record));
    file.close();
    if (got != sizeof(record) || record.magic != HEALTH_MAGIC || record.version != HEALTH_VERSION ||
        record.checksum != healthChecksum(record))
        return;
    bootCount = record.bootCount;
    watchdogReboots = record.watchdogReboots;
#endif
}

void saveHealthRecord()
{
#ifdef FSCom
    HealthRecord record{};
    record.magic = HEALTH_MAGIC;
    record.version = HEALTH_VERSION;
    record.bootCount = bootCount;
    record.watchdogReboots = watchdogReboots;
    record.checksum = healthChecksum(record);

    concurrency::LockGuard guard(spiLock);
    if (FSCom.exists(HEALTH_PATH))
        FSCom.remove(HEALTH_PATH);
    File file = FSCom.open(HEALTH_PATH, FILE_O_WRITE);
    if (!file)
        return;
    file.write(reinterpret_cast<const uint8_t *>(&record), sizeof(record));
    file.flush();
    file.close();
#endif
}

uint16_t percentX10(float value)
{
    if (value <= 0.0f)
        return 0;
    if (value >= 100.0f)
        return 1000U;
    return (uint16_t)(value * 10.0f + 0.5f);
}

uint32_t ageSecs(uint32_t whenMs)
{
    if (whenMs == 0)
        return UINT32_MAX;
    return (uint32_t)(millis() - whenMs) / 1000UL;
}

bool usbPowered()
{
    return powerStatus && powerStatus->isInitialized() && powerStatus->getHasUSB();
}

bool boardCanUseGps()
{
    const auto profile = currentHardwareRoleProfile();
    return profile.hardware.capabilities.internalGps || profile.hardware.capabilities.supportsExternalGps;
}

TakRepeaterPositionMode currentPositionMode()
{
    if (config.position.fixed_position)
        return TakRepeaterPositionMode::FIXED;
    return boardCanUseGps() ? TakRepeaterPositionMode::MOBILE : TakRepeaterPositionMode::NO_POSITION;
}

bool localPositionAvailable()
{
    if (!nodeDB)
        return false;
    meshtastic_PositionLite position{};
    return nodeDB->copyNodePosition(nodeDB->getNodeNum(), position) &&
           (position.latitude_i != 0 || position.longitude_i != 0);
}

bool gpsConnected()
{
#if !MESHTASTIC_EXCLUDE_GPS
    return gps && gps->isConnected();
#else
    return false;
#endif
}

bool gpsHasFix()
{
#if !MESHTASTIC_EXCLUDE_GPS
    return gps && gps->hasLock() && localPositionAvailable();
#else
    return false;
#endif
}

void applyGpsRuntime()
{
#if !MESHTASTIC_EXCLUDE_GPS
    if (!gps)
        return;
    if (currentPositionMode() == TakRepeaterPositionMode::MOBILE) {
        if (!gps->isEnabled())
            gps->enable();
        gps->up();
    } else if (gps->isEnabled()) {
        gps->disable();
    }
#endif
}

EffectiveCapabilities boardCapabilities()
{
    const auto profile = currentHardwareRoleProfile();
    return resolveCapabilities(profile.hardware.capabilities, PeripheralCapabilities{});
}

void bluetoothOn()
{
#if !MESHTASTIC_EXCLUDE_BLUETOOTH
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2)
    config.bluetooth.enabled = true;
    const auto caps = boardCapabilities();
    applyNimbleBluetoothLifecycle(nimbleBluetooth, caps, true);
#elif defined(ARCH_NRF52) || defined(ARCH_NRF54L15)
    config.bluetooth.enabled = true;
    setBluetoothEnable(true);
#endif
#endif
}

void bluetoothOff()
{
#if !MESHTASTIC_EXCLUDE_BLUETOOTH
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2)
    config.bluetooth.enabled = false;
    const auto caps = boardCapabilities();
    applyNimbleBluetoothLifecycle(nimbleBluetooth, caps, false);
#elif defined(ARCH_NRF52) || defined(ARCH_NRF54L15)
    if (!config.bluetooth.enabled)
        config.bluetooth.enabled = true;
    setBluetoothEnable(false);
    config.bluetooth.enabled = false;
#endif
#endif
}

bool bluetoothConnected()
{
#if !MESHTASTIC_EXCLUDE_BLUETOOTH
#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2)
    return nimbleBluetooth && nimbleBluetooth->isConnected();
#elif defined(ARCH_NRF52)
    return nrf52Bluetooth && nrf52Bluetooth->isConnected();
#elif defined(ARCH_NRF54L15)
    return nrf54l15Bluetooth && nrf54l15Bluetooth->isConnected();
#endif
#endif
    return false;
}

int configuredButtonPin()
{
#ifdef BUTTON_PIN
    return config.device.button_gpio ? (int)config.device.button_gpio : (int)BUTTON_PIN;
#else
    return -1;
#endif
}

bool boardHasLocalDisplay()
{
    return currentHardwareRoleProfile().hardware.capabilities.display.present;
}

void updateNoDisplayServiceButton(uint32_t now)
{
    if (boardHasLocalDisplay())
        return;
    const int pin = configuredButtonPin();
    if (pin < 0)
        return;

    const bool pressed = digitalRead((uint8_t)pin) == LOW;
    if (pressed) {
        if (!noDisplayButtonWasPressed) {
            noDisplayButtonWasPressed = true;
            noDisplayButtonHandled = false;
            noDisplayButtonPressedMs = now ? now : 1U;
        } else if (!noDisplayButtonHandled &&
                   (uint32_t)(now - noDisplayButtonPressedMs) >= TAK_SERVICE_BUTTON_HOLD_MS) {
            noDisplayButtonHandled = true;
            if (serviceWindowActive.load())
                takRepeaterServiceClose("button");
            else
                takRepeaterServiceOpen();
        }
    } else {
        noDisplayButtonWasPressed = false;
        noDisplayButtonHandled = false;
        noDisplayButtonPressedMs = 0;
    }
}

void updateServiceWindow(uint32_t now)
{
    if (!serviceWindowActive.load())
        return;

#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
    if (nimbleBluetooth) {
        const uint32_t traffic = nimbleBluetooth->getMeaningfulTrafficCount();
        if (traffic != observedBleTraffic) {
            observedBleTraffic = traffic;
            serviceLastActivityMs.store(now ? now : 1U);
            diagnosticLog("TAK_REP_SERVICE", "BLE_ACTIVITY");
        }
    }
#else
    if (bluetoothConnected())
        serviceLastActivityMs.store(now ? now : 1U);
#endif

    jarnsenServiceWebPump();

    const uint32_t started = serviceStartedMs.load();
    const uint32_t last = serviceLastActivityMs.load();
    const bool hardCap = started && (uint32_t)(now - started) >= TAK_SERVICE_HARD_CAP_MS;
    const bool idle = last && (uint32_t)(now - last) >= TAK_SERVICE_IDLE_MS;
    if (hardCap)
        takRepeaterServiceClose("hard-cap");
    else if (idle)
        takRepeaterServiceClose("idle");
}

void updateAirtimePolicy(uint32_t now)
{
    if ((uint32_t)(now - lastDynamicPolicyMs) < TAK_DYNAMIC_POLICY_MS)
        return;
    lastDynamicPolicyMs = now;

    const float cu = airTime ? airTime->channelUtilizationPercent() : 0.0f;
    uint8_t tier = 0;
    uint32_t nodeInfoSecs = TAK_NODEINFO_BASE_SECS;
    uint32_t telemetrySecs = TAK_TELEMETRY_BASE_SECS;
    uint32_t smartMinSecs = TAK_SMART_MIN_INTERVAL_SECS;

    if (cu >= 25.0f) {
        tier = 2;
        nodeInfoSecs = 12UL * 60UL * 60UL;
        telemetrySecs = 2UL * 60UL * 60UL;
        smartMinSecs = 10UL * 60UL;
    } else if (cu >= 15.0f) {
        tier = 1;
        nodeInfoSecs = 6UL * 60UL * 60UL;
        telemetrySecs = 60UL * 60UL;
        smartMinSecs = 3UL * 60UL;
    }

    // Only our own metadata/position cadence is changed. Forwarded mesh
    // packets are never throttled here.
    config.device.node_info_broadcast_secs = nodeInfoSecs;
    moduleConfig.telemetry.device_update_interval = telemetrySecs;
    if (!config.position.fixed_position && boardCanUseGps())
        config.position.broadcast_smart_minimum_interval_secs = smartMinSecs;

    if (tier != airtimeTier) {
        airtimeTier = tier;
        diagnosticLog("TAK_REP_AIRTIME", "tier=%u cu=%.1f%% nodeinfo=%us telemetry=%us smart_min=%us forwarding=unchanged",
                      (unsigned)tier, (double)cu, (unsigned)nodeInfoSecs, (unsigned)telemetrySecs,
                      (unsigned)smartMinSecs);
    }
}

void updatePositionAccounting()
{
    if (!positionModule)
        return;
    const uint32_t sent = positionModule->lastPositionSendMs();
    if (sent != 0 && sent != lastObservedPositionTxMs) {
        lastObservedPositionTxMs = sent;
        positionTxCount++;
#if defined(HELTEC_TRACKER_V1_1)
        trackerPowerMonitorNotePositionTx();
#endif
        diagnosticLog("TAK_REP_POSITION", "tx=%u mode=%s", (unsigned)positionTxCount,
                      takRepeaterPositionModeKey(currentPositionMode()));
    }
}

void updatePowerAndHealth(uint32_t now)
{
    const bool usb = usbPowered();
    if (!previousUsbKnown) {
        previousUsbKnown = true;
        previousUsb = usb;
    } else if (usb != previousUsb) {
        if (usb)
            usbRestoreCount++;
        else
            usbDropCount++;
        previousUsb = usb;
        diagnosticLog("TAK_REP_POWER", "%s drops=%u restores=%u battery=%u%%",
                      usb ? "USB_RESTORED" : "USB_LOST_BATTERY", (unsigned)usbDropCount,
                      (unsigned)usbRestoreCount,
                      powerStatus && powerStatus->getHasBattery() ? (unsigned)powerStatus->getBatteryChargePercent() : 0U);
    }

    const bool gpsNow = gpsConnected();
    if (gpsNow != previousGpsConnected) {
        previousGpsConnected = gpsNow;
        diagnosticLog("TAK_REP_GPS", "connected=%u mode=%s fix=%u", gpsNow ? 1U : 0U,
                      takRepeaterPositionModeKey(currentPositionMode()), gpsHasFix() ? 1U : 0U);
    }

#ifdef ARCH_ESP32
    const uint32_t freeHeap = ESP.getFreeHeap();
    if (minFreeHeap == 0 || freeHeap < minFreeHeap)
        minFreeHeap = freeHeap;
#endif

    updatePositionAccounting();

#if defined(HELTEC_TRACKER_V1_1)
#if !MESHTASTIC_EXCLUDE_GPS
    const bool moving = currentPositionMode() == TakRepeaterPositionMode::MOBILE && gpsHasFix() && gps &&
                        (float)gps->p.ground_speed >= 2.0f;
    const bool gnssActive = gps && gps->isEnabled();
#else
    const bool moving = false;
    const bool gnssActive = false;
#endif
    const bool parked = currentPositionMode() == TakRepeaterPositionMode::FIXED || !moving;
    trackerPowerMonitorTick(moving, parked, gnssActive, serviceWindowActive.load(),
                            screen && screen->isScreenOn());
#endif

    if (lastHealthLogMs == 0 || (uint32_t)(now - lastHealthLogMs) >= TAK_HEALTH_LOG_MS) {
        lastHealthLogMs = now ? now : 1U;
        const TakRepeaterStats s = takRepeaterStats();
        diagnosticLog("TAK_REP_HEALTH",
                      "mode=%s boot=%u reset=%u rx=%u tx=%u fwd=%u radio_age=%us pos_tx=%u gps=%u fix=%u "
                      "cu=%u.%u%% airtx=%u.%u%% usb=%u drops=%u restores=%u service=%u wlan=%u "
                      "ls=%u wakes=%u heap_min=%u watchdog=%u",
                      takRepeaterPositionModeKey(s.positionMode), (unsigned)s.bootCount, (unsigned)s.resetReason,
                      (unsigned)s.rxPackets, (unsigned)s.txPackets, (unsigned)s.forwardedPackets,
                      s.lastRadioAgeSecs == UINT32_MAX ? 0U : (unsigned)s.lastRadioAgeSecs, (unsigned)s.positionTxCount,
                      s.gpsConnected ? 1U : 0U, s.gpsFix ? 1U : 0U, (unsigned)(s.channelUtilizationX10 / 10U),
                      (unsigned)(s.channelUtilizationX10 % 10U), (unsigned)(s.txAirUtilizationX10 / 10U),
                      (unsigned)(s.txAirUtilizationX10 % 10U), s.usbPowered ? 1U : 0U, (unsigned)s.usbDropCount,
                      (unsigned)s.usbRestoreCount, s.serviceActive ? 1U : 0U, s.wifiServiceActive ? 1U : 0U,
                      (unsigned)s.lightSleepEntries, (unsigned)s.lightSleepWakes, (unsigned)s.minFreeHeap,
                      (unsigned)s.watchdogStage);
    }
}

void resetWatchdog()
{
    watchdogStage = 0;
    watchdogReconfigureFailures = 0;
    watchdogStageStartedMs = 0;
}

void updateRadioWatchdog(uint32_t now)
{
    const float cu = airTime ? airTime->channelUtilizationPercent() : 0.0f;
    const uint32_t lastRx = lastRxMs.load();
    if (cu < WATCH_CHANNEL_BUSY_PERCENT || lastRx == 0 || (uint32_t)(now - lastRx) < WATCH_SILENCE_MS) {
        resetWatchdog();
        return;
    }

    if (watchdogStage == 0) {
        watchdogStage = 1;
        watchdogStageStartedMs = now ? now : 1U;
        diagnosticLog("TAK_REP_WATCHDOG", "suspect rx_silence=%us cu=%.1f%% action=observe",
                      (unsigned)((now - lastRx) / 1000UL), (double)cu);
        return;
    }

    if ((uint32_t)(now - watchdogStageStartedMs) < WATCH_CONFIRM_MS)
        return;

    RadioInterface *radio = router ? router->getRadioIface() : nullptr;
    const bool recovered = radio && radio->reconfigure();
    watchdogStageStartedMs = now ? now : 1U;
    watchdogStage = 2;
    if (recovered) {
        watchdogReconfigureFailures = 0;
        diagnosticLog("TAK_REP_WATCHDOG", "radio_reconfigure=ok rx_silence=%us cu=%.1f%% reboot=0",
                      (unsigned)((now - lastRx) / 1000UL), (double)cu);
        return;
    }

    if (watchdogReconfigureFailures < UINT8_MAX)
        watchdogReconfigureFailures++;
    diagnosticLog("TAK_REP_WATCHDOG", "radio_reconfigure=failed failures=%u rx_silence=%us cu=%.1f%%",
                  (unsigned)watchdogReconfigureFailures, (unsigned)((now - lastRx) / 1000UL), (double)cu);

    if (watchdogReconfigureFailures >= 2U && rebootAtMsec == 0) {
        watchdogStage = 3;
        watchdogReboots++;
        saveHealthRecord();
        diagnosticLog("TAK_REP_WATCHDOG", "reboot=scheduled delay=5s reason=two_reconfigure_failures");
        rebootAtMsec = now + 5000UL;
    }
}

class TakRepeaterRxObserver final : public Observer<uint32_t>
{
  protected:
    int onNotify(uint32_t) override
    {
        if (!takRepeaterRoleActive())
            return 0;
        rxPackets.fetch_add(1U);
        const uint32_t now = millis();
        lastRxMs.store(now ? now : 1U);
        return 0;
    }
};

TakRepeaterRxObserver rxObserver;
bool rxObserverInstalled = false;

#ifdef ARCH_ESP32
class TakRepeaterLightSleepBeginObserver final : public Observer<void *>
{
  protected:
    int onNotify(void *) override
    {
        if (!takRepeaterRoleActive())
            return 0;
        lightSleepEntries.fetch_add(1U);
#if defined(HELTEC_TRACKER_V1_1)
        trackerPowerMonitorPrepareForLightSleep();
#endif
        return 0;
    }
};

class TakRepeaterLightSleepEndObserver final : public Observer<esp_sleep_wakeup_cause_t>
{
  protected:
    int onNotify(esp_sleep_wakeup_cause_t cause) override
    {
        if (!takRepeaterRoleActive())
            return 0;
        lightSleepWakes.fetch_add(1U);
        lastLightSleepWakeCause.store((uint8_t)cause);
#if defined(HELTEC_TRACKER_V1_1)
        trackerPowerMonitorCompleteLightSleep();
#endif
        return 0;
    }
};

class TakRepeaterDeepSleepObserver final : public Observer<void *>
{
  protected:
    int onNotify(void *deepSleep) override
    {
        if (takRepeaterRoleActive() && deepSleep)
            diagnosticLog("TAK_REP_SLEEP", "deep_request=critical_or_shutdown allowed=1 normal_mode=light_sleep");
        return 0;
    }
};

TakRepeaterLightSleepBeginObserver lightSleepBeginObserver;
TakRepeaterLightSleepEndObserver lightSleepEndObserver;
TakRepeaterDeepSleepObserver deepSleepObserver;
bool sleepObserversInstalled = false;
#endif

class TakRepeaterRuntimeThread final : public concurrency::OSThread
{
  public:
    TakRepeaterRuntimeThread() : concurrency::OSThread("JarnsenTakRep") {}

  protected:
    int32_t runOnce() override
    {
        if (!takRepeaterRoleActive()) {
            if (serviceWindowActive.load())
                takRepeaterServiceClose("role-changed");
            return 1000;
        }

        const uint32_t now = millis();
        const bool fixed = config.position.fixed_position;
        if (!fixedModeKnown || fixed != previousFixedMode) {
            previousFixedMode = fixed;
            fixedModeKnown = true;
            if (!takRepeaterApplyBaseConfig(true))
                diagnosticLog("TAK_REP_PROFILE", "mode_update persist=ERROR");
            applyGpsRuntime();
            diagnosticLog("TAK_REP_MODE", "mode=%s fixed=%u gps_capable=%u",
                          takRepeaterPositionModeKey(currentPositionMode()), fixed ? 1U : 0U,
                          boardCanUseGps() ? 1U : 0U);
        } else {
            applyGpsRuntime();
        }

        updateNoDisplayServiceButton(now);
        updateServiceWindow(now);
        updateAirtimePolicy(now);
        updatePowerAndHealth(now);
        updateRadioWatchdog(now);
        return 1000;
    }
};

TakRepeaterRuntimeThread *runtimeThread = nullptr;

} // namespace

bool takRepeaterRoleActive()
{
    return activeDeviceRoleIs(DeviceRole::TAK_REPEATER);
}

const char *takRepeaterPositionModeKey(TakRepeaterPositionMode mode)
{
    switch (mode) {
    case TakRepeaterPositionMode::FIXED:
        return "fixed";
    case TakRepeaterPositionMode::MOBILE:
        return "mobile";
    case TakRepeaterPositionMode::NO_POSITION:
    default:
        return "no_position";
    }
}

bool takRepeaterApplyBaseConfig(bool persist)
{
    if (!takRepeaterRoleActive())
        return false;

    DeviceRole persisted = DeviceRole::UNCONFIGURED;
    if (!readPersistedDeviceRole(persisted) || persisted != DeviceRole::TAK_REPEATER) {
        if (!writePersistedDeviceRole(DeviceRole::TAK_REPEATER)) {
            diagnosticLog("TAK_REP_PROFILE", "role_persist=ERROR");
            return false;
        }
    }

    bool configChanged = false;
    bool moduleChanged = false;

#define SET_CONFIG_IF_CHANGED(field, value)                                                                                      \
    do {                                                                                                                         \
        const auto desiredValue = (value);                                                                                       \
        if ((field) != desiredValue) {                                                                                           \
            (field) = desiredValue;                                                                                              \
            configChanged = true;                                                                                                \
        }                                                                                                                        \
    } while (0)

#define SET_MODULE_IF_CHANGED(field, value)                                                                                      \
    do {                                                                                                                         \
        const auto desiredValue = (value);                                                                                       \
        if ((field) != desiredValue) {                                                                                           \
            (field) = desiredValue;                                                                                              \
            moduleChanged = true;                                                                                                \
        }                                                                                                                        \
    } while (0)

    SET_CONFIG_IF_CHANGED(config.device.role, meshtastic_Config_DeviceConfig_Role_ROUTER_LATE);
    SET_CONFIG_IF_CHANGED(config.device.rebroadcast_mode, meshtastic_Config_DeviceConfig_RebroadcastMode_ALL);
#ifdef BUTTON_PIN
    SET_CONFIG_IF_CHANGED(config.device.button_gpio, (uint8_t)BUTTON_PIN);
#endif
    SET_CONFIG_IF_CHANGED(config.device.disable_triple_click, true);
    SET_CONFIG_IF_CHANGED(config.device.led_heartbeat_disabled, true);
    SET_CONFIG_IF_CHANGED(config.power.is_power_saving, false);
    SET_CONFIG_IF_CHANGED(config.power.min_wake_secs, 1U);
    SET_CONFIG_IF_CHANGED(config.power.ls_secs, TAK_LIGHT_SLEEP_CYCLE_SECS);
    SET_CONFIG_IF_CHANGED(config.power.wait_bluetooth_secs, 1U);
    SET_CONFIG_IF_CHANGED(config.network.wifi_enabled, false);
    SET_CONFIG_IF_CHANGED(config.bluetooth.enabled, false);
    SET_CONFIG_IF_CHANGED(config.display.screen_on_secs, 20U);
    SET_CONFIG_IF_CHANGED(config.device.node_info_broadcast_secs, TAK_NODEINFO_BASE_SECS);

    const TakRepeaterPositionMode mode = currentPositionMode();
#if !MESHTASTIC_EXCLUDE_GPS
    SET_CONFIG_IF_CHANGED(config.position.gps_mode,
                          mode == TakRepeaterPositionMode::MOBILE ? meshtastic_Config_PositionConfig_GpsMode_ENABLED
                                                                 : meshtastic_Config_PositionConfig_GpsMode_DISABLED);
    SET_CONFIG_IF_CHANGED(config.position.gps_update_interval, TAK_GPS_UPDATE_SECS);
#endif
    SET_CONFIG_IF_CHANGED(config.position.position_broadcast_smart_enabled, mode == TakRepeaterPositionMode::MOBILE);
    SET_CONFIG_IF_CHANGED(config.position.broadcast_smart_minimum_distance, TAK_SMART_DISTANCE_M);
    SET_CONFIG_IF_CHANGED(config.position.broadcast_smart_minimum_interval_secs, TAK_SMART_MIN_INTERVAL_SECS);
    SET_CONFIG_IF_CHANGED(config.position.position_broadcast_secs,
                          mode == TakRepeaterPositionMode::FIXED ? TAK_STATIONARY_POSITION_SECS : TAK_MOBILE_POSITION_SECS);

    SET_MODULE_IF_CHANGED(moduleConfig.telemetry.device_telemetry_enabled, true);
    SET_MODULE_IF_CHANGED(moduleConfig.telemetry.device_update_interval, TAK_TELEMETRY_BASE_SECS);

#undef SET_MODULE_IF_CHANGED
#undef SET_CONFIG_IF_CHANGED

    if (persist && (configChanged || moduleChanged)) {
        int segments = 0;
        if (configChanged)
            segments |= SEGMENT_CONFIG;
        if (moduleChanged)
            segments |= SEGMENT_MODULECONFIG;
        if (!nodeDB || !nodeDB->saveToDisk(segments)) {
            diagnosticLog("TAK_REP_PROFILE", "persist=ERROR config=%u module=%u", configChanged ? 1U : 0U,
                          moduleChanged ? 1U : 0U);
            return false;
        }
    }

    if (configChanged || moduleChanged)
        diagnosticLog("TAK_REP_PROFILE",
                      "applied mode=%s router=ROUTER_LATE rebroadcast=ALL light_sleep=%us fixed_preserved=%u persist=%u",
                      takRepeaterPositionModeKey(mode), (unsigned)TAK_LIGHT_SLEEP_CYCLE_SECS,
                      config.position.fixed_position ? 1U : 0U, persist ? 1U : 0U);
    return true;
}

bool takRepeaterServiceOpen()
{
    if (!takRepeaterRoleActive())
        return false;

    const uint32_t now = millis() ? millis() : 1U;
    const bool wasActive = serviceWindowActive.exchange(true);
    if (!wasActive)
        serviceStartedMs.store(now);
    serviceLastActivityMs.store(now);
    bluetoothOn();

#if defined(ARCH_ESP32) && !defined(CONFIG_IDF_TARGET_ESP32S2) && !MESHTASTIC_EXCLUDE_BLUETOOTH
    observedBleTraffic = nimbleBluetooth ? nimbleBluetooth->getMeaningfulTrafficCount() : 0U;
#endif

    if (!wasActive)
        diagnosticLog("TAK_REP_SERVICE", "OPEN ble=1 idle=%us hard_cap=%us wlan=%u",
                      (unsigned)(TAK_SERVICE_IDLE_MS / 1000UL), (unsigned)(TAK_SERVICE_HARD_CAP_MS / 1000UL),
                      jarnsenServiceWebActive() ? 1U : 0U);
    return true;
}

void takRepeaterServiceTouch()
{
    if (takRepeaterRoleActive() && serviceWindowActive.load())
        serviceLastActivityMs.store(millis() ? millis() : 1U);
}

void takRepeaterServiceClose(const char *reason)
{
    if (!serviceWindowActive.exchange(false))
        return;
    if (jarnsenServiceWebActive())
        jarnsenServiceWebStop();
    bluetoothOff();
    serviceStartedMs.store(0);
    serviceLastActivityMs.store(0);
    diagnosticLog("TAK_REP_SERVICE", "CLOSED reason=%s", reason ? reason : "requested");
}

void takRepeaterNoteRadioTx(bool forwarded)
{
    if (!takRepeaterRoleActive())
        return;
    txPackets.fetch_add(1U);
    if (forwarded)
        forwardedPackets.fetch_add(1U);
    const uint32_t now = millis();
    lastTxMs.store(now ? now : 1U);
}

TakRepeaterStats takRepeaterStats()
{
    TakRepeaterStats out{};
    out.active = takRepeaterRoleActive();
    if (!out.active)
        return out;

    out.positionMode = currentPositionMode();
    out.positionAvailable = localPositionAvailable();
    out.gpsConnected = gpsConnected();
    out.gpsFix = gpsHasFix();
    out.serviceActive = serviceWindowActive.load();
    out.wifiServiceActive = jarnsenServiceWebActive();
    out.usbPowered = usbPowered();
    out.lightSleepSupported = currentHardwareRoleProfile().hardware.capabilities.lightSleep;
    out.bootCount = bootCount;
    out.watchdogReboots = watchdogReboots;
    out.resetReason = resetReason;
    out.rxPackets = rxPackets.load();
    out.txPackets = txPackets.load();
    out.forwardedPackets = forwardedPackets.load();
    out.positionTxCount = positionTxCount;

    const uint32_t rx = lastRxMs.load();
    const uint32_t tx = lastTxMs.load();
    const uint32_t latest = rx == 0 ? tx : (tx == 0 ? rx : ((int32_t)(rx - tx) >= 0 ? rx : tx));
    out.lastRxAgeSecs = ageSecs(rx);
    out.lastTxAgeSecs = ageSecs(tx);
    out.lastRadioAgeSecs = ageSecs(latest);
    out.channelUtilizationX10 = percentX10(airTime ? airTime->channelUtilizationPercent() : 0.0f);
    out.txAirUtilizationX10 = percentX10(airTime ? airTime->utilizationTXPercent() : 0.0f);
    out.usbDropCount = usbDropCount;
    out.usbRestoreCount = usbRestoreCount;
    out.lightSleepEntries = lightSleepEntries.load();
    out.lightSleepWakes = lightSleepWakes.load();
    out.minFreeHeap = minFreeHeap;
    out.watchdogStage = watchdogStage;
    out.lastLightSleepWakeCause = lastLightSleepWakeCause.load();
    return out;
}

void takRepeaterRuntimeInit()
{
    if (runtimeInitialized || !takRepeaterRoleActive())
        return;

    if (!takRepeaterApplyBaseConfig(true)) {
        diagnosticLog("TAK_REP_PROFILE", "runtime_init=blocked reason=config_persist_failed");
        return;
    }

    loadHealthRecord();
    if (bootCount < UINT32_MAX)
        bootCount++;
#ifdef ARCH_ESP32
    resetReason = (uint32_t)esp_reset_reason();
#else
    resetReason = 0;
#endif
    saveHealthRecord();

    const uint32_t now = millis() ? millis() : 1U;
    rxPackets.store(0);
    txPackets.store(0);
    forwardedPackets.store(0);
    lightSleepEntries.store(0);
    lightSleepWakes.store(0);
    lastLightSleepWakeCause.store(0);
    lastRxMs.store(now);
    lastTxMs.store(now);
    previousUsbKnown = false;
    previousGpsConnected = gpsConnected();
    fixedModeKnown = true;
    previousFixedMode = config.position.fixed_position;
    lastHealthLogMs = 0;
    lastDynamicPolicyMs = 0;
    lastObservedPositionTxMs = positionModule ? positionModule->lastPositionSendMs() : 0;
    positionTxCount = 0;
    usbDropCount = 0;
    usbRestoreCount = 0;
    minFreeHeap = 0;
    airtimeTier = 0xffU;
    resetWatchdog();

    const int pin = configuredButtonPin();
    if (pin >= 0)
        pinMode((uint8_t)pin, INPUT_PULLUP);

    applyGpsRuntime();
    bluetoothOff();

#if defined(HELTEC_TRACKER_V1_1)
    trackerPowerMonitorInit();
#endif

    if (!rxObserverInstalled) {
        rxObserver.observe(&RadioInterface::loraRxPacketObservable);
        rxObserverInstalled = true;
    }

#ifdef ARCH_ESP32
    if (!sleepObserversInstalled) {
        lightSleepBeginObserver.observe(&notifyLightSleep);
        lightSleepEndObserver.observe(&notifyLightSleepEnd);
        deepSleepObserver.observe(&preflightSleep);
        sleepObserversInstalled = true;
    }
#endif

    diagnosticLog("TAK_REP_BOOT",
                  "board=%s mode=%s boot=%u reset=%u light_sleep=1 deep_sleep=critical_only gps_capable=%u "
                  "fixed=%u service=on_demand",
                  currentHardwareRoleProfile().hardware.displayName, takRepeaterPositionModeKey(currentPositionMode()),
                  (unsigned)bootCount, (unsigned)resetReason, boardCanUseGps() ? 1U : 0U,
                  config.position.fixed_position ? 1U : 0U);

    if (!runtimeThread)
        runtimeThread = new TakRepeaterRuntimeThread();
    runtimeInitialized = true;
}

} // namespace jarnsen

#else

namespace jarnsen
{

bool takRepeaterRoleActive()
{
    return false;
}
bool takRepeaterApplyBaseConfig(bool)
{
    return false;
}
void takRepeaterRuntimeInit() {}
TakRepeaterStats takRepeaterStats()
{
    return {};
}
const char *takRepeaterPositionModeKey(TakRepeaterPositionMode mode)
{
    switch (mode) {
    case TakRepeaterPositionMode::FIXED:
        return "fixed";
    case TakRepeaterPositionMode::MOBILE:
        return "mobile";
    case TakRepeaterPositionMode::NO_POSITION:
    default:
        return "no_position";
    }
}
bool takRepeaterServiceOpen()
{
    return false;
}
void takRepeaterServiceTouch() {}
void takRepeaterServiceClose(const char *) {}
void takRepeaterNoteRadioTx(bool) {}

} // namespace jarnsen

#endif
