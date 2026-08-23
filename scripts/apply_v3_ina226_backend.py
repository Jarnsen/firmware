from pathlib import Path

POWER = Path("src/infrastructure/HeltecV3PowerMonitor.cpp")
POWER_H = Path("src/infrastructure/HeltecV3PowerMonitor.h")
SERVICE = Path("src/infrastructure/HeltecV3ServicePage.cpp")

power = POWER.read_text()
power_h = POWER_H.read_text()
service = SERVICE.read_text()


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
    '''    bool currentValid;\n    bool energyValid;\n    int32_t currentMa;\n    uint32_t powerMw;\n    uint32_t consumedMah;\n    uint32_t consumedMwh;\n''',
    '''    bool inaPresent;\n    uint16_t inaBusVoltageMv;\n    bool currentValid;\n    bool energyValid;\n    int32_t currentMa;\n    uint32_t powerMw;\n    uint32_t consumedMah;\n    uint32_t consumedMwh;\n    int32_t listenAvgMa;\n    int32_t serviceAvgMa;\n    int32_t bleAvgMa;\n    int32_t displayAvgMa;\n''',
    "V3 INA226 public stats",
)

power = replace_once(
    power,
    '#include <Preferences.h>\n#include <esp_attr.h>\n',
    '#include <Preferences.h>\n#include <Wire.h>\n#include <esp_attr.h>\n',
    "V3 INA226 Wire include",
)

power = replace_once(
    power,
    '''constexpr uint32_t RATE_REFRESH_SECS = 30UL * 60UL;\n\nRTC_DATA_ATTR uint32_t retainedMagic = 0;\n''',
    '''constexpr uint32_t RATE_REFRESH_SECS = 30UL * 60UL;\n\nconstexpr uint8_t INA226_ADDRESS = 0x40;\nconstexpr uint8_t INA226_REG_CONFIG = 0x00;\nconstexpr uint8_t INA226_REG_BUS_VOLTAGE = 0x02;\nconstexpr uint8_t INA226_REG_CURRENT = 0x04;\nconstexpr uint8_t INA226_REG_CALIBRATION = 0x05;\nconstexpr uint8_t INA226_REG_MANUFACTURER = 0xFE;\nconstexpr uint8_t INA226_REG_DIE_ID = 0xFF;\nconstexpr uint16_t INA226_TI_MANUFACTURER = 0x5449;\nconstexpr uint16_t INA226_DIE_ID = 0x2260;\nconstexpr uint16_t INA226_CONFIG_CONTINUOUS = 0x4127;\nconstexpr uint16_t INA226_CALIBRATION_R100 = 2048;\nconstexpr int32_t INA226_CURRENT_LSB_UA = 25;\nconstexpr uint32_t INA226_SAMPLE_INTERVAL_MS = 1000UL;\nconstexpr uint32_t INA226_RETRY_INTERVAL_MS = 30UL * 1000UL;\nconstexpr uint32_t INA226_MAX_INTEGRATION_GAP_MS = 5000UL;\nconstexpr int32_t INA226_DISCHARGE_DEADBAND_UA = 500;\n\nRTC_DATA_ATTR uint32_t retainedMagic = 0;\n''',
    "V3 INA226 constants",
)

power = replace_once(
    power,
    '''RTC_DATA_ATTR uint32_t lastRateUpdateLearningSecs = 0;\n\nbool initialized = false;\n''',
    '''RTC_DATA_ATTR uint32_t lastRateUpdateLearningSecs = 0;\n\nRTC_DATA_ATTR uint64_t inaDischargeUaMs = 0;\nRTC_DATA_ATTR uint64_t inaEnergyUwMs = 0;\nRTC_DATA_ATTR uint64_t listenInaUaMs = 0;\nRTC_DATA_ATTR uint64_t serviceInaUaMs = 0;\nRTC_DATA_ATTR uint64_t bleInaUaMs = 0;\nRTC_DATA_ATTR uint64_t displayInaUaMs = 0;\nRTC_DATA_ATTR uint64_t listenInaMs = 0;\nRTC_DATA_ATTR uint64_t serviceInaMs = 0;\nRTC_DATA_ATTR uint64_t bleInaMs = 0;\nRTC_DATA_ATTR uint64_t displayInaMs = 0;\n\nbool initialized = false;\n''',
    "V3 INA226 retained energy state",
)

power = replace_once(
    power,
    '''uint32_t lastPersistMeasuredSecs = 0;\n\nuint32_t clampSecs(uint64_t value)\n''',
    '''uint32_t lastPersistMeasuredSecs = 0;\nbool inaPresent = false;\nbool inaSampleValid = false;\nbool inaWireReady = false;\nuint16_t inaBusVoltageMv = 0;\nint32_t inaCurrentUa = 0;\nuint32_t lastInaProbeMs = 0;\nuint32_t lastInaSampleMs = 0;\n\nuint32_t clamp32(uint64_t value)\n{\n    return value > UINT32_MAX ? UINT32_MAX : (uint32_t)value;\n}\n\nuint32_t clampSecs(uint64_t value)\n''',
    "V3 INA226 runtime state",
)

power = replace_once(
    power,
    '''uint32_t measuredSecs()\n{\n    return clampSecs((listenMs + serviceMs) / 1000ULL);\n}\n\nvoid resetLearning''',
    '''uint32_t measuredSecs()\n{\n    return clampSecs((listenMs + serviceMs) / 1000ULL);\n}\n\nuint32_t consumedUah() { return clamp32(inaDischargeUaMs / 3600000ULL); }\nuint32_t consumedUwh() { return clamp32(inaEnergyUwMs / 3600000ULL); }\n\nint32_t avgMa(uint64_t uaMs, uint64_t sampleMs)\n{\n    if (sampleMs == 0)\n        return 0;\n    return (int32_t)((uaMs / sampleMs) / 1000ULL);\n}\n\nbool inaWriteRegister(uint8_t reg, uint16_t value)\n{\n    Wire1.beginTransmission(INA226_ADDRESS);\n    Wire1.write(reg);\n    Wire1.write((uint8_t)(value >> 8));\n    Wire1.write((uint8_t)(value & 0xFFU));\n    return Wire1.endTransmission() == 0;\n}\n\nbool inaReadRegister(uint8_t reg, uint16_t &value)\n{\n    Wire1.beginTransmission(INA226_ADDRESS);\n    Wire1.write(reg);\n    if (Wire1.endTransmission(false) != 0)\n        return false;\n    if (Wire1.requestFrom((uint8_t)INA226_ADDRESS, (uint8_t)2) != 2)\n        return false;\n    value = ((uint16_t)Wire1.read() << 8) | (uint16_t)Wire1.read();\n    return true;\n}\n\nbool ensureInaWire()\n{\n    if (inaWireReady)\n        return true;\n    inaWireReady = Wire1.begin(I2C_SDA1, I2C_SCL1);\n    return inaWireReady;\n}\n\nbool inaProbeAndConfigure()\n{\n    if (!ensureInaWire())\n        return false;\n\n    uint16_t manufacturer = 0, dieId = 0;\n    if (!inaReadRegister(INA226_REG_MANUFACTURER, manufacturer) ||\n        !inaReadRegister(INA226_REG_DIE_ID, dieId) ||\n        manufacturer != INA226_TI_MANUFACTURER || (dieId & 0xFFF0U) != INA226_DIE_ID)\n        return false;\n    if (!inaWriteRegister(INA226_REG_CALIBRATION, INA226_CALIBRATION_R100) ||\n        !inaWriteRegister(INA226_REG_CONFIG, INA226_CONFIG_CONTINUOUS))\n        return false;\n\n    heltecV3DiagLog("INA226", "detected addr=0x40 R100 cal=%u SDA=%u SCL=%u",\n                    (unsigned)INA226_CALIBRATION_R100, (unsigned)I2C_SDA1, (unsigned)I2C_SCL1);\n    return true;\n}\n\nvoid syncInaConfiguration(uint32_t now)\n{\n    if (inaPresent)\n        return;\n    if (lastInaProbeMs != 0 && (uint32_t)(now - lastInaProbeMs) < INA226_RETRY_INTERVAL_MS)\n        return;\n\n    lastInaProbeMs = now ? now : 1;\n    inaPresent = inaProbeAndConfigure();\n    inaSampleValid = false;\n    lastInaSampleMs = 0;\n    if (!inaPresent)\n        heltecV3DiagLog("INA226", "not found at 0x40; source remains INTERNAL");\n}\n\nbool sampleIna(uint32_t now)\n{\n    if (!inaPresent)\n        return false;\n    if (lastInaSampleMs != 0 && (uint32_t)(now - lastInaSampleMs) < INA226_SAMPLE_INTERVAL_MS)\n        return inaSampleValid;\n\n    uint16_t rawBus = 0, rawCurrent = 0;\n    if (!inaReadRegister(INA226_REG_BUS_VOLTAGE, rawBus) ||\n        !inaReadRegister(INA226_REG_CURRENT, rawCurrent)) {\n        inaSampleValid = false;\n        inaPresent = false;\n        lastInaProbeMs = now ? now : 1;\n        return false;\n    }\n\n    const uint32_t sampleDeltaMs = lastInaSampleMs == 0 ? 0U : (uint32_t)(now - lastInaSampleMs);\n    lastInaSampleMs = now ? now : 1;\n    inaBusVoltageMv = (uint16_t)(((uint32_t)rawBus * 1250UL + 500UL) / 1000UL);\n    inaCurrentUa = (int32_t)(int16_t)rawCurrent * INA226_CURRENT_LSB_UA;\n    inaSampleValid = true;\n\n    if (sampleDeltaMs != 0 && sampleDeltaMs <= INA226_MAX_INTEGRATION_GAP_MS &&\n        inaCurrentUa > INA226_DISCHARGE_DEADBAND_UA) {\n        inaDischargeUaMs += (uint64_t)inaCurrentUa * sampleDeltaMs;\n        const uint64_t powerUw = ((uint64_t)inaCurrentUa * inaBusVoltageMv) / 1000ULL;\n        inaEnergyUwMs += powerUw * sampleDeltaMs;\n    }\n    return true;\n}\n\nvoid resetLearning''',
    "V3 INA226 backend helpers",
)

power = replace_once(
    power,
    '''    dischargeRateMilliPercentPerHour = prefs.getULong("rate", 0);\n    prefs.end();\n''',
    '''    dischargeRateMilliPercentPerHour = prefs.getULong("rate", 0);\n    inaDischargeUaMs = (uint64_t)prefs.getULong("usedUah", 0) * 3600000ULL;\n    inaEnergyUwMs = (uint64_t)prefs.getULong("usedUwh", 0) * 3600000ULL;\n    prefs.end();\n''',
    "V3 load INA energy totals",
)

power = replace_once(
    power,
    '''    prefs.putULong("rate", dischargeRateMilliPercentPerHour);\n    prefs.end();\n''',
    '''    prefs.putULong("rate", dischargeRateMilliPercentPerHour);\n    prefs.putULong("usedUah", consumedUah());\n    prefs.putULong("usedUwh", consumedUwh());\n    prefs.end();\n''',
    "V3 persist INA energy totals",
)

old_log = '''    heltecV3DiagLog("BATTERY", "src=internal %umV %u%% usb=%u charge=%u est=%s listen=%us service=%us ble=%us disp=%us tx=%u",\n                    (unsigned)stats.voltageMv, (unsigned)stats.batteryPercent, stats.usbPowered ? 1U : 0U,\n                    stats.charging ? 1U : 0U, remaining, (unsigned)stats.listenSecs, (unsigned)stats.serviceSecs,\n                    (unsigned)stats.bleSecs, (unsigned)stats.displaySecs, (unsigned)stats.positionTxCount);\n'''
new_log = '''    heltecV3DiagLog("BATTERY",\n                    "src=%s %umV %u%% usb=%u charge=%u est=%s current=%ldmA power=%umW used=%umAh/%umWh "\n                    "avgListen=%ldmA avgService=%ldmA avgBle=%ldmA avgDisplay=%ldmA listen=%us service=%us ble=%us disp=%us tx=%u",\n                    heltecV3PowerMonitorSourceText(), (unsigned)stats.voltageMv, (unsigned)stats.batteryPercent,\n                    stats.usbPowered ? 1U : 0U, stats.charging ? 1U : 0U, remaining,\n                    (long)(stats.currentValid ? stats.currentMa : 0), (unsigned)(stats.currentValid ? stats.powerMw : 0),\n                    (unsigned)stats.consumedMah, (unsigned)stats.consumedMwh,\n                    (long)stats.listenAvgMa, (long)stats.serviceAvgMa, (long)stats.bleAvgMa, (long)stats.displayAvgMa,\n                    (unsigned)stats.listenSecs, (unsigned)stats.serviceSecs, (unsigned)stats.bleSecs,\n                    (unsigned)stats.displaySecs, (unsigned)stats.positionTxCount);\n'''
power = replace_once(power, old_log, new_log, "V3 INA diagnostic power summary")

power = replace_once(
    power,
    '''        lastRateUpdateLearningSecs = 0;\n        loadPersistentTotals();\n''',
    '''        lastRateUpdateLearningSecs = 0;\n        inaDischargeUaMs = 0;\n        inaEnergyUwMs = 0;\n        listenInaUaMs = serviceInaUaMs = bleInaUaMs = displayInaUaMs = 0;\n        listenInaMs = serviceInaMs = bleInaMs = displayInaMs = 0;\n        loadPersistentTotals();\n''',
    "V3 reset INA energy state",
)

power = replace_once(
    power,
    '    heltecV3DiagLog("POWER", "monitor initialized source=internal ina226=prepared-not-enabled");\n',
    '    heltecV3DiagLog("POWER", "monitor initialized source=auto ina226=probe addr=0x40 R100 SDA=%u SCL=%u",\n                    (unsigned)I2C_SDA1, (unsigned)I2C_SCL1);\n',
    "V3 INA initialization log",
)

power = replace_once(
    power,
    '''    const uint32_t now = millis();\n    if (lastTickMs == 0) {\n''',
    '''    const uint32_t now = millis();\n    syncInaConfiguration(now);\n    sampleIna(now);\n    if (lastTickMs == 0) {\n''',
    "V3 INA sampling in power tick",
)

power = replace_once(
    power,
    '''    if (displayActive)\n        displayMs += deltaMs;\n\n    updateBatteryLearning(deltaMs);\n''',
    '''    if (displayActive)\n        displayMs += deltaMs;\n\n    if (inaSampleValid && inaCurrentUa > INA226_DISCHARGE_DEADBAND_UA) {\n        if (serviceActive) {\n            serviceInaUaMs += (uint64_t)inaCurrentUa * deltaMs;\n            serviceInaMs += deltaMs;\n        } else if (listening) {\n            listenInaUaMs += (uint64_t)inaCurrentUa * deltaMs;\n            listenInaMs += deltaMs;\n        }\n        if (bleActive) {\n            bleInaUaMs += (uint64_t)inaCurrentUa * deltaMs;\n            bleInaMs += deltaMs;\n        }\n        if (displayActive) {\n            displayInaUaMs += (uint64_t)inaCurrentUa * deltaMs;\n            displayInaMs += deltaMs;\n        }\n    }\n\n    updateBatteryLearning(deltaMs);\n''',
    "V3 state current profiling",
)

old_stats = '''    out.source = HeltecV3PowerSource::INTERNAL;\n    out.measuredSecs = measuredSecs();\n'''
new_stats = '''    out.source = inaPresent && inaSampleValid ? HeltecV3PowerSource::INA226 : HeltecV3PowerSource::INTERNAL;\n    out.measuredSecs = measuredSecs();\n'''
power = replace_once(power, old_stats, new_stats, "V3 dynamic power source")

old_invalid = '''    // INA226-facing values deliberately stay invalid here. When the sensor is\n    // installed later, only the source backend needs to populate these fields.\n    out.currentValid = false;\n    out.energyValid = false;\n\n    if (!powerStatus || !powerStatus->getHasBattery())\n        return out;\n'''
new_valid = '''    out.inaPresent = inaPresent;\n    out.inaBusVoltageMv = inaBusVoltageMv;\n    out.currentValid = inaPresent && inaSampleValid;\n    out.energyValid = inaPresent;\n    if (out.currentValid) {\n        out.currentMa = inaCurrentUa / 1000;\n        const int64_t powerMw = (int64_t)inaCurrentUa * inaBusVoltageMv / 1000000LL;\n        out.powerMw = powerMw > 0 ? (uint32_t)powerMw : 0U;\n    }\n    out.consumedMah = consumedUah() / 1000U;\n    out.consumedMwh = consumedUwh() / 1000U;\n    out.listenAvgMa = avgMa(listenInaUaMs, listenInaMs);\n    out.serviceAvgMa = avgMa(serviceInaUaMs, serviceInaMs);\n    out.bleAvgMa = avgMa(bleInaUaMs, bleInaMs);\n    out.displayAvgMa = avgMa(displayInaUaMs, displayInaMs);\n\n    if (!powerStatus || !powerStatus->getHasBattery()) {\n        if (out.currentValid)\n            out.voltageMv = inaBusVoltageMv;\n        return out;\n    }\n'''
power = replace_once(power, old_invalid, new_valid, "V3 publish INA measurements")

power = replace_once(
    power,
    '''    const int mv = powerStatus->getBatteryVoltageMv();\n    out.voltageMv = mv > 0 && mv < 65536 ? (uint16_t)mv : 0;\n''',
    '''    const int mv = powerStatus->getBatteryVoltageMv();\n    out.voltageMv = out.currentValid ? inaBusVoltageMv : (mv > 0 && mv < 65536 ? (uint16_t)mv : 0);\n''',
    "V3 use INA bus voltage when available",
)

power = replace_once(
    power,
    '''const char *heltecV3PowerMonitorSourceText()\n{\n    return "INTERNAL";\n}\n''',
    '''const char *heltecV3PowerMonitorSourceText()\n{\n    return inaPresent && inaSampleValid ? "INA226" : "INTERNAL";\n}\n''',
    "V3 dynamic source text",
)

# The previous power-menu patch has already produced this submenu before this script runs.
service = replace_once(
    service,
    '''        static char sourceLine[40], batteryLine[48], remainingLine[48], measuredLine[48];\n        static char listenLine[48], serviceLine[48], bleLine[48], displayLine[48], txLine[48], trendLine[48], inaLine[48];\n        static const char *options[] = {"Back", sourceLine, batteryLine, remainingLine, measuredLine, listenLine,\n                                        serviceLine, bleLine, displayLine, txLine, trendLine, inaLine};\n''',
    '''        static char sourceLine[40], batteryLine[48], remainingLine[48], measuredLine[48];\n        static char listenLine[48], serviceLine[48], bleLine[48], displayLine[48], txLine[48], trendLine[48], inaLine[48];\n        static char currentLine[48], powerLine[48], usedLine[48];\n        static const char *options[] = {"Back", sourceLine, batteryLine, remainingLine, inaLine, currentLine, powerLine, usedLine,\n                                        measuredLine, listenLine, serviceLine, bleLine, displayLine, txLine, trendLine};\n''',
    "V3 INA Power Statistics menu lines",
)

service = replace_once(
    service,
    '''        snprintf(inaLine, sizeof(inaLine), "INA226: prepared / disabled");\n\n        showOptions("Power Statistics", options, 12, [](int selected) {\n''',
    '''        if (p.inaPresent)\n            snprintf(inaLine, sizeof(inaLine), p.currentValid ? "INA226: ACTIVE" : "INA226: WAIT");\n        else\n            snprintf(inaLine, sizeof(inaLine), "INA226: NOT FOUND");\n        if (p.currentValid) {\n            snprintf(currentLine, sizeof(currentLine), "Current: %ld mA", (long)p.currentMa);\n            snprintf(powerLine, sizeof(powerLine), "Power: %u mW", (unsigned)p.powerMw);\n        } else {\n            snprintf(currentLine, sizeof(currentLine), "Current: --");\n            snprintf(powerLine, sizeof(powerLine), "Power: --");\n        }\n        snprintf(usedLine, sizeof(usedLine), "Used: %u mAh / %u mWh",\n                 (unsigned)p.consumedMah, (unsigned)p.consumedMwh);\n\n        showOptions("Power Statistics", options, 15, [](int selected) {\n''',
    "V3 live INA Power Statistics values",
)

for text, needle in [
    (power_h, "inaPresent"),
    (power_h, "listenAvgMa"),
    (power, "Wire1.begin(I2C_SDA1, I2C_SCL1)"),
    (power, "INA226_CALIBRATION_R100 = 2048"),
    (power, 'detected addr=0x40 R100'),
    (power, 'source remains INTERNAL'),
    (power, "consumedUah()"),
    (power, "avgListen=%ldmA"),
    (service, '"INA226: ACTIVE"'),
    (service, '"INA226: NOT FOUND"'),
    (service, '"Current: %ld mA"'),
    (service, 'showOptions("Power Statistics", options, 15'),
]:
    if needle not in text:
        raise SystemExit(f"V3 INA226 backend verification failed: {needle}")

POWER.write_text(power)
POWER_H.write_text(power_h)
SERVICE.write_text(service)
print("V3 INA226 backend ready: auto-detect 0x40/R100 on GPIO41/42, INTERNAL fallback, current/power/energy profiling")
