"""Improve the Tracker local service WLAN UX without touching role/power logic.

This patch runs after the existing Tracker service-upgrade and phone-Internet
patches. It adds a long-name AP SSID and enhances only the browser-side map UX.
"""
from pathlib import Path

WEB = Path("src/mesh/http/JarnsenServiceWeb.cpp")
PORTAL = Path("src/mesh/http/JarnsenTrackerServicePortalPage.h")


def once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    if source.count(old) != 1:
        raise SystemExit(f"{label} anchor not found exactly once")
    return source.replace(old, new, 1)


web = WEB.read_text(encoding="utf-8")
portal = PORTAL.read_text(encoding="utf-8")

# AP name: Jarnsen-<Meshtastic long name>, constrained to the 32-byte SSID limit.
ssid_anchor = "bool softApReady()\n{\n"
ssid_helper = r'''void buildTrackerServiceSsid()
{
    constexpr size_t WIFI_SSID_LIMIT = 32U;
    strlcpy(serviceSsid, "Jarnsen-", sizeof(serviceSsid));
    bool lastDash = true;
    const unsigned char *p = (const unsigned char *)owner.long_name;
    while (p && *p && strlen(serviceSsid) < WIFI_SSID_LIMIT) {
        const unsigned char c = *p++;
        if (std::isalnum(c)) {
            const size_t len = strlen(serviceSsid);
            serviceSsid[len] = (char)c;
            serviceSsid[len + 1] = 0;
            lastDash = false;
        } else if (!lastDash) {
            const size_t len = strlen(serviceSsid);
            if (len < WIFI_SSID_LIMIT) {
                serviceSsid[len] = '-';
                serviceSsid[len + 1] = 0;
                lastDash = true;
            }
        }
    }
    size_t len = strlen(serviceSsid);
    while (len > 8U && serviceSsid[len - 1] == '-')
        serviceSsid[--len] = 0;
    if (len <= 8U) {
        uint8_t mac[6] = {};
        esp_read_mac(mac, ESP_MAC_WIFI_SOFTAP);
        snprintf(serviceSsid, sizeof(serviceSsid), "Jarnsen-Tracker-%02X%02X", mac[4], mac[5]);
    }
}

bool softApReady()
{
'''
web = once(web, ssid_anchor, ssid_helper, "Tracker long-name SSID helper")
web = once(
    web,
    '''    uint8_t mac[6] = {};
    esp_read_mac(mac, ESP_MAC_WIFI_SOFTAP);
    snprintf(serviceSsid, sizeof(serviceSsid), "%s-%02X%02X", SSID_PREFIX, mac[4], mac[5]);
''',
    "    buildTrackerServiceSsid();\n",
    "Tracker long-name SSID start",
)

# Compact controls above the existing canvas. The MGRS grid is enabled by default.
portal = once(
    portal,
    ".hide{display:none}.dangerzone{",
    ".hide{display:none}.switch{display:inline-flex;align-items:center;gap:7px;padding:8px 10px;border:1px solid var(--line);border-radius:10px}.switch input{width:18px;height:18px}.dangerzone{",
    "Tracker map switch CSS",
)
portal = once(
    portal,
    '''<section class="card" id="map"><h2>Positionskarte</h2><div class="mapmodes"><button data-map="osm" onclick="setMapMode('osm')">OSM</button><button data-map="topo" onclick="setMapMode('topo')">Topo</button><button data-map="sat" onclick="setMapMode('sat')">Satellit</button><button data-map="hybrid" onclick="setMapMode('hybrid')">Hybrid</button><button data-map="offline" onclick="setMapMode('offline')">Offline</button></div>
''',
    '''<section class="card" id="map"><h2>Positionskarte</h2><div class="mapmodes"><button data-map="osm" onclick="setMapMode('osm')">OSM</button><button data-map="topo" onclick="setMapMode('topo')">Topo</button><button data-map="sat" onclick="setMapMode('sat')">Satellit</button><button data-map="hybrid" onclick="setMapMode('hybrid')">Hybrid</button><button data-map="offline" onclick="setMapMode('offline')">Offline</button><label class="switch"><input id="mgrsGrid" type="checkbox" onchange="toggleMgrs()">MGRS-Gitter</label><button id="phoneBtn" class="secondary" onclick="enablePhoneLocation()">Handyposition</button></div>
''',
    "Tracker map controls",
)
portal = once(
    portal,
    '<div class="mapbox"><canvas id="trackMap"></canvas><div class="mapbadge" id="mapBadge">Offline</div></div><div class="attrib" id="attrib"></div><div class="pointinfo" id="pointInfo">Punkte werden geladen …</div><div class="actions">',
    '<div class="mapbox"><canvas id="trackMap"></canvas><div class="mapbadge" id="mapBadge">Offline</div></div><div class="attrib" id="attrib"></div><div class="pointinfo" id="pointInfo">Karte antippen: MGRS-Koordinate des Kartenpunkts anzeigen.</div><div id="phoneStatus" class="status">Handyposition aus.</div><div class="actions">',
    "Tracker point/phone status",
)

# The original map functions remain as the fallback. This block is inserted just
# before boot() and deliberately overrides only drawOverlay/setMapMode plus map
# input handling, so the existing track/filter/tile logic stays unchanged.
interactive_js = r'''
// ----- Jarnsen Tracker interactive MGRS map -----
let jtrkMgrsOn=localStorage.getItem('jtrk-mgrs')!=='0',jtrkSelected=null,jtrkPhone=null,jtrkHeading=null,jtrkPhoneWatch=null,jtrkCompassSeen=false,jtrkOrientationRegistered=false,jtrkPointers=new Map(),jtrkDrag=null,jtrkPinch=null,jtrkSuppressTapUntil=0;
function jtrkFromScreen(x,y,w,h){const c=world(view.lon,view.lat,view.z);return unworld(c.x+x-w/2,c.y+y-h/2,view.z)}
function jtrkZone(lat,lon){let z=Math.max(1,Math.min(60,Math.floor((lon+180)/6)+1));if(lat>=56&&lat<64&&lon>=3&&lon<12)z=32;if(lat>=72&&lat<84){if(lon>=0&&lon<9)z=31;else if(lon<21)z=33;else if(lon<33)z=35;else if(lon<42)z=37}return z}
function jtrkBand(lat){const b='CDEFGHJKLMNPQRSTUVWX';if(lat<-80||lat>84)return'?';return b[Math.max(0,Math.min(19,Math.floor((lat+80)/8)))]}
function jtrkUtmF(lat,lon,forceZone){const a=6378137,e2=.00669438,k=.9996,rad=Math.PI/180,z=forceZone||jtrkZone(lat,lon),lo=((z-1)*6-180+3)*rad,la=lat*rad,lr=lon*rad,ep=e2/(1-e2),s=Math.sin(la),c=Math.cos(la),t=Math.tan(la),N=a/Math.sqrt(1-e2*s*s),T=t*t,C=ep*c*c,A=c*(lr-lo),M=a*((1-e2/4-3*e2*e2/64-5*e2**3/256)*la-(3*e2/8+3*e2*e2/32+45*e2**3/1024)*Math.sin(2*la)+(15*e2*e2/256+45*e2**3/1024)*Math.sin(4*la)-(35*e2**3/3072)*Math.sin(6*la));let E=k*N*(A+(1-T+C)*A**3/6+(5-18*T+T*T+72*C-58*ep)*A**5/120)+500000,Nt=k*(M+N*t*(A*A/2+(5-T+9*C+4*C*C)*A**4/24+(61-58*T+T*T+600*C-330*ep)*A**6/720));if(lat<0)Nt+=1e7;return{zone:z,north:lat>=0,e:E,n:Nt,band:jtrkBand(lat)}}
function jtrkUtmI(zone,north,E,Nt){const a=6378137,e2=.00669438,k=.9996,ep=e2/(1-e2),x=E-500000;let y=Nt;if(!north)y-=1e7;const M=y/k,mu=M/(a*(1-e2/4-3*e2*e2/64-5*e2**3/256)),e1=(1-Math.sqrt(1-e2))/(1+Math.sqrt(1-e2)),p1=mu+(3*e1/2-27*e1**3/32)*Math.sin(2*mu)+(21*e1*e1/16-55*e1**4/32)*Math.sin(4*mu)+(151*e1**3/96)*Math.sin(6*mu)+(1097*e1**4/512)*Math.sin(8*mu),s=Math.sin(p1),c=Math.cos(p1),t=Math.tan(p1),N1=a/Math.sqrt(1-e2*s*s),R1=a*(1-e2)/Math.pow(1-e2*s*s,1.5),T1=t*t,C1=ep*c*c,D=x/(N1*k),lat=p1-(N1*t/R1)*(D*D/2-(5+3*T1+10*C1-4*C1*C1-9*ep)*D**4/24+(61+90*T1+298*C1+45*T1*T1-252*ep-3*C1*C1)*D**6/720),lon=((zone-1)*6-180+3)*Math.PI/180+(D-(1+2*T1+C1)*D**3/6+(5-2*C1+28*T1-3*C1*C1+8*ep+24*T1*T1)*D**5/120)/c;return{lat:lat*180/Math.PI,lon:lon*180/Math.PI}}
function jtrkMgrsUtm(u,precision=5){const sets=['ABCDEFGH','JKLMNPQR','STUVWXYZ'],rows='ABCDEFGHJKLMNPQRSTUV',e100=Math.floor(u.e/100000);if(e100<1||e100>8)return'---';const el=sets[(u.zone-1)%3][e100-1],nl=rows[(Math.floor(u.n/100000)%20+(u.zone%2===0?5:0))%20],ep=String((Math.floor(u.e)%100000+100000)%100000).padStart(5,'0').slice(0,precision),np=String((Math.floor(u.n)%100000+100000)%100000).padStart(5,'0').slice(0,precision);return String(u.zone).padStart(2,'0')+u.band+' '+el+nl+(precision?' '+ep+' '+np:'')}
function jtrkMgrs(lat,lon){return jtrkMgrsUtm(jtrkUtmF(lat,lon),5)}
function jtrkGridStep(){return view.z<=8?100000:view.z<=11?10000:view.z<=14?1000:view.z<=16?100:10}
function jtrkGridDigits(v,p){return p?String((Math.floor(v)%100000+100000)%100000).padStart(5,'0').slice(0,p):''}
function jtrkGridStepText(s){return s>=1000?(s/1000)+' km':s+' m'}
function jtrkLabel(ctx,t,x,y,dark){ctx.save();ctx.font='10px system-ui';ctx.textBaseline='top';ctx.lineJoin='round';ctx.strokeStyle=dark?'rgba(0,0,0,.82)':'rgba(255,255,255,.94)';ctx.lineWidth=3;ctx.strokeText(t,x,y);ctx.fillStyle=dark?'#7dd3fc':'#075985';ctx.fillText(t,x,y);ctx.restore()}
function jtrkDrawMgrs(ctx,w,h){if(!jtrkMgrsOn){const b=mapMode==='offline'?'Offline':mapMode.toUpperCase();$('mapBadge').textContent=b;return}const center=jtrkUtmF(view.lat,view.lon),zone=center.zone,north=center.north,corners=[[0,0],[w,0],[0,h],[w,h]].map(q=>jtrkFromScreen(q[0],q[1],w,h)).map(p=>jtrkUtmF(p.lat,p.lon,zone));let minE=Math.min(...corners.map(p=>p.e)),maxE=Math.max(...corners.map(p=>p.e)),minN=Math.min(...corners.map(p=>p.n)),maxN=Math.max(...corners.map(p=>p.n)),step=jtrkGridStep();while((maxE-minE)/step>14||(maxN-minN)/step>14)step*=10;const precision=Math.max(0,Math.min(5,5-Math.round(Math.log10(step)))),dark=matchMedia('(prefers-color-scheme:dark)').matches,gridColor=dark?'rgba(56,189,248,.78)':'rgba(0,119,190,.72)';ctx.save();ctx.strokeStyle=gridColor;ctx.lineWidth=1;for(let e=Math.ceil(minE/step)*step;e<=maxE;e+=step){ctx.beginPath();let first=true,top=null;for(let i=0;i<=14;i++){const n=minN+(maxN-minN)*i/14,p=jtrkUtmI(zone,north,e,n),s=toScreen(p.lat,p.lon,w,h);if(first){ctx.moveTo(s.x,s.y);first=false}else ctx.lineTo(s.x,s.y);if(!top||s.y<top.y)top=s}ctx.stroke();if(top&&precision)jtrkLabel(ctx,jtrkGridDigits(e,precision),Math.max(4,Math.min(w-36,top.x+2)),3,dark)}for(let n=Math.ceil(minN/step)*step;n<=maxN;n+=step){ctx.beginPath();let first=true,left=null;for(let i=0;i<=14;i++){const e=minE+(maxE-minE)*i/14,p=jtrkUtmI(zone,north,e,n),s=toScreen(p.lat,p.lon,w,h);if(first){ctx.moveTo(s.x,s.y);first=false}else ctx.lineTo(s.x,s.y);if(!left||s.x<left.x)left=s}ctx.stroke();if(left&&precision)jtrkLabel(ctx,jtrkGridDigits(n,precision),4,Math.max(16,Math.min(h-14,left.y-5)),dark)}ctx.restore();const b=mapMode==='offline'?'Offline':mapMode.toUpperCase();$('mapBadge').textContent=b+' · MGRS '+jtrkMgrsUtm(center,0)+' · '+jtrkGridStepText(step)}
function jtrkDrawSelected(ctx,w,h){if(!jtrkSelected)return;const s=toScreen(jtrkSelected.lat,jtrkSelected.lon,w,h);ctx.save();ctx.strokeStyle='#d63384';ctx.lineWidth=2.5;ctx.beginPath();ctx.arc(s.x,s.y,8,0,Math.PI*2);ctx.stroke();ctx.beginPath();ctx.moveTo(s.x-12,s.y);ctx.lineTo(s.x+12,s.y);ctx.moveTo(s.x,s.y-12);ctx.lineTo(s.x,s.y+12);ctx.stroke();ctx.restore()}
function jtrkDrawPhone(ctx,w,h){if(!jtrkPhone)return;const s=toScreen(jtrkPhone.lat,jtrkPhone.lon,w,h),mpp=Math.max(.01,156543.03392*Math.cos(jtrkPhone.lat*Math.PI/180)/Math.pow(2,view.z));ctx.save();if(Number.isFinite(jtrkPhone.accuracy)){ctx.beginPath();ctx.arc(s.x,s.y,Math.min(90,Math.max(5,jtrkPhone.accuracy/mpp)),0,Math.PI*2);ctx.fillStyle='rgba(0,184,148,.12)';ctx.fill();ctx.strokeStyle='rgba(0,184,148,.4)';ctx.lineWidth=1;ctx.stroke()}ctx.translate(s.x,s.y);if(Number.isFinite(jtrkHeading)){ctx.rotate(jtrkHeading*Math.PI/180);ctx.beginPath();ctx.moveTo(0,-15);ctx.lineTo(9,10);ctx.lineTo(0,6);ctx.lineTo(-9,10);ctx.closePath();ctx.fillStyle='#00b894';ctx.fill();ctx.strokeStyle='#fff';ctx.lineWidth=2;ctx.stroke()}else{ctx.beginPath();ctx.arc(0,0,8,0,Math.PI*2);ctx.fillStyle='#00b894';ctx.fill();ctx.strokeStyle='#fff';ctx.lineWidth=2;ctx.stroke()}ctx.restore()}
drawOverlay=function(ctx,w,h){if(mapMode==='offline'){ctx.strokeStyle='rgba(100,120,140,.18)';ctx.lineWidth=1;for(let i=1;i<5;i++){ctx.beginPath();ctx.moveTo(w*i/5,0);ctx.lineTo(w*i/5,h);ctx.stroke();ctx.beginPath();ctx.moveTo(0,h*i/5);ctx.lineTo(w,h*i/5);ctx.stroke()}}jtrkDrawMgrs(ctx,w,h);if(track.length){const pts=track.map(p=>toScreen(p.lat,p.lon,w,h));ctx.strokeStyle='#1463d6';ctx.lineWidth=3;ctx.lineJoin='round';ctx.beginPath();pts.forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y));ctx.stroke();pts.forEach((p,i)=>{ctx.beginPath();ctx.arc(p.x,p.y,i===0||i===pts.length-1?7:4,0,Math.PI*2);ctx.fillStyle=i===0?'#16834a':i===pts.length-1?'#c93434':'#1463d6';ctx.fill();ctx.strokeStyle='#fff';ctx.lineWidth=1.5;ctx.stroke()})}jtrkDrawSelected(ctx,w,h);jtrkDrawPhone(ctx,w,h)};
setMapMode=function(mode){mapMode=mode;localStorage.setItem('jtrk-map',mode);document.querySelectorAll('[data-map]').forEach(b=>b.classList.toggle('active',b.dataset.map===mode));if($('mgrsGrid'))$('mgrsGrid').checked=jtrkMgrsOn;$('attrib').textContent=(providers[mode]?.attr||'Offline-Ansicht')+' · Ziehen zum Verschieben · zwei Finger zum Zoomen';drawMap()};
function toggleMgrs(){jtrkMgrsOn=$('mgrsGrid').checked;localStorage.setItem('jtrk-mgrs',jtrkMgrsOn?'1':'0');drawMap()}
function jtrkPointerPos(e){const r=$('trackMap').getBoundingClientRect();return{x:e.clientX-r.left,y:e.clientY-r.top}}
function jtrkStartPinch(){if(jtrkPointers.size<2)return;const [a,b]=[...jtrkPointers.values()].slice(0,2),mid={x:(a.x+b.x)/2,y:(a.y+b.y)/2},r=$('trackMap').getBoundingClientRect();jtrkPinch={dist:Math.max(1,Math.hypot(a.x-b.x,a.y-b.y)),zoom:view.z,anchor:jtrkFromScreen(mid.x,mid.y,r.width,r.height)};jtrkDrag=null}
function jtrkPointerDown(e){const c=$('trackMap'),p=jtrkPointerPos(e);jtrkPointers.set(e.pointerId,p);try{c.setPointerCapture(e.pointerId)}catch(_){}if(jtrkPointers.size===1)jtrkDrag={x:p.x,y:p.y,center:world(view.lon,view.lat,view.z),moved:false};else{jtrkStartPinch();jtrkSuppressTapUntil=Date.now()+400}e.preventDefault()}
function jtrkPointerMove(e){if(!jtrkPointers.has(e.pointerId))return;const p=jtrkPointerPos(e);jtrkPointers.set(e.pointerId,p);const r=$('trackMap').getBoundingClientRect();if(jtrkPointers.size>=2){if(!jtrkPinch)jtrkStartPinch();const [a,b]=[...jtrkPointers.values()].slice(0,2),mid={x:(a.x+b.x)/2,y:(a.y+b.y)/2},dist=Math.max(1,Math.hypot(a.x-b.x,a.y-b.y)),z=Math.max(2,Math.min(19,Math.round(jtrkPinch.zoom+Math.log2(dist/jtrkPinch.dist)))),aw=world(jtrkPinch.anchor.lon,jtrkPinch.anchor.lat,z),center=unworld(aw.x-(mid.x-r.width/2),aw.y-(mid.y-r.height/2),z);view.z=z;view.lat=center.lat;view.lon=center.lon;jtrkSuppressTapUntil=Date.now()+350;drawMap();e.preventDefault();return}if(jtrkDrag){const dx=p.x-jtrkDrag.x,dy=p.y-jtrkDrag.y;if(Math.hypot(dx,dy)>3)jtrkDrag.moved=true;const center=unworld(jtrkDrag.center.x-dx,jtrkDrag.center.y-dy,view.z);view.lat=center.lat;view.lon=center.lon;if(jtrkDrag.moved)jtrkSuppressTapUntil=Date.now()+250;drawMap();e.preventDefault()}}
function jtrkPointerEnd(e){jtrkPointers.delete(e.pointerId);if(jtrkPointers.size===0){if(jtrkDrag?.moved||jtrkPinch)jtrkSuppressTapUntil=Date.now()+250;jtrkDrag=null;jtrkPinch=null}else if(jtrkPointers.size===1){const p=[...jtrkPointers.values()][0];jtrkDrag={x:p.x,y:p.y,center:world(view.lon,view.lat,view.z),moved:true};jtrkPinch=null}}
function jtrkSelectCoordinate(e){e.stopImmediatePropagation();if(Date.now()<jtrkSuppressTapUntil)return;const r=e.currentTarget.getBoundingClientRect(),p=jtrkFromScreen(e.clientX-r.left,e.clientY-r.top,r.width,r.height);jtrkSelected=p;$('pointInfo').textContent='Kartenpunkt · '+jtrkMgrs(p.lat,p.lon)+' · '+p.lat.toFixed(6)+', '+p.lon.toFixed(6);drawMap()}
function jtrkOrientationHeading(e){let h=Number(e.webkitCompassHeading);if(Number.isFinite(h))return(h+360)%360;if(e.absolute&&Number.isFinite(e.alpha)){const a=Number(screen.orientation?.angle||window.orientation||0);return(360-e.alpha+a+360)%360}return null}
function jtrkOrientation(e){const h=jtrkOrientationHeading(e);if(h===null)return;jtrkCompassSeen=true;jtrkHeading=h;if(jtrkPhone)drawMap()}
function jtrkPhoneOk(p){jtrkPhone={lat:p.coords.latitude,lon:p.coords.longitude,accuracy:Number(p.coords.accuracy)||0};if(!jtrkCompassSeen&&Number.isFinite(p.coords.heading))jtrkHeading=p.coords.heading;$('phoneBtn').textContent='Handyposition aktiv';const d=Number.isFinite(jtrkHeading)?' · Blickrichtung '+Math.round(jtrkHeading)+'°':' · Blickrichtung nicht verfügbar';status('phoneStatus','Handy ±'+Math.round(jtrkPhone.accuracy)+' m'+d,'ok');drawMap()}
function jtrkPhoneError(e){const note=!window.isSecureContext?' Browser kann GPS auf http://192.168.4.1 aus Sicherheitsgründen sperren.':'';status('phoneStatus','Handyposition nicht verfügbar: '+(e.message||'Berechtigung fehlt')+'.'+note,'warn')}
function jtrkDisablePhone(){if(jtrkPhoneWatch!==null&&navigator.geolocation)navigator.geolocation.clearWatch(jtrkPhoneWatch);jtrkPhoneWatch=null;jtrkPhone=null;jtrkHeading=null;$('phoneBtn').textContent='Handyposition';status('phoneStatus','Handyposition aus.');drawMap()}
async function enablePhoneLocation(){if(jtrkPhoneWatch!==null){jtrkDisablePhone();return}if(!navigator.geolocation){status('phoneStatus','Browser stellt keine Standortfunktion bereit.','warn');return}try{if(!jtrkOrientationRegistered&&typeof DeviceOrientationEvent!=='undefined'){if(typeof DeviceOrientationEvent.requestPermission==='function'){const r=await DeviceOrientationEvent.requestPermission();if(r==='granted'){window.addEventListener('deviceorientation',jtrkOrientation,true);jtrkOrientationRegistered=true}}else{window.addEventListener('deviceorientationabsolute',jtrkOrientation,true);window.addEventListener('deviceorientation',jtrkOrientation,true);jtrkOrientationRegistered=true}}}catch(_){status('phoneStatus','Standort aktiv; Kompassfreigabe wurde nicht erteilt.','warn')}if(!window.isSecureContext)status('phoneStatus','Standort wird angefragt; manche Browser sperren GPS auf lokalen HTTP-Seiten.','warn');try{jtrkPhoneWatch=navigator.geolocation.watchPosition(jtrkPhoneOk,jtrkPhoneError,{enableHighAccuracy:true,maximumAge:2000,timeout:12000})}catch(e){jtrkPhoneError(e)}}
const jtrkCanvas=$('trackMap');jtrkCanvas.addEventListener('pointerdown',jtrkPointerDown,{passive:false});jtrkCanvas.addEventListener('pointermove',jtrkPointerMove,{passive:false});jtrkCanvas.addEventListener('pointerup',jtrkPointerEnd);jtrkCanvas.addEventListener('pointercancel',jtrkPointerEnd);jtrkCanvas.addEventListener('click',jtrkSelectCoordinate,true);jtrkCanvas.addEventListener('wheel',e=>{e.preventDefault();zoomMap(e.deltaY<0?1:-1)},{passive:false});
// ----- end interactive map -----
'''
portal = once(portal, "boot();\n</script>", interactive_js + "boot();\n</script>", "Tracker interactive map JS")

for marker in ("buildTrackerServiceSsid", "owner.long_name", "Jarnsen-Tracker-%02X%02X"):
    if marker not in web:
        raise SystemExit(f"missing Tracker AP marker: {marker}")
for marker in ("MGRS-Gitter", "jtrkDrawMgrs", "jtrkSelectCoordinate", "pointerdown", "watchPosition", "deviceorientationabsolute", "#00b894", "#d63384"):
    if marker not in portal:
        raise SystemExit(f"missing Tracker map marker: {marker}")

WEB.write_text(web, encoding="utf-8")
PORTAL.write_text(portal, encoding="utf-8")
print("Tracker service UX enabled: long-name AP, cyan MGRS grid, pan/pinch, map MGRS and phone marker")
