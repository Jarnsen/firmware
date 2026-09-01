# JARNSEN MESH Flasher

Windows mini flasher for provisioning JARNSEN MESH nodes.

## Target workflow

1. Detect connected serial device and board.
2. Read and save a reusable configuration profile from a configured master node.
3. Fetch the newest successful JARNSEN MESH firmware artifact for the detected board from GitHub.
4. Create a safety backup of the target flash before destructive flashing.
5. Flash the complete factory image / OTA-capable layout for the board.
6. Reconnect over the Meshtastic serial API.
7. Restore the saved base configuration, channels and module configuration.
8. Ask only for Long Name and Short Name, apply them, reboot and verify.

The implementation is intentionally split into independent services so hardware detection, GitHub release selection, flashing and provisioning can be tested separately before wiring the GUI to them.
