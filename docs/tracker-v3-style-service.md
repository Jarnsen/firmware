# Tracker V1.1 V3-style service behavior

For `TAK_TRACKER`, GPIO0 now opens the same maintenance interaction model proven on the Heltec V3 repeater:

- Power saving remains enabled in configuration.
- Hardware sleep is vetoed only while the local service window is active.
- Bluetooth is initialized only for the service window and deinitialized afterwards.
- The service window idles out after 120 seconds and has a 15 minute hard cap.
- The display is visible for 20 seconds (10 seconds at low battery).
- Service pages use one exclusive full-screen frame, reasserted at 1 Hz while visible so the stock Meshtastic UI cannot replace it during a one-off UI rebuild.
- The Bluetooth pairing PIN is composited over the service frame when required.
- Short GPIO0 presses advance the pages; long presses change supported settings.
- Vehicle motion/GNSS tracking remains handled by the existing TAK_TRACKER motion state machine and returns to deep sleep outside service.

The `TAK` role keeps its existing light-sleep leader policy and its own exclusive service pages.
