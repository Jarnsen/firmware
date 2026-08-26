"""Enable a service-scoped Bluetooth serial/debug log stream.

The stream reuses Meshtastic's existing LOGRADIO protobuf characteristic but
allows it only while the Jarnsen PC tool explicitly holds an encrypted service
session. It does not permanently enable config.security.debug_log_api_enabled.
"""

from pathlib import Path

NIMBLE = Path("src/nimble/NimbleBluetooth.cpp")
REDIRECT = Path("src/RedirectablePrint.cpp")

nimble = NIMBLE.read_text(encoding="utf-8")
redirect = REDIRECT.read_text(encoding="utf-8")

session_anchor = '''static std::atomic<bool> jarnsenLiveSession{false};
static std::atomic<JarnsenLiveCommand> jarnsenLiveCommand{JarnsenLiveCommand::NONE};
'''
if "jarnsenBtSerialSession" not in nimble:
    if nimble.count(session_anchor) != 1:
        raise SystemExit("Jarnsen live-session anchor not found exactly once")
    nimble = nimble.replace(
        session_anchor,
        '''static std::atomic<bool> jarnsenLiveSession{false};
static std::atomic<bool> jarnsenBtSerialSession{false};
static std::atomic<JarnsenLiveCommand> jarnsenLiveCommand{JarnsenLiveCommand::NONE};
''',
        1,
    )

service_end_anchor = '''static bool jarnsenServiceActive()
{
#if defined(HELTEC_TRACKER_V1_1)
    return trackerCommonServiceActive();
#else
    return heltecV3RuntimeServiceActive();
#endif
}
'''
# V3 and Tracker branches have opposite inactive fallback in their branch-local
# copy, so insert after the closing function using a regex-free structural find.
if 'extern "C" bool meshtasticJarnsenBtSerialLogActive()' not in nimble:
    start = nimble.find("static bool jarnsenServiceActive()")
    if start < 0:
        raise SystemExit("jarnsenServiceActive not found")
    end = nimble.find("\n}\n", start)
    if end < 0:
        raise SystemExit("jarnsenServiceActive end not found")
    end += 3
    helper = '''
extern "C" bool meshtasticJarnsenBtSerialLogActive()
{
    return jarnsenBtSerialSession.load() && jarnsenServiceActive() && nimbleBluetooth && nimbleBluetooth->isActive() &&
           nimbleBluetooth->isConnected();
}
'''
    nimble = nimble[:end] + helper + nimble[end:]

callback_anchor = '''        } else if (length == 8 && memcmp(data, "CLEARLOG", 8) == 0) {
            cancelJarnsenBleExport();
            clearJarnsenDiagLog();
            characteristic->setValue((const uint8_t *)"CLEARED", 7);
        } else if (length == 4 && memcmp(data, "HOLD", 4) == 0) {
'''
if 'memcmp(data, "BTLOGON", 7)' not in nimble:
    callback_new = '''        } else if (length == 8 && memcmp(data, "CLEARLOG", 8) == 0) {
            cancelJarnsenBleExport();
            clearJarnsenDiagLog();
            characteristic->setValue((const uint8_t *)"CLEARED", 7);
        } else if (length == 7 && memcmp(data, "BTLOGON", 7) == 0) {
            const bool allowed = jarnsenServiceActive() && setJarnsenBleQueueHold(true);
            jarnsenBtSerialSession = allowed;
            const char *status = allowed ? "BTLOG_READY" : "LOCKED";
            characteristic->setValue((const uint8_t *)status, strlen(status));
        } else if (length == 8 && memcmp(data, "BTLOGOFF", 8) == 0) {
            jarnsenBtSerialSession = false;
            setJarnsenBleQueueHold(false);
            characteristic->setValue((const uint8_t *)"IDLE", 4);
        } else if (length == 4 && memcmp(data, "HOLD", 4) == 0) {
'''
    if nimble.count(callback_anchor) != 1:
        raise SystemExit("CLEARLOG callback anchor not found exactly once")
    nimble = nimble.replace(callback_anchor, callback_new, 1)

reset_anchor = '''    cancelJarnsenBleExport();
    jarnsenLiveSession = false;
'''
if "jarnsenBtSerialSession.exchange(false)" not in nimble:
    reset_new = '''    cancelJarnsenBleExport();
    if (jarnsenBtSerialSession.exchange(false))
        setJarnsenBleQueueHold(false);
    jarnsenLiveSession = false;
'''
    if nimble.count(reset_anchor) != 1:
        raise SystemExit("BLE reset-session anchor not found exactly once")
    nimble = nimble.replace(reset_anchor, reset_new, 1)

weak_anchor = '''#if HAS_NETWORKING
extern meshtastic::Syslog syslog;
#endif
'''
if "meshtasticJarnsenBtSerialLogActive" not in redirect:
    if redirect.count(weak_anchor) != 1:
        raise SystemExit("RedirectablePrint weak-function anchor not found")
    redirect = redirect.replace(
        weak_anchor,
        weak_anchor + 'extern "C" bool meshtasticJarnsenBtSerialLogActive() __attribute__((weak));\n',
        1,
    )

gate_anchor = '''    if (config.security.debug_log_api_enabled && !pauseBluetoothLogging) {
'''
if "jarnsenServiceLog" not in redirect:
    gate_new = '''    const bool jarnsenServiceLog =
        meshtasticJarnsenBtSerialLogActive && meshtasticJarnsenBtSerialLogActive();
    if ((config.security.debug_log_api_enabled || jarnsenServiceLog) && !pauseBluetoothLogging) {
'''
    if redirect.count(gate_anchor) != 1:
        raise SystemExit("RedirectablePrint BLE-log gate anchor not found")
    redirect = redirect.replace(gate_anchor, gate_new, 1)

for marker in (
    "jarnsenBtSerialSession",
    'memcmp(data, "BTLOGON", 7)',
    'memcmp(data, "BTLOGOFF", 8)',
    '"BTLOG_READY"',
    'extern "C" bool meshtasticJarnsenBtSerialLogActive()',
):
    if marker not in nimble:
        raise SystemExit(f"missing NimBLE BT serial marker: {marker}")

for marker in (
    "meshtasticJarnsenBtSerialLogActive",
    "jarnsenServiceLog",
    "config.security.debug_log_api_enabled || jarnsenServiceLog",
):
    if marker not in redirect:
        raise SystemExit(f"missing RedirectablePrint BT serial marker: {marker}")

NIMBLE.write_text(nimble, encoding="utf-8")
REDIRECT.write_text(redirect, encoding="utf-8")
print("Jarnsen service-scoped Bluetooth LOGRADIO serial stream enabled")
