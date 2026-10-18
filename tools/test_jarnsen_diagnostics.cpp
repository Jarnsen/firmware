#include "Arduino.h"
#include "BluetoothStatus.h"
#include "FSCommon.h"
#include "GPSStatus.h"
#include "PowerStatus.h"
#include "configuration.h"
#include "esp_sleep.h"
#include "esp_system.h"
#include "jarnsen/core/mesh/JarnsenNodeStateCache.h"
#include "jarnsen/core/service/JarnsenDiagnosticLog.h"
#include "jarnsen/core/service/JarnsenDiagnosticPolicy.h"

#include <cassert>
#include <cstdarg>
#include <cstdio>
#include <string>
#include <vector>

uint32_t testMs = 1000, testEpoch = 100000;
bool testIsr = false;
int testReset = ESP_RST_POWERON;
esp_sleep_wakeup_cause_t testWake = ESP_SLEEP_WAKEUP_UNDEFINED;
TestConfig config;
TestPower *powerStatus = nullptr;
TestBluetooth *bluetoothStatus = nullptr;
TestGps *gpsStatus = nullptr;
TestFS testFs;
std::vector<std::string> lines;
bool logEnabled = true;

double jarnsenPositionDistanceMeters(int32_t a, int32_t b, int32_t c, int32_t d)
{
    return a == c && b == d ? 0.0 : 30.0;
}

namespace jarnsen
{
DeviceRole testRole = DeviceRole::TAK_TRACKER;
bool diagnosticLogEnabled()
{
    return logEnabled;
}
void diagnosticLog(const char *event, const char *fmt, ...)
{
    if (!logEnabled)
        return;
    DiagnosticWriteScope scope;
    if (!scope)
        return;
    char detail[256]{}, line[512]{};
    va_list args;
    va_start(args, fmt);
    vsnprintf(detail, sizeof(detail), fmt, args);
    va_end(args);
    if (diagnosticFormatLine(line, sizeof(line), event, detail)) {
        lines.emplace_back(line);
        diagnosticNoteWrite(true);
    }
}
} // namespace jarnsen

bool contains(const char *text)
{
    for (const auto &line : lines)
        if (line.find(text) != std::string::npos)
            return true;
    return false;
}

void testRepeatAndCrc()
{
    using namespace jarnsen;
    DiagnosticRepeatGate gate;
    uint32_t repeats = 0;
    assert(gate.accept("SLEEP_VETO", "usb=1", testMs, false, repeats));
    testMs += 10;
    assert(!gate.accept("SLEEP_VETO", "usb=1", testMs, false, repeats));
    assert(gate.accept("SLEEP_VETO", "service=1", testMs, false, repeats));
    assert(gate.accept("ERROR", "same", testMs, false, repeats));
    assert(gate.accept("ERROR", "same", testMs, false, repeats));
    assert(gate.accept("SLEEP_VETO", "usb=1", testMs, true, repeats));
    testMs += 60000;
    char event[24]{}, context[64]{};
    assert(gate.takeSummary(event, sizeof(event), context, sizeof(context), repeats));
    assert(std::string(event) == "SLEEP_VETO" && repeats == 1 && std::string(context) == "usb=1");
    testMs = UINT32_MAX - 100;
    DiagnosticRepeatGate wrap;
    assert(wrap.accept("CACHE", "same", testMs, false, repeats));
    testMs = 50;
    assert(!wrap.accept("CACHE", "same", testMs, false, repeats));
    const auto *bytes = reinterpret_cast<const uint8_t *>("123456789");
    assert((diagnosticCrc32(0xffffffffU, bytes, 9) ^ 0xffffffffU) == 0xcbf43926U);
    const uint32_t split = diagnosticCrc32(diagnosticCrc32(0xffffffffU, bytes, 4), bytes + 4, 5);
    assert((split ^ 0xffffffffU) == 0xcbf43926U);
    char multiline[320]{};
    assert(diagnosticFormatLine(multiline, sizeof(multiline), "WARN ", "line1\r\nline2"));
    assert(!std::strchr(multiline, '\n') && !std::strchr(multiline, '\r'));
}

void testCachePolicies()
{
    using namespace jarnsen;
    struct Scenario {
        DeviceRole role;
        NodeMovement movement;
        uint32_t ttl;
    };
    const Scenario scenarios[] = {
        {DeviceRole::TAK, NodeMovement::STATIONARY, 7200},
        {DeviceRole::TAK, NodeMovement::MOVING, 1200},
        {DeviceRole::TAK_TRACKER, NodeMovement::STATIONARY, 7200},
        {DeviceRole::TAK_TRACKER, NodeMovement::MOVING, 1200},
        {DeviceRole::TAK_REPEATER, NodeMovement::STATIONARY, 21600},
        {DeviceRole::TAK_REPEATER, NodeMovement::MOVING, 900},
        {DeviceRole::DRONE_REPEATER, NodeMovement::STATIONARY, 3600},
        {DeviceRole::DRONE_REPEATER, NodeMovement::MOVING, 600},
        {DeviceRole::UNCONFIGURED, NodeMovement::STATIONARY, 3600},
        {DeviceRole::UNCONFIGURED, NodeMovement::MOVING, 900},
    };
    for (const auto &scenario : scenarios) {
        NodeStateCache cache;
        NodeStateRecord record;
        record.nodeNum = 42;
        record.packetId = 123;
        record.sourceEpoch = 1000;
        record.rxEpoch = 1000;
        record.latitudeI = 500000000;
        record.longitudeI = 80000000;
        record.role = scenario.role;
        record.movement = scenario.movement;
        const auto opens = testFs.opens;
        assert(cache.note(record, 1000));
        assert(testFs.opens == opens); // Radio/cache path never touches the filesystem.
        NodeStateRecord found;
        assert(cache.find(42, found));
        assert(found.expiresEpoch == 1000 + scenario.ttl);
        record.sourceEpoch = 999;
        assert(!cache.note(record, 1000));
        record.sourceEpoch = 1000;
        record.origin = NodeStateOrigin::SYNC;
        assert(!cache.note(record, 1000));
        record.sourceEpoch = 1001;
        record.expiresEpoch = 1050;
        assert(cache.note(record, 1001));
        assert(cache.find(42, found) && found.expiresEpoch == 1050);
        cache.prune(1050);
        assert(!cache.find(42, found));
        assert(cache.count(1050) == 0);
    }
    NodeStateCache full;
    NodeStateRecord record;
    record.latitudeI = 500000000;
    record.longitudeI = 80000000;
    record.sourceEpoch = 1000;
    record.movement = NodeMovement::STATIONARY;
    record.role = DeviceRole::TAK;
    for (unsigned i = 1; i <= 129; ++i) {
        record.nodeNum = i;
        assert(full.note(record, 1000));
    }
    NodeStateRecord found;
    assert(full.count(1000) == 128 && !full.find(1, found) && full.find(129, found));
    record.sourceEpoch = 0;
    record.rxEpoch = 0;
    assert(!full.note(record, 1000));
    record.sourceEpoch = 1000;
    assert(!full.note(record, 9000));
    full.clear();
    assert(full.count(1000) == 0);
    record.nodeNum = 42;
    record.sourceEpoch = UINT32_MAX - 100;
    assert(full.note(record, record.sourceEpoch));
    assert(full.find(42, found) && found.expiresEpoch == UINT32_MAX);
    full.clear();
    record.sourceEpoch = 1000;
    record.role = DeviceRole::TAK_REPEATER;
    record.movement = NodeMovement::MOVING;
    assert(full.note(record, 1000));
    full.updateRole(42, DeviceRole::DRONE_REPEATER, 1700);
    assert(!full.find(42, found));
}

int main()
{
    using namespace jarnsen;
    testRepeatAndCrc();
    testMs = 1000;
    assert(!diagnosticTryWrite());
    diagnosticPolicyInit();
    testIsr = true;
    assert(!diagnosticTryWrite());
    testIsr = false;
    assert(diagnosticTryWrite());
    assert(!diagnosticTryWrite());
    diagnosticEndWrite();
    assert(!diagnosticConsoleLevelEnabled("DEBUG"));
    assert(!diagnosticConsoleLevelEnabled("INFO "));
    assert(diagnosticConsoleLevelEnabled("WARN "));
    diagnosticSetDetailEnabled(true);
    assert(diagnosticConsoleLevelEnabled("DEBUG"));
    testMs += DIAGNOSTIC_DETAIL_MS;
    assert(!diagnosticDetailEnabled());
    testMs = UINT32_MAX - 100;
    diagnosticSetDetailEnabled(true);
    testMs = 50;
    assert(diagnosticDetailEnabled());
    diagnosticSetDetailEnabled(false);
    testMs = 1000;
#ifdef ARCH_ESP32
    diagnosticSleepEnter(true, 600000);
    testEpoch += 600;
    testReset = ESP_RST_DEEPSLEEP;
    testWake = ESP_SLEEP_WAKEUP_TIMER;
    diagnosticRuntimeTick();
    assert(contains("resumed=1") && contains("actual_s=600") && contains("cause=timer"));
    diagnosticSleepEnter(true, 600000);
    testRole = DeviceRole::TAK_REPEATER;
    testReset = ESP_RST_PANIC;
    diagnosticRuntimeTick();
    assert(contains("resumed=0 reset=4"));
#endif
    for (auto role : {DeviceRole::TAK, DeviceRole::TAK_TRACKER, DeviceRole::TAK_REPEATER, DeviceRole::DRONE_REPEATER}) {
        testRole = role;
        testMs += 60001;
        diagnosticRuntimeTick();
        assert(contains(roleKey(role)));
    }
    for (int i = 0; i < 20; ++i)
        diagnosticRuntimeTick();
    const auto opens = testFs.opens;
    diagnosticSleepEnter(false, 300000);
    testMs += 123;
    diagnosticSleepWake(300000, 123, 0, ESP_SLEEP_WAKEUP_GPIO, 0, 1, -1);
    assert(testFs.opens == opens);
    diagnosticRuntimeTick();
    assert(contains("mode=light") && contains("actual_ms=123") && contains("at_ms="));
#ifdef ARCH_ESP32
    assert(contains("gpio_unresolved") && contains("levels_are_hints=1"));
    diagnosticSleepWake(30000, 30000, 0, ESP_SLEEP_WAKEUP_TIMER, 1, 0, -1);
    diagnosticRuntimeTick();
    diagnosticSleepWake(30000, 2, 259, ESP_SLEEP_WAKEUP_UNDEFINED, 1, 1, -1);
    diagnosticRuntimeTick();
    assert(contains("cause=start_rejected"));
    testMs += 60001;
    diagnosticRuntimeTick();
    assert(contains("timer=1 gpio_unresolved=1 other=0 start_rejected=1"));
#endif
    testCachePolicies();
    for (int i = 0; i < 20; ++i)
        diagnosticRuntimeTick();
    diagnosticNoteWrite(false);
    diagnosticNoteRotation(4096);
    testFs.files["old"] = "UPTIME+1s | FIRST | old\nUPTIME+2s | SECOND | old\n";
    testFs.files["cur"] = "UPTIME+3s | LAST | now\n";
    const auto currentBytes = testFs.files["cur"].size();
    testFs.files["cur"] += "UPTIME+99s | LATER | outside snapshot\n";
    char metadata[640]{};
    assert(diagnosticSnapshotMetadata(metadata, sizeof(metadata), "old", testFs.files["old"].size(), "cur", currentBytes));
    assert(std::strstr(metadata, "history_first=UPTIME+1s"));
    assert(std::strstr(metadata, "history_last=UPTIME+3s"));
    assert(!std::strstr(metadata, "UPTIME+99s"));
    assert(std::strstr(metadata, "discarded_bytes=4096"));
    assert(std::strstr(metadata, "io_errors=1"));
    assert(!diagnosticSnapshotMetadata(metadata, 10, "old", 1, "cur", 1));
    puts("PASS diagnostic policy, role TTLs, wake semantics, bounded queue, ISR/reentry, rollover, snapshot and CRC");
}
