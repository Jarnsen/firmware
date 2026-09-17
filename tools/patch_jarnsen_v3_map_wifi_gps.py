"""Add touch map controls, map-point MGRS lookup and Wi-Fi phone GPS fallback to the V3 portal."""
from pathlib import Path

WEB = Path("src/mesh/http/JarnsenServiceWeb.cpp")
PORTAL = Path("src/mesh/http/JarnsenV3ServicePortalPage.h")
MANAGER = Path("src/infrastructure/HeltecV3PhonePositionManager.cpp")
POSITION_H = Path("src/infrastructure/HeltecV3PositionPage.h")


def once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    if source.count(old) != 1:
        raise SystemExit(f"{label} anchor not found exactly once")
    return source.replace(old, new, 1)


def replace_between(source: str, start: str, end: str, replacement: str, label: str) -> str:
    if replacement in source:
        return source
    first = source.find(start)
    if first < 0:
        raise SystemExit(f"{label} start anchor not found")
    second = source.find(end, first + len(start))
    if second < 0:
        raise SystemExit(f"{label} end anchor not found")
    return source[:first] + replacement + source[second:]


web = WEB.read_text(encoding="utf-8")
portal = PORTAL.read_text(encoding="utf-8")
manager = MANAGER.read_text(encoding="utf-8")
position_h = POSITION_H.read_text(encoding="utf-8")

# ---------------------------------------------------------------------------
# Firmware: accept phone positions from the local WLAN service without going
# through BLE.  The existing V3 position manager remains the single policy
# owner, so smart distance/time filtering and fixed-position handling are not
# duplicated.  WLAN fixes are ignored while BLE is actively connected.
# ---------------------------------------------------------------------------
manager_anchor = '''    bool sendPositionToPhone(const meshtastic_Position &position, bool fresh)\n    {\n'''
manager_method = '''    bool submitWifiPosition(const meshtastic_Position &position)\n    {\n        if (!heltecV3RuntimeServiceActive() || bleConnected() || !phoneFixHasCoordinates(position))\n            return false;\n\n        if (!worker)\n            worker = new V3PhonePositionWorker(this);\n\n        portENTER_CRITICAL(&managerMux);\n        pendingPhoneFix = position;\n        phoneFixPending = true;\n        portEXIT_CRITICAL(&managerMux);\n        heltecV3DiagLog("PHONE_POS_WIFI", "queued lat=%d lon=%d acc=%umm", position.latitude_i, position.longitude_i,\n                        (unsigned)position.gps_accuracy);\n        return true;\n    }\n\n    bool sendPositionToPhone(const meshtastic_Position &position, bool fresh)\n    {\n'''
manager = once(manager, manager_anchor, manager_method, "V3 WiFi phone-position manager method")

manager_global_anchor = '''static V3PhonePositionManager v3PhonePositionManager;\n\n} // namespace\n\nvoid heltecV3PhoneMotionObserve'''
manager_global_new = '''static V3PhonePositionManager v3PhonePositionManager;\n\n} // namespace\n\nbool heltecV3SubmitWifiPhonePosition(int32_t latitudeI, int32_t longitudeI, uint32_t accuracyMm, uint32_t epoch)\n{\n    meshtastic_Position position = meshtastic_Position_init_default;\n    position.latitude_i = latitudeI;\n    position.longitude_i = longitudeI;\n    position.has_latitude_i = true;\n    position.has_longitude_i = true;\n    position.gps_accuracy = accuracyMm;\n    position.time = epoch;\n    position.timestamp = epoch;\n    position.location_source = meshtastic_Position_LocSource_LOC_EXTERNAL;\n    return v3PhonePositionManager.submitWifiPosition(position);\n}\n\nvoid heltecV3PhoneMotionObserve'''
manager = once(manager, manager_global_anchor, manager_global_new, "V3 WiFi phone-position global wrapper")

header_anchor = '''// Position policy data consumed by the native Meshtastic UI page.\nbool heltecV3GetPositionUiState'''
header_new = '''// Local service-WLAN fallback for phone GPS when BLE is not connected.\n// The normal V3 position manager remains responsible for validation and mesh TX.\nbool heltecV3SubmitWifiPhonePosition(int32_t latitudeI, int32_t longitudeI, uint32_t accuracyMm, uint32_t epoch);\n\n// Position policy data consumed by the native Meshtastic UI page.\nbool heltecV3GetPositionUiState'''
position_h = once(position_h, header_anchor, header_new, "V3 WiFi phone-position declaration")

# ---------------------------------------------------------------------------
# HTTP service endpoint.  Numeric query parameters keep the tiny hand-written
# HTTP server simple and avoid a second JSON parser in firmware.
# ---------------------------------------------------------------------------
web_include_anchor = '#include "infrastructure/HeltecV3BuildInfo.h"\n'
web_include_new = web_include_anchor + '#include "infrastructure/HeltecV3PositionPage.h"\n'
web = once(web, web_include_anchor, web_include_new, "V3 WiFi GPS position include")

cmath_anchor = '#include <cstring>\n'
cmath_new = cmath_anchor + '#include <cmath>\n#include <cstdlib>\n'
web = once(web, cmath_anchor, cmath_new, "V3 WiFi GPS numeric includes")

clear_anchor = '''void clearDiagnosticLog(WiFiClient &client, const char *token)\n{\n'''
web_helpers = r'''bool queryValue(const char *path, const char *key, char *out, size_t outSize)
{
    if (!path || !key || !out || outSize < 2)
        return false;
    const char *cursor = strchr(path, '?');
    if (!cursor)
        return false;
    cursor++;
    const size_t keyLen = strlen(key);
    while (*cursor) {
        if (strncmp(cursor, key, keyLen) == 0 && cursor[keyLen] == '=') {
            const char *value = cursor + keyLen + 1;
            const char *end = strchr(value, '&');
            const size_t length = end ? (size_t)(end - value) : strlen(value);
            if (length == 0 || length >= outSize)
                return false;
            memcpy(out, value, length);
            out[length] = 0;
            return true;
        }
        cursor = strchr(cursor, '&');
        if (!cursor)
            break;
        cursor++;
    }
    return false;
}

void receiveWifiPhonePosition(WiFiClient &client, const char *path, const char *token)
{
    if (strcmp(token, sessionToken) != 0) {
        sendStatus(client, 403, "Forbidden", "text/plain; charset=utf-8");
        client.print("Ungültige Servicesitzung.");
        return;
    }

    char latText[24] = {};
    char lonText[24] = {};
    char accText[20] = {};
    char timeText[20] = {};
    if (!queryValue(path, "lat", latText, sizeof(latText)) || !queryValue(path, "lon", lonText, sizeof(lonText)) ||
        !queryValue(path, "acc", accText, sizeof(accText)) || !queryValue(path, "time", timeText, sizeof(timeText))) {
        sendStatus(client, 400, "Bad Request", "text/plain; charset=utf-8");
        client.print("GPS-Parameter fehlen.");
        return;
    }

    char *latEnd = nullptr;
    char *lonEnd = nullptr;
    char *accEnd = nullptr;
    const double latitude = strtod(latText, &latEnd);
    const double longitude = strtod(lonText, &lonEnd);
    const double accuracyM = strtod(accText, &accEnd);
    const uint32_t epoch = strtoul(timeText, nullptr, 10);
    if (!latEnd || *latEnd || !lonEnd || *lonEnd || !accEnd || *accEnd || !std::isfinite(latitude) ||
        !std::isfinite(longitude) || !std::isfinite(accuracyM) || latitude < -90.0 || latitude > 90.0 ||
        longitude < -180.0 || longitude > 180.0 || accuracyM < 0.0 || accuracyM > 100000.0) {
        sendStatus(client, 400, "Bad Request", "text/plain; charset=utf-8");
        client.print("GPS-Parameter ungültig.");
        return;
    }

    const int32_t latitudeI = (int32_t)std::llround(latitude * 10000000.0);
    const int32_t longitudeI = (int32_t)std::llround(longitude * 10000000.0);
    const uint32_t accuracyMm = (uint32_t)std::llround(accuracyM * 1000.0);
    if (!heltecV3SubmitWifiPhonePosition(latitudeI, longitudeI, accuracyMm, epoch)) {
        sendStatus(client, 409, "Conflict", "application/json; charset=utf-8", "Cache-Control: no-store\r\n");
        client.print("{\"ok\":false,\"reason\":\"ble-or-service\"}");
        return;
    }

    sendStatus(client, 202, "Accepted", "application/json; charset=utf-8", "Cache-Control: no-store\r\n");
    client.print("{\"ok\":true,\"transport\":\"wifi\"}");
}

void clearDiagnosticLog(WiFiClient &client, const char *token)
{
'''
web = once(web, clear_anchor, web_helpers, "V3 WiFi GPS HTTP endpoint helper")

route_anchor = '''    else if (strcmp(method, "POST") == 0 && strcmp(path, "/log/clear") == 0)\n        clearDiagnosticLog(client, token);\n'''
route_new = '''    else if (strcmp(method, "POST") == 0 && strncmp(path, "/phone-position", 15) == 0)\n        receiveWifiPhonePosition(client, path, token);\n    else if (strcmp(method, "POST") == 0 && strcmp(path, "/log/clear") == 0)\n        clearDiagnosticLog(client, token);\n'''
web = once(web, route_anchor, route_new, "V3 WiFi GPS HTTP route")

# ---------------------------------------------------------------------------
# Portal map UX: default-visible blue/cyan MGRS grid, arbitrary map-point MGRS
# lookup, one-finger pan, two-finger pinch zoom, and live phone arrow.
# ---------------------------------------------------------------------------
portal = once(
    portal,
    "mgrsOn=localStorage.getItem('jv3-mgrs')==='1'",
    "mgrsOn=localStorage.getItem('jv3-mgrs')!=='0'",
    "MGRS grid default visible",
)
portal = once(
    portal,
    "let info=null,asset=null,latestMeta=null,allTrack=[]",
    "let info=null,asset=null,latestMeta=null,allTrack=[],mapProbe=null,phonePos=null,phoneHeading=null,phoneGpsWatch=null,lastWifiGpsPostMs=0",
    "portal map/GPS state",
)

map_actions_old = '<div class="mapbox"><canvas id="trackMap"></canvas><div class="mapbadge" id="mapBadge">Offline</div></div><div class="attrib" id="attrib"></div><div class="pointinfo" id="pointInfo">Punkte werden geladen …</div><div class="actions"><button onclick="loadTrack()">Neu laden</button><button class="secondary" onclick="fitTrack()">Auf Auswahl zoomen</button><button class="secondary" onclick="zoomMap(1)">+</button><button class="secondary" onclick="zoomMap(-1)">−</button><a class="button secondary" href="/track.geojson" download="Jarnsen-Positionsverlauf.geojson">GeoJSON</a><button class="danger" onclick="clearTrack()">Verlauf löschen</button></div><div id="trackStatus" class="status"></div></section>'
map_actions_new = '<div class="mapbox"><canvas id="trackMap"></canvas><div class="mapbadge" id="mapBadge">Offline</div></div><div class="attrib" id="attrib"></div><div class="pointinfo" id="pointInfo">Karte antippen: MGRS-Koordinate des Kartenpunkts · mit einem Finger verschieben · mit zwei Fingern zoomen.</div><div class="actions"><button id="phoneGpsBtn" onclick="startPhoneGps()">Handy-GPS starten</button><button onclick="loadTrack()">Neu laden</button><button class="secondary" onclick="fitTrack()">Auf Auswahl zoomen</button><button class="secondary" onclick="zoomMap(1)">+</button><button class="secondary" onclick="zoomMap(-1)">−</button><a class="button secondary" href="/track.geojson" download="Jarnsen-Positionsverlauf.geojson">GeoJSON</a><button class="danger" onclick="clearTrack()">Verlauf löschen</button></div><div id="phoneGpsStatus" class="status">Handyposition aus · WLAN-GPS übernimmt automatisch, sobald BLE nicht verbunden ist.</div><div id="trackStatus" class="status"></div></section>'
portal = once(portal, map_actions_old, map_actions_new, "V3 map phone GPS controls")

mgrs_block = r'''function toggleMgrs(){mgrsOn=$('mgrsGrid').checked;localStorage.setItem('jv3-mgrs',mgrsOn?'1':'0');renderMap()}
function gridStep(){return view.z<=8?100000:view.z<=11?10000:view.z<=14?1000:view.z<=16?100:10}
function drawGridLabel(x,text,px,py,w,h){const cs=getComputedStyle(document.documentElement),fg=cs.getPropertyValue('--fg').trim()||'#17212b',bg=cs.getPropertyValue('--card').trim()||'#fff';x.font='10px system-ui';x.lineWidth=4;x.strokeStyle=bg;x.fillStyle=fg;const tx=Math.max(4,Math.min(w-118,px)),ty=Math.max(11,Math.min(h-4,py));x.strokeText(text,tx,ty);x.fillText(text,tx,ty)}
function drawMgrsGrid(x,w,h){if(!mgrsOn)return;const center=utmForward(view.lat,view.lon),zone=center.zone,north=center.north,corners=[[0,0],[w,0],[0,h],[w,h]].map(q=>fromScreen(q[0],q[1],w,h)).map(p=>utmForward(p.lat,p.lon,zone));let minE=Math.min(...corners.map(p=>p.e)),maxE=Math.max(...corners.map(p=>p.e)),minN=Math.min(...corners.map(p=>p.n)),maxN=Math.max(...corners.map(p=>p.n)),step=gridStep();while((maxE-minE)/step>16||(maxN-minN)/step>16)step*=10;const digits=Math.max(0,Math.min(5,5-Math.round(Math.log10(step)))),dark=matchMedia('(prefers-color-scheme: dark)').matches;x.save();x.strokeStyle=dark?'rgba(56,189,248,.82)':'rgba(20,99,214,.70)';x.lineWidth=1.25;for(let e=Math.ceil(minE/step)*step;e<=maxE;e+=step){x.beginPath();let first=true;for(let i=0;i<=14;i++){const n=minN+(maxN-minN)*i/14,p=utmInverse(zone,north,e,n),s=toScreen(p.lat,p.lon,w,h);if(first){x.moveTo(s.x,s.y);first=false}else x.lineTo(s.x,s.y)}x.stroke();const p=utmInverse(zone,north,e,minN+(maxN-minN)*.08),s=toScreen(p.lat,p.lon,w,h),label=mgrsFromUtm({...utmForward(p.lat,p.lon,zone),e},digits);drawGridLabel(x,label,s.x+3,s.y-3,w,h)}for(let n=Math.ceil(minN/step)*step;n<=maxN;n+=step){x.beginPath();let first=true;for(let i=0;i<=14;i++){const e=minE+(maxE-minE)*i/14,p=utmInverse(zone,north,e,n),s=toScreen(p.lat,p.lon,w,h);if(first){x.moveTo(s.x,s.y);first=false}else x.lineTo(s.x,s.y)}x.stroke();const p=utmInverse(zone,north,minE+(maxE-minE)*.05,n),s=toScreen(p.lat,p.lon,w,h);drawGridLabel(x,String(Math.floor(n)%100000).padStart(5,'0'),s.x+3,s.y-3,w,h)}x.restore()}
'''
portal = replace_between(portal, "function toggleMgrs(){", "function drawTrack(x,w,h){", mgrs_block, "V3 blue MGRS grid")

render_old = "function renderMap(){const {x,w,h}=canvas(),serial=++renderSerial;drawTiles(x,w,h,serial);drawMgrsGrid(x,w,h);drawTrack(x,w,h)}"
render_new = r'''function drawProbe(x,w,h){if(!mapProbe)return;const s=toScreen(mapProbe.lat,mapProbe.lon,w,h);x.save();x.strokeStyle='#c93434';x.fillStyle='#fff';x.lineWidth=2;x.beginPath();x.arc(s.x,s.y,7,0,Math.PI*2);x.fill();x.stroke();x.beginPath();x.moveTo(s.x-12,s.y);x.lineTo(s.x+12,s.y);x.moveTo(s.x,s.y-12);x.lineTo(s.x,s.y+12);x.stroke();x.restore()}
function drawPhonePosition(x,w,h){if(!phonePos)return;const s=toScreen(phonePos.lat,phonePos.lon,w,h),hdeg=Number.isFinite(phoneHeading)?phoneHeading:(Number.isFinite(phonePos.course)?phonePos.course:null);x.save();x.translate(s.x,s.y);if(hdeg!==null){x.rotate(hdeg*Math.PI/180);x.beginPath();x.moveTo(0,-17);x.lineTo(11,11);x.lineTo(0,7);x.lineTo(-11,11);x.closePath();x.fillStyle='#1463d6';x.strokeStyle='#fff';x.lineWidth=2.5;x.fill();x.stroke()}else{x.beginPath();x.arc(0,0,8,0,Math.PI*2);x.fillStyle='#1463d6';x.strokeStyle='#fff';x.lineWidth=2.5;x.fill();x.stroke()}x.restore()}
function renderMap(){const {x,w,h}=canvas(),serial=++renderSerial;drawTiles(x,w,h,serial);drawMgrsGrid(x,w,h);drawTrack(x,w,h);drawProbe(x,w,h);drawPhonePosition(x,w,h)}'''
portal = once(portal, render_old, render_new, "V3 map overlays")

interaction_block = r'''function panMapPixels(dx,dy){const c=world(view.lon,view.lat,view.z),p=unworld(c.x-dx,c.y-dy,view.z);view.lat=p.lat;view.lon=p.lon;renderMap()}
function probeMapAt(clientX,clientY){const el=$('trackMap'),r=el.getBoundingClientRect(),p=fromScreen(clientX-r.left,clientY-r.top,r.width,r.height);mapProbe={lat:p.lat,lon:p.lon};$('pointInfo').textContent='Kartenpunkt · '+mgrs10(p.lat,p.lon)+' · '+p.lat.toFixed(6)+', '+p.lon.toFixed(6);renderMap()}
const mapPointers=new Map();let mapGestureMoved=false,mapLastCenter=null,mapPinchDistance=0,mapPinchAccum=1,mapDownAt=0;
function pointerCenter(){const a=[...mapPointers.values()];return{x:a.reduce((s,p)=>s+p.x,0)/a.length,y:a.reduce((s,p)=>s+p.y,0)/a.length}}
$('trackMap').addEventListener('pointerdown',e=>{e.currentTarget.setPointerCapture?.(e.pointerId);mapPointers.set(e.pointerId,{x:e.clientX,y:e.clientY});mapGestureMoved=false;mapDownAt=Date.now();mapLastCenter=pointerCenter();if(mapPointers.size===2){const a=[...mapPointers.values()];mapPinchDistance=Math.hypot(a[0].x-a[1].x,a[0].y-a[1].y);mapPinchAccum=1}e.preventDefault()});
$('trackMap').addEventListener('pointermove',e=>{if(!mapPointers.has(e.pointerId))return;const old=mapPointers.get(e.pointerId);mapPointers.set(e.pointerId,{x:e.clientX,y:e.clientY});const center=pointerCenter();if(mapLastCenter){const dx=center.x-mapLastCenter.x,dy=center.y-mapLastCenter.y;if(Math.abs(dx)+Math.abs(dy)>1){panMapPixels(dx,dy);mapGestureMoved=true}}mapLastCenter=center;if(mapPointers.size>=2){const a=[...mapPointers.values()],dist=Math.hypot(a[0].x-a[1].x,a[0].y-a[1].y);if(mapPinchDistance>0){mapPinchAccum*=dist/mapPinchDistance;if(mapPinchAccum>1.22){view.z=Math.min(19,view.z+1);mapPinchAccum=1;renderMap();mapGestureMoved=true}else if(mapPinchAccum<.82){view.z=Math.max(3,view.z-1);mapPinchAccum=1;renderMap();mapGestureMoved=true}}mapPinchDistance=dist}else if(Math.hypot(e.clientX-old.x,e.clientY-old.y)>3)mapGestureMoved=true;e.preventDefault()});
function endMapPointer(e){const wasSingle=mapPointers.size===1,mapPoint=mapPointers.get(e.pointerId);mapPointers.delete(e.pointerId);if(!mapPointers.size){if(wasSingle&&!mapGestureMoved&&Date.now()-mapDownAt<550&&mapPoint)probeMapAt(e.clientX,e.clientY);mapLastCenter=null;mapPinchDistance=0;mapPinchAccum=1}else{mapLastCenter=pointerCenter();if(mapPointers.size<2)mapPinchDistance=0}e.preventDefault()}
$('trackMap').addEventListener('pointerup',endMapPointer);$('trackMap').addEventListener('pointercancel',endMapPointer);window.addEventListener('resize',renderMap);

function compassEvent(e){let h=null;if(Number.isFinite(e.webkitCompassHeading))h=e.webkitCompassHeading;else if(e.absolute&&Number.isFinite(e.alpha))h=(360-e.alpha)%360;if(h!==null){phoneHeading=h;renderMap()}}
async function enableCompass(){try{if(typeof DeviceOrientationEvent!=='undefined'&&typeof DeviceOrientationEvent.requestPermission==='function'){const p=await DeviceOrientationEvent.requestPermission();if(p!=='granted')return false}window.addEventListener('deviceorientationabsolute',compassEvent,true);window.addEventListener('deviceorientation',compassEvent,true);return true}catch(_){return false}}
async function postWifiPhoneGps(p){if(!info||Date.now()-lastWifiGpsPostMs<3000)return;lastWifiGpsPostMs=Date.now();const q=new URLSearchParams({lat:String(p.lat),lon:String(p.lon),acc:String(p.accuracy||0),time:String(p.epoch||0)});try{const r=await fetch('/phone-position?'+q.toString(),{method:'POST',headers:{'X-Jarnsen-Token':info.token},cache:'no-store'});if(r.status===202)status('phoneGpsStatus','Handy-GPS aktiv · Position wird über WLAN an den V3 übertragen.','ok');else if(r.status===409)status('phoneGpsStatus','Handy-GPS aktiv · Bluetooth ist verbunden; WLAN-GPS wartet als Rückfallebene.','');else status('phoneGpsStatus','WLAN-GPS konnte nicht übertragen werden ('+r.status+').','warn')}catch(e){status('phoneGpsStatus','Handyposition sichtbar, aber WLAN-GPS-Übertragung fehlgeschlagen: '+e.message,'warn')}}
function phoneGeoOk(pos){const c=pos.coords;phonePos={lat:c.latitude,lon:c.longitude,accuracy:c.accuracy||0,course:Number.isFinite(c.heading)?c.heading:null,epoch:Math.floor((pos.timestamp||Date.now())/1000)};if(!Number.isFinite(phoneHeading)&&Number.isFinite(c.heading))phoneHeading=c.heading;renderMap();postWifiPhoneGps(phonePos)}
function phoneGeoError(e){const insecure=!window.isSecureContext?' Die lokale HTTP-Seite kann vom Browser für GPS blockiert werden.':'';status('phoneGpsStatus','Standortzugriff fehlgeschlagen: '+(e.message||'keine Freigabe')+'.'+insecure,'warn');$('phoneGpsBtn').textContent='Handy-GPS erneut starten'}
async function startPhoneGps(){if(!navigator.geolocation){status('phoneGpsStatus','Dieser Browser stellt keine Geolocation bereit.','warn');return}await enableCompass();if(phoneGpsWatch!==null){navigator.geolocation.clearWatch(phoneGpsWatch);phoneGpsWatch=null;phonePos=null;$('phoneGpsBtn').textContent='Handy-GPS starten';status('phoneGpsStatus','Handyposition aus.','');renderMap();return}$('phoneGpsBtn').textContent='Handy-GPS stoppen';status('phoneGpsStatus','Standort wird angefordert …');phoneGpsWatch=navigator.geolocation.watchPosition(phoneGeoOk,phoneGeoError,{enableHighAccuracy:true,maximumAge:3000,timeout:15000})}
if(navigator.permissions?.query)navigator.permissions.query({name:'geolocation'}).then(p=>{if(p.state==='granted'&&phoneGpsWatch===null)startPhoneGps()}).catch(()=>{});
'''
portal = replace_between(
    portal,
    "$('trackMap').addEventListener('click'",
    "function header(text,key)",
    interaction_block + "function header(text,key)",
    "V3 touch map and phone GPS interaction",
)

# Update the map hint so the now-default MGRS overlay is obvious.
portal = once(
    portal,
    '<label class="switch"><input id="mgrsGrid" type="checkbox" onchange="toggleMgrs()">MGRS-Gitter</label>',
    '<label class="switch"><input id="mgrsGrid" type="checkbox" onchange="toggleMgrs()">MGRS-Gitter sichtbar</label>',
    "V3 MGRS grid label",
)

for marker in (
    "submitWifiPosition",
    "PHONE_POS_WIFI",
    "heltecV3SubmitWifiPhonePosition",
):
    if marker not in manager:
        raise SystemExit(f"missing V3 WiFi GPS manager marker: {marker}")

for marker in (
    'strncmp(path, "/phone-position", 15)',
    "receiveWifiPhonePosition",
    "heltecV3SubmitWifiPhonePosition",
):
    if marker not in web:
        raise SystemExit(f"missing V3 WiFi GPS web marker: {marker}")

for marker in (
    "mapPointers",
    "probeMapAt",
    "drawPhonePosition",
    "Handy-GPS starten",
    "deviceorientationabsolute",
    "PHONE_POS_WIFI" if False else "postWifiPhoneGps",
    "MGRS-Gitter sichtbar",
):
    if marker not in portal:
        raise SystemExit(f"missing V3 map/GPS portal marker: {marker}")

WEB.write_text(web, encoding="utf-8")
PORTAL.write_text(portal, encoding="utf-8")
MANAGER.write_text(manager, encoding="utf-8")
POSITION_H.write_text(position_h, encoding="utf-8")
print("Heltec V3: touch/pinch map, blue MGRS grid, coordinate probe, phone arrow and WiFi GPS fallback enabled")
