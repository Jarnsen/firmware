# Jarnsen Tactical USB Display Mirror

The Windows viewer mirrors the Heltec Wireless Tracker display over USB and routes PC controls through Meshtastic's normal `InputBroker`.

## Features

- RGB565 Tactical color mirror with automatic monochrome fallback
- chunked `TMF3` transfer so large frames do not block controls
- default 460800 baud, selectable in the Windows launcher
- sharp pixel mode and smoothed HD mode
- freely resizable window and F11 fullscreen
- native-resolution PNG screenshots with F12 or Ctrl+S
- visible keyboard mapping below the image
- arrows or WASD, Space/Enter, Escape/Backspace and mouse wheel
- prioritized commands with ACK round-trip measurement
- live connection state, FPS, frame age, USB RTT, format and resolution
- double-buffered drawing and a newest-frame-only queue

## Stability hotfix

The RGB565 matcher tolerates the small monochrome overlays that Meshtastic adds after a Tactical page is rendered, such as page indicators. These overlay pixels are merged into the color frame instead of forcing an unintended monochrome fallback.

On ESP32 FreeRTOS targets, USB remote-control events are queued through `InputBroker` and processed on the normal input path. They are no longer dispatched synchronously from the mirror worker thread, preventing page-navigation races and tracker reboots while cycling through all pages.

## Start on Windows

1. Connect the tracker over USB.
2. Open `START-DISPLAY-MIRROR-WINDOWS.bat`.
3. Enter the COM port.
4. Select the baud rate. `460800` is recommended.
5. Select `Pixel scharf` or `HD geglaettet`.

The launcher installs or updates both required Python packages:

```powershell
py -m pip install --user --upgrade pyserial pillow
```

Manual start:

```powershell
py tactical_display_mirror.py COM5 --baud 460800 --mode pixel
py tactical_display_mirror.py COM5 --baud 460800 --mode hd
```

## PC controls

- Left/right or A/D: change pages
- Up/down or W/S: move through menus and selections
- Mouse wheel: move up/down
- Space or Enter: select/confirm
- Escape or Backspace: go back
- F11: toggle fullscreen
- F12 or Ctrl+S: save a PNG screenshot

Screenshots are written to the `screenshots` folder beside the viewer script.

## Display modes

### Pixel sharp

Uses nearest-neighbor scaling. Every tracker pixel stays hard-edged, which is best for inspecting the native 160x80 layout and small fonts.

### HD smoothed

Uses high-quality Lanczos scaling. It is visually smoother in a large window or fullscreen, while the underlying tracker frame remains unchanged.

## Status line

The bottom status line shows:

- USB connection state and COM port
- selected baud rate
- `RGB565/TMF3`, `Mono/TMF3` or a legacy format
- native frame resolution
- decoded frames per second
- age of the newest complete frame
- measured USB command ACK round-trip time

## Control and ACK protocol

The viewer assigns every control command an ID:

```text
@TMC <request-id> <LEFT|RIGHT|UP|DOWN|SPACE|ENTER|BACK>
```

The firmware interrupts the current image transfer, queues the event through `InputBroker`, and replies:

```text
@TMA <request-id> <OK|NOINPUT|ERR> <firmware-millis>
```

The viewer measures the time from sending the command to receiving this ACK and displays it as USB RTT. Legacy commands without a request ID remain accepted.

Capability negotiation is initiated with:

```text
@TMC CAPS TMF3 ACK1
```

The firmware responds with:

```text
@TMA CAPS TMF3 ACK1
```

## Frame protocol

Current firmware uses short chunks:

```text
@TMF3 <M|C> <width> <height> <frame-id> <chunk-index> <chunk-count> <hex-data>
```

- `M`: native one-bit ThingPulse page-buffer data
- `C`: RGB565 RLE records consisting of `count`, `color-high`, `color-low`
- unrelated Meshtastic log lines may appear between chunks
- incomplete older frames are discarded when a newer sequence starts
- the viewer keeps only the newest completed frame, avoiding a delayed backlog

Legacy complete-frame protocols remain supported:

```text
@TMF <width> <height> <mono-hex>
@TMF2 <width> <height> <frame-id> <RGB565-RLE-hex>
```

## Safety and scope

- The mirror is compiled only for the configured Tactical target.
- It does not alter LoRa packets, GPS handling, channels or stored settings.
- Remote controls use the same input path as physical buttons and a configured EC11.
- The ESP32-S3 native USB-CDC link is not a classic UART; the selected baud value is still kept consistent on the PC side, while responsiveness mainly comes from short chunks and command prioritization.
