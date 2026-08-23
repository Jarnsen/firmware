from pathlib import Path

POWER = Path("src/vehicle/TrackerPowerMonitor.cpp")
POWER_H = Path("src/vehicle/TrackerPowerMonitor.h")
STATUS = Path("src/vehicle/TrackerStatusModule.cpp")

power = POWER.read_text()
power_h = POWER_H.read_text()
status = STATUS.read_text()


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
    '''    uint16_t inaBusVoltageMv;\n    int32_t currentMilliAmpsX10;\n''',
    '''    uint16_t inaBusVoltageMv;\n    bool vbusValid;\n    int32_t currentMilliAmpsX10;\n''',
    "Tracker INA VBUS public validity",
)

power = replace_once(
    power,
    '''constexpr int32_t INA226_DISCHARGE_DEADBAND_UA = 500;\n''',
    '''constexpr int32_t INA226_DISCHARGE_DEADBAND_UA = 500;\n// Hailege breakout exposes VBS/VBUS separately. Current/mAh come from the\n// shunt and remain valid without VBS; power/mWh require a plausible bus input.\nconstexpr uint16_t INA226_VBUS_MIN_VALID_MV = 500;\n''',
    "Tracker INA VBUS validity threshold",
)

# Helper is deliberately shared by awake and sleep profiling.
helper_anchor = '''uint32_t dischargedUah() { return clamp32(inaDischargeUaMs / 3600000ULL); }\n'''
helper_new = '''bool inaVbusIsValid(uint16_t busMv) { return busMv >= INA226_VBUS_MIN_VALID_MV; }\nuint32_t dischargedUah() { return clamp32(inaDischargeUaMs / 3600000ULL); }\n'''
power = replace_once(power, helper_anchor, helper_new, "Tracker INA VBUS helper")

power = replace_once(
    power,
    '''                inaDischargeUaMs += (uint64_t)inaCurrentUa * sampleDeltaMs;\n                const uint64_t powerUw = ((uint64_t)inaCurrentUa * inaBusVoltageMv) / 1000ULL;\n                inaEnergyUwMs += powerUw * sampleDeltaMs;\n''',
    '''                inaDischargeUaMs += (uint64_t)inaCurrentUa * sampleDeltaMs;\n                if (inaVbusIsValid(inaBusVoltageMv)) {\n                    const uint64_t powerUw = ((uint64_t)inaCurrentUa * inaBusVoltageMv) / 1000ULL;\n                    inaEnergyUwMs += powerUw * sampleDeltaMs;\n                }\n''',
    "Tracker only integrate awake Wh with valid VBUS",
)

power = replace_once(
    power,
    '''    inaSleepUaMs += (uint64_t)currentUa * durationMs;\n    const uint64_t powerUw = ((uint64_t)currentUa * busMv) / 1000ULL;\n    inaSleepUwMs += powerUw * durationMs;\n''',
    '''    inaSleepUaMs += (uint64_t)currentUa * durationMs;\n    if (inaVbusIsValid(busMv)) {\n        const uint64_t powerUw = ((uint64_t)currentUa * busMv) / 1000ULL;\n        inaSleepUwMs += powerUw * durationMs;\n    }\n''',
    "Tracker only estimate sleep Wh with valid VBUS",
)

# Make VBUS status explicit in sleep breadcrumbs.
power = replace_once(
    power,
    '''                           "role=TAK mode=light sample=%lduA %umV duration=%lldms estimate=sample_x_duration",\n                           (long)capturedUa, (unsigned)capturedMv, (long long)(durationUs / 1000LL));\n''',
    '''                           "role=TAK mode=light sample=%lduA %umV vbus=%s duration=%lldms estimate=sample_x_duration",\n                           (long)capturedUa, (unsigned)capturedMv, inaVbusIsValid(capturedMv) ? "OK" : "MISSING",\n                           (long long)(durationUs / 1000LL));\n''',
    "Tracker light sleep VBUS breadcrumb",
)

power = replace_once(
    power,
    '''                           "role=TAK_TRACKER mode=deep sample=%lduA %umV duration=%us estimate=sample_x_duration",\n                           (long)currentUa, (unsigned)busMv, (unsigned)durationSecs);\n''',
    '''                           "role=TAK_TRACKER mode=deep sample=%lduA %umV vbus=%s duration=%us estimate=sample_x_duration",\n                           (long)currentUa, (unsigned)busMv, inaVbusIsValid(busMv) ? "OK" : "MISSING",\n                           (unsigned)durationSecs);\n''',
    "Tracker deep sleep VBUS breadcrumb",
)

power = replace_once(
    power,
    '''                           "role=TAK_TRACKER mode=deep sample=%lduA %umV duration=unknown estimate=not_integrated",\n                           (long)currentUa, (unsigned)busMv);\n''',
    '''                           "role=TAK_TRACKER mode=deep sample=%lduA %umV vbus=%s duration=unknown estimate=not_integrated",\n                           (long)currentUa, (unsigned)busMv, inaVbusIsValid(busMv) ? "OK" : "MISSING");\n''',
    "Tracker unknown deep sleep VBUS breadcrumb",
)

power = replace_once(
    power,
    '''    const char *inaState = !stats.inaConfigured ? "OFF" : (!stats.inaPresent ? "MISSING" : (stats.inaValid ? "OK" : "WAIT"));\n    const int32_t c = stats.currentMilliAmpsX10;\n''',
    '''    const char *inaState = !stats.inaConfigured ? "OFF" : (!stats.inaPresent ? "MISSING" : (stats.inaValid ? "OK" : "WAIT"));\n    const char *vbusState = !stats.inaConfigured || !stats.inaPresent ? "N/A" :\n                            (!stats.inaValid ? "WAIT" : (stats.vbusValid ? "OK" : "MISSING"));\n    const int32_t c = stats.currentMilliAmpsX10;\n''',
    "Tracker diagnostic VBUS state",
)

power = replace_once(
    power,
    '''                   "%umV %u%% usb=%u charge=%u est=%s ina=%s current=%s%ld.%ldmA total=%u.%umAh "\n''',
    '''                   "%umV %u%% usb=%u charge=%u est=%s ina=%s vbus=%s current=%s%ld.%ldmA total=%u.%umAh "\n''',
    "Tracker diagnostic VBUS summary format",
)

power = replace_once(
    power,
    '''                   stats.charging ? 1U : 0U, remaining, inaState, c < 0 ? "-" : "", (long)(ac / 10), (long)(ac % 10),\n''',
    '''                   stats.charging ? 1U : 0U, remaining, inaState, vbusState, c < 0 ? "-" : "",\n                   (long)(ac / 10), (long)(ac % 10),\n''',
    "Tracker diagnostic VBUS summary value",
)

power = replace_once(
    power,
    '''    out.inaBusVoltageMv = inaBusVoltageMv;\n    out.currentMilliAmpsX10 = inaCurrentUa / 100;\n    if (out.inaValid) {\n        const int64_t powerX10 = (int64_t)inaCurrentUa * inaBusVoltageMv / 100000LL;\n''',
    '''    out.inaBusVoltageMv = inaBusVoltageMv;\n    out.vbusValid = out.inaValid && inaVbusIsValid(inaBusVoltageMv);\n    out.currentMilliAmpsX10 = inaCurrentUa / 100;\n    if (out.inaValid && out.vbusValid) {\n        const int64_t powerX10 = (int64_t)inaCurrentUa * inaBusVoltageMv / 100000LL;\n''',
    "Tracker publish VBUS validity and guard live power",
)

# Final status page comes from apply_tracker_ina226_capacity_fix.py earlier in the build chain.
status = replace_once(
    status,
    '''        if (!p.inaConfigured) snprintf(inaLine, sizeof(inaLine), "INA226: OFF");\n        else if (!p.inaPresent) snprintf(inaLine, sizeof(inaLine), "INA226: MISSING");\n        else if (!p.inaValid) snprintf(inaLine, sizeof(inaLine), "INA226: WAIT");\n        else snprintf(inaLine, sizeof(inaLine), "INA226: ACTIVE  %umV", (unsigned)p.inaBusVoltageMv);\n\n        if (p.inaValid) {\n            const int32_t c = p.currentMilliAmpsX10;\n            const int32_t ac = c < 0 ? -c : c;\n            snprintf(currentLine, sizeof(currentLine), "Current: %s%ld.%ld mA", c < 0 ? "-" : "",\n                     (long)(ac / 10), (long)(ac % 10));\n            const int32_t w = p.powerMilliWattsX10;\n            const int32_t aw = w < 0 ? -w : w;\n            snprintf(powerLine, sizeof(powerLine), "Power: %s%ld.%ld mW", w < 0 ? "-" : "",\n                     (long)(aw / 10), (long)(aw % 10));\n        } else {\n            snprintf(currentLine, sizeof(currentLine), "Current: --");\n            snprintf(powerLine, sizeof(powerLine), "Power: --");\n        }\n\n        snprintf(usedLine, sizeof(usedLine), "Used: %u.%u mAh / %u.%u mWh",\n                 (unsigned)(p.dischargedMahX10 / 10U), (unsigned)(p.dischargedMahX10 % 10U),\n                 (unsigned)(p.dischargedMwhX10 / 10U), (unsigned)(p.dischargedMwhX10 % 10U));\n''',
    '''        if (!p.inaConfigured) snprintf(inaLine, sizeof(inaLine), "INA226: OFF");\n        else if (!p.inaPresent) snprintf(inaLine, sizeof(inaLine), "INA226: MISSING");\n        else if (!p.inaValid) snprintf(inaLine, sizeof(inaLine), "INA226: WAIT");\n        else if (!p.vbusValid) snprintf(inaLine, sizeof(inaLine), "INA226: VBUS MISSING");\n        else snprintf(inaLine, sizeof(inaLine), "INA226: ACTIVE  %umV", (unsigned)p.inaBusVoltageMv);\n\n        if (p.inaValid) {\n            const int32_t c = p.currentMilliAmpsX10;\n            const int32_t ac = c < 0 ? -c : c;\n            snprintf(currentLine, sizeof(currentLine), "Current: %s%ld.%ld mA", c < 0 ? "-" : "",\n                     (long)(ac / 10), (long)(ac % 10));\n        } else {\n            snprintf(currentLine, sizeof(currentLine), "Current: --");\n        }\n        if (p.inaValid && p.vbusValid) {\n            const int32_t w = p.powerMilliWattsX10;\n            const int32_t aw = w < 0 ? -w : w;\n            snprintf(powerLine, sizeof(powerLine), "Power: %s%ld.%ld mW", w < 0 ? "-" : "",\n                     (long)(aw / 10), (long)(aw % 10));\n        } else if (p.inaValid) {\n            snprintf(powerLine, sizeof(powerLine), "Power: -- (VBUS)");\n        } else {\n            snprintf(powerLine, sizeof(powerLine), "Power: --");\n        }\n\n        if (p.vbusValid)\n            snprintf(usedLine, sizeof(usedLine), "Used: %u.%u mAh / %u.%u mWh",\n                     (unsigned)(p.dischargedMahX10 / 10U), (unsigned)(p.dischargedMahX10 % 10U),\n                     (unsigned)(p.dischargedMwhX10 / 10U), (unsigned)(p.dischargedMwhX10 % 10U));\n        else\n            snprintf(usedLine, sizeof(usedLine), "Used: %u.%u mAh / -- mWh",\n                     (unsigned)(p.dischargedMahX10 / 10U), (unsigned)(p.dischargedMahX10 % 10U));\n''',
    "Tracker Power Statistics VBUS warning",
)

for text, needle in [
    (power_h, "bool vbusValid;"),
    (power, "INA226_VBUS_MIN_VALID_MV"),
    (power, "inaVbusIsValid"),
    (power, 'vbus=%s'),
    (status, '"INA226: VBUS MISSING"'),
    (status, '"Power: -- (VBUS)"'),
    (status, '"Used: %u.%u mAh / -- mWh"'),
]:
    if needle not in text:
        raise SystemExit(f"Tracker INA226 VBUS verification failed: {needle}")

POWER.write_text(power)
POWER_H.write_text(power_h)
STATUS.write_text(status)
print("Tracker INA226 VBUS guard ready: current/mAh independent, power/mWh require VBS/VBUS in awake and sleep modes")
