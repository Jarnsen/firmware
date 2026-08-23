from pathlib import Path

SERVICE = Path("src/infrastructure/HeltecV3ServicePage.cpp")
MESH_H = Path("src/infrastructure/HeltecV3MeshMonitor.h")
MESH = Path("src/infrastructure/HeltecV3MeshMonitor.cpp")
MESH_PAGE = Path("src/infrastructure/HeltecV3MeshPages.cpp")
RADIO = Path("src/mesh/RadioLibInterface.cpp")

service = SERVICE.read_text()
mesh_h = MESH_H.read_text()
mesh = MESH.read_text()
mesh_page = MESH_PAGE.read_text()
radio = RADIO.read_text()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"{label}: already applied")
        return text
    if old not in text:
        raise SystemExit(f"{label}: anchor not found")
    print(f"{label}: applied")
    return text.replace(old, new, 1)


# Mesh Health and Antenna Test already have dedicated first-class pages.
# Keep the Service picker only for deeper service functions.
old_root = '''    case V3ServiceMenu::ROOT: {
        // Previous verified root signature retained as a migration breadcrumb:
        // static const char *options[] = {"Back", "Mesh Health", "Antenna Test", "Diagnostic Log"};
        static const char *options[] = {"Back", "Mesh Health", "Antenna Test", "Power Statistics", "Diagnostic Log"};
        showOptions("V3 Service", options, 5, [](int selected) {
            switch (selected) {
            case 0: queueAction(V3MenuAction::CLOSE); break;
            case 1: queueAction(V3MenuAction::NAV_MESH); break;
            case 2: queueAction(V3MenuAction::NAV_ANTENNA); break;
            case 3: queueMenu(V3ServiceMenu::POWER_STATS); break;
            case 4: queueMenu(V3ServiceMenu::DIAG_LOG); break;
            default: break;
            }
        });
        break;
    }
'''
new_root = '''    case V3ServiceMenu::ROOT: {
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
service = replace_once(service, old_root, new_root, "deduplicate V3 service root")

service = replace_once(
    service,
    'enum class V3MenuAction : uint8_t { NONE = 0, CLOSE, NAV_MESH, NAV_ANTENNA, EXPORT_LOG, CLEAR_LOG };',
    'enum class V3MenuAction : uint8_t { NONE = 0, CLOSE, EXPORT_LOG, CLEAR_LOG };',
    "remove duplicate service navigation actions",
)

navigate_block = '''void navigateFromService(unsigned pagesForward)
{
    closeMenuInternal(false);
    if (!screen)
        return;
    for (unsigned i = 0; i < pagesForward; ++i)
        screen->showNextFrame();
    screen->runNow();
}

'''
if navigate_block in service:
    service = service.replace(navigate_block, '', 1)
    print("remove duplicate service navigation helper: applied")
else:
    print("remove duplicate service navigation helper: already absent")

nav_cases = '''    case V3MenuAction::NAV_MESH:
        // Local page order is Position -> Service -> Mesh Health -> Antenna Test.
        navigateFromService(1);
        break;
    case V3MenuAction::NAV_ANTENNA:
        navigateFromService(2);
        break;
'''
if nav_cases in service:
    service = service.replace(nav_cases, '', 1)
    print("remove duplicate service navigation cases: applied")
else:
    print("remove duplicate service navigation cases: already absent")

service = replace_once(
    service,
    '#include "infrastructure/HeltecV3PowerMonitor.h"\n',
    '#include "infrastructure/HeltecV3PowerMonitor.h"\n#include "infrastructure/HeltecV3MeshMonitor.h"\n',
    "show antenna TX lock on Service page",
)

service = replace_once(
    service,
    '''    display->setTextAlignment(TEXT_ALIGN_RIGHT);
    snprintf(line, sizeof(line), "USB:%s", heltecV3RuntimeUsbMaintenanceActive() ? "MAINT" : "OFF");
    display->drawString(right, textPos[2], line);
''',
    '''    display->setTextAlignment(TEXT_ALIGN_RIGHT);
    if (heltecV3AntennaTxLocked())
        snprintf(line, sizeof(line), "TX:LOCK");
    else
        snprintf(line, sizeof(line), "USB:%s", heltecV3RuntimeUsbMaintenanceActive() ? "MAINT" : "OFF");
    display->drawString(right, textPos[2], line);
''',
    "show persistent antenna TX lock in compact Service status",
)


# Preserve old persisted phase numbers: append SWAP_LOCKED as value 5.
mesh_h = replace_once(
    mesh_h,
    '''enum class HeltecV3AntennaPhase : uint8_t {
    IDLE = 0,
    A_RUNNING,
    A_SAVED,
    B_RUNNING,
    COMPLETE,
};
''',
    '''enum class HeltecV3AntennaPhase : uint8_t {
    IDLE = 0,
    A_RUNNING = 1,
    A_SAVED = 2,
    B_RUNNING = 3,
    COMPLETE = 4,
    SWAP_LOCKED = 5,
};
''',
    "add persistent antenna swap phase without changing old values",
)

mesh_h = replace_once(
    mesh_h,
    '''    uint16_t liveSamples = 0;
    uint32_t liveSeconds = 0;
    HeltecV3AntennaResult a;
''',
    '''    uint16_t liveSamples = 0;
    uint32_t liveSeconds = 0;
    bool txLocked = false;
    bool txSafeToSwap = false;
    HeltecV3AntennaResult a;
''',
    "add antenna TX safety state to UI model",
)

mesh_h = replace_once(
    mesh_h,
    '''bool heltecV3AntennaHandleLongPress();
''',
    '''bool heltecV3AntennaHandleLongPress();

// Persistent safety lock used only during the deliberate A -> B antenna swap.
// RX/BLE/display/diagnostics continue; every new LoRa TX is blocked.
bool heltecV3AntennaTxLocked();
bool heltecV3AntennaTxSafeToSwap();
''',
    "expose antenna TX safety lock",
)


# Radio path: reject before queueing and gate startSend immediately before the PA.
# This double gate also covers packets that were already queued when the user
# deliberately entered the antenna swap lock.
radio = replace_once(
    radio,
    '#include "main.h"\n',
    '#include "main.h"\n#if defined(_VARIANT_HELTEC_V3)\n#include "infrastructure/HeltecV3MeshMonitor.h"\n#endif\n',
    "connect V3 antenna lock to radio TX path",
)

radio = replace_once(
    radio,
    '''ErrorCode RadioLibInterface::send(meshtastic_MeshPacket *p)
{

#ifndef DISABLE_WELCOME_UNSET
''',
    '''ErrorCode RadioLibInterface::send(meshtastic_MeshPacket *p)
{
#if defined(_VARIANT_HELTEC_V3)
    if (heltecV3AntennaTxLocked()) {
        LOG_WARN("send - V3 antenna swap TX lock");
        txDrop++;
        packetPool.release(p);
        return ERRNO_DISABLED;
    }
#endif

#ifndef DISABLE_WELCOME_UNSET
''',
    "reject new packets while antenna swap TX lock is active",
)

radio = replace_once(
    radio,
    '''bool RadioLibInterface::startSend(meshtastic_MeshPacket *txp)
{
    /* NOTE: Minimize the actions before startTransmit() to keep the time between
             channel scan and actual transmit as low as possible to avoid collisions. */
    if (disabled || !config.lora.tx_enabled) {
        LOG_WARN("Drop Tx packet because LoRa Tx disabled");
''',
    '''bool RadioLibInterface::startSend(meshtastic_MeshPacket *txp)
{
    /* NOTE: Minimize the actions before startTransmit() to keep the time between
             channel scan and actual transmit as low as possible to avoid collisions. */
#if defined(_VARIANT_HELTEC_V3)
    const bool antennaSafetyLocked = heltecV3AntennaTxLocked();
#else
    constexpr bool antennaSafetyLocked = false;
#endif
    if (disabled || !config.lora.tx_enabled || antennaSafetyLocked) {
        LOG_WARN("Drop Tx packet because %s", antennaSafetyLocked ? "V3 antenna swap TX lock" : "LoRa Tx disabled");
''',
    "gate actual RF startSend with antenna TX lock",
)


# Antenna monitor persistence and guided swap state.
mesh = replace_once(
    mesh,
    '#include "infrastructure/HeltecV3DiagnosticLog.h"\n',
    '#include "infrastructure/HeltecV3DiagnosticLog.h"\n#include "mesh/RadioLibInterface.h"\n',
    "allow antenna monitor to observe active RF TX",
)

mesh = replace_once(
    mesh,
    '''bool antennaLoaded = false;

bool roleEnabled()
''',
    '''bool antennaLoaded = false;
volatile bool antennaTxLocked = false;

bool roleEnabled()
''',
    "add runtime antenna TX lock state",
)

mesh = replace_once(
    mesh,
    '''    const uint8_t phase = prefs.getUChar("phase", 0);
    antennaPhase = phase <= (uint8_t)HeltecV3AntennaPhase::COMPLETE
                       ? (HeltecV3AntennaPhase)phase
                       : HeltecV3AntennaPhase::IDLE;
''',
    '''    const uint8_t phase = prefs.getUChar("phase", 0);
    antennaPhase = phase <= (uint8_t)HeltecV3AntennaPhase::SWAP_LOCKED
                       ? (HeltecV3AntennaPhase)phase
                       : HeltecV3AntennaPhase::IDLE;
''',
    "accept persisted SWAP_LOCKED phase",
)

mesh = replace_once(
    mesh,
    '''    antennaB.medianSnrQ4 = (int16_t)prefs.getShort("bSnr", 0);
    prefs.end();

    // A running test cannot survive power-off because its raw sample window is
    // intentionally RAM-only. A completed A result does survive so the antenna
    // can safely be changed with the V3 powered down.
    if (antennaPhase == HeltecV3AntennaPhase::A_RUNNING)
        antennaPhase = HeltecV3AntennaPhase::IDLE;
    else if (antennaPhase == HeltecV3AntennaPhase::B_RUNNING)
        antennaPhase = antennaA.valid ? HeltecV3AntennaPhase::A_SAVED : HeltecV3AntennaPhase::IDLE;
''',
    '''    antennaB.medianSnrQ4 = (int16_t)prefs.getShort("bSnr", 0);
    antennaTxLocked = prefs.getBool("swapLock", false);
    prefs.end();

    // Raw A/B sample windows are RAM-only. The explicit swap lock is different:
    // it MUST survive reboot so an accidental restart with no antenna cannot
    // silently re-enable automatic Meshtastic transmissions.
    if (antennaTxLocked) {
        antennaPhase = HeltecV3AntennaPhase::SWAP_LOCKED;
    } else if (antennaPhase == HeltecV3AntennaPhase::A_RUNNING) {
        antennaPhase = HeltecV3AntennaPhase::IDLE;
    } else if (antennaPhase == HeltecV3AntennaPhase::B_RUNNING) {
        antennaPhase = antennaA.valid ? HeltecV3AntennaPhase::A_SAVED : HeltecV3AntennaPhase::IDLE;
    } else if (antennaPhase == HeltecV3AntennaPhase::SWAP_LOCKED) {
        antennaPhase = antennaA.valid ? HeltecV3AntennaPhase::A_SAVED : HeltecV3AntennaPhase::IDLE;
    }
''',
    "restore persistent antenna swap TX lock safely",
)

mesh = replace_once(
    mesh,
    '''    prefs.putShort("bRssi", antennaB.medianRssiDbm);
    prefs.putShort("bSnr", antennaB.medianSnrQ4);
    prefs.end();
''',
    '''    prefs.putShort("bRssi", antennaB.medianRssiDbm);
    prefs.putShort("bSnr", antennaB.medianSnrQ4);
    prefs.putBool("swapLock", antennaTxLocked);
    prefs.end();
''',
    "persist antenna TX lock",
)

mesh = replace_once(
    mesh,
    '''    case HeltecV3AntennaPhase::B_RUNNING: return "B_RUNNING";
    case HeltecV3AntennaPhase::COMPLETE: return "COMPLETE";
''',
    '''    case HeltecV3AntennaPhase::B_RUNNING: return "B_RUNNING";
    case HeltecV3AntennaPhase::COMPLETE: return "COMPLETE";
    case HeltecV3AntennaPhase::SWAP_LOCKED: return "SWAP_LOCKED";
''',
    "name SWAP_LOCKED diagnostic phase",
)

mesh = replace_once(
    mesh,
    '''    out.liveSamples = liveSampleCount;
    out.liveSeconds = liveStartedMs ? (uint32_t)(millis() - liveStartedMs) / 1000UL : 0;
    out.a = antennaA;
''',
    '''    out.liveSamples = liveSampleCount;
    out.liveSeconds = liveStartedMs ? (uint32_t)(millis() - liveStartedMs) / 1000UL : 0;
    out.txLocked = antennaTxLocked;
    out.txSafeToSwap = heltecV3AntennaTxSafeToSwap();
    out.a = antennaA;
''',
    "publish antenna TX lock state",
)

mesh = replace_once(
    mesh,
    '''    case HeltecV3AntennaPhase::A_SAVED:
        antennaPhase = HeltecV3AntennaPhase::B_RUNNING;
        antennaB = HeltecV3AntennaResult{};
        clearLiveSamples();
        saveAntennaState();
        heltecV3DiagLog("ANT_B_START", "ref=!%08x target=%u minimum=%u", (unsigned)antennaReferenceNode,
                        (unsigned)ANT_TARGET_SAMPLES, (unsigned)ANT_MIN_SAMPLES);
        return true;

    case HeltecV3AntennaPhase::B_RUNNING: {
''',
    '''    case HeltecV3AntennaPhase::A_SAVED:
        // Saving A alone does not disturb repeater traffic. This second long
        // press deliberately enters the physical antenna-swap safety state.
        antennaPhase = HeltecV3AntennaPhase::SWAP_LOCKED;
        antennaTxLocked = true;
        saveAntennaState();
        heltecV3DiagLog("ANT_SWAP_LOCK", "TX locked; keep antenna connected until any in-flight TX is idle");
        return true;

    case HeltecV3AntennaPhase::SWAP_LOCKED:
        // Never auto-unlock on a timeout. New TX and queued TX attempts are
        // blocked by send() and startSend(). A packet that was already on-air
        // when PREPARE SWAP was pressed is allowed to finish with antenna A on.
        if (!heltecV3AntennaTxSafeToSwap()) {
            heltecV3DiagLog("ANT_SWAP_WAIT", "TX lock active but an RF transmission is still in flight; keep antenna connected");
            return true;
        }
        antennaB = HeltecV3AntennaResult{};
        clearLiveSamples();
        antennaPhase = HeltecV3AntennaPhase::B_RUNNING;
        antennaTxLocked = false; // explicit user confirmation that an antenna is connected
        saveAntennaState();
        heltecV3DiagLog("ANT_B_START",
                        "antenna connected confirmed; TX unlocked; ref=!%08x target=%u minimum=%u",
                        (unsigned)antennaReferenceNode, (unsigned)ANT_TARGET_SAMPLES, (unsigned)ANT_MIN_SAMPLES);
        return true;

    case HeltecV3AntennaPhase::B_RUNNING: {
''',
    "replace power-cycle antenna swap with persistent TX-lock flow",
)

mesh = replace_once(
    mesh,
    '''void heltecV3MeshMonitorPrintSnapshot(Print &out)
''',
    '''bool heltecV3AntennaTxLocked()
{
    loadAntennaState();
    return antennaTxLocked;
}

bool heltecV3AntennaTxSafeToSwap()
{
    loadAntennaState();
    if (!antennaTxLocked)
        return false;
    RadioLibInterface *radio = RadioLibInterface::instance;
    return radio && !radio->isSending();
}

void heltecV3MeshMonitorPrintSnapshot(Print &out)
''',
    "add antenna TX lock query helpers",
)

mesh = replace_once(
    mesh,
    '''    out.printf("ANTENNA phase=%s ref=%s !%08x live=%u A=%u/%ddBm/%+.2fdB B=%u/%ddBm/%+.2fdB\\r\\n",
               phaseText(ant.phase), ant.referenceName, (unsigned)ant.referenceNode, (unsigned)ant.liveSamples,
               (unsigned)ant.a.samples, (int)ant.a.medianRssiDbm, ant.a.medianSnrQ4 / 4.0f,
               (unsigned)ant.b.samples, (int)ant.b.medianRssiDbm, ant.b.medianSnrQ4 / 4.0f);
''',
    '''    out.printf("ANTENNA phase=%s ref=%s !%08x live=%u txLock=%u safeSwap=%u A=%u/%ddBm/%+.2fdB B=%u/%ddBm/%+.2fdB\\r\\n",
               phaseText(ant.phase), ant.referenceName, (unsigned)ant.referenceNode, (unsigned)ant.liveSamples,
               ant.txLocked ? 1U : 0U, ant.txSafeToSwap ? 1U : 0U,
               (unsigned)ant.a.samples, (int)ant.a.medianRssiDbm, ant.a.medianSnrQ4 / 4.0f,
               (unsigned)ant.b.samples, (int)ant.b.medianRssiDbm, ant.b.medianSnrQ4 / 4.0f);
''',
    "export antenna TX safety state in diagnostic snapshot",
)

mesh = replace_once(
    mesh,
    '''HeltecV3AntennaState heltecV3AntennaState() { return {}; }
bool heltecV3AntennaHandleLongPress() { return false; }

#endif''',
    '''HeltecV3AntennaState heltecV3AntennaState() { return {}; }
bool heltecV3AntennaHandleLongPress() { return false; }
bool heltecV3AntennaTxLocked() { return false; }
bool heltecV3AntennaTxSafeToSwap() { return false; }

#endif''',
    "add non-V3 antenna TX safety stubs",
)


# Guided OLED flow: A save is harmless. PREP SWAP engages TX lock. The user
# must keep A connected until the one already-active RF packet (if any) ends.
mesh_page = replace_once(
    mesh_page,
    '''    if (a.phase == HeltecV3AntennaPhase::A_SAVED) {
        snprintf(l, sizeof(l), "A:%ddBm", (int)a.a.medianRssiDbm);
        snprintf(r, sizeof(r), "SNR:%+.1fdB", a.a.medianSnrQ4 / 4.0f);
        drawPair(display, left, right, textPos[2], l, r);
        drawPair(display, left, right, textPos[3], "POWER OFF", "CHANGE ANT");
        drawPair(display, left, right, textPos[4], "", "HOLD:START B");
        finishStockPage(display, state, x, y);
        return;
    }

    if (a.phase == HeltecV3AntennaPhase::COMPLETE) {
''',
    '''    if (a.phase == HeltecV3AntennaPhase::A_SAVED) {
        snprintf(l, sizeof(l), "A:%ddBm", (int)a.a.medianRssiDbm);
        snprintf(r, sizeof(r), "SNR:%+.1fdB", a.a.medianSnrQ4 / 4.0f);
        drawPair(display, left, right, textPos[2], l, r);
        drawPair(display, left, right, textPos[3], "A SAVED", "TX NORMAL");
        drawPair(display, left, right, textPos[4], "", "HOLD:PREP SWAP");
        finishStockPage(display, state, x, y);
        return;
    }

    if (a.phase == HeltecV3AntennaPhase::SWAP_LOCKED) {
        if (!a.txSafeToSwap) {
            drawPair(display, left, right, textPos[2], "TX LOCKING", "WAIT");
            drawPair(display, left, right, textPos[3], "KEEP ANT", "CONNECTED");
            drawPair(display, left, right, textPos[4], "", "WAIT TX FINISH");
        } else {
            drawPair(display, left, right, textPos[2], "TX LOCKED", "SAFE");
            drawPair(display, left, right, textPos[3], "CHANGE A", "TO B");
            drawPair(display, left, right, textPos[4], "", "HOLD:B CONNECTED");
        }
        finishStockPage(display, state, x, y);
        return;
    }

    if (a.phase == HeltecV3AntennaPhase::COMPLETE) {
''',
    "guide live antenna swap with persistent TX lock",
)


required = [
    (service, 'static const char *options[] = {"Back", "Power Statistics", "Diagnostic Log"}'),
    (service, 'TX:LOCK'),
    (mesh_h, 'SWAP_LOCKED = 5'),
    (mesh_h, 'heltecV3AntennaTxLocked();'),
    (mesh, 'prefs.putBool("swapLock", antennaTxLocked);'),
    (mesh, 'ANT_SWAP_LOCK'),
    (mesh, 'ANT_SWAP_WAIT'),
    (mesh, 'return radio && !radio->isSending();'),
    (mesh_page, 'HOLD:PREP SWAP'),
    (mesh_page, 'HOLD:B CONNECTED'),
    (radio, 'send - V3 antenna swap TX lock'),
    (radio, 'antennaSafetyLocked'),
]
for text, needle in required:
    if needle not in text:
        raise SystemExit(f"V3 antenna TX safety verification failed: {needle}")

for forbidden in ['V3MenuAction::NAV_MESH', 'V3MenuAction::NAV_ANTENNA', 'navigateFromService(']:
    if forbidden in service:
        raise SystemExit(f"V3 service dedupe verification failed: {forbidden}")
if '"POWER OFF", "CHANGE ANT"' in mesh_page:
    raise SystemExit("V3 antenna safety verification failed: old power-cycle swap UI remains")

SERVICE.write_text(service)
MESH_H.write_text(mesh_h)
MESH.write_text(mesh)
MESH_PAGE.write_text(mesh_page)
RADIO.write_text(radio)

print("V3 antenna safety ready: PREP SWAP -> persistent central TX lock -> antenna confirm -> B test")
