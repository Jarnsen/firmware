# JARNSEN-MESH-FLASHER Hardware-in-the-Loop

The Windows self-hosted runner can validate attached supported USB nodes without hard-coded COM ports.

## General read-only hardware contract

`hardware_flash_contract.py` auto-discovers attached wired USB serial boards, identifies their board keys, and performs non-destructive checks:

- node read/board detection
- firmware release resolution and flash preflight
- Build 168+ `JARNSEN_TOOL_ROLE_INFO` verification with `role_api=1`

Bluetooth serial ports are ignored for auto-discovery.

The older optional firmware-only destructive path remains separately armed through:

- `JARNSEN_FLASHER_HW_FLASH=1`
- `JARNSEN_FLASHER_HW_FLASH_CONFIRM=I_ACCEPT_FIRMWARE_FLASH`

## Dedicated T-Beam Supreme full-cycle HIL

On `feat/mini-serial-flasher`, the normal Windows Flasher build runs an additional full-cycle test when exactly one wired `LILYGO T-Beam Supreme` is detected on the `jarn-pc` self-hosted runner.

The full-cycle test uses `supreme_full_hil.py` and exercises the real First-Flash path:

1. auto-discover the wired Supreme and independently confirm it a second time
2. activate the canonical TAK functional profile for the test
3. resolve and validate the latest Supreme Unified-Core firmware
4. run the normal `provision` preflight
5. create the full safety backup
6. erase/write the validated Supreme factory image using the Flasher runtime
7. wait for USB/application return
8. write the TAK profile and persistent firmware role
9. write deterministic HIL Long/Short names
10. reboot and wait for stable return
11. verify board, firmware version/build, profile, names and `role_api=1` with `persisted=1`

The test records per-phase timings and a non-secret trace under `ci-logs/supreme-hil`.

### Safety boundaries

The destructive full-cycle path is intentionally narrow:

- automatic destructive execution is accepted only on the `feat/mini-serial-flasher` GitHub Actions ref
- only a node detected and then independently re-confirmed as `tbeam_supreme` can be erased
- zero Supreme nodes means a clean skip
- more than one Supreme node means a hard failure rather than guessing
- Bluetooth/virtual COM ports are not eligible
- all normal Flasher board support remains unchanged; the Supreme restriction applies only to this dedicated destructive HIL path

A local manual execution is blocked unless `JARNSEN_SUPREME_HIL_CONFIRM=I_ACCEPT_SUPREME_FACTORY_FLASH` is set explicitly.

The attached Supreme is therefore a dedicated test node on this feature branch: leaving it connected authorizes the branch HIL run to erase/reflash and reconfigure that Supreme as part of regression testing.
