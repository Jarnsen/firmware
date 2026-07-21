# Jarnsen Tactical USB Display Mirror

This development tool mirrors the **Tactical** OLED frame of the Heltec Wireless Tracker V1.1 to a Windows PC over the existing USB-C connection.

## Safety and scope

- The mirror is compiled only for the exact `heltec-wireless-tracker` target.
- It sends at most one changed 128×64 monochrome frame every 500 ms.
- It does not change LoRa packets, GPS handling, Meshtastic channels or stored settings.
- The current implementation mirrors only the Tactical page, not every standard Meshtastic display page.
- The previous boot-tested Tactical commit remains available as the rollback point.

## Start on Windows

1. Connect the tracker over USB.
2. Set the device role to `TRACKER` or `TAK_TRACKER`.
3. Open the Tactical display page on the tracker.
4. Double-click `START-DISPLAY-MIRROR-WINDOWS.bat`.
5. Enter the COM port, for example `COM5`.

The launcher installs PySerial and opens a scaled black-and-white 128×64 viewer.

Manual start:

```powershell
py -m pip install --user pyserial
py tactical_display_mirror.py COM5
```

Optional scale:

```powershell
py tactical_display_mirror.py COM5 --scale 8
```

## Serial frame protocol

Firmware emits a newline-terminated ASCII record:

```text
@TMF 128 64 <2048 hexadecimal characters>
```

The payload is the native ThingPulse OLED page buffer: 128 columns × 8 vertical pages, one bit per pixel. Normal Meshtastic log lines can remain on the same serial connection; the viewer ignores everything that does not contain the `@TMF` marker.
