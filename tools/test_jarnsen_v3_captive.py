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
const tileCache = new Map(), events = [];
let onlineMapState = 'checking', tileFailureStreak = 0, mapStyle = 'streets';
class Image {}
function trimTiles() {}
function requestMapDraw() {}
function reportWebDiagnostic(...args) { events.push(args); }
function setOnlineMapState(state) { onlineMapState = state; }
function setInternetState() {}
function scheduleInternetProbe() {}
"""
        javascript += "\nfunction onlineTile(" + tile
        javascript += r"""
const source = {id:'osm', base:true, url:()=> 'https://example.invalid/tile'};
const first = onlineTile(source, 2, 0, 0);
assert.equal(events.length, 0);
first.img.onload();
assert.deepEqual(events, [['map_loaded', 'tile_loaded', 'osm']]);
onlineTile(source, 2, 1, 0).img.onload();
assert.equal(events.length, 1);
onlineTile(source, 2, 2, 0).img.onerror();
assert.equal(events.length, 1);
"""
        subprocess.run([node, "-"], input=javascript, text=True, check=True)


if __name__ == "__main__":
    unittest.main()
