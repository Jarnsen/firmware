# JARNSEN Service-Web: HTTPS, Mobilfunk und Browser-GPS

## Ziel

Das Service-Web muss auf Android und iPhone ohne ATAK-App funktionieren.

- Der Node liefert ausschließlich Mesh-/Node-Daten.
- Die Eigenposition **EIGEN** stammt ausschließlich aus dem internen GPS des Telefons/Browsers.
- Die Telefonposition wird niemals zum Node oder ins Mesh übertragen.
- Entfernung und Richtung in 6400 Strich werden im Browser aus EIGEN -> Ziel berechnet.
- Der verbundene Node bleibt eine normale, getrennte Nodeposition.
- Lokaler Nodezugriff läuft über das Service-WLAN; Internet darf parallel über Mobilfunk laufen.

## Browser-GPS

Geolocation darf nur in einem sicheren Browser-Kontext gestartet werden. Das WebUI prüft deshalb
`window.isSecureContext`, bevor `navigator.geolocation.watchPosition()` verwendet wird.

Über HTTP bleibt Telefon-GPS deaktiviert. Es gibt keinen manuellen Lat/Lon-Fallback und keinen
`/phone-position` Upload zum Node.

## HTTPS-Zielbild

Das HTTP-Captive-Portal auf Port 80 bleibt nur für WLAN-Erkennung, PIN und den kontrollierten
Übergang in die normale Oberfläche erhalten.

Die eigentliche Oberfläche soll unter einem öffentlich vertrauenswürdigen HTTPS-Hostnamen laufen,
der innerhalb des Service-WLANs auf `192.168.4.1` zeigt.

Beispielschema (Domain noch nicht festgelegt):

`https://<node-id>.nodes.<service-domain>/`

Der ESP32-Unterbau enthält bereits `esp32_https_server`. Die bestehende Meshtastic-HTTPS-
Implementierung speichert Zertifikat und Private Key persistent in NVS und kann deshalb als
Grundlage für die JARNSEN-Service-HTTPS-Schicht verwendet werden.

## Zertifikate

Kein gemeinsamer Private Key für alle Nodes.

Bestmögliches Modell:

1. Jeder Node erhält eine eigene TLS-Identität / eigenen privaten Schlüssel.
2. Der private Schlüssel bleibt auf dem Node.
3. Eine zentrale ACME-Automation kontrolliert ausschließlich die Domain-/DNS-Validierung.
4. Die Automation stellt für den Node-Hostnamen ein neues Zertifikat aus.
5. Nur das neue Zertifikat / die Chain wird zum Node provisioniert; DNS-Zugangsdaten kommen nie auf den Node.
6. Vor Ablauf wird automatisch erneuert.

Ein öffentlich vertrauenswürdiges Zertifikat kann nicht für die private Adresse `192.168.4.1`
ausgestellt werden. Dafür ist ein FQDN erforderlich.

## Erneuerung

Die Erneuerung soll automatisch erfolgen. Der Node selbst führt jedoch keine DNS-01-Validierung aus
und speichert keine DNS-Provider-Zugangsdaten.

Solange noch keine Service-Domain und kein DNS-Provider festgelegt sind, bleibt die öffentlich
vertrauenswürdige Zertifikatsausstellung ein externer Blocker. Selbstsigniertes HTTPS ist nur ein
Diagnose-/Fallback-Pfad und erfüllt das Ziel "Browser-GPS ohne manuelle Zertifikatsinstallation"
nicht zuverlässig.

## Mobilfunk-Internet

Nach erfolgreicher Anmeldung darf der Node nicht dauerhaft Standard-Gateway für das Telefon bleiben.
Der lokale Route zu `192.168.4.0/24` bleibt über WLAN erhalten, während der Default-Internetverkehr
wieder über Mobilfunk läuft. Die Umschaltung muss kontrolliert erfolgen, damit die eigentliche
WebUI-Sitzung nicht unerwartet geschlossen wird.
