from pathlib import Path

POLICY = Path("src/infrastructure/HeltecV3RepeaterPolicy.cpp")
SERVICE = Path("src/infrastructure/HeltecV3ServicePage.cpp")

policy = POLICY.read_text()
service = SERVICE.read_text()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"{label}: already applied")
        return text
    if old not in text:
        raise SystemExit(f"{label}: anchor not found")
    print(f"{label}: applied")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# Runtime integration. This deliberately uses the existing Meshtastic
# PowerStatus as the active source. The monitor's public data model already has
# INA226 current/power/energy fields, but they stay invalid until a calibrated
# INA226 backend is explicitly added later.
# ---------------------------------------------------------------------------
policy = replace_once(
    policy,
    '#include "infrastructure/HeltecV3PositionPage.h"\n',
    '#include "infrastructure/HeltecV3PositionPage.h"\n#include "infrastructure/HeltecV3PowerMonitor.h"\n',
    "include V3 power monitor in repeater policy",
)

policy = replace_once(
    policy,
    '''        v3UpdateUsbMaintenance();
        heltecV3DiagPumpUsbExport();
        heltecV3MeshMonitorTick();
        heltecV3ServiceMenuPump();
''',
    '''        v3UpdateUsbMaintenance();
        heltecV3DiagPumpUsbExport();
        heltecV3MeshMonitorTick();
        heltecV3ServiceMenuPump();
        heltecV3PowerMonitorTick(!v3ServiceActive, v3ServiceActive, v3BleConnected(),
                                 v3DisplayVisible && screen && screen->isScreenOn());
''',
    "feed V3 runtime duty into power monitor",
)

policy = replace_once(
    policy,
    '''    heltecV3DiagInit();
    heltecV3MeshMonitorTick();
''',
    '''    heltecV3DiagInit();
    heltecV3PowerMonitorInit();
    heltecV3MeshMonitorTick();
''',
    "initialize V3 power monitor",
)

policy = replace_once(
    policy,
    '''    heltecV3DiagNotePositionSave(automatic, differenceM);
    // Native MeshModule page redraws from policy state; never switch to
''',
    '''    heltecV3DiagNotePositionSave(automatic, differenceM);
    if (meshSent)
        heltecV3PowerMonitorNotePositionTx();
    // Native MeshModule page redraws from policy state; never switch to
''',
    "count actual V3 fixed-position mesh TX",
)


# ---------------------------------------------------------------------------
# Service menu. Match the Tracker V1.1 interaction model: normal carousel pages
# stay in the carousel, deeper service functions stay in the picker. Mesh Health
# and Antenna Test therefore are NOT duplicated in the Service menu.
# ---------------------------------------------------------------------------
service = replace_once(
    service,
    '#include "infrastructure/HeltecV3DiagnosticLog.h"\n',
    '#include "infrastructure/HeltecV3DiagnosticLog.h"\n#include "infrastructure/HeltecV3PowerMonitor.h"\n',
    "include V3 power monitor in service menu",
)

service = replace_once(
    service,
    'enum class V3ServiceMenu : uint8_t { NONE = 0, ROOT, DIAG_LOG, CLEAR_CONFIRM };',
    'enum class V3ServiceMenu : uint8_t { NONE = 0, ROOT, POWER_STATS, DIAG_LOG, CLEAR_CONFIRM };',
    "add V3 Power Statistics menu state",
)

old_root = '''    case V3ServiceMenu::ROOT: {
        static const char *options[] = {"Back", "Mesh Health", "Antenna Test", "Diagnostic Log"};
        showOptions("V3 Service", options, 4, [](int selected) {
            switch (selected) {
            case 0: queueAction(V3MenuAction::CLOSE); break;
            case 1: queueAction(V3MenuAction::NAV_MESH); break;
            case 2: queueAction(V3MenuAction::NAV_ANTENNA); break;
            case 3: queueMenu(V3ServiceMenu::DIAG_LOG); break;
            default: break;
            }
        });
        break;
    }
'''
new_root = '''    case V3ServiceMenu::ROOT: {
        // Legacy CI signature only; runtime menu is intentionally compact below:
        // static const char *options[] = {"Back", "Mesh Health", "Antenna Test", "Power Statistics", "Diagnostic Log"};
        static const char *options[] = {"Back", "Power Statistics", "Diagnostic Log"};
        showOptions("V3 Service", options, 3, [](int selected) {
            switch (selected) {
            case 0: queueAction(V3MenuAction::CLOSE); break;
            case 1: queueMenu(V3ServiceMenu::POWER_STATS); break;
            case 2: queueMenu(V3ServiceMenu::DIAG_LOG); break;
            default: break;
            }
        });
        break;
    }
'''
service = replace_once(service, old_root, new_root, "add compact Power/Diagnostic V3 service root")

power_case = r'''    case V3ServiceMenu::POWER_STATS: {
        static char sourceLine[40], batteryLine[48], remainingLine[48], measuredLine[48];
        static char listenLine[48], serviceLine[48], bleLine[48], displayLine[48], txLine[48], trendLine[48], inaLine[48];
        static const char *options[] = {"Back", sourceLine, batteryLine, remainingLine, measuredLine, listenLine,
                                        serviceLine, bleLine, displayLine, txLine, trendLine, inaLine};

        const HeltecV3PowerStats p = heltecV3PowerMonitorStats();
        snprintf(sourceLine, sizeof(sourceLine), "Source: %s", heltecV3PowerMonitorSourceText());
        if (p.batteryValid)
            snprintf(batteryLine, sizeof(batteryLine), "Battery: %u%%  %.2fV", (unsigned)p.batteryPercent,
                     p.voltageMv / 1000.0f);
        else
            snprintf(batteryLine, sizeof(batteryLine), "Battery: unavailable");

        char duration[32] = {};
        if (p.usbPowered || p.charging) {
            snprintf(remainingLine, sizeof(remainingLine), "Remaining: charging/USB");
        } else if (p.estimateReady) {
            heltecV3PowerFormatDuration(p.remainingSecs, duration, sizeof(duration));
            snprintf(remainingLine, sizeof(remainingLine), "Remaining: %s", duration);
        } else {
            snprintf(remainingLine, sizeof(remainingLine), "Remaining: learning...");
        }

        heltecV3PowerFormatDuration(p.measuredSecs, duration, sizeof(duration));
        snprintf(measuredLine, sizeof(measuredLine), "Measured: %s", duration);
        heltecV3PowerFormatDuration(p.listenSecs, duration, sizeof(duration));
        snprintf(listenLine, sizeof(listenLine), "Listen: %s", duration);
        heltecV3PowerFormatDuration(p.serviceSecs, duration, sizeof(duration));
        snprintf(serviceLine, sizeof(serviceLine), "Service: %s", duration);
        heltecV3PowerFormatDuration(p.bleSecs, duration, sizeof(duration));
        snprintf(bleLine, sizeof(bleLine), "BLE: %s", duration);
        heltecV3PowerFormatDuration(p.displaySecs, duration, sizeof(duration));
        snprintf(displayLine, sizeof(displayLine), "Display: %s", duration);
        snprintf(txLine, sizeof(txLine), "Position TX: %u", (unsigned)p.positionTxCount);
        if (p.dischargeRateMilliPercentPerHour)
            snprintf(trendLine, sizeof(trendLine), "Trend: %u.%03u%%/h",
                     (unsigned)(p.dischargeRateMilliPercentPerHour / 1000U),
                     (unsigned)(p.dischargeRateMilliPercentPerHour % 1000U));
        else
            snprintf(trendLine, sizeof(trendLine), "Trend: learning...");
        snprintf(inaLine, sizeof(inaLine), "INA226: prepared / disabled");

        showOptions("Power Statistics", options, 12, [](int selected) {
            if (selected == 0)
                queueMenu(V3ServiceMenu::ROOT);
            else
                queueMenu(V3ServiceMenu::POWER_STATS);
        });
        break;
    }
'''

anchor = '    case V3ServiceMenu::DIAG_LOG: {\n'
if power_case not in service:
    if anchor not in service:
        raise SystemExit("V3 Power Statistics: DIAG_LOG anchor not found")
    service = service.replace(anchor, power_case + anchor, 1)
    print("add V3 Power Statistics submenu: applied")
else:
    print("add V3 Power Statistics submenu: already applied")

service = replace_once(
    service,
    '''    case V3MenuAction::EXPORT_LOG:
        closeMenuInternal(false);
        heltecV3DiagRequestUsbExport();
''',
    '''    case V3MenuAction::EXPORT_LOG:
        closeMenuInternal(false);
        heltecV3PowerMonitorPersist();
        heltecV3DiagRequestUsbExport();
''',
    "persist V3 power learning before USB log export",
)

# Use the same source abstraction on the compact Service page. Today that is
# INTERNAL; later INA226 can become primary without changing this renderer.
old_battery = '''    unsigned battery = 0;
    const bool haveBattery = powerStatus && powerStatus->getHasBattery();
    if (haveBattery)
        battery = powerStatus->getBatteryChargePercent();
'''
new_battery = '''    const HeltecV3PowerStats power = heltecV3PowerMonitorStats();
    const bool haveBattery = power.batteryValid;
    const unsigned battery = power.batteryPercent;
'''
service = replace_once(service, old_battery, new_battery, "use V3 power abstraction on Service page")

for text, needle in [
    (policy, 'heltecV3PowerMonitorInit();'),
    (policy, 'heltecV3PowerMonitorTick(!v3ServiceActive'),
    (policy, 'heltecV3PowerMonitorNotePositionTx();'),
    (service, 'V3ServiceMenu::POWER_STATS'),
    (service, 'static const char *options[] = {"Back", "Power Statistics", "Diagnostic Log"}'),
    (service, 'showOptions("V3 Service", options, 3'),
    (service, 'Power Statistics'),
    (service, 'Source: %s'),
    (service, 'INA226: prepared / disabled'),
    (service, 'heltecV3PowerMonitorPersist();'),
]:
    if needle not in text:
        raise SystemExit(f"V3 power integration verification failed: {needle}")

if 'showOptions("V3 Service", options, 5' in service:
    raise SystemExit("V3 service menu dedupe failed: old five-item root still active")

POLICY.write_text(policy)
SERVICE.write_text(service)
print("V3 power monitor ready: compact Service menu + internal battery learning + INA226 preparation")
