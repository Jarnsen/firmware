"""Make the Heltec V3 WLAN portal a real live device view.

Runs after the existing V3 portal/Internet/map patches.  It also repairs the
map patch's accidental duplicated `function header(text,key)` token, which made
the whole inline JavaScript fail to parse and left the portal looking frozen.

The firmware exposes a compact /live.json endpoint backed directly by the V3
power, mesh, diagnostic and position state.  The browser polls that endpoint
every two seconds through the explicit local V3 address (192.168.4.1), so
GitHub/map Internet traffic can continue to use the phone's mobile route.
"""
from pathlib import Path

WEB = Path("src/mesh/http/JarnsenServiceWeb.cpp")
PORTAL = Path("src/mesh/http/JarnsenV3ServicePortalPage.h")


def once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    if source.count(old) != 1:
        raise SystemExit(f"{label} anchor not found exactly once")
    return source.replace(old, new, 1)


def replace_between(source: str, start: str, end: str, replacement: str, label: str) -> str:
    first = source.find(start)
    if first < 0:
        raise SystemExit(f"{label} start anchor not found")
    second = source.find(end, first + len(start))
    if second < 0:
        raise SystemExit(f"{label} end anchor not found")
    return source[:first] + replacement + source[second:]


web = WEB.read_text(encoding="utf-8")
portal = PORTAL.read_text(encoding="utf-8")

# ---------------------------------------------------------------------------
# Repair a JavaScript parse error introduced by the touch-map replacement.
# replace_between() keeps the end anchor, so appending the same function name
# to the replacement produced `function header(...)function header(...)`.
# A syntax error here prevents *all* boot/status/map code from running.
# ---------------------------------------------------------------------------
broken_header = "function header(text,key)function header(text,key)"
if broken_header in portal:
    portal = portal.replace(broken_header, "function header(text,key)", 1)

# ---------------------------------------------------------------------------
# Firmware-side live snapshot.
# ---------------------------------------------------------------------------
include_anchor = '#include "infrastructure/HeltecV3DiagnosticLog.h"\n'
include_new = (
    include_anchor
    + '#include "infrastructure/HeltecV3MeshMonitor.h"\n'
    + '#include "infrastructure/HeltecV3PowerMonitor.h"\n'
    + '#include "infrastructure/HeltecV3Runtime.h"\n'
)
web = once(web, include_anchor, include_new, "V3 live endpoint includes")

send_log_anchor = "void sendLog(WiFiClient &client)\n{\n"
live_helpers = r'''void noteWebRequest(const char *method, const char *path)
{
#if defined(_VARIANT_HELTEC_V3)
    static uint32_t liveRequests = 0;
    if (!method || !path)
        return;
    if (strcmp(path, "/live.json") == 0) {
        liveRequests++;
        // First requests prove that the phone is really reading the V3.  After
        // that, log only every ~30 s at the normal 2 s poll rate so the
        // diagnostic file is not flooded by the live view itself.
        if (liveRequests <= 3U || (liveRequests % 15U) == 0U)
            heltecV3DiagLog("WEB_REQ", "%s %s count=%u", method, path, (unsigned)liveRequests);
    } else if (strcmp(path, "/status") == 0 || strcmp(path, "/track.geojson") == 0 || strcmp(path, "/log") == 0) {
        heltecV3DiagLog("WEB_REQ", "%s %s", method, path);
    }
#else
    (void)method;
    (void)path;
#endif
}

void sendLiveJson(WiFiClient &client)
{
#if defined(_VARIANT_HELTEC_V3)
    const HeltecV3PowerStats power = heltecV3PowerMonitorStats();
    const HeltecV3MeshSummary mesh = heltecV3MeshMonitorSummary();
    const HeltecV3DiagStats diag = heltecV3DiagStats();
    HeltecV3PositionUiState position = {};
    const bool havePositionState = heltecV3GetPositionUiState(position);
    const bool savedPosition = havePositionState && position.haveSavedPosition;
    const bool phonePosition = havePositionState && position.havePhonePosition;

    sendStatus(client, 200, "OK", "application/json; charset=utf-8",
               "Cache-Control: no-store\r\nAccess-Control-Allow-Origin: *\r\n");
    client.print("{");
    client.printf("\"uptime_s\":%u,\"state\":\"%s\",\"ble_state\":\"%s\",",
                  (unsigned)(millis() / 1000UL), heltecV3RuntimeStateText(), heltecV3RuntimeBleStateText());
    client.printf("\"battery_valid\":%s,\"battery_pct\":%u,\"voltage_mv\":%u,\"usb\":%s,\"charging\":%s,",
                  power.batteryValid ? "true" : "false", (unsigned)power.batteryPercent, (unsigned)power.voltageMv,
                  power.usbPowered ? "true" : "false", power.charging ? "true" : "false");
    client.printf("\"estimate_ready\":%s,\"remaining_s\":%u,\"measured_s\":%u,\"listen_s\":%u,\"service_s\":%u,",
                  power.estimateReady ? "true" : "false", (unsigned)power.remainingSecs, (unsigned)power.measuredSecs,
                  (unsigned)power.listenSecs, (unsigned)power.serviceSecs);
    client.printf("\"ble_s\":%u,\"display_s\":%u,\"position_tx\":%u,\"track_count\":%u,",
                  (unsigned)power.bleSecs, (unsigned)power.displaySecs, (unsigned)power.positionTxCount,
                  (unsigned)jarnsenPositionTrackCount());
    client.printf("\"known_nodes\":%u,\"active_15m\":%u,\"active_1h\":%u,\"active_24h\":%u,\"direct_15m\":%u,\"rx_1h\":%u,",
                  (unsigned)mesh.knownNodes, (unsigned)mesh.active15m, (unsigned)mesh.active1h, (unsigned)mesh.active24h,
                  (unsigned)mesh.direct15m, (unsigned)mesh.rx1h);
    client.printf("\"boot_count\":%u,\"crash_count\":%u,\"service_open_count\":%u,\"ble_connections\":%u,\"ble_recovery\":%u,",
                  (unsigned)diag.bootCount, (unsigned)diag.crashResetCount, (unsigned)diag.serviceOpenCount,
                  (unsigned)diag.bleConnectionCount, (unsigned)diag.bleRecoveryCount);
    client.printf("\"position_valid\":%s,\"position_lat_i\":%ld,\"position_lon_i\":%ld,",
                  savedPosition ? "true" : "false", (long)position.savedLatitudeI, (long)position.savedLongitudeI);
    client.printf("\"phone_position_valid\":%s,\"phone_lat_i\":%ld,\"phone_lon_i\":%ld,\"phone_age_s\":%u,\"phone_fresh\":%s,",
                  phonePosition ? "true" : "false", (long)position.phoneLatitudeI, (long)position.phoneLongitudeI,
                  (unsigned)position.phoneAgeSecs, position.phoneFresh ? "true" : "false");
    client.printf("\"log_bytes\":%u}", (unsigned)heltecV3DiagLogSize());
#else
    sendStatus(client, 404, "Not Found", "application/json; charset=utf-8");
    client.print("{\"ok\":false}");
#endif
}

void sendLog(WiFiClient &client)
{
'''
web = once(web, send_log_anchor, live_helpers, "V3 live JSON helper")

request_anchor = '''    lastActivityMs = millis() ? millis() : 1;
    if (strcmp(method, "GET") == 0 && strcmp(path, "/status") == 0)
'''
request_new = '''    lastActivityMs = millis() ? millis() : 1;
    noteWebRequest(method, path);
    if (strcmp(method, "GET") == 0 && strcmp(path, "/status") == 0)
'''
web = once(web, request_anchor, request_new, "V3 web request diagnostics")

route_anchor = '''    if (strcmp(method, "GET") == 0 && strcmp(path, "/status") == 0)
        sendJsonStatus(client);
    else if (strcmp(method, "GET") == 0 && strcmp(path, "/log") == 0)
'''
route_new = '''    if (strcmp(method, "GET") == 0 && strcmp(path, "/status") == 0)
        sendJsonStatus(client);
    else if (strcmp(method, "GET") == 0 && strcmp(path, "/live.json") == 0)
        sendLiveJson(client);
    else if (strcmp(method, "GET") == 0 && strcmp(path, "/log") == 0)
'''
web = once(web, route_anchor, route_new, "V3 live JSON route")

# Add CORS to the static status snapshot too.  In normal use this is same-origin,
# but it makes the explicit 192.168.4.1 fetch robust if a captive mini-browser
# initially opened the document under a probe host.
status_cors_old = 'sendStatus(client, 200, "OK", "application/json; charset=utf-8", "Cache-Control: no-store\\r\\n");'
status_cors_new = 'sendStatus(client, 200, "OK", "application/json; charset=utf-8", "Cache-Control: no-store\\r\\nAccess-Control-Allow-Origin: *\\r\\n");'
if status_cors_old in web:
    web = web.replace(status_cors_old, status_cors_new, 1)

# ---------------------------------------------------------------------------
# Browser-side live polling.  Keep GitHub/tile requests untouched: only local
# device APIs are forced to the V3's on-link address.
# ---------------------------------------------------------------------------
overview_old = '<div class="metric">Akku<b id="mBat">–</b></div></div><div id="overviewStatus" class="status">V3 lokal über WLAN · Internet/Online-Karten über Mobilfunk.</div>'
overview_new = '<div class="metric">Akku<b id="mBat">–</b></div><div class="metric">Verbindung<b id="mLive">Verbindet …</b></div></div><div id="overviewStatus" class="status">Live-Verbindung zum V3 wird aufgebaut …</div>'
portal = once(portal, overview_old, overview_new, "V3 live connection metric")

mesh_old = '<div class="metric">Resets / Panic<b id="pReset">–</b></div></div><div class="status">Werte werden beim Laden des Diagnoselogs aktualisiert.</div></section>'
mesh_new = '<div class="metric">Resets / Panic<b id="pReset">–</b></div><div class="metric">Nodes bekannt<b id="pKnown">–</b></div><div class="metric">Aktiv 15 min<b id="pActive15">–</b></div><div class="metric">RX 1 h<b id="pRx1h">–</b></div></div><div id="liveDetails" class="status">Live-Werte werden direkt vom V3 gelesen …</div></section>'
portal = once(portal, mesh_old, mesh_new, "V3 live mesh metrics")

# Use direct local links as well as direct local fetches.
portal = portal.replace('href="/track.geojson"', 'href="http://192.168.4.1/track.geojson"')
portal = portal.replace('href="/log"', 'href="http://192.168.4.1/log"')

live_boot = r'''const LOCAL_ORIGIN='http://192.168.4.1';let liveTimer=null,liveBusy=false,lastLiveOkMs=0,lastLiveTrackCount=-1,lastTrackReloadMs=0;
function localFetch(path,opts={}){return fetch(LOCAL_ORIGIN+path,{cache:'no-store',...opts})}
function livePositionText(j){if(!j.position_valid)return'keine gespeicherte Position';const lat=Number(j.position_lat_i)/1e7,lon=Number(j.position_lon_i)/1e7;try{return mgrs10(lat,lon)}catch(_){return lat.toFixed(5)+', '+lon.toFixed(5)}}
function paintLive(j){lastLiveOkMs=Date.now();$('mLive').textContent='LIVE';$('barState').textContent='V3 verbunden · Live 0 s';status('overviewStatus','V3 verbunden · Live-Daten direkt über WLAN · Internet über Mobilfunk.','ok');$('mBat').textContent=j.battery_valid?j.battery_pct+'%':'–';$('pVolt').textContent=j.battery_valid?j.voltage_mv+' mV':'–';$('pPct').textContent=j.battery_valid?j.battery_pct+'%':'–';$('pEst').textContent=j.estimate_ready?fmtSec(j.remaining_s):(j.usb||j.charging?'USB/Laden':'lernt …');$('pListen').textContent=fmtSec(j.listen_s);$('pService').textContent=fmtSec(j.service_s);$('pBle').textContent=fmtSec(j.ble_s);$('pDisp').textContent=fmtSec(j.display_s);$('pTx').textContent=String(j.position_tx??'–');$('pReset').textContent=(j.boot_count??'–')+' / '+(j.crash_count??'–');$('pKnown').textContent=String(j.known_nodes??'–');$('pActive15').textContent=String(j.active_15m??'–');$('pRx1h').textContent=String(j.rx_1h??'–');$('liveDetails').textContent='Status '+(j.state||'–')+' · BLE '+(j.ble_state||'–')+' · '+livePositionText(j)+' · Log '+Math.round((j.log_bytes||0)/1024)+' KB';const tc=Number(j.track_count||0);$('mPoints').textContent=tc;if(lastLiveTrackCount>=0&&tc!==lastLiveTrackCount&&Date.now()-lastTrackReloadMs>3000){lastTrackReloadMs=Date.now();loadTrack()}lastLiveTrackCount=tc}
async function pollLive(){if(liveBusy)return;liveBusy=true;try{const r=await localFetch('/live.json');if(!r.ok)throw Error('HTTP '+r.status);paintLive(await r.json())}catch(e){const age=lastLiveOkMs?Math.max(0,Math.floor((Date.now()-lastLiveOkMs)/1000)):null;$('mLive').textContent='OFFLINE';$('barState').textContent=age===null?'V3 nicht erreichbar':'V3 Verbindung unterbrochen · vor '+age+' s';status('overviewStatus','Verbindung zum V3 unterbrochen: '+e.message,'err')}finally{liveBusy=false}}
function startLivePolling(){if(liveTimer)clearInterval(liveTimer);pollLive();liveTimer=setInterval(pollLive,2000)}
async function boot(){
try{const r=await localFetch('/status');if(!r.ok)throw Error('HTTP '+r.status);info=await r.json();$('device').textContent=(info.long_name||info.title)+' · '+info.device+' · '+info.node_id;$('barName').textContent=info.long_name||'Jarnsen V3';$('mNode').textContent=info.short_name||info.node_id;$('mRole').textContent=info.role||'–';$('mSsid').textContent=info.ssid;$('mPoints').textContent=info.track_count;$('mFw').textContent=info.build_sha||'–';$('fwInstalled').textContent=info.build_sha||'–'}catch(e){status('overviewStatus','Status nicht lesbar: '+e.message,'err')}
setMapMode(mapMode);$('mgrsGrid').checked=mgrsOn;startLivePolling();await Promise.allSettled([loadTrack(),checkFirmware()])}
'''
portal = replace_between(portal, "async function boot(){", "function canvas(){", live_boot, "V3 live portal boot/poller")

local_replacements = (
    ("fetch('/track.geojson'", "localFetch('/track.geojson'"),
    ("fetch('/log'", "localFetch('/log'"),
    ("fetch('/track/clear'", "localFetch('/track/clear'"),
    ("fetch('/log/clear'", "localFetch('/log/clear'"),
    ("fetch('/shutdown'", "localFetch('/shutdown'"),
    ("fetch('/phone-position?'", "localFetch('/phone-position?'"),
    ("fetch('/update'", "localFetch('/update'"),
)
for old, new in local_replacements:
    portal = portal.replace(old, new)

# Keep a visible age even if a browser stalls timers briefly.  pollLive() resets
# the text to zero on every successful snapshot.
age_hook = "window.addEventListener('resize',renderMap);"
age_hook_new = age_hook + "setInterval(()=>{if(lastLiveOkMs&&!liveBusy){const a=Math.max(0,Math.floor((Date.now()-lastLiveOkMs)/1000));if(a>2)$('barState').textContent='V3 verbunden · Live vor '+a+' s'}},1000);"
portal = once(portal, age_hook, age_hook_new, "V3 live age indicator")

# ---------------------------------------------------------------------------
# Build-time guards: fail the firmware build instead of shipping another frozen
# portal if the inline JS is accidentally malformed in this known way.
# ---------------------------------------------------------------------------
if broken_header in portal:
    raise SystemExit("V3 portal still contains duplicated function header token")

for marker in (
    '#include "infrastructure/HeltecV3PowerMonitor.h"',
    '#include "infrastructure/HeltecV3MeshMonitor.h"',
    "sendLiveJson",
    'strcmp(path, "/live.json")',
    'heltecV3DiagLog("WEB_REQ"',
):
    if marker not in web:
        raise SystemExit(f"missing V3 live web marker: {marker}")

for marker in (
    "LOCAL_ORIGIN='http://192.168.4.1'",
    "pollLive",
    "setInterval(pollLive,2000)",
    "mLive",
    "pKnown",
    "pActive15",
    "pRx1h",
    "localFetch('/status')",
    "localFetch('/track.geojson'",
):
    if marker not in portal:
        raise SystemExit(f"missing V3 live portal marker: {marker}")

WEB.write_text(web, encoding="utf-8")
PORTAL.write_text(portal, encoding="utf-8")
print("Heltec V3: repaired portal JS and enabled 2s live device snapshots at /live.json")
