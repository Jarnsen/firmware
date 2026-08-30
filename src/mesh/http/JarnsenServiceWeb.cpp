#include "mesh/http/JarnsenServiceWeb.h"

#if defined(ARCH_ESP32) && HAS_WIFI && (defined(_VARIANT_HELTEC_V3) || defined(HELTEC_TRACKER_V1_1))

#include "DebugConfiguration.h"
#include "NodeDB.h"
#include "Throttle.h"
#include "mesh/http/JarnsenPositionTrack.h"
#include "mesh/wifi/WiFiAPClient.h"

#if defined(_VARIANT_HELTEC_V3)
#include "infrastructure/HeltecV3DiagnosticLog.h"
#else
#include "vehicle/TrackerDiagnosticLog.h"
#endif

#include <Arduino.h>
#include <DNSServer.h>
#include <Update.h>
#include <WiFi.h>
#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <esp_mac.h>
#include <esp_system.h>
#include <esp_wifi.h>
#include <mbedtls/sha256.h>
#include <strings.h>

namespace
{
constexpr const char *SERVICE_PASSWORD = "24011980";
constexpr const char *SERVICE_ADDRESS = "192.168.4.1";
constexpr uint32_t IDLE_TIMEOUT_MS = 10UL * 60UL * 1000UL;
constexpr uint32_t CLIENT_TIMEOUT_MS = 15000UL;
constexpr size_t MAX_HEADER_BYTES = 4096U;
constexpr size_t MAX_FIRMWARE_BYTES = 0x330000U;
constexpr size_t MIN_FIRMWARE_BYTES = 256U * 1024U;

#if defined(_VARIANT_HELTEC_V3)
constexpr const char *DEVICE_CODE = "HELTEC_V3_REPEATER";
constexpr const char *DEVICE_TITLE = "Heltec V3";
constexpr const char *SSID_PREFIX = "Jarnsen-V3";
constexpr const char *GITHUB_TAG = "jarnsen-v3-latest";
constexpr const char *FIRMWARE_ASSET = "heltec-v3-repeater-light-sleep.update.bin";
#else
constexpr const char *DEVICE_CODE = "HELTEC_TRACKER_V1.1";
constexpr const char *DEVICE_TITLE = "Tracker V1.1";
constexpr const char *SSID_PREFIX = "Jarnsen-Tracker";
constexpr const char *GITHUB_TAG = "jarnsen-tracker-latest";
constexpr const char *FIRMWARE_ASSET = "heltec-tracker-v11-vehicle-motion-wake.update.bin";
#endif

DNSServer dnsServer;
WiFiServer httpServer(80);
bool serviceActive = false;
bool updateInProgress = false;
bool hadStation = false;
uint32_t lastActivityMs = 0;
uint32_t restartRequestedMs = 0;
char serviceSsid[40] = {};
char sessionToken[17] = {};
char serviceError[112] = {};

const char PAGE[] PROGMEM = R"JARN(<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover,user-scalable=no">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>JARN-MESH</title>
<style>
:root{color-scheme:light dark;--bg:#f2f2f7;--card:rgba(255,255,255,.82);--card-solid:#fff;--fg:#111113;--muted:#6e6e73;--line:rgba(60,60,67,.18);--accent:#007aff;--accent2:#5ac8fa;--green:#34c759;--orange:#ff9500;--red:#ff3b30;--gray:#8e8e93;--map:#e9edf2;--glass:rgba(255,255,255,.72);--shadow:0 10px 34px rgba(0,0,0,.08)}
@media(prefers-color-scheme:dark){:root{--bg:#000;--card:rgba(28,28,30,.88);--card-solid:#1c1c1e;--fg:#f5f5f7;--muted:#98989d;--line:rgba(84,84,88,.62);--accent:#0a84ff;--accent2:#64d2ff;--green:#30d158;--orange:#ff9f0a;--red:#ff453a;--gray:#8e8e93;--map:#121416;--glass:rgba(28,28,30,.76);--shadow:0 12px 36px rgba(0,0,0,.36)}}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}html{background:var(--bg)}body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.35 -apple-system,BlinkMacSystemFont,"SF Pro Text","Helvetica Neue",Arial,sans-serif}.app{max-width:820px;margin:0 auto;padding:calc(env(safe-area-inset-top) + 18px) 14px calc(env(safe-area-inset-bottom) + 36px)}button,a,input{font:inherit}.hero{padding:4px 4px 14px}.eyebrow{font-size:12px;font-weight:800;letter-spacing:.08em;color:var(--muted);text-transform:uppercase}.heroRow{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.hero h1{font-size:31px;line-height:1.03;letter-spacing:-.035em;margin:4px 0 5px;max-width:580px}.heroMeta{color:var(--muted);font-size:14px}.online{display:inline-flex;align-items:center;gap:6px;border-radius:999px;padding:7px 10px;background:color-mix(in srgb,var(--green) 14%,transparent);color:var(--green);font-size:12px;font-weight:800;white-space:nowrap}.online:before{content:"";width:7px;height:7px;border-radius:50%;background:currentColor}.quickGrid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-bottom:14px}.quick{border:0;text-align:left;color:var(--fg);background:var(--card);border:1px solid var(--line);border-radius:22px;padding:15px;min-height:94px;box-shadow:var(--shadow);backdrop-filter:blur(22px);-webkit-backdrop-filter:blur(22px);cursor:pointer}.quick:active{transform:scale(.985)}.quickLabel{font-size:13px;color:var(--muted);font-weight:650}.quickValue{display:block;margin-top:7px;font-size:20px;line-height:1.08;font-weight:750;letter-spacing:-.02em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.quickSub{display:block;margin-top:4px;color:var(--muted);font-size:12px}.card{background:var(--card);border:1px solid var(--line);border-radius:24px;padding:16px;margin:12px 0;box-shadow:var(--shadow);backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px)}.cardHead{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:12px}.card h2{font-size:21px;letter-spacing:-.02em;margin:2px 0 0}.badge{border-radius:999px;padding:6px 9px;background:rgba(120,120,128,.12);font-size:12px;color:var(--muted);font-weight:700}.muted{color:var(--muted)}.mapStylePicker{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:3px;margin:0 0 10px;padding:3px;border-radius:13px;background:rgba(118,118,128,.12);border:1px solid var(--line)}.mapStylePicker button{appearance:none;border:0;border-radius:10px;min-height:38px;padding:7px 8px;background:transparent;color:var(--muted);font-size:13px;font-weight:750;cursor:pointer}.mapStylePicker button.active{background:var(--card-solid);color:var(--fg);box-shadow:0 1px 4px rgba(0,0,0,.16)}.mapShell{position:relative;border-radius:20px;overflow:hidden;background:var(--map);border:1px solid var(--line);height:min(64vw,510px);min-height:370px;touch-action:none;user-select:none;-webkit-user-select:none}#mapCanvas{display:block;width:100%;height:100%;touch-action:none}.mapToolbar{position:absolute;left:10px;right:10px;top:10px;display:flex;gap:7px;flex-wrap:wrap;pointer-events:none}.mapToolbar button,.zoomStack button{pointer-events:auto}.glassBtn{height:42px;border:1px solid var(--line);border-radius:14px;background:var(--glass);color:var(--fg);padding:0 12px;font-weight:720;box-shadow:0 4px 18px rgba(0,0,0,.10);backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px)}.glassBtn.active{background:var(--accent);color:#fff;border-color:transparent}.zoomStack{position:absolute;right:10px;bottom:12px;display:flex;flex-direction:column;gap:7px}.zoomStack button{width:44px;height:44px;padding:0;font-size:24px}.northBadge{position:absolute;left:12px;bottom:12px;background:var(--glass);border:1px solid var(--line);border-radius:12px;padding:7px 9px;font-size:11px;font-weight:760;color:var(--muted);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);pointer-events:none}.mapAttribution{position:absolute;left:12px;bottom:48px;max-width:calc(100% - 78px);background:var(--glass);border:1px solid var(--line);border-radius:10px;padding:5px 7px;font-size:9px;line-height:1.2;font-weight:650;color:var(--muted);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);pointer-events:none}.navHud{position:absolute;left:50%;top:64px;transform:translateX(-50%);min-width:185px;text-align:center;padding:10px 14px;border-radius:18px;background:var(--glass);border:1px solid var(--line);box-shadow:0 8px 24px rgba(0,0,0,.14);backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px)}.navHud.hidden{display:none}.navMil{font-size:25px;font-weight:850;letter-spacing:.02em}.navDist{font-size:14px;color:var(--muted);margin-top:1px}.sheet{margin-top:12px;border-radius:20px;background:rgba(120,120,128,.10);padding:14px;display:none}.sheet.visible{display:block}.sheetTitle{font-size:20px;font-weight:780;letter-spacing:-.02em}.sheetBig{display:flex;justify-content:space-between;gap:10px;margin-top:9px}.sheetBig strong{font-size:24px;letter-spacing:-.02em}.sheetMeta{margin-top:7px;color:var(--muted);font-size:13px;word-break:break-word}.actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}.btn{appearance:none;border:0;border-radius:14px;background:var(--accent);color:#fff;min-height:44px;padding:10px 14px;font-weight:740;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;justify-content:center}.btn.secondary{background:rgba(120,120,128,.12);color:var(--accent);border:1px solid var(--line)}.btn.danger{background:var(--red)}.btn:disabled{opacity:.45}.status{min-height:22px;margin-top:9px;color:var(--muted);font-size:13px}.ok{color:var(--green)}.err{color:var(--red)}.metrics{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px;margin-top:12px}.metric{background:rgba(120,120,128,.09);border-radius:16px;padding:12px}.metric span{display:block;color:var(--muted);font-size:12px}.metric b{display:block;font-size:20px;margin-top:4px}.hide{display:none!important}pre{white-space:pre-wrap;word-break:break-word;max-height:44vh;overflow:auto;background:rgba(120,120,128,.10);border-radius:16px;padding:12px;font:12px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace}progress{width:100%;height:10px;margin-top:12px;accent-color:var(--accent)}input[type=file]{width:100%;font-size:16px;margin:9px 0}.warn{border-left:3px solid var(--orange);padding-left:10px}.footer{padding:12px 4px;color:var(--muted);font-size:12px;text-align:center}
@media(max-width:520px){.hero h1{font-size:28px}.quickGrid{grid-template-columns:repeat(2,minmax(0,1fr))}.quick{min-height:88px;padding:13px;border-radius:20px}.quickValue{font-size:18px}.mapShell{height:470px;min-height:470px}.mapToolbar{right:62px}.card{border-radius:22px;padding:14px}.sheetBig strong{font-size:21px}}
</style>
</head>
<body>
<main class="app">
<header class="hero">
<div class="eyebrow">JARN-MESH</div>
<div class="heroRow"><div><h1 id="nodeName">Node wird gelesen …</h1><div class="heroMeta" id="nodeMeta">Service wird verbunden …</div></div><div class="online">ONLINE</div></div>
</header>
<section class="quickGrid" aria-label="Übersicht">
<button class="quick" id="positionTile" type="button"><span class="quickLabel">Position / MGRS</span><span class="quickValue" id="positionValue">—</span><span class="quickSub" id="positionSub">Position wird geladen</span></button>
<button class="quick" id="radioTile" type="button"><span class="quickLabel">Funk / LoRa</span><span class="quickValue">Meshtastic</span><span class="quickSub">Mesh-Funk aktiv</span></button>
<button class="quick" id="networkTile" type="button"><span class="quickLabel">Nachbarn / Netz</span><span class="quickValue" id="networkValue">—</span><span class="quickSub" id="networkSub">Netz wird gelesen</span></button>
<button class="quick" id="systemTile" type="button"><span class="quickLabel">System / Service</span><span class="quickValue" id="systemValue">WLAN</span><span class="quickSub" id="systemSub">192.168.4.1</span></button>
</section>
<section class="card" id="mapCard">
<div class="cardHead"><div><div class="eyebrow">Karte</div><h2>Taktische Lage</h2></div><div class="badge" id="mapCount">0 Nodes</div></div>
<div class="mapStylePicker" role="group" aria-label="Kartentyp"><button class="active" id="streetMapBtn" type="button">Karte</button><button id="satelliteMapBtn" type="button">Satellit</button><button id="hybridMapBtn" type="button">Hybrid</button></div>
<div class="mapShell" id="mapShell">
<canvas id="mapCanvas" aria-label="Interaktive taktische Karte"></canvas>
<div class="mapToolbar">
<button class="glassBtn" id="centerBtn" type="button">◎ Standort</button>
<button class="glassBtn active" id="nodesBtn" type="button">Nodes</button>
<button class="glassBtn active" id="trackBtn" type="button">Track</button>
<button class="glassBtn" id="compassBtn" type="button">Kompass</button>
</div>
<div class="navHud hidden" id="navHud"><div class="navMil" id="navMil">0000 Strich</div><div class="navDist" id="navDist">—</div></div>
<div class="zoomStack"><button class="glassBtn" id="zoomIn" type="button" aria-label="Vergrößern">+</button><button class="glassBtn" id="zoomOut" type="button" aria-label="Verkleinern">−</button></div>
<div class="mapAttribution hide" id="mapAttribution"></div>
<div class="northBadge" id="mapNetBadge">N ↑ · KARTE AUTO</div>
</div>
<div class="sheet" id="selectionSheet">
<div class="sheetTitle" id="selectionTitle">Ziel</div>
<div class="sheetBig"><strong id="selectionMil">—</strong><strong id="selectionDist">—</strong></div>
<div class="sheetMeta" id="selectionMgrs">—</div>
<div class="sheetMeta" id="selectionAge"></div>
<div class="actions"><button class="btn" id="navigateBtn" type="button">NAVIGIEREN</button><button class="btn secondary" id="closeSelection" type="button">Schließen</button></div>
</div>
<div class="status" id="mapStatus">Karte wird geladen …</div>
</section>
<section class="card" id="logCard">
<div class="cardHead"><div><div class="eyebrow">Service</div><h2>Diagnose &amp; Logs</h2></div></div>
<div class="actions"><button class="btn" id="analyseBtn" type="button">Log laden &amp; auswerten</button><a class="btn secondary" href="/log" download>Log speichern</a></div>
<div class="status" id="logStatus"></div><div class="metrics hide" id="metrics"></div><pre class="hide" id="raw"></pre>
</section>
<section class="card" id="firmwareCard">
<div class="cardHead"><div><div class="eyebrow">Firmware</div><h2>WLAN Update</h2></div></div>
<p class="muted">Die Firmware wird vor der Aktivierung im Node per SHA-256 geprüft.</p>
<div class="actions"><button class="btn" id="githubBtn" type="button">Aktuelle GitHub-Firmware laden</button></div>
<div class="hide" id="fallback"><p class="warn muted">Falls iOS die GitHub-Datei nicht direkt weiterreichen kann, Datei laden und anschließend hier auswählen.</p><a class="btn secondary" id="downloadLink" target="_blank">Firmware aus GitHub laden</a><input id="file" type="file" accept=".bin,application/octet-stream"><button class="btn" id="uploadBtn" type="button">Ausgewählte Firmware installieren</button></div>
<progress class="hide" id="progress" max="100" value="0"></progress><div class="status" id="fwStatus"></div>
</section>
<section class="card" id="connectionCard">
<div class="cardHead"><div><div class="eyebrow">Verbindung</div><h2>Service WLAN</h2></div></div>
<div class="metrics"><div class="metric"><span>SSID</span><b id="ssid">—</b></div><div class="metric"><span>Adresse</span><b>192.168.4.1</b></div></div>
<p class="muted">Das Portal bleibt lokal am Node. Externe Karten- und GitHub-Daten werden direkt vom Telefon geladen, wenn iOS/Android parallel zum Node-WLAN Internet über Mobilfunk bereitstellt.</p>
</section>
<div class="footer">JARN-MESH · lokales Captive Portal</div>
</main>
<script>
const API='https://api.github.com/repos/Jarnsen/firmware/releases/tags/';
const BASEMAPS={
 streets:{name:'KARTE',attribution:'© OpenStreetMap-Mitwirkende',layers:[{id:'osm-streets',base:true,url:(z,x,y)=>'https://tile.openstreetmap.org/'+z+'/'+x+'/'+y+'.png'}]},
 satellite:{name:'SATELLIT',attribution:'Esri · Maxar · Earthstar Geographics · GIS User Community',layers:[{id:'esri-imagery',base:true,url:(z,x,y)=>'https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/'+z+'/'+y+'/'+x}]},
 hybrid:{name:'HYBRID',attribution:'Esri · Maxar · Earthstar Geographics · GIS User Community',layers:[{id:'esri-imagery',base:true,url:(z,x,y)=>'https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/'+z+'/'+y+'/'+x},{id:'esri-transport',base:false,url:(z,x,y)=>'https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Transportation/MapServer/tile/'+z+'/'+y+'/'+x},{id:'esri-labels',base:false,url:(z,x,y)=>'https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/'+z+'/'+y+'/'+x}]}
};
const $=id=>document.getElementById(id);
let info=null,asset=null,nodes=[],selfPos=null,track=[],selected=null,navTarget=null,heading=null;
let showNodes=true,showTrack=true,followSelf=true,mapStyle='streets';
let view={lat:49.4,lon:7.0,span:.02};
const pointers=new Map();let dragStart=null,pinchStart=null;
const tileCache=new Map();let onlineMapState='checking',tileFailureStreak=0,mapDrawQueued=false;
function setStatus(id,text,kind=''){const e=$(id);e.textContent=text;e.className='status '+kind}
function esc(s){return String(s??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')}
function distM(a,b){const R=6371000,rad=Math.PI/180,p1=a.lat*rad,p2=b.lat*rad,dp=(b.lat-a.lat)*rad,dl=(b.lon-a.lon)*rad;const h=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;return 2*R*Math.asin(Math.min(1,Math.sqrt(h)))}
function bearingDeg(a,b){const r=Math.PI/180,p1=a.lat*r,p2=b.lat*r,dl=(b.lon-a.lon)*r;const y=Math.sin(dl)*Math.cos(p2),x=Math.cos(p1)*Math.sin(p2)-Math.sin(p1)*Math.cos(p2)*Math.cos(dl);return(Math.atan2(y,x)*180/Math.PI+360)%360}
function strich(deg){return String(Math.round(deg/360*6400)%6400).padStart(4,'0')+' Strich'}
function distanceText(m){return m<1000?Math.round(m)+' m':(m/1000).toFixed(m<10000?2:1).replace('.',',')+' km'}
function ageText(epoch){if(!epoch)return'Alter unbekannt';const s=Math.max(0,Math.round(Date.now()/1000-epoch));if(s<60)return'vor '+s+' s';if(s<3600)return'vor '+Math.round(s/60)+' min';if(s<86400)return'vor '+(s/3600).toFixed(1).replace('.',',')+' h';return'vor '+Math.round(s/86400)+' d'}
function freshness(epoch){if(!epoch)return'old';const s=Date.now()/1000-epoch;return s<300?'fresh':s<1800?'stale':'old'}
function canvas(){const c=$('mapCanvas'),r=c.getBoundingClientRect(),d=Math.min(devicePixelRatio||1,2);const W=Math.max(1,Math.round(r.width*d)),H=Math.max(1,Math.round(r.height*d));if(c.width!==W||c.height!==H){c.width=W;c.height=H}const ctx=c.getContext('2d');ctx.setTransform(d,0,0,d,0,0);return{c,ctx,w:r.width,h:r.height,d}}
function cosLat(){return Math.max(.18,Math.cos(view.lat*Math.PI/180))}
function project(p,w,h){const k=h/view.span,c=cosLat();return{x:w/2+(p.lon-view.lon)*c*k,y:h/2-(p.lat-view.lat)*k}}
function unproject(x,y,w,h){const k=h/view.span,c=cosLat();return{lat:view.lat-(y-h/2)/k,lon:view.lon+(x-w/2)/(c*k)}}
function fitAll(){const pts=[];if(selfPos)pts.push(selfPos);if(showNodes)nodes.forEach(n=>pts.push(n));if(showTrack)track.forEach(p=>pts.push(p));if(!pts.length)return;const avg=pts.reduce((s,p)=>s+p.lat,0)/pts.length,c=Math.max(.18,Math.cos(avg*Math.PI/180));let minLat=Math.min(...pts.map(p=>p.lat)),maxLat=Math.max(...pts.map(p=>p.lat)),minX=Math.min(...pts.map(p=>p.lon*c)),maxX=Math.max(...pts.map(p=>p.lon*c));const r=$('mapCanvas').getBoundingClientRect(),aspect=Math.max(.45,r.width/r.height);const latRange=Math.max(.001,maxLat-minLat),lonAsLat=Math.max(.001,(maxX-minX)/aspect);view.lat=(minLat+maxLat)/2;view.lon=(minX+maxX)/(2*c);view.span=Math.min(120,Math.max(.002,Math.max(latRange,lonAsLat)*1.5));followSelf=false;drawMap()}
function centerSelf(){if(!selfPos)return;view.lat=selfPos.lat;view.lon=selfPos.lon;if(view.span>.08||view.span<.002)view.span=.02;followSelf=true;drawMap()}
function zoom(f){view.span=Math.max(.0005,Math.min(120,view.span*f));followSelf=false;drawMap()}
function roundRect(ctx,x,y,w,h,r){r=Math.min(r,w/2,h/2);ctx.beginPath();ctx.moveTo(x+r,y);ctx.arcTo(x+w,y,x+w,y+h,r);ctx.arcTo(x+w,y+h,x,y+h,r);ctx.arcTo(x,y+h,x,y,r);ctx.arcTo(x,y,x+w,y,r);ctx.closePath()}
function theme(){const s=getComputedStyle(document.documentElement);return{fg:s.getPropertyValue('--fg').trim(),muted:s.getPropertyValue('--muted').trim(),line:s.getPropertyValue('--line').trim(),accent:s.getPropertyValue('--accent').trim(),green:s.getPropertyValue('--green').trim(),orange:s.getPropertyValue('--orange').trim(),gray:s.getPropertyValue('--gray').trim(),glass:s.getPropertyValue('--glass').trim(),map:s.getPropertyValue('--map').trim()}}
function requestMapDraw(){if(mapDrawQueued)return;mapDrawQueued=true;requestAnimationFrame(()=>{mapDrawQueued=false;drawMap()})}
function setBasemap(style){if(!BASEMAPS[style])return;mapStyle=style;['streetMapBtn','satelliteMapBtn','hybridMapBtn'].forEach(id=>$(id).classList.remove('active'));$(({streets:'streetMapBtn',satellite:'satelliteMapBtn',hybrid:'hybridMapBtn'})[style]).classList.add('active');tileFailureStreak=0;setOnlineMapState('checking');drawMap()}
function setOnlineMapState(state){onlineMapState=state;const b=$('mapNetBadge'),a=$('mapAttribution'),style=BASEMAPS[mapStyle];if(state==='online'){b.textContent='N ↑ · ONLINE · '+style.name;a.textContent=style.attribution;a.classList.remove('hide')}else if(state==='offline'){b.textContent='N ↑ · OFFLINE · '+style.name;a.classList.add('hide')}else{b.textContent='N ↑ · '+style.name+' AUTO';a.classList.add('hide')}}
function tileZoom(h){return Math.max(2,Math.min(19,Math.round(Math.log2((360*Math.max(300,h))/(Math.max(.0005,view.span)*256)))))}
function tileX(lon,z){return(lon+180)/360*(2**z)}
function tileY(lat,z){const r=Math.max(-85.05112878,Math.min(85.05112878,lat))*Math.PI/180;return(1-Math.asinh(Math.tan(r))/Math.PI)/2*(2**z)}
function tileLon(x,z){return x/(2**z)*360-180}
function tileLat(y,z){return Math.atan(Math.sinh(Math.PI*(1-2*y/(2**z))))*180/Math.PI}
function trimTiles(){if(tileCache.size<=360)return;for(const [k,v] of tileCache){if(v.state!=='loading')tileCache.delete(k);if(tileCache.size<=280)break}}
function onlineTile(source,z,x,y){const n=2**z;if(y<0||y>=n)return null;const xn=((x%n)+n)%n,key=source.id+'/'+z+'/'+xn+'/'+y;let e=tileCache.get(key);if(e&&e.state==='error'&&Date.now()-e.at>30000){tileCache.delete(key);e=null}if(e)return e;trimTiles();const img=new Image();e={state:'loading',img,x:xn,y,z,at:Date.now()};tileCache.set(key,e);img.decoding='async';img.onload=()=>{e.state='ready';e.at=Date.now();if(source.base){tileFailureStreak=0;setOnlineMapState('online')}requestMapDraw()};img.onerror=()=>{e.state='error';e.at=Date.now();if(source.base){tileFailureStreak++;if(tileFailureStreak>=4)setOnlineMapState('offline')}requestMapDraw()};img.src=source.url(z,xn,y);return e}
function drawTileSource(ctx,w,h,z,source){const nw=unproject(0,0,w,h),se=unproject(w,h,w,h),west=Math.min(nw.lon,se.lon),east=Math.max(nw.lon,se.lon),north=Math.max(nw.lat,se.lat),south=Math.min(nw.lat,se.lat);let x0=Math.floor(tileX(west,z))-1,x1=Math.floor(tileX(east,z))+1,y0=Math.floor(tileY(north,z))-1,y1=Math.floor(tileY(south,z))+1;const count=(x1-x0+1)*(y1-y0+1);if(count<=0||count>64)return{ready:0,pending:0,valid:false};let ready=0,pending=0;for(let y=y0;y<=y1;y++)for(let x=x0;x<=x1;x++){const e=onlineTile(source,z,x,y);if(!e)continue;if(e.state==='loading'){pending++;continue}if(e.state!=='ready')continue;let lonL=tileLon(e.x,z);while(lonL-view.lon>180)lonL-=360;while(view.lon-lonL>180)lonL+=360;const lonR=lonL+360/(2**z),latT=tileLat(y,z),latB=tileLat(y+1,z),a=project({lat:latT,lon:lonL},w,h),b=project({lat:latB,lon:lonR},w,h);ctx.drawImage(e.img,a.x,a.y,b.x-a.x,b.y-a.y);ready++}return{ready,pending,valid:true}}
function drawOnlineTiles(ctx,w,h){const style=BASEMAPS[mapStyle],z=tileZoom(h),base=drawTileSource(ctx,w,h,z,style.layers[0]);if(!base.valid){setOnlineMapState('offline');return 0}if(base.ready>0){for(let i=1;i<style.layers.length;i++)drawTileSource(ctx,w,h,z,style.layers[i]);setOnlineMapState('online')}else if(base.pending>0&&onlineMapState!=='online')setOnlineMapState('checking');else if(tileFailureStreak>=4)setOnlineMapState('offline');return base.ready}
function drawGrid(ctx,w,h,t){ctx.fillStyle=t.map;ctx.fillRect(0,0,w,h);const online=drawOnlineTiles(ctx,w,h);ctx.save();ctx.globalAlpha=online?.18:1;ctx.strokeStyle=t.line;ctx.lineWidth=1;const stepPx=Math.max(54,Math.min(110,h/5));for(let x=(w/2)%stepPx;x<w;x+=stepPx){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,h);ctx.stroke()}for(let y=(h/2)%stepPx;y<h;y+=stepPx){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke()}ctx.restore()}
function drawLabel(ctx,x,y,text,t){ctx.font='600 11px -apple-system,BlinkMacSystemFont,sans-serif';const m=ctx.measureText(text),w=m.width+14,h=24;let lx=Math.max(4,Math.min(x-w/2,$('mapCanvas').getBoundingClientRect().width-w-4)),ly=y-38;roundRect(ctx,lx,ly,w,h,9);ctx.fillStyle=t.glass;ctx.fill();ctx.strokeStyle=t.line;ctx.stroke();ctx.fillStyle=t.fg;ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(text,lx+w/2,ly+h/2)}
function drawMap(){const{ctx,w,h}=canvas(),t=theme();drawGrid(ctx,w,h,t);if(showTrack&&track.length>1){ctx.strokeStyle=t.accent;ctx.globalAlpha=.48;ctx.lineWidth=3;ctx.lineJoin='round';ctx.beginPath();track.forEach((p,i)=>{const q=project(p,w,h);i?ctx.lineTo(q.x,q.y):ctx.moveTo(q.x,q.y)});ctx.stroke();ctx.globalAlpha=1}if(navTarget&&selfPos){const a=project(selfPos,w,h),b=project(navTarget,w,h);ctx.save();ctx.setLineDash([9,7]);ctx.strokeStyle=t.orange;ctx.lineWidth=3;ctx.beginPath();ctx.moveTo(a.x,a.y);ctx.lineTo(b.x,b.y);ctx.stroke();ctx.restore()}if(showNodes){nodes.forEach(n=>{const q=project(n,w,h);if(q.x<-40||q.y<-40||q.x>w+40||q.y>h+40)return;const f=freshness(n.last_heard),col=f==='fresh'?t.accent:f==='stale'?t.orange:t.gray;ctx.beginPath();ctx.arc(q.x,q.y,selected&&selected.type==='node'&&selected.id===n.id?12:9,0,Math.PI*2);ctx.fillStyle=col;ctx.globalAlpha=f==='old'?.48:1;ctx.fill();ctx.globalAlpha=1;ctx.strokeStyle='#fff';ctx.lineWidth=2;ctx.stroke();drawLabel(ctx,q.x,q.y,n.short||n.name||n.id,t)})}if(selfPos){const q=project(selfPos,w,h);ctx.save();ctx.translate(q.x,q.y);ctx.rotate(((heading??0)*Math.PI)/180);ctx.beginPath();ctx.moveTo(0,-23);ctx.lineTo(15,17);ctx.lineTo(0,11);ctx.lineTo(-15,17);ctx.closePath();ctx.fillStyle=t.accent;ctx.shadowColor='rgba(0,0,0,.22)';ctx.shadowBlur=8;ctx.fill();ctx.shadowBlur=0;ctx.strokeStyle='#fff';ctx.lineWidth=2.5;ctx.stroke();ctx.restore();ctx.beginPath();ctx.arc(q.x,q.y,5,0,Math.PI*2);ctx.fillStyle='#fff';ctx.fill()}if(selected&&selected.type==='point'){const q=project(selected,w,h);ctx.beginPath();ctx.arc(q.x,q.y,10,0,Math.PI*2);ctx.fillStyle=t.orange;ctx.fill();ctx.strokeStyle='#fff';ctx.lineWidth=2;ctx.stroke()}updateNavigation()}
function nearestNode(x,y,w,h){let best=null,bd=34*34;nodes.forEach(n=>{const q=project(n,w,h),d=(q.x-x)**2+(q.y-y)**2;if(d<bd){bd=d;best=n}});return best}
async function selectMapPoint(p){selected={type:'point',lat:p.lat,lon:p.lon,name:'Kartenpunkt',mgrs:'MGRS wird berechnet …'};showSelection();drawMap();try{const r=await fetch('/mgrs?lat='+p.lat.toFixed(7)+'&lon='+p.lon.toFixed(7),{cache:'no-store'});if(r.ok){const j=await r.json();if(selected&&selected.type==='point'){selected.mgrs=j.mgrs||'—';showSelection()}}}catch(_){}}
function showSelection(){if(!selected){$('selectionSheet').classList.remove('visible');return}const target=selected.type==='node'?selected:selected;$('selectionSheet').classList.add('visible');$('selectionTitle').textContent=selected.type==='node'?(selected.name||selected.short||selected.id):'Kartenpunkt';$('selectionMgrs').textContent=(selected.mgrs||'—')+(selected.type==='point'?' · '+selected.lat.toFixed(7)+', '+selected.lon.toFixed(7):'');$('selectionAge').textContent=selected.type==='node'?(ageText(selected.last_heard)+(selected.hops!=null?' · '+selected.hops+' Hops':'')+(Number.isFinite(selected.snr)?' · SNR '+selected.snr.toFixed(1)+' dB':'')):'Koordinate aus der Karte';if(selfPos){const d=distM(selfPos,target),b=bearingDeg(selfPos,target);$('selectionMil').textContent=strich(b);$('selectionDist').textContent=distanceText(d)}else{$('selectionMil').textContent='—';$('selectionDist').textContent='Eigene Position fehlt'}$('navigateBtn').textContent=navTarget&&sameTarget(navTarget,target)?'ZIEL BEENDEN':'NAVIGIEREN'}
function sameTarget(a,b){if(!a||!b)return false;if(a.id&&b.id)return a.id===b.id;return Math.abs(a.lat-b.lat)<1e-8&&Math.abs(a.lon-b.lon)<1e-8}
function toggleNavigation(){if(!selected)return;const target=selected.type==='node'?selected:selected;if(navTarget&&sameTarget(navTarget,target)){navTarget=null;$('navHud').classList.add('hidden')}else{navTarget={...target};$('navHud').classList.remove('hidden')}showSelection();drawMap()}
function updateNavigation(){if(!navTarget||!selfPos){$('navHud').classList.add('hidden');return}const d=distM(selfPos,navTarget),b=bearingDeg(selfPos,navTarget);$('navMil').textContent=strich(b);$('navDist').textContent=distanceText(d)+' · '+(navTarget.name||navTarget.short||'Kartenpunkt');$('navHud').classList.remove('hidden');if(selected)showSelection()}
async function enableCompass(){try{if(typeof DeviceOrientationEvent!=='undefined'&&typeof DeviceOrientationEvent.requestPermission==='function'){const p=await DeviceOrientationEvent.requestPermission();if(p!=='granted')throw Error('Kompassfreigabe abgelehnt')}const h=e=>{let v=null;if(typeof e.webkitCompassHeading==='number')v=e.webkitCompassHeading;else if(e.absolute&&typeof e.alpha==='number')v=(360-e.alpha)%360;if(v!=null&&Number.isFinite(v)){heading=v;$('compassBtn').classList.add('active');drawMap()}};window.addEventListener('deviceorientation',h,true);setStatus('mapStatus','Kompass aktiv. Pfeil zeigt die Blickrichtung.','ok')}catch(e){setStatus('mapStatus','Kompass nicht verfügbar: '+e.message,'err')}}
async function loadSituation(){try{const r=await fetch('/nodes.json',{cache:'no-store'});if(!r.ok)throw Error(await r.text());const j=await r.json();nodes=Array.isArray(j.nodes)?j.nodes:[];selfPos=j.self&&Number.isFinite(j.self.lat)&&Number.isFinite(j.self.lon)?j.self:null;if(selfPos&&followSelf){view.lat=selfPos.lat;view.lon=selfPos.lon}if(navTarget&&navTarget.id){const fresh=nodes.find(n=>n.id===navTarget.id);if(fresh)navTarget={...fresh}}$('mapCount').textContent=nodes.length+' Nodes';$('networkValue').textContent=(j.online??0)+' online';$('networkSub').textContent=(j.total??0)+' bekannt';if(selfPos){$('positionValue').textContent=selfPos.mgrs||'Position';$('positionSub').textContent='Eigener Standort';}else{$('positionValue').textContent='Keine Position';$('positionSub').textContent='GPS / Quelle prüfen'}setStatus('mapStatus',nodes.length+' Nodes mit Position geladen.','ok');drawMap()}catch(e){setStatus('mapStatus','Lagedaten nicht verfügbar: '+e.message,'err')}}
async function loadTrack(){try{const r=await fetch('/track.geojson',{cache:'no-store'});if(!r.ok)throw Error(await r.text());const j=await r.json();track=(j.features||[]).map(f=>({lat:f.geometry.coordinates[1],lon:f.geometry.coordinates[0],...f.properties}));drawMap()}catch(e){setStatus('mapStatus','Track nicht verfügbar: '+e.message,'err')}}
function setupMapInput(){const c=$('mapCanvas');c.addEventListener('pointerdown',e=>{c.setPointerCapture(e.pointerId);pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});if(pointers.size===1)dragStart={x:e.clientX,y:e.clientY,lat:view.lat,lon:view.lon,moved:false};if(pointers.size===2){const a=[...pointers.values()];pinchStart={dist:Math.hypot(a[0].x-a[1].x,a[0].y-a[1].y),span:view.span}}});c.addEventListener('pointermove',e=>{if(!pointers.has(e.pointerId))return;pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});if(pointers.size===2&&pinchStart){const a=[...pointers.values()],d=Math.max(10,Math.hypot(a[0].x-a[1].x,a[0].y-a[1].y));view.span=Math.max(.0005,Math.min(120,pinchStart.span*pinchStart.dist/d));followSelf=false;drawMap();return}if(pointers.size===1&&dragStart){const r=c.getBoundingClientRect(),dx=e.clientX-dragStart.x,dy=e.clientY-dragStart.y,k=r.height/view.span,cl=Math.max(.18,Math.cos(dragStart.lat*Math.PI/180));if(Math.abs(dx)+Math.abs(dy)>6)dragStart.moved=true;view.lat=dragStart.lat+dy/k;view.lon=dragStart.lon-dx/(cl*k);followSelf=false;drawMap()}});const finish=e=>{const was=dragStart&&!dragStart.moved&&pointers.size===1;pointers.delete(e.pointerId);if(was){const r=c.getBoundingClientRect(),x=e.clientX-r.left,y=e.clientY-r.top,n=nearestNode(x,y,r.width,r.height);if(n){selected={type:'node',...n};showSelection();drawMap()}else selectMapPoint(unproject(x,y,r.width,r.height))}if(pointers.size<2)pinchStart=null;if(pointers.size===0)dragStart=null};c.addEventListener('pointerup',finish);c.addEventListener('pointercancel',finish)}
async function boot(){const r=await fetch('/status',{cache:'no-store'});if(!r.ok)throw Error('Status '+r.status);info=await r.json();$('nodeName').textContent=info.name||info.title||'JARN-MESH';$('nodeMeta').textContent=[info.short,info.title,info.device].filter(Boolean).join(' · ');$('ssid').textContent=info.ssid||'—';$('systemValue').textContent='WLAN';$('systemSub').textContent=info.ssid||'192.168.4.1';if(info.position&&info.position.mgrs){$('positionValue').textContent=info.position.mgrs;$('positionSub').textContent='Eigener Standort'}$('networkValue').textContent=(info.online??0)+' online';$('networkSub').textContent=(info.nodes??0)+' bekannt'}
async function analyse(){setStatus('logStatus','Log wird geladen …');const r=await fetch('/log',{cache:'no-store'});if(!r.ok){setStatus('logStatus','Logdownload fehlgeschlagen.','err');return}const t=await r.text(),lines=t.split(/\r?\n/),count=x=>lines.filter(l=>l.includes(x)).length,last=[...lines].reverse().find(l=>l.includes(' | '))||'–';const values=[['Zeilen',lines.filter(Boolean).length],['Warnungen',count('WARN')+count('REJECT')],['Fehler/Resets',count('ERROR')+count('PANIC')+count('BROWNOUT')],['BLE-Verbindungen',count('BLE_CONNECT')],['Positions-TX',count('POSITION_TX')+count('PHONE_POS_TX')],['Loggröße',Math.round(new Blob([t]).size/1024)+' KB']];$('metrics').innerHTML=values.map(v=>'<div class="metric"><span>'+esc(v[0])+'</span><b>'+esc(v[1])+'</b></div>').join('')+'<div class="metric" style="grid-column:1/-1"><span>Letztes Ereignis</span><b style="font-size:13px">'+esc(last)+'</b></div>';$('metrics').classList.remove('hide');$('raw').textContent=t;$('raw').classList.remove('hide');setStatus('logStatus','Log vollständig geladen.','ok')}
async function latest(){const r=await fetch(API+info.tag,{headers:{Accept:'application/vnd.github+json'},cache:'no-store'});if(!r.ok)throw Error('GitHub antwortet mit '+r.status);const release=await r.json();asset=release.assets.find(a=>a.name===info.asset);if(!asset||!asset.digest?.startsWith('sha256:'))throw Error('Passende geprüfte Firmware fehlt im Release');return asset}
function resetProgress(){const p=$('progress');p.value=0;p.classList.add('hide')}
async function githubUpdate(){try{setStatus('fwStatus','GitHub-Release wird über die Internetverbindung des Telefons geprüft …');const a=await latest();$('downloadLink').href=a.browser_download_url;setStatus('fwStatus','Firmware wird direkt über das Telefon aus GitHub geladen …');const r=await fetch(a.browser_download_url,{cache:'no-store'});if(!r.ok)throw Error('Download '+r.status);await upload(await r.blob(),a)}catch(e){resetProgress();$('fallback').classList.remove('hide');setStatus('fwStatus','Direkte Internetverbindung nicht verfügbar: '+e.message,'err')}}
async function uploadSelected(){try{const f=$('file').files[0];if(!f)throw Error('Bitte zuerst die .bin-Datei auswählen');await upload(f,asset||await latest())}catch(e){resetProgress();setStatus('fwStatus',e.message,'err')}}
async function upload(blob,a){if(blob.size!==a.size)throw Error('Dateigröße passt nicht zum GitHub-Release');const expected=a.digest.slice(7).toLowerCase();if(!/^[0-9a-f]{64}$/.test(expected))throw Error('GitHub liefert keine gültige SHA-256-Prüfsumme');if(!confirm('Firmware für '+info.title+' installieren? Der Node startet danach neu.'))return;const p=$('progress');p.classList.remove('hide');p.value=0;setStatus('fwStatus','Firmware wird vom Telefon zum Node übertragen und dort geprüft …');await new Promise((resolve,reject)=>{const x=new XMLHttpRequest();x.open('POST','/update');x.setRequestHeader('Content-Type','application/octet-stream');x.setRequestHeader('X-Jarnsen-Token',info.token);x.setRequestHeader('X-Jarnsen-Device',info.device);x.setRequestHeader('X-Jarnsen-Sha256',expected);x.upload.onprogress=e=>{if(e.lengthComputable)p.value=Math.round(e.loaded*100/e.total)};x.onload=()=>x.status===200?resolve():reject(Error(x.responseText||'Update fehlgeschlagen'));x.onerror=()=>reject(Error('WLAN-Verbindung zum Node unterbrochen'));x.send(blob)});p.value=100;setStatus('fwStatus','Update geprüft. Node startet neu.','ok')}
$('positionTile').addEventListener('click',()=>{$('mapCard').scrollIntoView({behavior:'smooth'})});$('networkTile').addEventListener('click',()=>{$('mapCard').scrollIntoView({behavior:'smooth'})});$('radioTile').addEventListener('click',()=>{$('connectionCard').scrollIntoView({behavior:'smooth'})});$('systemTile').addEventListener('click',()=>{$('connectionCard').scrollIntoView({behavior:'smooth'})});$('streetMapBtn').addEventListener('click',()=>setBasemap('streets'));$('satelliteMapBtn').addEventListener('click',()=>setBasemap('satellite'));$('hybridMapBtn').addEventListener('click',()=>setBasemap('hybrid'));$('centerBtn').addEventListener('click',centerSelf);$('zoomIn').addEventListener('click',()=>zoom(.65));$('zoomOut').addEventListener('click',()=>zoom(1.55));$('nodesBtn').addEventListener('click',()=>{showNodes=!showNodes;$('nodesBtn').classList.toggle('active',showNodes);drawMap()});$('trackBtn').addEventListener('click',()=>{showTrack=!showTrack;$('trackBtn').classList.toggle('active',showTrack);drawMap()});$('compassBtn').addEventListener('click',enableCompass);$('navigateBtn').addEventListener('click',toggleNavigation);$('closeSelection').addEventListener('click',()=>{selected=null;$('selectionSheet').classList.remove('visible');drawMap()});$('analyseBtn').addEventListener('click',analyse);$('githubBtn').addEventListener('click',githubUpdate);$('uploadBtn').addEventListener('click',uploadSelected);window.addEventListener('resize',drawMap);window.addEventListener('online',()=>{tileFailureStreak=0;setOnlineMapState('checking');drawMap()});setupMapInput();
boot().then(()=>Promise.all([loadSituation(),loadTrack()])).then(()=>{if(selfPos)centerSelf();else fitAll()}).catch(e=>setStatus('mapStatus','Service nicht erreichbar: '+e.message,'err'));setInterval(loadSituation,10000);
</script>
</body></html>)JARN";

bool startDiagExport()
{
#if defined(_VARIANT_HELTEC_V3)
    return heltecV3DiagStartBleExport();
#else
    return trackerDiagStartBleExport();
#endif
}

size_t readDiagExport(uint8_t *buffer, size_t capacity)
{
#if defined(_VARIANT_HELTEC_V3)
    return heltecV3DiagReadBleExport(buffer, capacity);
#else
    return trackerDiagReadBleExport(buffer, capacity);
#endif
}

void cancelDiagExport()
{
#if defined(_VARIANT_HELTEC_V3)
    heltecV3DiagCancelBleExport();
#else
    trackerDiagCancelBleExport();
#endif
}

void logEvent(const char *event, const char *detail)
{
#if defined(_VARIANT_HELTEC_V3)
    heltecV3DiagLog(event, "%s", detail);
#else
    trackerDiagLog(event, "%s", detail);
#endif
}

bool readLine(WiFiClient &client, char *out, size_t capacity, size_t &totalBytes)
{
    if (!out || capacity < 2)
        return false;
    size_t used = 0;
    const uint32_t startedMs = millis() ? millis() : 1;
    while (Throttle::isWithinTimespanMs(startedMs, CLIENT_TIMEOUT_MS)) {
        while (client.available()) {
            const int value = client.read();
            if (value < 0)
                break;
            totalBytes++;
            if (totalBytes > MAX_HEADER_BYTES)
                return false;
            if (value == '\n') {
                if (used && out[used - 1] == '\r')
                    used--;
                out[used] = 0;
                return true;
            }
            if (used + 1 < capacity)
                out[used++] = (char)value;
        }
        if (!client.connected())
            return false;
        delay(1);
    }
    return false;
}

void sendStatus(WiFiClient &client, int code, const char *status, const char *type, const char *extra = nullptr)
{
    client.printf("HTTP/1.1 %d %s\r\nContent-Type: %s\r\nCache-Control: no-store\r\nConnection: close\r\n", code, status, type);
    if (extra)
        client.print(extra);
    client.print("\r\n");
}

void sendJsonString(WiFiClient &client, const char *text)
{
    client.print('"');
    if (text) {
        for (const unsigned char *p = reinterpret_cast<const unsigned char *>(text); *p; ++p) {
            switch (*p) {
            case '"': client.print("\\\""); break;
            case '\\': client.print("\\\\"); break;
            case '\n': client.print("\\n"); break;
            case '\r': client.print("\\r"); break;
            case '\t': client.print("\\t"); break;
            default:
                if (*p >= 0x20)
                    client.write(*p);
                break;
            }
        }
    }
    client.print('"');
}

void sendPage(WiFiClient &client)
{
    sendStatus(client, 200, "OK", "text/html; charset=utf-8");
    client.print(PAGE);
}

bool copySelfPosition(meshtastic_PositionLite &position)
{
    return nodeDB && nodeDB->copyNodePosition(nodeDB->getNodeNum(), position) &&
           (position.latitude_i != 0 || position.longitude_i != 0);
}

void sendJsonStatus(WiFiClient &client)
{
    sendStatus(client, 200, "OK", "application/json; charset=utf-8");
    const meshtastic_NodeInfoLite *self = nodeDB ? nodeDB->getMeshNode(nodeDB->getNodeNum()) : nullptr;
    const char *longName = self && self->long_name[0] ? self->long_name : DEVICE_TITLE;
    const char *shortName = self && self->short_name[0] ? self->short_name : "JARN";
    meshtastic_PositionLite position{};
    const bool hasPosition = copySelfPosition(position);
    char mgrs[28] = "---";
    if (hasPosition)
        jarnsenPositionTrackFormatMgrs8(position.latitude_i, position.longitude_i, mgrs, sizeof(mgrs));

    client.print("{\"title\":");
    sendJsonString(client, DEVICE_TITLE);
    client.print(",\"device\":");
    sendJsonString(client, DEVICE_CODE);
    client.print(",\"name\":");
    sendJsonString(client, longName);
    client.print(",\"short\":");
    sendJsonString(client, shortName);
    client.print(",\"ssid\":");
    sendJsonString(client, serviceSsid);
    client.print(",\"token\":");
    sendJsonString(client, sessionToken);
    client.print(",\"tag\":");
    sendJsonString(client, GITHUB_TAG);
    client.print(",\"asset\":");
    sendJsonString(client, FIRMWARE_ASSET);
    client.printf(",\"track_count\":%u,\"nodes\":%u,\"online\":%u", (unsigned)jarnsenPositionTrackCount(),
                  nodeDB ? (unsigned)nodeDB->getNumMeshNodes() : 0U, nodeDB ? (unsigned)nodeDB->getNumOnlineMeshNodes(true) : 0U);
    if (hasPosition) {
        client.printf(",\"position\":{\"lat\":%.7f,\"lon\":%.7f,\"mgrs\":", position.latitude_i * 1e-7,
                      position.longitude_i * 1e-7);
        sendJsonString(client, mgrs);
        client.print("}");
    } else {
        client.print(",\"position\":null");
    }
    client.print("}");
}

void sendNodeJson(WiFiClient &client, const meshtastic_NodeInfoLite &node, const meshtastic_PositionLite &position)
{
    char id[16] = {};
    snprintf(id, sizeof(id), "!%08x", (unsigned)node.num);
    char mgrs[28] = "---";
    jarnsenPositionTrackFormatMgrs8(position.latitude_i, position.longitude_i, mgrs, sizeof(mgrs));
    const char *longName = node.long_name[0] ? node.long_name : id;
    const char *shortName = node.short_name[0] ? node.short_name : id;

    client.print("{\"id\":");
    sendJsonString(client, id);
    client.print(",\"name\":");
    sendJsonString(client, longName);
    client.print(",\"short\":");
    sendJsonString(client, shortName);
    client.printf(",\"lat\":%.7f,\"lon\":%.7f,\"last_heard\":%u,\"time\":%u,\"snr\":%.2f,\"hops\":%u,\"via_mqtt\":%s,\"mgrs\":",
                  position.latitude_i * 1e-7, position.longitude_i * 1e-7, (unsigned)node.last_heard, (unsigned)position.time,
                  (double)node.snr, (unsigned)node.hops_away, nodeInfoLiteViaMqtt(&node) ? "true" : "false");
    sendJsonString(client, mgrs);
    client.print("}");
}

void sendNodesJson(WiFiClient &client)
{
    sendStatus(client, 200, "OK", "application/json; charset=utf-8");
    if (!nodeDB) {
        client.print("{\"self\":null,\"nodes\":[],\"total\":0,\"online\":0}");
        return;
    }

    const NodeNum selfNum = nodeDB->getNodeNum();
    meshtastic_PositionLite selfPosition{};
    const bool hasSelf = copySelfPosition(selfPosition);
    client.print("{\"self\":");
    if (hasSelf) {
        const meshtastic_NodeInfoLite *self = nodeDB->getMeshNode(selfNum);
        if (self) {
            sendNodeJson(client, *self, selfPosition);
        } else {
            char mgrs[28] = "---";
            jarnsenPositionTrackFormatMgrs8(selfPosition.latitude_i, selfPosition.longitude_i, mgrs, sizeof(mgrs));
            client.printf("{\"id\":\"self\",\"name\":\"%s\",\"short\":\"SELF\",\"lat\":%.7f,\"lon\":%.7f,\"last_heard\":0,\"time\":%u,\"snr\":0,\"hops\":0,\"via_mqtt\":false,\"mgrs\":",
                          DEVICE_TITLE, selfPosition.latitude_i * 1e-7, selfPosition.longitude_i * 1e-7, (unsigned)selfPosition.time);
            sendJsonString(client, mgrs);
            client.print("}");
        }
    } else {
        client.print("null");
    }

    client.print(",\"nodes\":[");
    bool first = true;
    uint32_t readIndex = 0;
    const meshtastic_NodeInfoLite *node = nodeDB->readNextMeshNode(readIndex);
    while (node) {
        if (node->num != selfNum) {
            meshtastic_PositionLite position{};
            if (nodeDB->copyNodePosition(node->num, position) && (position.latitude_i != 0 || position.longitude_i != 0)) {
                if (!first)
                    client.print(',');
                sendNodeJson(client, *node, position);
                first = false;
            }
        }
        node = nodeDB->readNextMeshNode(readIndex);
        yield();
    }
    client.printf("],\"total\":%u,\"online\":%u}", (unsigned)nodeDB->getNumMeshNodes(),
                  (unsigned)nodeDB->getNumOnlineMeshNodes(true));
}

void sendMgrs(WiFiClient &client, const char *path)
{
    double latitude = 0.0;
    double longitude = 0.0;
    if (!path || sscanf(path, "/mgrs?lat=%lf&lon=%lf", &latitude, &longitude) != 2 || latitude < -90.0 || latitude > 90.0 ||
        longitude < -180.0 || longitude > 180.0) {
        sendStatus(client, 400, "Bad Request", "application/json; charset=utf-8");
        client.print("{\"error\":\"invalid_coordinate\"}");
        return;
    }
    const int32_t latitudeI = (int32_t)llround(latitude * 1e7);
    const int32_t longitudeI = (int32_t)llround(longitude * 1e7);
    char mgrs[28] = "---";
    if (!jarnsenPositionTrackFormatMgrs8(latitudeI, longitudeI, mgrs, sizeof(mgrs))) {
        sendStatus(client, 422, "Unprocessable Entity", "application/json; charset=utf-8");
        client.print("{\"error\":\"mgrs_unavailable\"}");
        return;
    }
    sendStatus(client, 200, "OK", "application/json; charset=utf-8");
    client.printf("{\"lat\":%.7f,\"lon\":%.7f,\"mgrs\":", latitude, longitude);
    sendJsonString(client, mgrs);
    client.print("}");
}

bool writeChunk(WiFiClient &client, const uint8_t *data, size_t length)
{
    client.printf("%x\r\n", (unsigned)length);
    if (client.write(data, length) != length)
        return false;
    return client.print("\r\n") == 2;
}

void sendLog(WiFiClient &client)
{
    if (!startDiagExport()) {
        sendStatus(client, 409, "Conflict", "text/plain; charset=utf-8");
        client.print("Logexport ist bereits belegt.");
        return;
    }
    sendStatus(client, 200, "OK", "text/plain; charset=utf-8",
               "Content-Disposition: attachment; filename=Jarnsen-Diagnoselog.txt\r\nTransfer-Encoding: chunked\r\n");
    uint8_t buffer[1024];
    bool ok = true;
    while (client.connected()) {
        const size_t count = readDiagExport(buffer, sizeof(buffer));
        if (count == 0)
            break;
        if (!writeChunk(client, buffer, count)) {
            ok = false;
            break;
        }
        lastActivityMs = millis() ? millis() : 1;
        yield();
    }
    if (ok)
        client.print("0\r\n\r\n");
    else
        cancelDiagExport();
}

bool writeTextChunk(WiFiClient &client, const char *text)
{
    return writeChunk(client, (const uint8_t *)text, strlen(text));
}

void sendTrack(WiFiClient &client)
{
    if (!jarnsenPositionTrackStartExport()) {
        sendStatus(client, 409, "Conflict", "text/plain; charset=utf-8");
        client.print("Positionsexport ist bereits belegt.");
        return;
    }

    sendStatus(client, 200, "OK", "application/geo+json; charset=utf-8",
               "Content-Disposition: attachment; filename=Jarnsen-Positionsverlauf.geojson\r\nTransfer-Encoding: chunked\r\n");
    bool ok = writeTextChunk(client, "{\"type\":\"FeatureCollection\",\"features\":[");
    bool first = true;
    JarnsenTrackPoint point;
    while (ok && client.connected() && jarnsenPositionTrackReadExport(point)) {
        char mgrs[28] = "---";
        jarnsenPositionTrackFormatMgrs8(point.latitudeI, point.longitudeI, mgrs, sizeof(mgrs));
        char feature[384] = {};
        snprintf(feature, sizeof(feature),
                 "%s{\"type\":\"Feature\",\"geometry\":{\"type\":\"Point\",\"coordinates\":[%.7f,%.7f]},"
                 "\"properties\":{\"epoch\":%u,\"mgrs\":\"%s\",\"source\":\"%s\",\"accuracy\":%u}}",
                 first ? "" : ",", point.longitudeI * 1e-7, point.latitudeI * 1e-7, (unsigned)point.epoch, mgrs,
                 jarnsenPositionTrackSourceName(point.source), (unsigned)point.accuracyMm);
        ok = writeTextChunk(client, feature);
        first = false;
        lastActivityMs = millis() ? millis() : 1;
        yield();
    }
    jarnsenPositionTrackEndExport();
    if (ok && client.connected()) {
        ok = writeTextChunk(client, "]}");
        if (ok)
            client.print("0\r\n\r\n");
    }
}

void clearTrack(WiFiClient &client, const char *token)
{
    if (strcmp(token, sessionToken) != 0) {
        sendStatus(client, 403, "Forbidden", "text/plain; charset=utf-8");
        client.print("Ungültige Servicesitzung.");
        return;
    }
    jarnsenPositionTrackClear();
    logEvent("TRACK_CLEAR", "positions=0");
    sendStatus(client, 200, "OK", "application/json; charset=utf-8");
    client.print("{\"ok\":true,\"track_count\":0}");
}

bool validHexHash(const char *hash)
{
    if (!hash || strlen(hash) != 64)
        return false;
    for (size_t i = 0; i < 64; i++)
        if (!std::isxdigit((unsigned char)hash[i]))
            return false;
    return true;
}

uint8_t hexNibble(char value)
{
    if (value >= '0' && value <= '9')
        return (uint8_t)(value - '0');
    value = (char)std::tolower((unsigned char)value);
    return (uint8_t)(value - 'a' + 10);
}

void hashFromText(const char *text, uint8_t hash[32])
{
    for (size_t i = 0; i < 32; i++)
        hash[i] = (uint8_t)((hexNibble(text[i * 2]) << 4U) | hexNibble(text[i * 2 + 1]));
}

void sendUpdateError(WiFiClient &client, int code, const char *message)
{
    Update.abort();
    updateInProgress = false;
    sendStatus(client, code, "Update Error", "text/plain; charset=utf-8");
    client.print(message);
    logEvent("WLAN_OTA_FAIL", message);
}

void receiveUpdate(WiFiClient &client, size_t contentLength, const char *device, const char *hashText, const char *token)
{
    if (updateInProgress) {
        sendStatus(client, 409, "Conflict", "text/plain; charset=utf-8");
        client.print("Ein Update läuft bereits.");
        return;
    }
    if (strcmp(device, DEVICE_CODE) != 0 || strcmp(token, sessionToken) != 0 || !validHexHash(hashText) ||
        contentLength < MIN_FIRMWARE_BYTES || contentLength > MAX_FIRMWARE_BYTES) {
        sendStatus(client, 400, "Bad Request", "text/plain; charset=utf-8");
        client.print("Gerätetyp, Sitzung, Größe oder SHA-256 ist ungültig.");
        return;
    }

    updateInProgress = true;
    if (!Update.begin(contentLength, U_FLASH)) {
        sendUpdateError(client, 500, "Inaktive Firmwarepartition kann nicht vorbereitet werden.");
        return;
    }

    uint8_t expectedHash[32];
    uint8_t actualHash[32];
    hashFromText(hashText, expectedHash);
    mbedtls_sha256_context sha;
    mbedtls_sha256_init(&sha);
    mbedtls_sha256_starts(&sha, 0);

    uint8_t buffer[2048];
    size_t received = 0;
    uint32_t progressMs = millis() ? millis() : 1;
    bool validHeader = true;
    while (received < contentLength && client.connected()) {
        const size_t available = client.available();
        if (available == 0) {
            if (!Throttle::isWithinTimespanMs(progressMs, CLIENT_TIMEOUT_MS))
                break;
            delay(1);
            continue;
        }
        const size_t want = std::min(sizeof(buffer), std::min(available, contentLength - received));
        const size_t count = client.readBytes(buffer, want);
        if (count == 0)
            continue;
        if (received == 0 && buffer[0] != 0xe9)
            validHeader = false;
        if (!validHeader || Update.write(buffer, count) != count) {
            mbedtls_sha256_free(&sha);
            sendUpdateError(client, 500, validHeader ? "Firmware konnte nicht geschrieben werden." : "Keine gültige ESP32-Firmware.");
            return;
        }
        mbedtls_sha256_update(&sha, buffer, count);
        received += count;
        progressMs = millis() ? millis() : 1;
        lastActivityMs = progressMs;
        yield();
    }
    mbedtls_sha256_finish(&sha, actualHash);
    mbedtls_sha256_free(&sha);

    if (received != contentLength) {
        sendUpdateError(client, 408, "Firmwareübertragung wurde unterbrochen.");
        return;
    }
    if (memcmp(expectedHash, actualHash, sizeof(expectedHash)) != 0) {
        sendUpdateError(client, 422, "SHA-256 stimmt nicht mit dem GitHub-Release überein.");
        return;
    }
    if (!Update.end(false)) {
        sendUpdateError(client, 500, "Firmwareprüfung oder Aktivierung fehlgeschlagen.");
        return;
    }

    updateInProgress = false;
    sendStatus(client, 200, "OK", "application/json; charset=utf-8");
    client.print("{\"ok\":true,\"restart\":true}");
    logEvent("WLAN_OTA_OK", hashText);
    restartRequestedMs = millis() ? millis() : 1;
}

void handleClient(WiFiClient &client)
{
    size_t headerBytes = 0;
    char line[512] = {};
    if (!readLine(client, line, sizeof(line), headerBytes))
        return;
    char method[8] = {};
    char path[160] = {};
    if (sscanf(line, "%7s %159s", method, path) != 2)
        return;

    size_t contentLength = 0;
    char device[40] = {};
    char hash[65] = {};
    char token[32] = {};
    while (readLine(client, line, sizeof(line), headerBytes) && line[0]) {
        char *value = strchr(line, ':');
        if (!value)
            continue;
        *value++ = 0;
        while (*value == ' ')
            value++;
        if (strcasecmp(line, "Content-Length") == 0)
            contentLength = strtoul(value, nullptr, 10);
        else if (strcasecmp(line, "X-Jarnsen-Device") == 0)
            strlcpy(device, value, sizeof(device));
        else if (strcasecmp(line, "X-Jarnsen-Sha256") == 0)
            strlcpy(hash, value, sizeof(hash));
        else if (strcasecmp(line, "X-Jarnsen-Token") == 0)
            strlcpy(token, value, sizeof(token));
    }

    lastActivityMs = millis() ? millis() : 1;
    if (strcmp(method, "GET") == 0 && strcmp(path, "/status") == 0)
        sendJsonStatus(client);
    else if (strcmp(method, "GET") == 0 && strcmp(path, "/nodes.json") == 0)
        sendNodesJson(client);
    else if (strcmp(method, "GET") == 0 && strncmp(path, "/mgrs?", 6) == 0)
        sendMgrs(client, path);
    else if (strcmp(method, "GET") == 0 && strcmp(path, "/log") == 0)
        sendLog(client);
    else if (strcmp(method, "GET") == 0 && strcmp(path, "/track.geojson") == 0)
        sendTrack(client);
    else if (strcmp(method, "POST") == 0 && strcmp(path, "/track/clear") == 0)
        clearTrack(client, token);
    else if (strcmp(method, "POST") == 0 && strcmp(path, "/update") == 0)
        receiveUpdate(client, contentLength, device, hash, token);
    else if (strcmp(method, "GET") == 0)
        sendPage(client);
    else {
        sendStatus(client, 404, "Not Found", "text/plain; charset=utf-8");
        client.print("Nicht gefunden.");
    }
}

bool softApReady()
{
    const wifi_mode_t mode = WiFi.getMode();
    return (mode == WIFI_AP || mode == WIFI_AP_STA) && WiFi.softAPIP() == IPAddress(192, 168, 4, 1);
}

bool waitForSoftAp()
{
    const uint32_t startedMs = millis() ? millis() : 1;
    do {
        if (softApReady())
            return true;
        delay(20);
    } while (Throttle::isWithinTimespanMs(startedMs, 2000UL));
    return softApReady();
}

bool startSoftApAttempt(uint8_t attempt)
{
    WiFi.softAPdisconnect(false);
    if (!hadStation) {
        WiFi.disconnect(true, false);
        WiFi.mode(WIFI_OFF);
        delay(100);
    }

    const wifi_mode_t wantedMode = hadStation ? WIFI_AP_STA : WIFI_AP;
    const bool modeOk = WiFi.mode(wantedMode);
    delay(120);
    WiFi.setSleep(false);
    const esp_err_t powerSaveResult = esp_wifi_set_ps(WIFI_PS_NONE);
    const bool configOk = WiFi.softAPConfig(IPAddress(192, 168, 4, 1), IPAddress(192, 168, 4, 1), IPAddress(255, 255, 255, 0));
    const bool startOk = configOk && WiFi.softAP(serviceSsid, SERVICE_PASSWORD, 6, 0, 4);
    const bool ready = modeOk && startOk && waitForSoftAp();
    if (!ready) {
        snprintf(serviceError, sizeof(serviceError), "Versuch %u: mode=%u cfg=%u ap=%u ip=%s ps=%d", (unsigned)attempt,
                 modeOk ? 1U : 0U, configOk ? 1U : 0U, startOk ? 1U : 0U, WiFi.softAPIP().toString().c_str(),
                 (int)powerSaveResult);
        logEvent("WLAN_AP_RETRY", serviceError);
        LOG_WARN("Jarnsen WLAN AP start failed: %s", serviceError);
    }
    return ready;
}
} // namespace

bool jarnsenServiceWebStart()
{
    if (serviceActive)
        return true;

    uint8_t mac[6] = {};
    esp_read_mac(mac, ESP_MAC_WIFI_SOFTAP);
    snprintf(serviceSsid, sizeof(serviceSsid), "%s-%02X%02X", SSID_PREFIX, mac[4], mac[5]);
    const uint64_t randomToken = ((uint64_t)esp_random() << 32U) | esp_random();
    snprintf(sessionToken, sizeof(sessionToken), "%08x%08x", (unsigned)(randomToken >> 32U), (unsigned)randomToken);

    hadStation = WiFi.status() == WL_CONNECTED;
    WiFi.persistent(false);
    serviceError[0] = 0;
    bool started = false;
    for (uint8_t attempt = 1; attempt <= 3 && !started; attempt++)
        started = startSoftApAttempt(attempt);
    if (!started) {
        WiFi.softAPdisconnect(false);
        WiFi.mode(hadStation ? WIFI_STA : WIFI_OFF);
        if (!serviceError[0])
            snprintf(serviceError, sizeof(serviceError), "Access Point konnte nicht initialisiert werden");
        logEvent("WLAN_SERVICE_FAIL", serviceError);
        return false;
    }

    dnsServer.start(53, "*", IPAddress(192, 168, 4, 1));
    httpServer.begin();
    httpServer.setNoDelay(true);
    serviceActive = true;
    lastActivityMs = millis() ? millis() : 1;
    restartRequestedMs = 0;
    serviceError[0] = 0;
    char detail[96] = {};
    snprintf(detail, sizeof(detail), "ssid=%s ip=%s idle=600s", serviceSsid, SERVICE_ADDRESS);
    logEvent("WLAN_SERVICE", detail);
    LOG_INFO("Jarnsen WLAN service started: SSID=%s IP=%s", serviceSsid, SERVICE_ADDRESS);
    return true;
}

void jarnsenServiceWebStop()
{
    if (!serviceActive || updateInProgress)
        return;
    dnsServer.stop();
    httpServer.end();
    WiFi.softAPdisconnect(false);
    WiFi.mode(hadStation ? WIFI_STA : WIFI_OFF);
    serviceActive = false;
    restartRequestedMs = 0;
    logEvent("WLAN_SERVICE", "stopped");
    LOG_INFO("Jarnsen WLAN service stopped");
}

void jarnsenServiceWebPump()
{
    if (!serviceActive)
        return;
    if (restartRequestedMs != 0 && !Throttle::isWithinTimespanMs(restartRequestedMs, 1500UL)) {
        delay(50);
        ESP.restart();
    }
    dnsServer.processNextRequest();
    WiFiClient client = httpServer.available();
    if (client) {
        handleClient(client);
        client.flush();
        client.stop();
    }
    if (!updateInProgress && !Throttle::isWithinTimespanMs(lastActivityMs, IDLE_TIMEOUT_MS))
        jarnsenServiceWebStop();
}

bool jarnsenServiceWebActive()
{
    return serviceActive;
}

const char *jarnsenServiceWebSsid()
{
    return serviceSsid[0] ? serviceSsid : SSID_PREFIX;
}

const char *jarnsenServiceWebPassword()
{
    return SERVICE_PASSWORD;
}

const char *jarnsenServiceWebAddress()
{
    return SERVICE_ADDRESS;
}

const char *jarnsenServiceWebLastError()
{
    return serviceError;
}

#endif
