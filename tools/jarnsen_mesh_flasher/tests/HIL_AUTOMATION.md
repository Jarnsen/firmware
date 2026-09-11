# JARNSEN-MESH-FLASHER Hardware-in-the-Loop

The Windows self-hosted runner can validate an attached supported USB node without a hard-coded COM port.

## Default CI behavior

`hardware_flash_contract.py` auto-discovers one attached wired USB serial board, identifies its board key, and performs non-destructive checks:

- node read/board detection
- firmware release resolution and flash preflight
- Build 168+ `JARNSEN_TOOL_ROLE_INFO` verification with `role_api=1`

Bluetooth serial ports are ignored for auto-discovery.

## Destructive flashing remains armed separately

Merely leaving a node connected never authorizes a firmware write. The existing firmware-only HIL flash path requires both runner environment variables:

- `JARNSEN_FLASHER_HW_FLASH=1`
- `JARNSEN_FLASHER_HW_FLASH_CONFIRM=I_ACCEPT_FIRMWARE_FLASH`

This keeps automatic regression checking useful while preventing an attached field node from being reflashed accidentally by an ordinary commit.
