from pathlib import Path

POWER = Path("src/vehicle/TrackerPowerMonitor.cpp")
POWER_H = Path("src/vehicle/TrackerPowerMonitor.h")
COMMON = Path("src/vehicle/TrackerCommonPolicy.cpp")

power = POWER.read_text()
power_h = POWER_H.read_text()
common = COMMON.read_text()


def replace_once(text, old, new, label):
    if new in text:
        print(f"{label}: already applied")
        return text
    if old not in text:
        raise SystemExit(f"{label}: anchor not found")
    print(f"{label}: applied")
    return text.replace(old, new, 1)


power_h = replace_once(
    power_h,
    '''    uint32_t dischargedMahX10;\n    uint32_t dischargedMwhX10;\n\n    bool capacityReady;\n''',
    '''    uint32_t dischargedMahX10;\n    uint32_t dischargedMwhX10;\n    uint32_t awakeMeasuredMahX10;\n    uint32_t awakeMeasuredMwhX10;\n    uint32_t sleepEstimatedMahX10;\n    uint32_t sleepEstimatedMwhX10;\n    uint32_t lightSleepSecs;\n    uint32_t deepSleepSecs;\n    int32_t lightSleepMilliAmpsX10;\n    int32_t deepSleepMilliAmpsX10;\n\n    bool capacityReady;\n''',
    "Tracker sleep profiling stats",
)

power_h = replace_once(
    power_h,
    '''void trackerPowerMonitorPersist();\nvoid trackerPowerMonitorPrepareForDeepSleep();\nTrackerPowerStats trackerPowerMonitorStats();\n''',
    '''void trackerPowerMonitorPersist();\nvoid trackerPowerMonitorPrepareForLightSleep();\nvoid trackerPowerMonitorCompleteLightSleep();\nvoid trackerPowerMonitorPrepareForDeepSleep(uint32_t plannedSleepSecs);\nTrackerPowerStats trackerPowerMonitorStats();\n''',
    "Tracker sleep profiling API",
)

power = replace_once(
    power,
    '#include "PowerStatus.h"\n#include "vehicle/TrackerDiagnosticLog.h"\n',
    '#include "PowerStatus.h"\n#include "gps/RTC.h"\n#include "vehicle/TrackerDiagnosticLog.h"\n',
    "Tracker sleep RTC include",
)

power = replace_once(
    power,
    '#include <Wire.h>\n#include <esp_attr.h>\n#include <cstdio>\n',
    '#include <Wire.h>\n#include <esp_attr.h>\n#include <esp_sleep.h>\n#include <esp_timer.h>\n#include <cstdio>\n',
    "Tracker sleep ESP includes",
)

power = replace_once(
    power,
    '''constexpr uint16_t INA226_CONFIG_CONTINUOUS = 0x4127;\nconstexpr uint16_t INA226_CONFIG_POWER_DOWN = 0x4120;\n''',
    '''constexpr uint16_t INA226_CONFIG_CONTINUOUS = 0x4127;\nconstexpr uint16_t INA226_CONFIG_POWER_DOWN = 0x4120;\n// One-shot shunt+bus conversion with 8.244 ms per channel. The INA226\n// performs this conversion after the CPU enters sleep and then returns to\n// power-down by itself. No CPU wake is created only for measurement.\nconstexpr uint16_t INA226_CONFIG_SLEEP_SINGLE = 0x41FB;\n''',
    "Tracker INA sleep one-shot config",
)

power = replace_once(
    power,
    '''constexpr uint32_t INA226_MAX_INTEGRATION_GAP_MS = 5000UL;\nconstexpr int32_t INA226_DISCHARGE_DEADBAND_UA = 500;\n''',
    '''constexpr uint32_t INA226_MAX_INTEGRATION_GAP_MS = 5000UL;\nconstexpr int32_t INA226_DISCHARGE_DEADBAND_UA = 500;\nconstexpr int32_t INA226_SLEEP_MIN_UA = 50;\nconstexpr int64_t INA226_LIGHT_SLEEP_REFRESH_US = 15LL * 60LL * 1000000LL;\nconstexpr int64_t INA226_SLEEP_SHOT_MIN_US = 20000LL;\n''',
    "Tracker sleep profiling constants",
)

power = replace_once(
    power,
    '''RTC_DATA_ATTR uint32_t capacityBaselineUsedUah = 0;\n\nbool initialized = false;\n''',
    '''RTC_DATA_ATTR uint32_t capacityBaselineUsedUah = 0;\n\n// Sleep energy stays separate from continuously measured awake energy.\n// It is estimated from a real INA226 sample captured while the ESP is asleep.\nRTC_DATA_ATTR uint64_t inaSleepUaMs = 0;\nRTC_DATA_ATTR uint64_t inaSleepUwMs = 0;\nRTC_DATA_ATTR uint64_t lightSleepMs = 0;\nRTC_DATA_ATTR uint64_t deepSleepMs = 0;\nRTC_DATA_ATTR int32_t lightSleepBaselineUa = 0;\nRTC_DATA_ATTR uint16_t lightSleepBaselineMv = 0;\nRTC_DATA_ATTR int32_t deepSleepLastUa = 0;\nRTC_DATA_ATTR uint16_t deepSleepLastMv = 0;\nRTC_DATA_ATTR bool deepSleepShotPending = false;\nRTC_DATA_ATTR uint32_t deepSleepPlannedSecs = 0;\nRTC_DATA_ATTR uint32_t deepSleepStartEpoch = 0;\n\nbool initialized = false;\n''',
    "Tracker retained sleep profiling state",
)

power = replace_once(
    power,
    '''uint32_t lastInaProbeMs = 0;\nuint32_t lastInaSampleMs = 0;\n\nuint32_t clamp32(uint64_t value)''',
    '''uint32_t lastInaProbeMs = 0;\nuint32_t lastInaSampleMs = 0;\n\nbool lightSleepIntervalPending = false;\nbool lightSleepShotPending = false;\nint64_t lightSleepStartedUs = 0;\nint64_t lastLightSleepProfileUs = 0;\n\nuint32_t clamp32(uint64_t value)''',
    "Tracker volatile light sleep profiling state",
)

power = replace_once(
    power,
    '''uint32_t dischargedUah() { return clamp32(inaDischargeUaMs / 3600000ULL); }\nuint32_t dischargedUwh() { return clamp32(inaEnergyUwMs / 3600000ULL); }\n\nvoid resetLearning''',
    '''uint32_t dischargedUah() { return clamp32(inaDischargeUaMs / 3600000ULL); }\nuint32_t dischargedUwh() { return clamp32(inaEnergyUwMs / 3600000ULL); }\nuint32_t sleepEstimatedUah() { return clamp32(inaSleepUaMs / 3600000ULL); }\nuint32_t sleepEstimatedUwh() { return clamp32(inaSleepUwMs / 3600000ULL); }\nuint32_t totalDischargedUah() { return clamp32((uint64_t)dischargedUah() + sleepEstimatedUah()); }\nuint32_t totalDischargedUwh() { return clamp32((uint64_t)dischargedUwh() + sleepEstimatedUwh()); }\n\nvoid resetLearning''',
    "Tracker combined measured/estimated energy helpers",
)

register_anchor = '''bool inaReadRegister(uint8_t reg, uint16_t &value)\n{\n    Wire.beginTransmission(INA226_ADDRESS);\n    Wire.write(reg);\n    if (Wire.endTransmission(false) != 0)\n        return false;\n    if (Wire.requestFrom((uint8_t)INA226_ADDRESS, (uint8_t)2) != 2)\n        return false;\n    value = ((uint16_t)Wire.read() << 8) | (uint16_t)Wire.read();\n    return true;\n}\n\n'''
helpers = '''bool ensureInaWire()\n{\n    if (inaWireReady)\n        return true;\n    inaWireReady = Wire.begin(SDA, SCL);\n    return inaWireReady;\n}\n\nbool readInaInstant(int32_t &currentUa, uint16_t &busMv)\n{\n    if (!ensureInaWire())\n        return false;\n\n    uint16_t manufacturer = 0, dieId = 0, rawBus = 0, rawCurrent = 0;\n    if (!inaReadRegister(INA226_REG_MANUFACTURER, manufacturer) ||\n        !inaReadRegister(INA226_REG_DIE_ID, dieId) ||\n        manufacturer != INA226_TI_MANUFACTURER || (dieId & 0xFFF0U) != INA226_DIE_ID ||\n        !inaReadRegister(INA226_REG_BUS_VOLTAGE, rawBus) ||\n        !inaReadRegister(INA226_REG_CURRENT, rawCurrent))\n        return false;\n\n    busMv = (uint16_t)(((uint32_t)rawBus * 1250UL + 500UL) / 1000UL);\n    currentUa = (int32_t)(int16_t)rawCurrent * INA226_CURRENT_LSB_UA;\n    return true;\n}\n\nvoid addSleepEstimate(int32_t currentUa, uint16_t busMv, uint64_t durationMs, bool deep)\n{\n    if (durationMs == 0)\n        return;\n\n    if (deep)\n        deepSleepMs += durationMs;\n    else\n        lightSleepMs += durationMs;\n\n    if (currentUa <= INA226_SLEEP_MIN_UA)\n        return;\n\n    inaSleepUaMs += (uint64_t)currentUa * durationMs;\n    const uint64_t powerUw = ((uint64_t)currentUa * busMv) / 1000ULL;\n    inaSleepUwMs += powerUw * durationMs;\n}\n\nvoid recoverDeepSleepShot()\n{\n    if (!deepSleepShotPending)\n        return;\n\n    const esp_sleep_wakeup_cause_t cause = esp_sleep_get_wakeup_cause();\n    uint32_t durationSecs = 0;\n    if (cause == ESP_SLEEP_WAKEUP_TIMER) {\n        durationSecs = deepSleepPlannedSecs;\n    } else if (cause == ESP_SLEEP_WAKEUP_EXT0\n#if defined(ESP_SLEEP_WAKEUP_GPIO)\n               || cause == ESP_SLEEP_WAKEUP_GPIO\n#endif\n    ) {\n        const uint32_t nowEpoch = getValidTime(RTCQualityDevice);\n        if (deepSleepStartEpoch != 0 && nowEpoch >= deepSleepStartEpoch) {\n            durationSecs = nowEpoch - deepSleepStartEpoch;\n            if (deepSleepPlannedSecs != 0 && durationSecs > deepSleepPlannedSecs)\n                durationSecs = deepSleepPlannedSecs;\n        }\n    }\n\n    int32_t currentUa = 0;\n    uint16_t busMv = 0;\n    const bool sampleOk = trackerIna226Enabled() && readInaInstant(currentUa, busMv);\n    if (sampleOk) {\n        deepSleepLastUa = currentUa;\n        deepSleepLastMv = busMv;\n        if (durationSecs != 0) {\n            addSleepEstimate(currentUa, busMv, (uint64_t)durationSecs * 1000ULL, true);\n            trackerDiagLog("POWER_SLEEP",\n                           "role=TAK_TRACKER mode=deep sample=%lduA %umV duration=%us estimate=sample_x_duration",\n                           (long)currentUa, (unsigned)busMv, (unsigned)durationSecs);\n        } else {\n            trackerDiagLog("POWER_SLEEP",\n                           "role=TAK_TRACKER mode=deep sample=%lduA %umV duration=unknown estimate=not_integrated",\n                           (long)currentUa, (unsigned)busMv);\n        }\n    } else {\n        trackerDiagLog("POWER_SLEEP", "role=TAK_TRACKER mode=deep sample=unavailable estimate=not_integrated");\n    }\n\n    deepSleepShotPending = false;\n    deepSleepPlannedSecs = 0;\n    deepSleepStartEpoch = 0;\n    inaPresent = false;\n    inaSampleValid = false;\n    lastInaProbeMs = 0;\n    lastInaSampleMs = 0;\n}\n\n'''
if helpers not in power:
    if register_anchor not in power:
        raise SystemExit("Tracker sleep INA helpers: anchor not found")
    power = power.replace(register_anchor, register_anchor + helpers, 1)
    print("Tracker sleep INA helpers: applied")

power = replace_once(
    power,
    '''    if (!inaWireReady) {\n        inaWireReady = Wire.begin(SDA, SCL);\n        if (!inaWireReady)\n            return false;\n    }\n\n    uint16_t manufacturer = 0;\n''',
    '''    if (!ensureInaWire())\n        return false;\n\n    uint16_t manufacturer = 0;\n''',
    "Tracker shared INA wire initialization",
)

power = replace_once(
    power,
    '''    inaEnergyUwMs = (uint64_t)prefs.getULong("usedUwh", 0) * 3600000ULL;\n    learnedCapacityMah = prefs.getULong("capMah", 0);\n''',
    '''    inaEnergyUwMs = (uint64_t)prefs.getULong("usedUwh", 0) * 3600000ULL;\n    inaSleepUaMs = (uint64_t)prefs.getULong("sleepUah", 0) * 3600000ULL;\n    inaSleepUwMs = (uint64_t)prefs.getULong("sleepUwh", 0) * 3600000ULL;\n    lightSleepMs = (uint64_t)prefs.getULong("lightSlpS", 0) * 1000ULL;\n    deepSleepMs = (uint64_t)prefs.getULong("deepSlpS", 0) * 1000ULL;\n    learnedCapacityMah = prefs.getULong("capMah", 0);\n''',
    "Tracker load sleep energy totals",
)

power = replace_once(
    power,
    '''    prefs.putULong("usedUah", dischargedUah());\n    prefs.putULong("usedUwh", dischargedUwh());\n    prefs.putULong("capMah", learnedCapacityMah);\n''',
    '''    prefs.putULong("usedUah", dischargedUah());\n    prefs.putULong("usedUwh", dischargedUwh());\n    prefs.putULong("sleepUah", sleepEstimatedUah());\n    prefs.putULong("sleepUwh", sleepEstimatedUwh());\n    prefs.putULong("lightSlpS", clampSecs(lightSleepMs / 1000ULL));\n    prefs.putULong("deepSlpS", clampSecs(deepSleepMs / 1000ULL));\n    prefs.putULong("capMah", learnedCapacityMah);\n''',
    "Tracker persist sleep energy totals",
)

power = replace_once(power, '    const uint32_t used = dischargedUah();\n', '    const uint32_t used = totalDischargedUah();\n',
                     "Tracker capacity learning includes sleep estimate")

power = replace_once(
    power,
    '''        inaEnergyUwMs = 0;\n        learnedCapacityMah = 0;\n''',
    '''        inaEnergyUwMs = 0;\n        inaSleepUaMs = 0;\n        inaSleepUwMs = 0;\n        lightSleepMs = 0;\n        deepSleepMs = 0;\n        lightSleepBaselineUa = 0;\n        lightSleepBaselineMv = 0;\n        deepSleepLastUa = 0;\n        deepSleepLastMv = 0;\n        deepSleepShotPending = false;\n        deepSleepPlannedSecs = 0;\n        deepSleepStartEpoch = 0;\n        learnedCapacityMah = 0;\n''',
    "Tracker reset sleep profiling state",
)

power = replace_once(
    power,
    '''    initialized = true;\n    lastTickMs = millis();\n    lastPersistMeasuredSecs = measuredSecs();\n}\n''',
    '''    initialized = true;\n    recoverDeepSleepShot();\n    lastTickMs = millis();\n    lastPersistMeasuredSecs = measuredSecs();\n}\n''',
    "Tracker recover deep sleep INA shot at boot",
)

old_prepare = '''void trackerPowerMonitorPrepareForDeepSleep()\n{\n    if (!initialized)\n        trackerPowerMonitorInit();\n    savePersistentTotals();\n    inaPowerDown();\n    capacityWindowValid = false;\n    capacityResetAfterExternal = true;\n}\n'''
new_prepare = '''void trackerPowerMonitorPrepareForLightSleep()\n{\n    if (!initialized)\n        trackerPowerMonitorInit();\n\n    const uint32_t now = millis();\n    syncInaConfiguration(now);\n    if (!trackerIna226Enabled() || !inaPresent)\n        return;\n\n    lightSleepStartedUs = esp_timer_get_time();\n    lightSleepIntervalPending = true;\n\n    const bool refresh = lightSleepBaselineUa <= INA226_SLEEP_MIN_UA || lastLightSleepProfileUs == 0 ||\n                         lightSleepStartedUs - lastLightSleepProfileUs >= INA226_LIGHT_SLEEP_REFRESH_US;\n    if (refresh && inaWriteRegister(INA226_REG_CONFIG, INA226_CONFIG_SLEEP_SINGLE)) {\n        lightSleepShotPending = true;\n    } else {\n        lightSleepShotPending = false;\n        inaPowerDown();\n    }\n\n    inaSampleValid = false;\n    lastInaSampleMs = 0;\n}\n\nvoid trackerPowerMonitorCompleteLightSleep()\n{\n    if (!lightSleepIntervalPending)\n        return;\n\n    const int64_t nowUs = esp_timer_get_time();\n    const int64_t durationUs = nowUs > lightSleepStartedUs ? nowUs - lightSleepStartedUs : 0;\n    int32_t sampleUa = lightSleepBaselineUa;\n    uint16_t sampleMv = lightSleepBaselineMv;\n\n    if (lightSleepShotPending && durationUs >= INA226_SLEEP_SHOT_MIN_US) {\n        int32_t capturedUa = 0;\n        uint16_t capturedMv = 0;\n        if (readInaInstant(capturedUa, capturedMv)) {\n            lightSleepBaselineUa = capturedUa;\n            lightSleepBaselineMv = capturedMv;\n            sampleUa = capturedUa;\n            sampleMv = capturedMv;\n            lastLightSleepProfileUs = nowUs;\n            trackerDiagLog("POWER_SLEEP",\n                           "role=TAK mode=light sample=%lduA %umV duration=%lldms estimate=sample_x_duration",\n                           (long)capturedUa, (unsigned)capturedMv, (long long)(durationUs / 1000LL));\n        }\n    }\n\n    if (durationUs > 0 && sampleUa > INA226_SLEEP_MIN_UA && sampleMv != 0)\n        addSleepEstimate(sampleUa, sampleMv, (uint64_t)(durationUs / 1000LL), false);\n\n    if (trackerIna226Enabled() && inaPresent) {\n        if (!inaWriteRegister(INA226_REG_CONFIG, INA226_CONFIG_CONTINUOUS))\n            inaPresent = false;\n    }\n    inaSampleValid = false;\n    lastInaSampleMs = 0;\n    lightSleepIntervalPending = false;\n    lightSleepShotPending = false;\n    lightSleepStartedUs = 0;\n}\n\nvoid trackerPowerMonitorPrepareForDeepSleep(uint32_t plannedSleepSecs)\n{\n    if (!initialized)\n        trackerPowerMonitorInit();\n\n    savePersistentTotals();\n    deepSleepShotPending = false;\n    deepSleepPlannedSecs = plannedSleepSecs;\n    deepSleepStartEpoch = getValidTime(RTCQualityDevice);\n\n    const uint32_t now = millis();\n    syncInaConfiguration(now);\n    if (trackerIna226Enabled() && inaPresent) {\n        deepSleepShotPending = inaWriteRegister(INA226_REG_CONFIG, INA226_CONFIG_SLEEP_SINGLE);\n        if (!deepSleepShotPending)\n            inaPowerDown();\n    }\n\n    inaSampleValid = false;\n    lastInaSampleMs = 0;\n    capacityWindowValid = false;\n    capacityResetAfterExternal = true;\n}\n'''
power = replace_once(power, old_prepare, new_prepare, "Tracker light/deep sleep INA profiling")

power = replace_once(
    power,
    '''    out.dischargedMahX10 = dischargedUah() / 100U;\n    out.dischargedMwhX10 = dischargedUwh() / 100U;\n    out.learnedCapacityMah = learnedCapacityMah;\n''',
    '''    out.awakeMeasuredMahX10 = dischargedUah() / 100U;\n    out.awakeMeasuredMwhX10 = dischargedUwh() / 100U;\n    out.sleepEstimatedMahX10 = sleepEstimatedUah() / 100U;\n    out.sleepEstimatedMwhX10 = sleepEstimatedUwh() / 100U;\n    out.dischargedMahX10 = totalDischargedUah() / 100U;\n    out.dischargedMwhX10 = totalDischargedUwh() / 100U;\n    out.lightSleepSecs = clampSecs(lightSleepMs / 1000ULL);\n    out.deepSleepSecs = clampSecs(deepSleepMs / 1000ULL);\n    out.lightSleepMilliAmpsX10 = lightSleepBaselineUa / 100;\n    out.deepSleepMilliAmpsX10 = deepSleepLastUa / 100;\n    out.learnedCapacityMah = learnedCapacityMah;\n''',
    "Tracker publish measured plus sleep estimated energy",
)

# Add sleep estimates to the 15-minute diagnostic summary without writing raw samples every second.
old_log_head = '''                   "%umV %u%% usb=%u charge=%u est=%s ina=%s current=%s%ld.%ldmA used=%u.%umAh cap=%umAh conf=%u%% "\n                   "move=%us park=%us gps=%us ble=%us disp=%us tx=%u",\n'''
new_log_head = '''                   "%umV %u%% usb=%u charge=%u est=%s ina=%s current=%s%ld.%ldmA total=%u.%umAh "\n                   "sleepEst=%u.%umAh lightSleep=%us deepSleep=%us cap=%umAh conf=%u%% "\n                   "move=%us park=%us gps=%us ble=%us disp=%us tx=%u",\n'''
power = replace_once(power, old_log_head, new_log_head, "Tracker diagnostic sleep summary format")
old_log_args = '''                   (unsigned)(stats.dischargedMahX10 / 10U), (unsigned)(stats.dischargedMahX10 % 10U),\n                   (unsigned)stats.learnedCapacityMah, (unsigned)stats.capacityConfidence,\n                   (unsigned)stats.movingSecs, (unsigned)stats.parkedSecs, (unsigned)stats.gnssSecs,\n'''
new_log_args = '''                   (unsigned)(stats.dischargedMahX10 / 10U), (unsigned)(stats.dischargedMahX10 % 10U),\n                   (unsigned)(stats.sleepEstimatedMahX10 / 10U), (unsigned)(stats.sleepEstimatedMahX10 % 10U),\n                   (unsigned)stats.lightSleepSecs, (unsigned)stats.deepSleepSecs,\n                   (unsigned)stats.learnedCapacityMah, (unsigned)stats.capacityConfidence,\n                   (unsigned)stats.movingSecs, (unsigned)stats.parkedSecs, (unsigned)stats.gnssSecs,\n'''
power = replace_once(power, old_log_args, new_log_args, "Tracker diagnostic sleep summary values")

common = replace_once(
    common,
    '''        armDeepSleepMotionWake();\n        trackerPowerMonitorPrepareForDeepSleep();\n\n        const uint32_t sleepMs = trackerEffectiveParkIntervalSecs() * 1000UL;\n''',
    '''        armDeepSleepMotionWake();\n\n        const uint32_t sleepMs = trackerEffectiveParkIntervalSecs() * 1000UL;\n        trackerPowerMonitorPrepareForDeepSleep(sleepMs / 1000UL);\n''',
    "Tracker deep sleep profiler gets planned duration",
)

# This script runs after apply_tracker_common_motion_sleep_fix.py, so these observer anchors exist.
common = replace_once(
    common,
    '''        if (!trackerRoleEnabled())\n            return 0;\n\n        const gpio_num_t pin = (gpio_num_t)VEHICLE_MOTION_WAKE_PIN;\n''',
    '''        if (!trackerRoleEnabled())\n            return 0;\n\n        if (!trackerUsesDeepSleep() && parked)\n            trackerPowerMonitorPrepareForLightSleep();\n\n        const gpio_num_t pin = (gpio_num_t)VEHICLE_MOTION_WAKE_PIN;\n''',
    "Tracker TAK light sleep INA sample arm",
)

common = replace_once(
    common,
    '''        attachInterrupt(digitalPinToInterrupt(VEHICLE_MOTION_WAKE_PIN), motionISR, FALLING);\n        motionLightSleepWakeArmed = false;\n        return 0;\n''',
    '''        attachInterrupt(digitalPinToInterrupt(VEHICLE_MOTION_WAKE_PIN), motionISR, FALLING);\n        motionLightSleepWakeArmed = false;\n        if (!trackerUsesDeepSleep() && parked)\n            trackerPowerMonitorCompleteLightSleep();\n        return 0;\n''',
    "Tracker TAK light sleep INA sample readback",
)

common = replace_once(
    common,
    '''            motionLightSleepWakeArmed = false;\n            attachInterrupt(digitalPinToInterrupt(VEHICLE_MOTION_WAKE_PIN), motionISR, FALLING);\n            return 0;\n''',
    '''            motionLightSleepWakeArmed = false;\n            attachInterrupt(digitalPinToInterrupt(VEHICLE_MOTION_WAKE_PIN), motionISR, FALLING);\n            if (!trackerUsesDeepSleep() && parked)\n                trackerPowerMonitorCompleteLightSleep();\n            return 0;\n''',
    "Tracker cancel light sleep sample on aborted sleep",
)

for text, needle in [
    (power_h, "sleepEstimatedMahX10"),
    (power_h, "trackerPowerMonitorPrepareForLightSleep"),
    (power_h, "trackerPowerMonitorPrepareForDeepSleep(uint32_t plannedSleepSecs)"),
    (power, "INA226_CONFIG_SLEEP_SINGLE"),
    (power, "recoverDeepSleepShot();"),
    (power, 'role=TAK mode=light'),
    (power, 'role=TAK_TRACKER mode=deep'),
    (power, "totalDischargedUah()"),
    (common, "trackerPowerMonitorPrepareForLightSleep();"),
    (common, "trackerPowerMonitorCompleteLightSleep();"),
    (common, "trackerPowerMonitorPrepareForDeepSleep(sleepMs / 1000UL);"),
]:
    if needle not in text:
        raise SystemExit(f"Tracker sleep profiling verification failed: {needle}")

POWER.write_text(power)
POWER_H.write_text(power_h)
COMMON.write_text(common)
print("Tracker INA sleep profiling ready: TAK light sleep + TAK_TRACKER deep sleep, no measurement-only wakeups")
