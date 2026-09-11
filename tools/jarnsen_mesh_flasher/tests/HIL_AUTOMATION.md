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

On `feat/mini-serial-flasher`, the normal Windows Flasher build runs an additional destructive full-cycle test when exactly one wired `LILYGO T-Beam Supreme` is detected on the `jarn-pc` self-hosted runner.

The first stage uses `supreme_full_hil.py` and exercises the real First-Flash path:

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

## One-node feature matrix

After the first-flash stage passes, `supreme_feature_matrix_hil.py` continues on the same physical Supreme. This deliberately uses one dedicated node to cover every meaningful Flasher function that can be verified with one device:

1. run hardware-backed preflight for `update`, `repair` and `factory`
2. read/export the node profile through the normal Flasher service path
3. write and verify `TAK TRACKER`, including persistent JARNSEN role and deterministic names
4. write and verify `TAK REPEATER`, including persistent JARNSEN role and deterministic names
5. switch back to canonical `TAK`
6. reboot twice and prove profile, role, names, board and firmware identity survive both restarts
7. perform a real firmware-only update and prove profile, role and names remain unchanged
8. reboot into raw USB service mode and download a real `JARNSEN_TOOL_FULL` diagnostic log; both protocol markers must be present
9. execute the production `FlasherApp._perform_flash(..., flash_mode="repair")` orchestration through a headless UI facade, including backup, full factory flash, profile restore, names, reboot and verification
10. perform a fresh device rescan and require exactly one detected `tbeam_supreme`, then run the final state verification again

The matrix therefore exercises real hardware paths for discovery, board identification, preflight, firmware resolving/validation, full backup, factory flash, profile export, profile writes, all Supreme-compatible functional role transitions, long/short name writes, persistent role service, repeated reboot persistence, firmware-only update, raw USB diagnostic-log download, production repair orchestration and final device rescan.

`DRONE REPEATER` is intentionally not written to the Supreme because the current compatibility contract restricts it to the Heltec Wireless Tracker V1.1 firmware line.

With only one physical node, features that inherently require another independent radio/device cannot be proven end-to-end: over-the-air peer exchange, multi-hop/repeater forwarding, interference/range behavior and the physical swap portion of serial multi-node production flashing. Those require at least a second node and remain outside this one-node HIL gate.

The test records per-phase timings and a non-secret trace under `ci-logs/supreme-hil`. The feature matrix extends the same `report.json`, so a failed phase leaves the exact hardware stage and timing visible in the workflow artifacts.

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
