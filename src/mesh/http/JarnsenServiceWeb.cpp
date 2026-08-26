#include "mesh/http/JarnsenServiceWeb.h"

#if defined(ARCH_ESP32) && HAS_WIFI && (defined(_VARIANT_HELTEC_V3) || defined(HELTEC_TRACKER_V1_1))

#include "DebugConfiguration.h"
#include "NodeDB.h"
#include "Throttle.h"
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
#include <cstdio>
#include <cstring>
#include <esp_mac.h>
#include <esp_system.h>
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

const char PAGE[] PROGMEM = R"HTML(<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Jarnsen Mobile Service</title><style>
:root{color-scheme:light dark;--bg:#f3f5f8;--card:#fff;--fg:#16202a;--muted:#647181;--blue:#0969da;--green:#18794e;--red:#c62828;--line:#d9e0e7}
@media(prefers-color-scheme:dark){:root{--bg:#0d1117;--card:#161b22;--fg:#e6edf3;--muted:#9ba7b4;--blue:#58a6ff;--green:#3fb950;--red:#ff7b72;--line:#30363d}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:16px system-ui,-apple-system,sans-serif}.wrap{max-width:760px;margin:auto;padding:18px 14px 40px}h1{font-size:25px;margin:4px 0}h2{font-size:19px;margin:0 0 12px}.sub,.muted{color:var(--muted)}.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px;margin:14px 0;box-shadow:0 2px 12px #0001}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.metric{border:1px solid var(--line);border-radius:12px;padding:11px}.metric b{display:block;font-size:22px;margin-top:4px}button,.button{appearance:none;border:0;border-radius:11px;background:var(--blue);color:#fff;padding:12px 14px;font-weight:650;font-size:15px;text-decoration:none;display:inline-block;text-align:center;cursor:pointer}button.secondary,.button.secondary{background:transparent;color:var(--blue);border:1px solid var(--blue)}button.danger{background:var(--red)}button:disabled{opacity:.45}.actions{display:flex;flex-wrap:wrap;gap:9px}.status{margin-top:10px;min-height:24px;color:var(--muted)}.ok{color:var(--green)}.err{color:var(--red)}progress{width:100%;height:12px;margin-top:10px}pre{white-space:pre-wrap;word-break:break-word;max-height:42vh;overflow:auto;background:var(--bg);border-radius:10px;padding:11px;font-size:12px}input[type=file]{width:100%;padding:10px 0}.hide{display:none}.warn{border-left:4px solid #d29922;padding-left:10px}@media(max-width:430px){.grid{grid-template-columns:1fr}.actions>*{width:100%}}
</style></head><body><main class="wrap"><h1>Jarnsen Mobile Service</h1><div class="sub" id="device">Gerät wird gelesen …</div>
<section class="card"><h2>Diagnoselog</h2><div class="actions"><button onclick="analyse()">Log laden &amp; auswerten</button><a class="button secondary" href="/log" download>Log speichern</a></div><div id="logStatus" class="status"></div><div id="metrics" class="grid hide"></div><pre id="raw" class="hide"></pre></section>
<section class="card"><h2>Firmwareupdate über WLAN</h2><p class="muted">Die passende aktuelle Firmware wird ausschließlich aus dem Jarnsen-GitHub-Release gewählt und vor dem Neustart per SHA-256 geprüft.</p><div class="actions"><button id="githubBtn" onclick="githubUpdate()">Aktuelle GitHub-Firmware laden</button></div><div id="fallback" class="hide"><p class="warn">Safari konnte die GitHub-Datei nicht automatisch an den Node weiterreichen. Lade sie über den Link in „Dateien“ und wähle sie anschließend hier aus.</p><a id="downloadLink" class="button secondary" target="_blank">Firmware aus GitHub laden</a><input id="file" type="file" accept=".bin,application/octet-stream"><button onclick="uploadSelected()">Ausgewählte Firmware installieren</button></div><progress id="progress" class="hide" max="100" value="0"></progress><div id="fwStatus" class="status"></div></section>
<section class="card"><h2>Verbindung</h2><div class="grid"><div class="metric">WLAN<b id="ssid">–</b></div><div class="metric">Adresse<b>192.168.4.1</b></div></div><p class="muted">Der WLAN-Service beendet sich nach zehn Minuten ohne Aktivität automatisch.</p></section></main>
<script>
const API='https://api.github.com/repos/Jarnsen/firmware/releases/tags/';let info=null,asset=null;
const $=id=>document.getElementById(id);function setStatus(id,text,kind=''){const e=$(id);e.textContent=text;e.className='status '+kind}
async function boot(){const r=await fetch('/status',{cache:'no-store'});info=await r.json();$('device').textContent=info.title+' · '+info.device;$('ssid').textContent=info.ssid}
async function analyse(){setStatus('logStatus','Log wird geladen …');const r=await fetch('/log',{cache:'no-store'});if(!r.ok){setStatus('logStatus','Logdownload fehlgeschlagen.','err');return}const t=await r.text(),lines=t.split(/\r?\n/),count=x=>lines.filter(l=>l.includes(x)).length,last=[...lines].reverse().find(l=>l.includes(' | '))||'–';const values=[['Zeilen',lines.filter(Boolean).length],['Warnungen',count('WARN')+count('REJECT')],['Fehler/Resets',count('ERROR')+count('PANIC')+count('BROWNOUT')],['BLE-Verbindungen',count('BLE_CONNECT')],['Positions-TX',count('POSITION_TX')+count('PHONE_POS_TX')],['Loggröße',Math.round(new Blob([t]).size/1024)+' KB']];$('metrics').innerHTML=values.map(v=>'<div class="metric">'+v[0]+'<b>'+v[1]+'</b></div>').join('')+'<div class="metric" style="grid-column:1/-1">Letztes Ereignis<b style="font-size:13px">'+last.replaceAll('&','&amp;').replaceAll('<','&lt;')+'</b></div>';$('metrics').classList.remove('hide');$('raw').textContent=t;$('raw').classList.remove('hide');setStatus('logStatus','Log vollständig geladen.','ok')}
async function latest(){const r=await fetch(API+info.tag,{headers:{Accept:'application/vnd.github+json'},cache:'no-store'});if(!r.ok)throw Error('GitHub antwortet mit '+r.status);const release=await r.json();asset=release.assets.find(a=>a.name===info.asset);if(!asset||!asset.digest?.startsWith('sha256:'))throw Error('Passende geprüfte Firmware fehlt im Release');return asset}
async function githubUpdate(){try{setStatus('fwStatus','GitHub-Release wird geprüft …');const a=await latest();$('downloadLink').href=a.browser_download_url;setStatus('fwStatus','Firmware wird direkt aus GitHub geladen …');const r=await fetch(a.browser_download_url,{cache:'no-store'});if(!r.ok)throw Error('Download '+r.status);const blob=await r.blob();await upload(blob,a)}catch(e){$('fallback').classList.remove('hide');setStatus('fwStatus','Direkte Übergabe nicht möglich: '+e.message,'err')}}
async function uploadSelected(){try{const f=$('file').files[0];if(!f)throw Error('Bitte zuerst die .bin-Datei auswählen');const a=asset||await latest();await upload(f,a)}catch(e){setStatus('fwStatus',e.message,'err')}}
async function upload(blob,a){if(blob.size!==a.size)throw Error('Dateigröße passt nicht zum GitHub-Release');const expected=a.digest.slice(7).toLowerCase();if(!/^[0-9a-f]{64}$/.test(expected))throw Error('GitHub liefert keine gültige SHA-256-Prüfsumme');if(!confirm('Firmware für '+info.title+' installieren? Der Node startet danach neu.'))return;const p=$('progress');p.classList.remove('hide');p.value=0;setStatus('fwStatus','Firmware wird übertragen und im Node per SHA-256 geprüft …');await new Promise((resolve,reject)=>{const x=new XMLHttpRequest();x.open('POST','/update');x.setRequestHeader('Content-Type','application/octet-stream');x.setRequestHeader('X-Jarnsen-Token',info.token);x.setRequestHeader('X-Jarnsen-Device',info.device);x.setRequestHeader('X-Jarnsen-Sha256',expected);x.upload.onprogress=e=>{if(e.lengthComputable)p.value=Math.round(e.loaded*100/e.total)};x.onload=()=>x.status===200?resolve():reject(Error(x.responseText||'Update fehlgeschlagen'));x.onerror=()=>reject(Error('WLAN-Verbindung unterbrochen'));x.send(blob)});p.value=100;setStatus('fwStatus','Update geprüft. Node startet neu.','ok');setTimeout(()=>{p.value=0;p.classList.add('hide')},1200)}
boot().catch(e=>setStatus('logStatus','Service nicht erreichbar: '+e.message,'err'));
</script></body></html>)HTML";

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
    client.printf("HTTP/1.1 %d %s\r\nContent-Type: %s\r\nCache-Control: no-store\r\nConnection: close\r\n", code, status,
                  type);
    if (extra)
        client.print(extra);
    client.print("\r\n");
}

void sendPage(WiFiClient &client)
{
    sendStatus(client, 200, "OK", "text/html; charset=utf-8");
    client.print(PAGE);
}

void sendJsonStatus(WiFiClient &client)
{
    sendStatus(client, 200, "OK", "application/json; charset=utf-8");
    client.printf("{\"title\":\"%s\",\"device\":\"%s\",\"ssid\":\"%s\",\"token\":\"%s\",\"tag\":\"%s\",\"asset\":\"%s\"}",
                  DEVICE_TITLE, DEVICE_CODE, serviceSsid, sessionToken, GITHUB_TAG, FIRMWARE_ASSET);
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
            sendUpdateError(client, 500, validHeader ? "Firmware konnte nicht geschrieben werden." : "Keine ESP32-S3-Firmware.");
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
    else if (strcmp(method, "GET") == 0 && strcmp(path, "/log") == 0)
        sendLog(client);
    else if (strcmp(method, "POST") == 0 && strcmp(path, "/update") == 0)
        receiveUpdate(client, contentLength, device, hash, token);
    else if (strcmp(method, "GET") == 0)
        sendPage(client);
    else {
        sendStatus(client, 404, "Not Found", "text/plain; charset=utf-8");
        client.print("Nicht gefunden.");
    }
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

    hadStation = WiFi.status() == WL_CONNECTED || config.network.wifi_enabled;
    WiFi.persistent(false);
    WiFi.mode(hadStation ? WIFI_AP_STA : WIFI_AP);
    WiFi.softAPConfig(IPAddress(192, 168, 4, 1), IPAddress(192, 168, 4, 1), IPAddress(255, 255, 255, 0));
    if (!WiFi.softAP(serviceSsid, SERVICE_PASSWORD)) {
        if (!hadStation)
            WiFi.mode(WIFI_OFF);
        return false;
    }

    dnsServer.start(53, "*", IPAddress(192, 168, 4, 1));
    httpServer.begin();
    httpServer.setNoDelay(true);
    serviceActive = true;
    lastActivityMs = millis() ? millis() : 1;
    restartRequestedMs = 0;
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
    WiFi.softAPdisconnect(true);
    if (!hadStation)
        WiFi.mode(WIFI_OFF);
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

#endif
