# JARNSEN Service-Web: HTTPS und Telefon-GPS

## Ziel

Das Service-Web funktioniert auf Android und iPhone ohne ATAK-App.

- Der Node liefert Mesh- und Node-Daten.
- EIGEN stammt nur aus dem GPS des Telefons im Browser.
- Die Telefonposition wird nicht an den Node und nicht ins Mesh übertragen.
- Entfernung und Richtung in 6400 Strich werden lokal im Browser berechnet.
- Nodeposition und EIGEN bleiben getrennt.
- Nodezugriff läuft lokal über WLAN; Internet kann parallel über Mobilfunk laufen.

## HTTPS ohne Domain

Port 80 bleibt für Captive Portal und Ersteinrichtung erhalten. Nach der TLS-Provisionierung steht die Bedienoberfläche zusätzlich unter `https://192.168.4.1/` bereit.

Es wird keine öffentliche Domain und kein öffentlicher Zertifikatsdienst benötigt. Der Windows-Flasher verwaltet eine lokale JARNSEN MESH Root CA und erstellt pro Node ein eigenes Serverzertifikat mit IP-SAN `192.168.4.1`.

Die Root-CA bleibt langfristig bestehen. Node-Zertifikate werden für 800 Tage erstellt und vom Flasher automatisch erneuert, wenn weniger als 90 Tage Restlaufzeit vorhanden sind.

## iPhone

Das WebUI bietet `JARNSEN-ZERTIFIKAT EINRICHTEN` und liefert ein `.mobileconfig` mit der öffentlichen JARNSEN Root-CA.

Auf einem normalen iPhone:

1. Einstellungen -> Allgemein -> VPN & Geräteverwaltung -> Profil installieren.
2. Einstellungen -> Allgemein -> Info -> Zertifikatsvertrauenseinstellungen -> JARNSEN MESH Root CA -> Volles Vertrauen aktivieren.
3. Danach `https://192.168.4.1/` öffnen und Standortzugriff erlauben.

Diese Einrichtung ist pro iPhone nur einmal nötig, solange alle Nodes von derselben JARNSEN Root-CA provisioniert werden.

## Browser-GPS

Auf der HTTPS-Seite verwendet das WebUI `navigator.geolocation.watchPosition()`.

Es gibt keinen `/phone-position` Upload und keine manuelle Lat/Lon-Eingabe. EIGEN bleibt ausschließlich im Browser.

## Mobilfunk-Internet

Das WLAN bleibt für `192.168.4.0/24` zuständig. Über die WebUI-Funktion Mobilfunk-Internet aktivieren wird die Node als Standard-Internetroute entfernt, sodass das Telefon seinen Internetverkehr wieder über Mobilfunk führen kann.

## Persistenz

TLS-Material liegt persistent im Node-Speicher. Normale OTA-Updates sollen es erhalten. Nach einem vollständigen Factory-Flash mit Flash-Löschung provisioniert der Windows-Flasher es erneut.
