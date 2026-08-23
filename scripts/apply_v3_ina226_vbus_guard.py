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
    '''    bool inaPresent;\n    uint16_t inaBusVoltageMv;\n    bool currentValid;\n''',
    '''    bool inaPresent;\n    uint16_t inaBusVoltageMv;\n    bool vbusValid;\n    bool currentValid;\n''',
    "V3 INA VBUS public validity",
)

power = replace_once(
    power,
    '''constexpr int32_t INA226_DISCHARGE_DEADBAND_UA = 500;\n''',
    '''constexpr int32_t INA226_DISCHARGE_DEADBAND_UA = 500;\n// VBS/VBUS is a separate analog input on the Hailege breakout. Below this\n// threshold we still trust shunt current/mAh, but not power or mWh.\nconstexpr uint16_t INA226_VBUS_MIN_VALID_MV = 500;\n''',
    "V3 INA VBUS validity threshold",
)

power = replace_once(
    power,
    '''uint16_t inaBusVoltageMv = 0;\nint32_t inaCurrentUa = 0;\n''',
    '''uint16_t inaBusVoltageMv = 0;\nbool inaVbusValid = false;\nint32_t inaCurrentUa = 0;\n''',
    "V3 INA VBUS runtime state",
)

power = replace_once(
    power,
    '''        inaSampleValid = false;\n        inaPresent = false;\n        lastInaProbeMs = now ? now : 1;\n''',
    '''        inaSampleValid = false;\n        inaVbusValid = false;\n        inaPresent = false;\n        lastInaProbeMs = now ? now : 1;\n''',
    "V3 clear VBUS validity on INA read failure",
)

power = replace_once(
    power,
    '''    inaBusVoltageMv = (uint16_t)(((uint32_t)rawBus * 1250UL + 500UL) / 1000UL);\n    inaCurrentUa = (int32_t)(int16_t)rawCurrent * INA226_CURRENT_LSB_UA;\n    inaSampleValid = true;\n''',
    '''    inaBusVoltageMv = (uint16_t)(((uint32_t)rawBus * 1250UL + 500UL) / 1000UL);\n    inaVbusValid = inaBusVoltageMv >= INA226_VBUS_MIN_VALID_MV;\n    inaCurrentUa = (int32_t)(int16_t)rawCurrent * INA226_CURRENT_LSB_UA;\n    inaSampleValid = true;\n''',
    "V3 validate separate VBS VBUS input",
)

power = replace_once(
    power,
    '''        inaDischargeUaMs += (uint64_t)inaCurrentUa * sampleDeltaMs;\n        const uint64_t powerUw = ((uint64_t)inaCurrentUa * inaBusVoltageMv) / 1000ULL;\n        inaEnergyUwMs += powerUw * sampleDeltaMs;\n''',
    '''        inaDischargeUaMs += (uint64_t)inaCurrentUa * sampleDeltaMs;\n        if (inaVbusValid) {\n            const uint64_t powerUw = ((uint64_t)inaCurrentUa * inaBusVoltageMv) / 1000ULL;\n            inaEnergyUwMs += powerUw * sampleDeltaMs;\n        }\n''',
    "V3 only integrate Wh with valid VBUS",
)

power = replace_once(
    power,
    '''                    "src=%s %umV %u%% usb=%u charge=%u est=%s current=%ldmA power=%umW used=%umAh/%umWh "\n''',
    '''                    "src=%s vbus=%s %umV %u%% usb=%u charge=%u est=%s current=%ldmA power=%umW used=%umAh/%umWh "\n''',
    "V3 diagnostic VBUS status format",
)

power = replace_once(
    power,
    '''                    heltecV3PowerMonitorSourceText(), (unsigned)stats.voltageMv, (unsigned)stats.batteryPercent,\n''',
    '''                    heltecV3PowerMonitorSourceText(), stats.vbusValid ? "OK" : (stats.inaPresent ? "MISSING" : "N/A"),\n                    (unsigned)stats.voltageMv, (unsigned)stats.batteryPercent,\n''',
    "V3 diagnostic VBUS status value",
)

power = replace_once(
    power,
    '''    out.inaPresent = inaPresent;\n    out.inaBusVoltageMv = inaBusVoltageMv;\n    out.currentValid = inaPresent && inaSampleValid;\n    out.energyValid = inaPresent;\n    if (out.currentValid) {\n        out.currentMa = inaCurrentUa / 1000;\n        const int64_t powerMw = (int64_t)inaCurrentUa * inaBusVoltageMv / 1000000LL;\n        out.powerMw = powerMw > 0 ? (uint32_t)powerMw : 0U;\n    }\n''',
    '''    out.inaPresent = inaPresent;\n    out.inaBusVoltageMv = inaBusVoltageMv;\n    out.vbusValid = inaPresent && inaSampleValid && inaVbusValid;\n    out.currentValid = inaPresent && inaSampleValid;\n    out.energyValid = out.vbusValid;\n    if (out.currentValid)\n        out.currentMa = inaCurrentUa / 1000;\n    if (out.currentValid && out.vbusValid) {\n        const int64_t powerMw = (int64_t)inaCurrentUa * inaBusVoltageMv / 1000000LL;\n        out.powerMw = powerMw > 0 ? (uint32_t)powerMw : 0U;\n    }\n''',
    "V3 separate current and VBUS energy validity",
)

power = replace_once(
    power,
    '''    out.voltageMv = out.currentValid ? inaBusVoltageMv : (mv > 0 && mv < 65536 ? (uint16_t)mv : 0);\n''',
    '''    out.voltageMv = out.vbusValid ? inaBusVoltageMv : (mv > 0 && mv < 65536 ? (uint16_t)mv : 0);\n''',
    "V3 use INA voltage only with valid VBUS",
)

service = replace_once(
    service,
    '''        if (p.inaPresent)\n            snprintf(inaLine, sizeof(inaLine), p.currentValid ? "INA226: ACTIVE" : "INA226: WAIT");\n        else\n            snprintf(inaLine, sizeof(inaLine), "INA226: NOT FOUND");\n        if (p.currentValid) {\n            snprintf(currentLine, sizeof(currentLine), "Current: %ld mA", (long)p.currentMa);\n            snprintf(powerLine, sizeof(powerLine), "Power: %u mW", (unsigned)p.powerMw);\n        } else {\n            snprintf(currentLine, sizeof(currentLine), "Current: --");\n            snprintf(powerLine, sizeof(powerLine), "Power: --");\n        }\n        snprintf(usedLine, sizeof(usedLine), "Used: %u mAh / %u mWh",\n                 (unsigned)p.consumedMah, (unsigned)p.consumedMwh);\n''',
    '''        if (!p.inaPresent)\n            snprintf(inaLine, sizeof(inaLine), "INA226: NOT FOUND");\n        else if (!p.currentValid)\n            snprintf(inaLine, sizeof(inaLine), "INA226: WAIT");\n        else if (!p.vbusValid)\n            snprintf(inaLine, sizeof(inaLine), "INA226: VBUS MISSING");\n        else\n            snprintf(inaLine, sizeof(inaLine), "INA226: ACTIVE");\n        if (p.currentValid)\n            snprintf(currentLine, sizeof(currentLine), "Current: %ld mA", (long)p.currentMa);\n        else\n            snprintf(currentLine, sizeof(currentLine), "Current: --");\n        if (p.currentValid && p.vbusValid)\n            snprintf(powerLine, sizeof(powerLine), "Power: %u mW", (unsigned)p.powerMw);\n        else if (p.currentValid)\n            snprintf(powerLine, sizeof(powerLine), "Power: -- (VBUS)");\n        else\n            snprintf(powerLine, sizeof(powerLine), "Power: --");\n        if (p.energyValid)\n            snprintf(usedLine, sizeof(usedLine), "Used: %u mAh / %u mWh",\n                     (unsigned)p.consumedMah, (unsigned)p.consumedMwh);\n        else\n            snprintf(usedLine, sizeof(usedLine), "Used: %u mAh / -- mWh", (unsigned)p.consumedMah);\n''',
    "V3 Power Statistics VBUS warning",
)

for text, needle in [
    (power_h, "bool vbusValid;"),
    (power, "INA226_VBUS_MIN_VALID_MV"),
    (power, "inaVbusValid = inaBusVoltageMv >= INA226_VBUS_MIN_VALID_MV"),
    (power, 'vbus=%s'),
    (service, '"INA226: VBUS MISSING"'),
    (service, '"Power: -- (VBUS)"'),
    (service, '"Used: %u mAh / -- mWh"'),
]:
    if needle not in text:
        raise SystemExit(f"V3 INA226 VBUS verification failed: {needle}")

POWER.write_text(power)
POWER_H.write_text(power_h)
SERVICE.write_text(service)
print("V3 INA226 VBUS guard ready: current/mAh independent, power/mWh require VBS/VBUS")
