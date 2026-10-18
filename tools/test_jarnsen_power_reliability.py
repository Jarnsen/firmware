#!/usr/bin/env python3
"""Exercise production sleep gates, power status, and RX wiring without hardware."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source(path):
    return (ROOT / path).read_text()


def definition(text, signature):
    start = text.index(signature)
    opening = text.index("{", start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


class PowerReliabilityTest(unittest.TestCase):
    def compile_run(self, body):
        compiler = shutil.which("g++") or shutil.which("clang++")
        self.assertIsNotNone(compiler, "Native C++ compiler required")
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            (temp / "Arduino.h").write_text(
                "#pragma once\n#include <cstdint>\n#include <cstddef>\n"
                "uint32_t millis();\n"
            )
            (temp / "configuration.h").write_text(
                "#pragma once\n#define BATTERY_PIN 1\n"
            )
            (temp / "PowerStatus.h").write_text(source("src/PowerStatus.h"))
            program = temp / "test.cpp"
            program.write_text(body)
            binary = temp / "test"
            subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-Wno-unused-parameter",
                    "-I" + str(temp),
                    "-I" + str(ROOT / "src"),
                    str(program),
                    "-o",
                    str(binary),
                ],
                check=True,
            )
            subprocess.run([str(binary)], check=True)

    def test_sleep_veto_releases_scheduler_and_preserves_safety(self):
        sleep = source("src/sleep.cpp")
        common = source("src/vehicle/TrackerCommonPolicy.cpp")
        runtime = source("src/jarnsen/core/runtime/JarnsenRuntimePolicy.cpp")
        harness = r"""
#include <cassert>
#include <cstdarg>
#include <cstdint>
#include <string>
#include "Observer.h"
uint32_t nowMs=100, flushes=0, bleStops=0;
uint32_t millis() { return nowMs; }
struct Throttle {
 static bool isWithinTimespanMs(uint32_t at,uint32_t span) { return uint32_t(nowMs-at)<span; }
};
std::string lastEvent, lastDetail;
namespace jarnsen {
 void diagnosticLog(const char *,const char *,...) {}
 void diagnosticQueueEvent(const char *event,const char *fmt,...) {
  char detail[256]; va_list args;va_start(args,fmt);
  vsnprintf(detail,sizeof detail,fmt,args);va_end(args);
  lastEvent=event;lastDetail=detail;
 }
 enum class DeviceRole { TAK };
 bool takActive=true;
 bool activeDeviceRoleIs(DeviceRole) { return takActive; }
}
using namespace jarnsen;
Observable<void *> preflightSleep;
bool criticalSleepRequested=false;
bool serviceActive=false,motionActive=false,motionCandidatePending=false,parkHeartbeatFixPending=false;
bool parkSleepReadyForPreflight=false;
uint32_t finalPositionWaitStartedMs=0;
bool trackerRoleEnabled() { return true; }
struct Console { void flush(){++flushes;} } consoleObject, *console=&consoleObject;
void setBluetoothEnable(bool enable) { assert(!enable);++bleStops; }
bool usb=false;
struct Power { bool getHasUSB(){return usb;} } powerObject, *powerStatus=&powerObject;
bool radioBusy=false;
struct RadioObserver:Observer<void *> { int onNotify(void *) override{return radioBusy ? 1:0;} } radio;
"""
        harness += definition(sleep, "bool isCriticalSleepRequested()")
        harness += definition(sleep, "bool doPreflightSleep(")
        harness += definition(sleep, "static bool waitEnterSleep(")
        harness += definition(common, "class TrackerCommonSleepObserver") + ";\n"
        harness += definition(runtime, "class JarnsenTakSleepObserver") + ";\n"
        deep_prefix = sleep.split("void doDeepSleep(", 1)[1].split(
            "    jarnsen::diagnosticSleepEnter", 1
        )[0]
        harness += r"""
#define LOG_INFO(...) ((void)0)
#define LOG_POWERFSM(...) ((void)0)
constexpr bool INCLUDE_vTaskSuspend=false;
constexpr uint32_t portMAX_DELAY=UINT32_MAX;
bool deepEntered=false;
void doDeepSleep(""" + deep_prefix + " deepEntered=true; }\n"
        light_prefix = sleep.split("esp_sleep_wakeup_cause_t doLightSleep(", 1)[
            1
        ].split("    notifyLightSleep.notifyObservers", 1)[0]
        harness += (
            r"""
enum esp_sleep_wakeup_cause_t { ESP_SLEEP_WAKEUP_UNDEFINED, ESP_SLEEP_WAKEUP_TIMER };
unsigned lightEntered=0;
esp_sleep_wakeup_cause_t doLightSleep("""
            + light_prefix
            + " ++lightEntered; return ESP_SLEEP_WAKEUP_TIMER; }\n"
        )
        fsm = source("src/PowerFSM.cpp")
        harness += r"""
struct Config {struct {uint32_t sds_secs=300;} power;} config;
struct Default { static uint32_t getConfiguredOrDefaultMs(uint32_t s){return s*1000;} };
constexpr uint32_t PREFLIGHT_SLEEP_RETRY_MS=1000;
static uint32_t lastSdsAttemptMs=0;
"""
        for name in ("sdsEnter", "lowBattSDSEnter", "sdsIdle", "lowBattSdsIdle"):
            harness += definition(fsm, "static void " + name + "()")
        harness += r"""
int main() {
 radio.observe(&preflightSleep,"radio");
 TrackerCommonSleepObserver tracker;
 tracker.observe(&preflightSleep,"tracker_common");
 JarnsenTakSleepObserver policy;
 policy.observe(&preflightSleep,"tak_policy");
 motionActive=true;
 for(unsigned i=0;i<1000;++i) {
  assert(!waitEnterSleep(false,false));nowMs+=100;
 }
 assert(flushes==0 && bleStops==0 && lastDetail.find("tracker_common")!=std::string::npos);
 assert(doLightSleep(30000)==ESP_SLEEP_WAKEUP_UNDEFINED && lightEntered==0);
 motionActive=false; // The scheduler gets to run between retries.
 assert(waitEnterSleep(false,false));assert(flushes==1 && bleStops==1);
 assert(doLightSleep(30000)==ESP_SLEEP_WAKEUP_TIMER && lightEntered==1);
 assert(!waitEnterSleep(false,true)); // TAK keeps receiving during routine operation.
 assert(lastDetail.find("tak_policy")!=std::string::npos);
 motionActive=true;
 radioBusy=true;
 assert(!waitEnterSleep(false,true,true)); // Critical mode still protects an on-air TX.
 assert(lastDetail.find("radio")!=std::string::npos);
 doDeepSleep(1000,false,true);assert(!deepEntered);
 radioBusy=false;
 doDeepSleep(1000,false,true);assert(deepEntered);
 assert(!isCriticalSleepRequested()); // Scope must not leak into the next ordinary request.
 assert(!waitEnterSleep(false,false));
 takActive=false;parkSleepReadyForPreflight=true;
 assert(doPreflightSleep(true,false)); // TAK_TRACKER's completed park transaction may sleep.
 radioBusy=true;assert(!doPreflightSleep(true,false));
 radioBusy=false;parkSleepReadyForPreflight=false;
 assert(!doPreflightSleep(true,false)); // Movement still prevents unrelated deep requests.
 takActive=true;
 serviceActive=true;motionActive=false;
 assert(!doPreflightSleep(false,false));
 assert(lastDetail.find("code=1")!=std::string::npos);
 serviceActive=false;motionCandidatePending=true;
 assert(!doPreflightSleep(false,false));
 assert(lastDetail.find("code=3")!=std::string::npos);
 motionCandidatePending=false;finalPositionWaitStartedMs=1;
 assert(!doPreflightSleep(false,false));
 assert(lastDetail.find("code=4")!=std::string::npos);
 finalPositionWaitStartedMs=0;parkHeartbeatFixPending=true;
 assert(!doPreflightSleep(false,false));
 assert(lastDetail.find("code=5")!=std::string::npos);
 nowMs=UINT32_MAX-10;assert(!waitEnterSleep(false,false));
 nowMs=30;parkHeartbeatFixPending=false;assert(waitEnterSleep(false,false));
 deepEntered=false;radioBusy=true;nowMs=UINT32_MAX-500;
 lowBattSDSEnter();assert(!deepEntered);
 radioBusy=false;nowMs=498;lowBattSdsIdle();assert(!deepEntered);
 nowMs=499;lowBattSdsIdle();assert(deepEntered);
 deepEntered=false;nowMs+=1000;sdsEnter();assert(!deepEntered);
 nowMs+=1000;sdsIdle();assert(!deepEntered); // Routine TAK deep sleep stays vetoed.
 assert(waitEnterSleep(true,true)); // Existing explicit shutdown bypass stays available.
}
"""
        self.compile_run(harness)

    def test_power_status_updates_without_voltage_change(self):
        self.compile_run(r"""
#include <cassert>
#include <cstdint>
#include <cstring>
#include "PowerStatus.h"
uint32_t millis(){return 0;}
using namespace meshtastic;
int main() {
 PowerStatus status;
 PowerStatus unknown(OptUnknown,OptUnknown,OptUnknown,0,0);
 status.updateStatus(&unknown);assert(status.getHasUSBState()==OptUnknown);
 PowerStatus battery(OptTrue,OptFalse,OptFalse,3906,71,"adc");
 status.updateStatus(&battery);assert(status.getHasBattery() && !status.getHasUSB());
 assert(status.getBatteryChargePercent()==71);
 PowerStatus charging(OptTrue,OptTrue,OptTrue,3906,71,"adc");
 status.updateStatus(&charging);assert(status.getHasUSB() && status.getIsCharging());
 PowerStatus changed(OptTrue,OptTrue,OptFalse,3906,72,"ina");
 status.updateStatus(&changed);assert(!status.getIsCharging());
 assert(status.getBatteryChargePercent()==72);
 assert(!strcmp(status.getBatteryVoltageSource(),"ina"));
 status.updateStatus(&battery);assert(!status.getHasUSB());
}
""")

    def test_receive_notifications_do_not_depend_on_led(self):
        radio = source("src/mesh/RadioLibInterface.cpp")
        receive = radio.split('printPacket("Lora RX", mp);', 1)[1].split(
            "deliverToReceiver(mp);", 1
        )[0]
        observer = definition(
            source("src/jarnsen/core/runtime/JarnsenTakRepeaterPolicy.cpp"),
            "class TakRepeaterRxObserver",
        )
        for led in (False, True):
            with self.subTest(led=led):
                self.compile_run(
                    ("#define LED_LORA 1\n" if led else "")
                    + r"""
#include <atomic>
#include <cassert>
#include "Observer.h"
uint32_t millis(){return 12345;}
std::atomic<uint32_t> rxPackets{0},lastRxMs{0};
bool takRepeaterRoleActive(){return true;}
"""
                    + observer
                    + r""";
int main() {
 Observable<uint32_t> loraRxPacketObservable;
 TakRepeaterRxObserver observer;observer.observe(&loraRxPacketObservable);
 struct Packet {uint32_t from=123;} packet,*mp=&packet;
 struct AirTime {void logAirtime(int,int){}} air,*airTime=&air;
 constexpr int RX_LOG=0,rxMsec=12;
"""
                    + receive
                    + r"""
 assert(rxPackets.load()==1 && lastRxMs.load()==12345);
}
"""
                )


if __name__ == "__main__":
    unittest.main()
