# JARNSEN MESH Flasher

Windows mini flasher for provisioning JARNSEN MESH nodes.

## Supported targets

- Heltec Wireless Tracker V1.1 (`heltec-wireless-tracker`)
- Heltec V3 (`heltec-v3`)

The app detects an already-running Meshtastic node automatically. If a device is blank or only in bootloader mode, the board can be selected manually.

## Automatic workflow

1. Detect the serial device and board.
2. Read and save a reusable Meshtastic base profile from a configured master node, or load an existing `.yaml`, `.yml` or `.cfg` profile.
3. Resolve the newest successful JARNSEN MESH firmware artifact for the selected board from GitHub Actions.
4. Download and validate the factory image, firmware metadata, OTA system image and LittleFS image.
5. Create a full flash safety backup before any destructive operation.
6. Erase and flash Factory + OTA + LittleFS using the offsets from the firmware metadata.
7. Wait for the node to reconnect over serial.
8. Restore the saved base profile.
9. Set Long Name and Short Name.
10. Reboot and verify the node with the Meshtastic serial API.

Backups, profiles, firmware cache and logs are stored below `%LOCALAPPDATA%\JarnsenMeshFlasher`.

## GitHub authentication

Reading public workflow metadata works anonymously. Downloading GitHub Actions artifacts requires authentication. The app automatically uses `GH_TOKEN` / `GITHUB_TOKEN`, or the token from an existing `gh auth login` session.

## Development

```powershell
cd tools\jarnsen_mesh_flasher
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

The packaged Windows build contains two executables in the same folder:

- `JarnsenMeshFlasher.exe` – GUI
- `_JarnsenMeshHelper.exe` – bundled Meshtastic/esptool command helper used by the GUI

Do not separate the helper from the GUI executable.
