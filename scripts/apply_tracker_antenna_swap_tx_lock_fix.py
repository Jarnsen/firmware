from pathlib import Path

COMMON = Path("src/vehicle/TrackerCommonPolicy.cpp")
STATUS = Path("src/vehicle/TrackerStatusModule.cpp")
RADIO = Path("src/mesh/RadioLibInterface.cpp")

common = COMMON.read_text()
status = STATUS.read_text()
radio = RADIO.read_text()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"{label}: already applied")
        return text
    if old not in text:
        raise SystemExit(f"{label}: anchor not found")
    print(f"{label}: applied")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# Boot policy. The antenna backend starts fail-safe locked and only releases TX
# after this initialization has loaded the persisted swap state from NVS.
# ---------------------------------------------------------------------------
common = replace_once(
    common,
    '#include "TrackerStatusModule.h"\n',
    '#include "TrackerStatusModule.h"\n#include "vehicle/TrackerAntennaTest.h"\n',
    "include Tracker antenna safety in common policy",
)

if '    trackerAntennaTestInit();\n' not in common:
    if '    trackerPowerMonitorInit();\n' in common:
        common = common.replace(
            '    trackerPowerMonitorInit();\n',
            '    trackerPowerMonitorInit();\n    trackerAntennaTestInit();\n',
            1,
        )
        print("initialize Tracker antenna safety after power monitor: applied")
    elif '    trackerServiceSettingsInit();\n' in common:
        common = common.replace(
            '    trackerServiceSettingsInit();\n',
            '    trackerServiceSettingsInit();\n    trackerAntennaTestInit();\n',
            1,
        )
        print("initialize Tracker antenna safety after service settings: applied")
    else:
        raise SystemExit("Tracker antenna init: setupTrackerCommonPolicy anchor not found")
else:
    print("initialize Tracker antenna safety: already applied")


# ---------------------------------------------------------------------------
# Radio safety. Reject newly generated packets before queueing and gate queued
# packets again at the final startSend boundary. A packet already physically on
# air when PREP SWAP is pressed is allowed to finish while antenna A is still
# connected; the UI does not report SAFE until isSending() is false.
# ---------------------------------------------------------------------------
radio = replace_once(
    radio,
    '#include "main.h"\n',
    '#include "main.h"\n#if defined(HELTEC_TRACKER_V1_1)\n#include "vehicle/TrackerAntennaTest.h"\n#endif\n',
    "connect Tracker antenna lock to radio TX path",
)

radio = replace_once(
    radio,
    '''ErrorCode RadioLibInterface::send(meshtastic_MeshPacket *p)\n{\n\n#ifndef DISABLE_WELCOME_UNSET\n''',
    '''ErrorCode RadioLibInterface::send(meshtastic_MeshPacket *p)\n{\n#if defined(HELTEC_TRACKER_V1_1)\n    if (trackerAntennaTxLocked()) {\n        LOG_WARN("send - Tracker antenna swap TX lock");\n        txDrop++;\n        packetPool.release(p);\n        return ERRNO_DISABLED;\n    }\n#endif\n\n#ifndef DISABLE_WELCOME_UNSET\n''',
    "reject new Tracker packets while antenna swap TX lock is active",
)

radio = replace_once(
    radio,
    '''bool RadioLibInterface::startSend(meshtastic_MeshPacket *txp)\n{\n    /* NOTE: Minimize the actions before startTransmit() to keep the time between\n             channel scan and actual transmit as low as possible to avoid collisions. */\n    if (disabled || !config.lora.tx_enabled) {\n        LOG_WARN("Drop Tx packet because LoRa Tx disabled");\n''',
    '''bool RadioLibInterface::startSend(meshtastic_MeshPacket *txp)\n{\n    /* NOTE: Minimize the actions before startTransmit() to keep the time between\n             channel scan and actual transmit as low as possible to avoid collisions. */\n#if defined(HELTEC_TRACKER_V1_1)\n    const bool antennaSafetyLocked = trackerAntennaTxLocked();\n#else\n    constexpr bool antennaSafetyLocked = false;\n#endif\n    if (disabled || !config.lora.tx_enabled || antennaSafetyLocked) {\n        LOG_WARN("Drop Tx packet because %s", antennaSafetyLocked ? "Tracker antenna swap TX lock" : "LoRa Tx disabled");\n''',
    "gate Tracker actual RF startSend with antenna TX lock",
)

radio = replace_once(
    radio,
    '''            addReceiveMetadata(mp);\n\n            mp->which_payload_variant =\n''',
    '''            addReceiveMetadata(mp);\n#if defined(HELTEC_TRACKER_V1_1)\n            trackerAntennaOnRadioPacket(*mp);\n#endif\n\n            mp->which_payload_variant =\n''',
    "observe Tracker physical LoRa RX for passive antenna A/B samples",
)


# ---------------------------------------------------------------------------
# Tracker native service UI. Antenna Test belongs under System because the
# Tracker has no dedicated antenna carousel page; this avoids duplicating normal
# pages while keeping the one-button stock selection-picker interaction.
# The INA226 patch runs immediately before this one, so preserve its menu state.
# ---------------------------------------------------------------------------
status = replace_once(
    status,
    '#include "vehicle/TrackerPowerMonitor.h"\n',
    '#include "vehicle/TrackerPowerMonitor.h"\n#include "vehicle/TrackerAntennaTest.h"\n',
    "include Tracker antenna test in native service UI",
)

status = replace_once(
    status,
    '''    POWER_STATS,\n    INA226_HW,\n};\n''',
    '''    POWER_STATS,\n    INA226_HW,\n    ANTENNA_TEST,\n};\n''',
    "add Tracker antenna test menu state",
)

old_system = '''    case TrackerMenu::SYSTEM: {\n        static const char *opts[] = {"Back", "System Info", "Diagnostics", "Power Statistics", "INA226 Hardware"};\n        showTrackerOptions("System", opts, 5, initialSelection, [](int selected) {\n            if (selected == 0) queueTrackerMenu(TrackerMenu::ROOT, trackerRootSelection);\n            else if (selected == 1) queueTrackerMenu(TrackerMenu::SYSTEM_INFO, 0);\n            else if (selected == 2) queueTrackerMenu(TrackerMenu::DIAGNOSTICS, 0);\n            else if (selected == 3) queueTrackerMenu(TrackerMenu::POWER_STATS, 0);\n            else if (selected == 4) queueTrackerMenu(TrackerMenu::INA226_HW, 0);\n        });\n        break;\n    }\n'''
new_system = '''    case TrackerMenu::SYSTEM: {\n        static const char *opts[] = {"Back", "System Info", "Diagnostics", "Power Statistics", "INA226 Hardware", "Antenna Test"};\n        showTrackerOptions("System", opts, 6, initialSelection, [](int selected) {\n            if (selected == 0) queueTrackerMenu(TrackerMenu::ROOT, trackerRootSelection);\n            else if (selected == 1) queueTrackerMenu(TrackerMenu::SYSTEM_INFO, 0);\n            else if (selected == 2) queueTrackerMenu(TrackerMenu::DIAGNOSTICS, 0);\n            else if (selected == 3) queueTrackerMenu(TrackerMenu::POWER_STATS, 0);\n            else if (selected == 4) queueTrackerMenu(TrackerMenu::INA226_HW, 0);\n            else if (selected == 5) queueTrackerMenu(TrackerMenu::ANTENNA_TEST, 0);\n        });\n        break;\n    }\n'''
status = replace_once(status, old_system, new_system, "add Antenna Test to Tracker System menu")

antenna_case = r'''    case TrackerMenu::ANTENNA_TEST: {
        static char stateLine[40], refLine[40], sampleLine[40], aLine[48], bLine[48], safetyLine[48], resultLine[48], actionLine[48];
        static const char *opts[] = {"Back", stateLine, refLine, sampleLine, aLine, bLine, safetyLine, resultLine, actionLine};
        const TrackerAntennaState a = trackerAntennaState();

        snprintf(stateLine, sizeof(stateLine), "State: %s", trackerAntennaPhaseText(a.phase));
        if (a.referenceNode)
            snprintf(refLine, sizeof(refLine), "Ref: %s !%04x", a.referenceName, (unsigned)(a.referenceNode & 0xffffU));
        else
            snprintf(refLine, sizeof(refLine), "Ref: last direct on start");

        if (a.phase == TrackerAntennaPhase::A_RUNNING || a.phase == TrackerAntennaPhase::B_RUNNING)
            snprintf(sampleLine, sizeof(sampleLine), "Samples: %u/60  min 40", (unsigned)a.liveSamples);
        else
            snprintf(sampleLine, sizeof(sampleLine), "Samples: min 40 / target 60");

        if (a.a.valid)
            snprintf(aLine, sizeof(aLine), "A: %ddBm  SNR %+.1fdB", (int)a.a.medianRssiDbm, a.a.medianSnrQ4 / 4.0f);
        else
            snprintf(aLine, sizeof(aLine), "A: --");
        if (a.b.valid)
            snprintf(bLine, sizeof(bLine), "B: %ddBm  SNR %+.1fdB", (int)a.b.medianRssiDbm, a.b.medianSnrQ4 / 4.0f);
        else
            snprintf(bLine, sizeof(bLine), "B: --");

        if (a.txLocked)
            snprintf(safetyLine, sizeof(safetyLine), "TX: LOCKED %s", a.txSafeToSwap ? "SAFE" : "WAIT");
        else
            snprintf(safetyLine, sizeof(safetyLine), "TX: NORMAL");

        if (a.a.valid && a.b.valid) {
            const char *winner = a.deltaRssiDb >= 3 ? "B MUCH BETTER" :
                                 a.deltaRssiDb <= -3 ? "A MUCH BETTER" :
                                 a.deltaRssiDb >= 1 ? "B BETTER" :
                                 a.deltaRssiDb <= -1 ? "A BETTER" : "ABOUT EQUAL";
            snprintf(resultLine, sizeof(resultLine), "Delta: %+ddB  %s", (int)a.deltaRssiDb, winner);
        } else {
            snprintf(resultLine, sizeof(resultLine), "Compare: passive direct RX");
        }

        switch (a.phase) {
        case TrackerAntennaPhase::IDLE:
            snprintf(actionLine, sizeof(actionLine), "ACTION: START A");
            break;
        case TrackerAntennaPhase::A_RUNNING:
            snprintf(actionLine, sizeof(actionLine), "ACTION: %s", a.liveSamples >= 40 ? "SAVE A" : "CHECK A");
            break;
        case TrackerAntennaPhase::A_SAVED:
            snprintf(actionLine, sizeof(actionLine), "ACTION: PREP SWAP / LOCK TX");
            break;
        case TrackerAntennaPhase::SWAP_LOCKED:
            snprintf(actionLine, sizeof(actionLine), "ACTION: %s", a.txSafeToSwap ? "B CONNECTED / START B" : "WAIT TX FINISH");
            break;
        case TrackerAntennaPhase::B_RUNNING:
            snprintf(actionLine, sizeof(actionLine), "ACTION: %s", a.liveSamples >= 40 ? "SAVE B" : "CHECK B");
            break;
        case TrackerAntennaPhase::COMPLETE:
            snprintf(actionLine, sizeof(actionLine), "ACTION: NEW TEST");
            break;
        }

        showTrackerOptions("Antenna Test", opts, 9, initialSelection, [](int selected) {
            if (selected == 0) {
                queueTrackerMenu(TrackerMenu::SYSTEM, 5);
            } else if (selected == 8) {
                trackerAntennaHandleAction();
                queueTrackerMenu(TrackerMenu::ANTENNA_TEST, 8);
            } else {
                // Informational rows are selectable only so one-button users can
                // refresh the live sample/TX-safe state without changing it.
                queueTrackerMenu(TrackerMenu::ANTENNA_TEST, selected);
            }
        });
        break;
    }

'''

start = status.find('void showTrackerMenu(TrackerMenu menu, int initialSelection)\n')
end = status.find('bool trackerServiceMenuActive()\n', start)
if start < 0 or end < 0:
    raise SystemExit("Tracker Antenna Test: showTrackerMenu boundary not found")
segment = status[start:end]
if 'case TrackerMenu::ANTENNA_TEST:' not in segment:
    default_pos = segment.rfind('    default:\n')
    if default_pos < 0:
        raise SystemExit("Tracker Antenna Test: final menu default not found")
    absolute = start + default_pos
    status = status[:absolute] + antenna_case + status[absolute:]
    print("Tracker Antenna Test submenu: applied")
else:
    print("Tracker Antenna Test submenu: already applied")


for text, needle in [
    (common, 'trackerAntennaTestInit();'),
    (radio, 'trackerAntennaTxLocked()'),
    (radio, 'trackerAntennaOnRadioPacket(*mp);'),
    (radio, 'const bool antennaSafetyLocked = trackerAntennaTxLocked();'),
    (status, 'TrackerMenu::ANTENNA_TEST'),
    (status, '"INA226 Hardware", "Antenna Test"'),
    (status, 'ACTION: PREP SWAP / LOCK TX'),
    (status, 'B CONNECTED / START B'),
    (status, 'TX: LOCKED %s'),
]:
    if needle not in text:
        raise SystemExit(f"Tracker antenna safety verification failed: {needle}")

COMMON.write_text(common)
STATUS.write_text(status)
RADIO.write_text(radio)
print("Tracker antenna test ready: passive A/B RX + deliberate persistent TX swap lock + reboot-safe radio gate")
