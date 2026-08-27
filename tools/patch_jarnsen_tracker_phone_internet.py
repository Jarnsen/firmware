"""Keep phone Internet available beside the Tracker local service WLAN and auto-check firmware.

This patch runs after patch_jarnsen_tracker_service_upgrade.py. It deliberately keeps
192.168.4.0/24 as an on-link service network but removes the DHCP default-router
offer and wildcard captive DNS. A phone can therefore keep its cellular route
for GitHub/map traffic while reaching the Tracker locally at 192.168.4.1.
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

# Expose the build SHA stamped by the existing Tracker workflow and use the official
# ESP-NETIF DHCP API for a local-only AP (DHCP option 3/router disabled).
include_anchor = '#include "mesh/http/JarnsenTrackerServicePortalPage.h"\n'
include_new = include_anchor + '#include "vehicle/JarnsenBuildGenerated.h"\n'
web = once(web, include_anchor, include_new, "Tracker build-info include")

netif_anchor = '#include <esp_mac.h>\n'
netif_new = netif_anchor + '#include <esp_netif.h>\n'
web = once(web, netif_anchor, netif_new, "ESP-NETIF include")

send_page_anchor = '}\n\nvoid sendPage(WiFiClient &client)\n'
dhcp_helper = r'''}

bool configureLocalOnlyDhcp()
{
    esp_netif_t *apNetif = esp_netif_get_handle_from_ifkey("WIFI_AP_DEF");
    if (!apNetif) {
        LOG_WARN("Jarnsen WLAN: SoftAP netif not found; cannot enable local-only routing");
        return false;
    }

    // Configure DHCP before the phone leases an address. Omitting option 3
    // prevents the service WLAN from replacing the phone's cellular default
    // route while the 192.168.4.0/24 subnet remains directly reachable.
    const esp_err_t stopResult = esp_netif_dhcps_stop(apNetif);
    if (stopResult != ESP_OK && stopResult != ESP_ERR_ESP_NETIF_DHCP_ALREADY_STOPPED) {
        LOG_WARN("Jarnsen WLAN: DHCP stop failed: %s", esp_err_to_name(stopResult));
        return false;
    }

    uint8_t routerOffer = 0;
    const esp_err_t optionResult = esp_netif_dhcps_option(apNetif, ESP_NETIF_OP_SET,
                                                          ESP_NETIF_ROUTER_SOLICITATION_ADDRESS,
                                                          &routerOffer, sizeof(routerOffer));
    const esp_err_t startResult = esp_netif_dhcps_start(apNetif);
    if (optionResult != ESP_OK || startResult != ESP_OK) {
        LOG_WARN("Jarnsen WLAN: local-only DHCP failed: option=%s start=%s", esp_err_to_name(optionResult),
                 esp_err_to_name(startResult));
        return false;
    }

    LOG_INFO("Jarnsen WLAN: local-only DHCP active; mobile data may remain the Internet route");
    return true;
}

void sendPage(WiFiClient &client)
'''
web = once(web, send_page_anchor, dhcp_helper, "local-only DHCP helper")

status_old = r'''        "\"track_count\":%u,\"long_name\":\"%s\",\"short_name\":\"%s\",\"node_id\":\"!%08x\",\"role\":\"%s\","
        "\"health\":{\"boots\":%u,\"crashes\":%u,\"service\":%u,\"ble\":%u,\"wlan\":%u,\"wlan_fail\":%u,\"reset\":\"%s\"},"
'''
status_new = r'''        "\"track_count\":%u,\"long_name\":\"%s\",\"short_name\":\"%s\",\"node_id\":\"!%08x\",\"role\":\"%s\",\"build_sha\":\"%s\","
        "\"health\":{\"boots\":%u,\"crashes\":%u,\"service\":%u,\"ble\":%u,\"wlan\":%u,\"wlan_fail\":%u,\"reset\":\"%s\"},"
'''
web = once(web, status_old, status_new, "build SHA in Tracker service status format")

args_old = r'''        (unsigned)jarnsenPositionTrackCount(), longName, shortName, (unsigned)nodeNum, trackerServiceRoleName(),
        (unsigned)health.bootCount, (unsigned)health.crashResetCount, (unsigned)health.serviceOpenCount,
'''
args_new = r'''        (unsigned)jarnsenPositionTrackCount(), longName, shortName, (unsigned)nodeNum, trackerServiceRoleName(), JARNSEN_BUILD_SHA,
        (unsigned)health.bootCount, (unsigned)health.crashResetCount, (unsigned)health.serviceOpenCount,
'''
web = once(web, args_old, args_new, "build SHA in Tracker service status args")

captive_dns_anchor = '    dnsServer.start(53, "*", IPAddress(192, 168, 4, 1));\n    httpServer.begin();\n'
local_ap_start = '''    // No wildcard captive DNS here: external names must keep using the phone's
    // Internet-capable network. 192.168.4.1 remains reachable through the
    // directly connected service subnet.
    dnsServer.stop();
    const bool localOnlyDhcp = configureLocalOnlyDhcp();
    if (!localOnlyDhcp)
        LOG_WARN("Jarnsen WLAN: phone may still prefer the AP as its default route");
    httpServer.begin();
'''
web = once(web, captive_dns_anchor, local_ap_start, "remove captive DNS and enable local-only DHCP")

pump_dns_anchor = '    dnsServer.processNextRequest();\n'
pump_dns_new = '    // Wildcard captive DNS intentionally disabled so cellular Internet remains usable.\n'
web = once(web, pump_dns_anchor, pump_dns_new, "disable captive DNS pump")

# Portal: make the network split visible and perform a firmware check as soon as
# the page has its local /status data.
portal = once(
    portal,
    '<small id="barState">WLAN SERVICE · 192.168.4.1</small>',
    '<small id="barState">Tracker lokal · Internet über Mobilfunk</small>',
    "portal network banner",
)
portal = once(
    portal,
    '<div id="overviewStatus" class="status">Lokale Servicedaten bereit.</div>',
    '<div id="overviewStatus" class="status">Tracker lokal über WLAN · Internet/Online-Karten über Mobilfunk.</div>',
    "portal network status",
)

firmware_section = '<section class="card" id="firmware"><h2>Firmwareupdate über WLAN</h2><p class="muted">Die passende aktuelle Firmware wird aus dem Jarnsen-GitHub-Release gewählt und vor Installation per SHA-256 geprüft.</p><div class="actions"><button id="githubBtn" onclick="githubUpdate()">Aktuelle GitHub-Firmware laden</button></div><div id="fallback" class="hide"><p class="warn">Der Captive-Browser konnte die GitHub-Datei nicht direkt weiterreichen. Datei laden und anschließend hier auswählen.</p><a id="downloadLink" class="button secondary" target="_blank">Firmware aus GitHub laden</a><input id="file" type="file" accept=".bin,application/octet-stream"><button onclick="uploadSelected()">Ausgewählte Firmware installieren</button></div><progress id="progress" class="hide" max="100" value="0"></progress><div id="fwStatus" class="status"></div></section>'
firmware_section_new = '<section class="card" id="firmware"><h2>Firmwareupdate über WLAN</h2><p class="muted">Der Firmwarestand wird beim Öffnen automatisch über GitHub geprüft. Die Firmware wird vor Installation per SHA-256 gegen das Release verifiziert.</p><div class="grid"><div class="metric">Installiert<b id="fwInstalled">–</b></div><div class="metric">GitHub<b id="fwLatest">Prüfe …</b></div><div class="metric">Status<b id="fwState">Prüfe …</b></div></div><div class="actions"><button id="githubBtn" onclick="githubUpdate()" disabled>Firmware wird geprüft …</button></div><div id="fallback" class="hide"><p class="warn">Direkter Download nicht möglich. Internet/Mobilfunk prüfen oder die Firmware-Datei über GitHub laden und anschließend hier auswählen.</p><a id="downloadLink" class="button secondary" target="_blank">Firmware aus GitHub laden</a><input id="file" type="file" accept=".bin,application/octet-stream"><button onclick="uploadSelected()">Ausgewählte Firmware installieren</button></div><progress id="progress" class="hide" max="100" value="0"></progress><div id="fwStatus" class="status">Firmwarestand wird geprüft …</div></section>'
portal = once(portal, firmware_section, firmware_section_new, "automatic firmware status panel")

portal = once(
    portal,
    "let info=null,asset=null,allTrack=[]",
    "let info=null,asset=null,latestMeta=null,allTrack=[]",
    "portal latest metadata state",
)

boot_new = r'''async function boot(){
try{const r=await fetch('/status',{cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);info=await r.json();$('device').textContent=(info.long_name||info.title)+' · '+info.device+' · '+info.node_id;$('barName').textContent=info.long_name||'Jarnsen Tracker';$('mNode').textContent=info.short_name||info.node_id;$('mRole').textContent=info.role||'–';$('mSsid').textContent=info.ssid;$('mPoints').textContent=info.track_count;$('mBoots').textContent=info.health.boots;$('mCrash').textContent=info.health.crashes;$('hKnown').textContent=info.mesh.observed;$('h15').textContent=info.mesh.active15;$('h1h').textContent=info.mesh.active1h;$('h24').textContent=info.mesh.active24;$('hDirect').textContent=info.mesh.direct15;$('hRx').textContent=info.mesh.rx1h;$('hLast').textContent=info.mesh.last_node||'–';$('hRssi').textContent=info.mesh.last_age<4294967295?info.mesh.last_rssi+' dBm':'–';$('hSnr').textContent=info.mesh.last_age<4294967295?(info.mesh.last_snr_q4/4).toFixed(1)+' dB':'–';$('dSvc').textContent=info.health.service;$('dBle').textContent=info.health.ble;$('dWlan').textContent=info.health.wlan;$('dWlanFail').textContent=info.health.wlan_fail;$('dReset').textContent=info.health.reset;$('fwInstalled').textContent=info.build_sha||'–';$('barState').textContent='Tracker lokal · Internet über Mobilfunk';}catch(e){status('overviewStatus','Status nicht lesbar: '+e.message,'err')}
setMapMode(mapMode);await Promise.allSettled([loadTrack(),checkFirmware()])}
'''
portal = replace_between(portal, "async function boot(){", "function canvas(){", boot_new, "portal boot firmware check")

latest_and_check = r'''async function internetFetch(url,opts={},timeoutMs=8000){const c=new AbortController(),t=setTimeout(()=>c.abort(),timeoutMs);try{return await fetch(url,{...opts,cache:'no-store',signal:c.signal})}finally{clearTimeout(t)}}
async function latest(){const r=await internetFetch(API+info.tag,{headers:{Accept:'application/vnd.github+json'}});if(!r.ok)throw Error('GitHub Release '+r.status);const j=await r.json(),man=j.assets.find(a=>a.name===info.asset.replace('.update.bin','.ota.json')),bin=j.assets.find(a=>a.name===info.asset);if(!bin)throw Error('Firmware-Datei nicht gefunden');asset=bin;let sha=bin.digest?.startsWith('sha256:')?bin.digest.slice(7):'',sourceSha='';if(man){try{const mr=await internetFetch(man.browser_download_url,{},8000);if(mr.ok){const mj=await mr.json();sha=mj.firmware_sha256||mj.sha256||sha;sourceSha=mj.source_sha||''}}catch(_){}}latestMeta={bin,sha,sourceSha};return latestMeta}
async function checkFirmware(){const btn=$('githubBtn');btn.disabled=true;status('fwStatus','GitHub-Firmwarestand wird geprüft …');$('fwState').textContent='Prüfe …';try{const a=await latest(),installed=String(info?.build_sha||'').toLowerCase(),remote=String(a.sourceSha||'').toLowerCase(),known=installed&&installed!=='unknown',current=known&&remote&&remote.startsWith(installed);$('fwInstalled').textContent=known?installed:'unbekannt';$('fwLatest').textContent=remote?remote.slice(0,8):'verfügbar';if(current){$('fwState').textContent='Aktuell ✓';btn.textContent='Firmware aktuell ✓';btn.disabled=true;status('fwStatus','Firmware ist aktuell · Build '+installed,'ok')}else{$('fwState').textContent='Update verfügbar';btn.textContent='Update installieren';btn.disabled=false;status('fwStatus',remote?'Update verfügbar · installiert '+(known?installed:'unbekannt')+' · GitHub '+remote.slice(0,8):'GitHub-Firmware verfügbar; Buildvergleich nicht möglich.','warn')}}catch(e){const installed=String(info?.build_sha||'');$('fwInstalled').textContent=installed||'–';$('fwLatest').textContent='offline';$('fwState').textContent='Keine Prüfung';btn.textContent='Firmware erneut prüfen';btn.disabled=false;status('fwStatus','GitHub-Prüfung nicht möglich – keine Internetverbindung bzw. Mobilfunk prüfen: '+(e.name==='AbortError'?'Zeitüberschreitung':e.message),'warn')}}
'''
portal = replace_between(portal, "async function latest(){", "function resetProgress()", latest_and_check, "latest firmware and automatic comparison")

# The existing updater expects a GitHub asset object. Keep that path, but use the
# already fetched metadata to avoid a second online lookup.
upload_selected_old = "async function uploadSelected(){try{const f=$('file').files[0];if(!f)throw Error('Bitte zuerst die .bin-Datei auswählen');await upload(f,asset||await latest())}catch(e){resetProgress();status('fwStatus',e.message,'err')}}"
upload_selected_new = "async function uploadSelected(){try{const f=$('file').files[0];if(!f)throw Error('Bitte zuerst die .bin-Datei auswählen');const a=latestMeta||await latest();await upload(f,a.bin||asset)}catch(e){resetProgress();status('fwStatus',e.message,'err')}}"
portal = once(portal, upload_selected_old, upload_selected_new, "manual upload reuse firmware metadata")

# githubUpdate() still uses the same verified release asset, but latest() now
# returns metadata rather than the raw asset.
github_update_old = "async function githubUpdate(){try{status('fwStatus','GitHub-Release wird geprüft …');const a=await latest();$('downloadLink').href=a.browser_download_url;status('fwStatus','Firmware wird direkt aus GitHub geladen …');const r=await fetch(a.browser_download_url,{cache:'no-store'});if(!r.ok)throw Error('Download '+r.status);await upload(await r.blob(),a)}catch(e){resetProgress();$('fallback').classList.remove('hide');status('fwStatus','Direkte Übergabe nicht möglich: '+e.message,'err')}}"
github_update_new = "async function githubUpdate(){try{status('fwStatus','GitHub-Release wird geprüft …');const m=latestMeta||await latest(),a=m.bin;$('downloadLink').href=a.browser_download_url;status('fwStatus','Firmware wird über Mobilfunk/Internet geladen …');const r=await internetFetch(a.browser_download_url,{},30000);if(!r.ok)throw Error('Download '+r.status);await upload(await r.blob(),a)}catch(e){resetProgress();$('fallback').classList.remove('hide');status('fwStatus','Direkte Übergabe nicht möglich: '+e.message,'err')}}"
portal = once(portal, github_update_old, github_update_new, "GitHub update with metadata")

for marker in (
    '#include "vehicle/JarnsenBuildGenerated.h"',
    '#include <esp_netif.h>',
    'ESP_NETIF_ROUTER_SOLICITATION_ADDRESS',
    'configureLocalOnlyDhcp()',
    'build_sha',
    'Wildcard captive DNS intentionally disabled',
):
    if marker not in web:
        raise SystemExit(f"missing Tracker phone-Internet web marker: {marker}")

for marker in (
    'Internet über Mobilfunk',
    'fwInstalled',
    'fwLatest',
    'checkFirmware()',
    'firmware_sha256',
    'source_sha',
    'Firmware aktuell ✓',
    'keine Internetverbindung',
):
    if marker not in portal:
        raise SystemExit(f"missing Tracker phone-Internet portal marker: {marker}")

WEB.write_text(web, encoding="utf-8")
PORTAL.write_text(portal, encoding="utf-8")
print("Tracker V1.1: local-only service WLAN, cellular Internet coexistence and automatic firmware check enabled")
