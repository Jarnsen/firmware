# JARNSEN MESH Flasher

Windows mini flasher for provisioning JARNSEN MESH nodes.

## Supported targets

- Heltec Wireless Tracker V1.1 (`heltec-wireless-tracker`)
- Heltec V3 (`heltec-v3`)
- Seeed Wio Tracker L1 (`seeed_wio_tracker_L1`)
- Heltec V4 (`heltec-v4`)
- LILYGO T-Beam (`tbeam`)
- LILYGO T-Beam Supreme (`tbeam-s3-core`)

The app detects an already-running Meshtastic node automatically. If a device is blank or only in bootloader mode, the board can be selected manually.

## Flash modes

- **Firmware-Update** writes only the validated application partitions (or the Wio UF2). Profile, names, channels, NVS and logs remain unchanged.
- **Reparatur** creates a safety backup, reinstalls the complete firmware and restores the selected profile and names.
- **Werkseinstellung** creates a safety backup and performs a clean installation without restoring local settings.
- **Serie** provisions one positively identified device at a time and records every attempt.

Every mode uses the same preflight contract: connected board, firmware board, version, checksums, image headers, flash transport and dynamic partition targets must agree before a write starts. Interrupted ESP transfers are retried at progressively safer baud rates.

## Automatic repair workflow

1. Detect the serial device and board.
2. Read and save a reusable Meshtastic base profile from a configured master node, or load an existing `.yaml`, `.yml` or `.cfg` profile.
3. Resolve the newest successful JARNSEN MESH firmware artifact for the selected board from GitHub Actions.
4. Continue or reuse the cached artifact download and validate SHA256, image format and board identity.
5. Create a full flash safety backup before any destructive operation.
6. Erase and flash the board-specific Factory image using the package's validated layout.
7. Wait for the node to reconnect over serial.
8. Restore the saved base profile.
9. Set Long Name and Short Name.
10. Reboot and verify the node with the Meshtastic serial API.

Backups, profiles, firmware cache and logs are stored below `%LOCALAPPDATA%\JarnsenMeshFlasher`.
The protocol panel can create a redacted support ZIP. It contains runtime, device and artifact metadata plus the application log, but no profiles, firmware files, PSKs, tokens or private keys.

## Optional connected-board contract

The Windows workflow always runs the hardware contract in safe read-only mode. It skips when no explicit port map is configured:

```powershell
$env:JARNSEN_FLASHER_HW_PORTS='tracker=COM3,repeater=COM4,wio=COM5'
python tests\hardware_flash_contract.py
```

Real update writes require both explicit safety switches:

```powershell
$env:JARNSEN_FLASHER_HW_FLASH='1'
$env:JARNSEN_FLASHER_HW_FLASH_CONFIRM='I_ACCEPT_FIRMWARE_FLASH'
python tests\hardware_flash_contract.py
```

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
