#!/usr/bin/env python3
"""Compile the shared boot diagnostics on retained and portable platforms."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class UnifiedBootDiagnosticsTest(unittest.TestCase):
    def test_boot_stages_and_panic_retention(self):
        compiler = shutil.which("g++") or shutil.which("clang++")
        if not compiler:
            self.skipTest("Host C++ compiler unavailable; board builds remain required")
        stubs = {
            "Arduino.h": "#pragma once\n#include <cstdint>\nclass Print {};\nextern uint32_t nowMs;\ninline uint32_t millis(){return nowMs;}\n",
            "configuration.h": "#pragma once\n",
            "esp_attr.h": "#pragma once\n#define RTC_NOINIT_ATTR\n",
            "esp_heap_caps.h": "#pragma once\n#define MALLOC_CAP_8BIT 1\ninline unsigned heap_caps_get_free_size(int){return 40000;}\ninline unsigned heap_caps_get_minimum_free_size(int){return 30000;}\ninline unsigned heap_caps_get_largest_free_block(int){return 20000;}\n",
            "esp_system.h": "#pragma once\nenum esp_reset_reason_t {ESP_RST_POWERON=1,ESP_RST_EXT,ESP_RST_SW,ESP_RST_PANIC,ESP_RST_INT_WDT,ESP_RST_TASK_WDT,ESP_RST_WDT,ESP_RST_DEEPSLEEP,ESP_RST_BROWNOUT};\nextern esp_reset_reason_t resetReasonStub;\ninline esp_reset_reason_t esp_reset_reason(){return resetReasonStub;}\ninline int esp_register_shutdown_handler(void(*)()){return 0;}\n",
            "freertos/FreeRTOS.h": "#pragma once\nusing UBaseType_t=unsigned;\n",
            "freertos/task.h": '#pragma once\ninline unsigned uxTaskGetStackHighWaterMark(void*){return 1000;}\ninline const char *pcTaskGetName(void*){return "main";}\n',
        }
        harness = r"""
#include <cassert>
#include <cstdarg>
#include <cstdio>
#include <string>
#include <vector>
#include "Arduino.h"
#ifdef ARCH_ESP32
#include "esp_system.h"
esp_reset_reason_t resetReasonStub=ESP_RST_POWERON;
#endif
uint32_t nowMs=10;
std::vector<std::string> logs;
namespace jarnsen {
void diagnosticLog(const char *event,const char *fmt,...) {
 char detail[512];va_list args;va_start(args,fmt);
 vsnprintf(detail,sizeof(detail),fmt,args);va_end(args);
 logs.emplace_back(std::string(event)+" "+detail);
}
}
#include "jarnsen/core/service/JarnsenCrashTrace.cpp"
bool contains(const char *text) {
 for(const auto &line:logs)if(line.find(text)!=std::string::npos)return true;
 return false;
}
int main() {
 using namespace jarnsen;
 crashTraceBootStage(1000,"setup:begin");
 nowMs=20;crashTraceBootStage(1001,"fs_init:begin");
 assert(logs.empty()); // No persistent I/O before filesystem/logger readiness.
 crashTraceBootLoggingReady();
 assert(contains("BOOT_BEGIN") && contains("at_ms=10 step=1000 name=setup:begin"));
 const auto size=logs.size();crashTraceBootLoggingReady();crashTraceReport(42);
 assert(logs.size()==size);
 nowMs=30;crashTraceBootStage(1002,"modules:begin");
 assert(contains("at_ms=30 step=1002 name=modules:begin"));
#ifdef ARCH_ESP32
 assert(contains("retained=1"));
 assert(std::string(crashTraceResetReasonName(11))=="USB");
 assert(!resetLooksLikeCrash(11) && resetLooksLikeCrash(6));
 // Deep sleep does not execute the software shutdown handler.
 initialized=false;reported=false;previousTraceValid=false;
 bootLoggingReady=false;earlyCount=0;earlyDropped=0;
 resetReasonStub=ESP_RST_DEEPSLEEP;nowMs=1;logs.clear();
 crashTraceBootStage(1000,"setup:begin");crashTraceBootLoggingReady();
 assert(contains("reset=DEEPSLEEP") && !contains("UNCLEAN_SHUTDOWN"));
 assert(!contains("LAST_LINES_BEFORE_RESET"));
 nowMs=30;crashTraceBootStage(1002,"modules:begin");
 // Simulate a warm panic: RTC memory survives; ordinary globals restart.
 initialized=false;reported=false;previousTraceValid=false;
 bootLoggingReady=false;earlyCount=0;earlyDropped=0;
 resetReasonStub=ESP_RST_PANIC;nowMs=1;logs.clear();
 crashTraceBootStage(1000,"setup:begin");
 crashTraceBootLoggingReady();
 assert(contains("reset=PANIC") && contains("uptime_source=last_checkpoint"));
 assert(contains("LAST_LINES_BEFORE_RESET") && contains("name=modules:begin"));
#else
 assert(contains("retained=0") && contains("previous_uptime_known=0"));
#endif
}
"""
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            for name, content in stubs.items():
                target = temp / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content)
            cpp = temp / "boot.cpp"
            cpp.write_text(harness)
            for arch in (
                "ARCH_ESP32",
                "ARCH_NRF52",
                "ARCH_RP2040",
                "ARCH_STM32WL",
                "ARCH_PORTDUINO",
            ):
                with self.subTest(arch=arch):
                    binary = temp / arch
                    subprocess.run(
                        [
                            compiler,
                            "-std=c++17",
                            "-Wall",
                            "-Wextra",
                            "-Werror",
                            "-D" + arch,
                            "-I" + str(temp),
                            "-I" + str(ROOT / "src"),
                            str(cpp),
                            "-o",
                            str(binary),
                        ],
                        check=True,
                    )
                    subprocess.run([str(binary)], check=True)

    def test_common_startup_and_radio_hooks(self):
        main = (ROOT / "src/main.cpp").read_text().split("void setup()", 1)[1]
        self.assertLess(
            main.index("fsInit();"), main.index("crashTraceBootLoggingReady();")
        )
        for stage in (
            "node_db:begin",
            "modules:begin",
            "lora_init:begin",
            "setup:done",
            "loop:first",
        ):
            self.assertIn(stage, main)
        router = (ROOT / "src/mesh/Router.cpp").read_text()
        self.assertIn("src == RX_SRC_RADIO && !p->via_mqtt", router)
        self.assertLess(
            router.index("diagnosticNotePacket("),
            router.index("MeshModule::callModules(*p, src)"),
        )


if __name__ == "__main__":
    unittest.main()
