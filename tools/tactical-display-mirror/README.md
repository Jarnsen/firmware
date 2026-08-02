# Jarnsen Tactical USB Display Mirror

This development tool mirrors the **Tactical** display of the Heltec Wireless Tracker V1.1 to a Windows PC over the existing USB-C connection and can control the tracker remotely.

## Safety and scope

- The mirror is compiled only for the exact `heltec-wireless-tracker` target.
- It supports the legacy monochrome stream and the RGB565 Tactical color stream.
- It does not change LoRa packets, GPS handling, Meshtastic channels or stored settings.
- Remote input is routed through Meshtastic's `InputBroker`, the same path used by physical controls.

## Start on Windows

1. Connect the tracker over USB.
2. Set the device role to `TRACKER` or `TAK_TRACKER`.
3. Open the Tactical display page on the tracker.
4. Double-click `START-DISPLAY-MIRROR-WINDOWS.bat`.
5. Enter the COM port, for example `COM5`.

The launcher installs PySerial and opens a scaled viewer. RGB565 frames are selected automatically when the Tactical renderer publishes them.

Manual start:

```powershell
py -m pip install --user pyserial
py tactical_display_mirror.py COM5
```

Optional scale:

```powershell
py tactical_display_mirror.py COM5 --scale 8
```

## PC controls

- Arrow keys: navigate pages and menu rows
- Mouse wheel: move up/down
- Space or Enter: select/press
- Escape or Backspace: go back

The viewer sends `@TMC LEFT`, `RIGHT`, `UP`, `DOWN`, `SELECT` or `BACK` commands. The firmware converts them to regular `InputBroker` events.

## Optional EC11 rotary encoder

The Tactical input path also supports an EC11 configured through the existing canned-message rotary settings. No GPIOs are hardcoded because safe free pins differ between boards and attached peripherals.

Configure three verified free 3.3 V GPIOs for A, B and the push switch, then enable `canned_message.rotary1_enabled`. If no custom event mapping is stored, the Tactical firmware uses these defaults:

- clockwise: `DOWN`
- counter-clockwise: `UP`
- press: `SELECT`
- long press: `SELECT_LONG`

The bare encoder common pin connects to GND. Only EC11 breakout boards that explicitly require supply voltage should be connected to 3.3 V; never feed an ESP32 GPIO with 5 V.

## Serial frame protocol

Firmware emits a newline-terminated ASCII record:

```text
@TMF 128 64 <2048 hexadecimal characters>
```

The payload is the native ThingPulse OLED page buffer: 128 columns × 8 vertical pages, one bit per pixel. Normal Meshtastic log lines can remain on the same serial connection; the viewer ignores everything that does not contain the `@TMF` marker.

Color Tactical frames use:

```text
@TMF2 <width> <height> <frame-id> <RGB565-RLE-data>
```

The viewer decodes the run-length encoded RGB565 payload and falls back to `@TMF` for monochrome frames.
