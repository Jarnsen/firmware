#!/usr/bin/env python3
"""Host regression tests for the local-only V3 captive experiment."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "src/mesh/http/JarnsenServiceWeb.cpp").read_text(encoding="utf-8")


class CaptiveTest(unittest.TestCase):
    def test_probe_responses_and_reassociation(self):
        compiler = shutil.which("g++") or shutil.which("clang++")
        if not compiler:
            self.skipTest(
                "Host C++ compiler unavailable; firmware compilation remains required"
            )
        response = SOURCE.split("void sendCaptiveComplete(", 1)[1].split(
            "void sendCaptiveApi(", 1
        )[0]
        station = SOURCE.split(
            "const uint8_t stations = static_cast<uint8_t>(WiFi.softAPgetStationNum());",
            1,
        )[1].split("if (stations > 0U && captiveTraceJoinMs != 0U)", 1)[0]
        harness = r"""
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
struct WiFiClient {
    int status = 0;
    std::string body;
    void print(const char *s) { body += s; }
};
void sendStatus(WiFiClient &c, int status, const char *, const char *) { c.status = status; }
void logEvent(const char *, const char *) {}
bool pathMatches(const char *a, const char *b) { return std::strcmp(a, b) == 0; }
bool portalAuthorized = true;
uint32_t portalAuthorizedAtMs = 123U, postAuthDhcpSwitchRequestedMs = 456U;
bool captiveDnsActive = false;
uint8_t lastObservedStationCount = 1U, captiveTraceProbe = 0U, captiveTraceForeign = 0U;
uint8_t captiveTraceWebui = 0U, captiveTraceCheckpoint = 0U;
uint32_t captiveTraceJoinMs = 0U;
uint32_t millis() { return 5000U; }
"""
        harness += "\nvoid sendCaptiveComplete(" + response
        harness += "\nvoid observe(uint8_t stations) {\n" + station + "\n}\n"
        harness += r"""
int main() {
    const char *paths[] = {"/hotspot-detect.html", "/library/test/success.html",
                           "/generate_204", "/gen_204", "/connecttest.txt"};
    for (const char *path : paths) {
        for (bool head : {false, true}) {
            WiFiClient client;
            sendCaptiveComplete(client, path, head);
            if (SERVICE_V3_AUTO_PINLESS) {
                assert(client.status == 503);
                assert(client.body.find("Success") == std::string::npos);
            } else {
                const bool android = pathMatches(path, "/generate_204") || pathMatches(path, "/gen_204");
                assert(client.status == (android ? 204 : 200));
                if (!head && pathMatches(path, "/hotspot-detect.html"))
                    assert(client.body.find("Success") != std::string::npos);
            }
            if (head) assert(client.body.empty());
        }
    }
    for (int i = 0; i < 3; ++i) {
        observe(0);
        observe(1);
        assert(portalAuthorized);
        assert(portalAuthorizedAtMs == 123U);
        assert(postAuthDhcpSwitchRequestedMs == 456U);
        assert(!captiveDnsActive);
    }
    portalAuthorized = false;
    observe(0);
    observe(1);
    assert(!portalAuthorized);
}
"""
        with tempfile.TemporaryDirectory() as directory:
            cpp = Path(directory) / "captive.cpp"
            binary = Path(directory) / "captive"
            cpp.write_text(harness, encoding="utf-8")
            for v3 in ("true", "false"):
                subprocess.run(
                    [
                        compiler,
                        "-std=c++17",
                        "-Wall",
                        "-Wextra",
                        "-Werror",
                        "-DSERVICE_V3_AUTO_PINLESS=" + v3,
                        str(cpp),
                        "-o",
                        str(binary),
                    ],
                    check=True,
                )
                subprocess.run([str(binary)], check=True)

    def test_map_success_requires_loaded_tile(self):
        node = shutil.which("node")
        if not node:
            for version in ("node24", "node20"):
                candidate = (
                    Path.home()
                    / "actions-runner"
                    / "externals"
                    / version
                    / "bin"
                    / "node"
                )
                if candidate.is_file():
                    node = str(candidate)
                    break
        self.assertIsNotNone(node, "Node.js is required")
        tile = SOURCE.split("function onlineTile(", 1)[1].split("\n", 1)[0]
        javascript = r"""
const assert = require('node:assert/strict');
const tileCache = new Map(), events = [], internetStates = [];
let onlineMapState = 'checking', tileFailureStreak = 0, mapStyle = 'streets';
class Image {}
function trimTiles() {}
function requestMapDraw() {}
function reportWebDiagnostic(...args) { events.push(args); }
function setOnlineMapState(state) { onlineMapState = state; }
function setInternetState(state) { internetStates.push(state); }
function scheduleInternetProbe() {}
"""
        javascript += "\nfunction onlineTile(" + tile
        javascript += r"""
const source = {id:'osm', base:true, url:()=> 'https://example.invalid/tile'};
const first = onlineTile(source, 2, 0, 0);
assert.equal(events.length, 0);
first.img.onload();
assert.deepEqual(events, [['map_loaded', 'tile_loaded', 'osm']]);
assert.deepEqual(internetStates, []);
onlineTile(source, 2, 1, 0).img.onload();
assert.equal(events.length, 1);
onlineTile(source, 2, 2, 0).img.onerror();
assert.equal(events.length, 1);
assert.deepEqual(internetStates, []);
"""
        subprocess.run([node, "-"], input=javascript, text=True, check=True)

    def test_internet_probe_diagnostics(self):
        node = shutil.which("node")
        if not node:
            for version in ("node24", "node20"):
                candidate = (
                    Path.home()
                    / "actions-runner"
                    / "externals"
                    / version
                    / "bin"
                    / "node"
                )
                if candidate.is_file():
                    node = str(candidate)
                    break
        self.assertIsNotNone(node, "Node.js is required")
        probe = SOURCE.split("async function probeInternetTarget(id,url){", 1)[1].split(
            "function scheduleInternetProbe(", 1
        )[0]
        reporter = SOURCE.split("function reportWebDiagnostic(", 1)[1].split(
            "function reportClientEvent(", 1
        )[0]
        harness = r"""
const assert = require('node:assert/strict');
const events = [], states = [], timers = [], headers = [];
let internetProbePromise = null, internetState = 'checking', internetProbeRetryStep = 0;
let tileFailureStreak = 0, now = 0;
const performance = {now:()=>now}, tileCache = new Map();
function setTimeout(fn) { timers.push(fn); return timers.length; }
function clearTimeout() {}
function setInternetState(state) { internetState=state; states.push(state); }
function setOnlineMapState() {}
function setStatus() {}
function drawMap() {}
function scheduleInternetProbe() {}
function reportClientEvent(event) { events.push([event]); }
function reportWebDiagnostic(...args) { events.push(args); }
async function fetch() { throw Error('not configured'); }
"""
        harness += "\nasync function probeInternetTarget(id,url){" + probe
        harness += r"""
(async()=>{
 for(const scenario of ['ok','http','network','timeout','body']){
  events.length=0;states.length=0;timers.length=0;now=0;internetState='online';
  fetch=async (_url,options)=>{
   now=123;
   if(scenario==='network')throw new TypeError('private URL must not be logged');
   if(scenario==='timeout'){timers.at(-1)();throw new Error('aborted');}
   return {status:scenario==='http'?503:200,ok:scenario!=='http',arrayBuffer:async()=>{
    if(scenario==='body')throw new TypeError('body failed');
    return new ArrayBuffer(1);
   }};
  };
  const result=await probeInternetTarget('osm','https://example.invalid/?test=1');
  const event=events.find(e=>e[0]==='internet_probe');
  assert.equal(event[1],{ok:'ok',http:'http_error',network:'network_tls_cors',timeout:'timeout',body:'network_tls_cors'}[scenario]);
  assert.equal(event[3].http,['network','timeout'].includes(scenario)?0:scenario==='http'?503:200);
  assert.equal(event[3].ms,123);
  assert.equal(result,scenario==='ok');
  assert.equal(internetState,'online');
  assert.equal(states.length,0);
 }
 for(const [osm,cf] of [[false,false],[false,true],[true,false],[true,true]]){
  events.length=0;states.length=0;timers.length=0;internetState='online';let requests=0;
  fetch=async (url,options)=>{
   requests++;
   assert.equal(options.credentials,'omit');
   assert.equal(options.referrerPolicy,'no-referrer');
   assert.equal(options.cache,'no-store');
   const ok=url.includes('openstreetmap.org')?osm:cf;
   if(!ok)throw new TypeError('network');
   return {status:200,ok:true,arrayBuffer:async()=>new ArrayBuffer(1)};
  };
  const results=await Promise.all([probeInternet(),probeInternet()]);
  assert.deepEqual(results,[osm||cf,osm||cf]);
  assert.equal(requests,2);
  assert.equal(internetState,osm||cf?'online':'offline');
  const probes=events.filter(e=>e[0]==='internet_probe');
  assert.equal(probes.length,2);
  assert.deepEqual(probes.map(e=>e[2]).sort(),['cf','osm']);
 }
})().catch(error=>{console.error(error);process.exitCode=1});
"""
        subprocess.run([node, "-"], input=harness, text=True, check=True)
        harness = r"""
const assert=require('node:assert/strict');
let clientDiagWindow=0,clientDiagCount=0;
const clientDiagRecent=new Map(),info={token:'local-session'},sent=[];
function diagPlatform(){return 'android'}
function diagBrowser(){return 'firefox'}
function diagToken(value){return value}
function fetch(_url,options){sent.push(options.headers);return Promise.resolve()}
"""
        harness += "\nfunction reportWebDiagnostic(" + reporter
        harness += r"""
reportWebDiagnostic('internet_probe','network_tls_cors','osm',{ms:4500,http:0});
const detail=sent[0]['X-Jarnsen-Detail'];
assert(detail.length<=80);
assert(detail.includes('src=osm ms=4500 http=0'));
assert(detail.includes('code=network_tls_cors'));
for(let i=0;i<20;i++)reportWebDiagnostic('internet_probe','timeout','osm',{ms:4500,http:0});
assert.equal(sent.length,12);
"""
        subprocess.run([node, "-"], input=harness, text=True, check=True)

    def test_wifi_event_queue(self):
        compiler = shutil.which("g++") or shutil.which("clang++")
        if not compiler:
            self.skipTest("Host C++ compiler unavailable")
        events = SOURCE.split("struct ServiceWifiEvent {", 1)[1].split(
            "\n#endif\n\nconst char PAGE[]", 1
        )[0]
        harness = r"""
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>
using portMUX_TYPE = int;
#define portMUX_INITIALIZER_UNLOCKED 0
bool locked=false;
void portENTER_CRITICAL(int *) { assert(!locked); locked=true; }
void portEXIT_CRITICAL(int *) { assert(locked); locked=false; }
uint32_t millis() { return 12345U; }
std::vector<std::string> messages;
void logEvent(const char *, const char *detail) { assert(!locked); messages.emplace_back(detail); }
enum arduino_event_id_t {ARDUINO_EVENT_WIFI_AP_START, ARDUINO_EVENT_WIFI_AP_STOP,
 ARDUINO_EVENT_WIFI_AP_STACONNECTED, ARDUINO_EVENT_WIFI_AP_STADISCONNECTED,
 ARDUINO_EVENT_WIFI_AP_STAIPASSIGNED, IGNORED};
struct Joined { uint16_t aid=7; };
struct Left {
 uint16_t aid=7;
#if HAS_REASON
 int reason=8;
#endif
};
struct arduino_event_info_t { Joined wifi_ap_staconnected; Left wifi_ap_stadisconnected; };
"""
        harness += "\nstruct ServiceWifiEvent {" + events
        harness += r"""
int main() {
 arduino_event_info_t info;
 captureServiceWifiEvent(IGNORED,info);
 assert(serviceWifiCount==0);
 captureServiceWifiEvent(ARDUINO_EVENT_WIFI_AP_STADISCONNECTED,info);
 assert(messages.empty());
 drainServiceWifiEvents();
 assert(messages.size()==1);
 assert(messages[0].find("event=sta_leave at_ms=12345 age_ms=0 aid=7")!=std::string::npos);
 assert(messages[0].find(HAS_REASON?"reason=8":"reason=unavailable")!=std::string::npos);
 messages.clear();
 for(int i=0;i<12;i++)captureServiceWifiEvent(ARDUINO_EVENT_WIFI_AP_STACONNECTED,info);
 assert(serviceWifiCount==8);
 assert(serviceWifiDropped==4);
 drainServiceWifiEvents();
 assert(serviceWifiCount==0 && serviceWifiDropped==0);
 assert(messages.size()==9);
 assert(messages[0]=="queue_dropped=4");
 for(int i=0;i<3;i++){
  captureServiceWifiEvent(ARDUINO_EVENT_WIFI_AP_STOP,info);
  drainServiceWifiEvents();
  assert(serviceWifiCount==0);
 }
}
"""
        with tempfile.TemporaryDirectory() as directory:
            cpp = Path(directory) / "events.cpp"
            binary = Path(directory) / "events"
            cpp.write_text(harness, encoding="utf-8")
            for reason in ("0", "1"):
                subprocess.run(
                    [
                        compiler,
                        "-std=c++17",
                        "-Wall",
                        "-Wextra",
                        "-Werror",
                        "-DHAS_REASON=" + reason,
                        str(cpp),
                        "-o",
                        str(binary),
                    ],
                    check=True,
                )
                subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    unittest.main()
