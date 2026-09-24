#pragma once

// Shared runtime ownership bridge for the JARNSEN five-page display.
// These functions are no-ops on unsupported boards and on the Heltec Tracker
// V1.1, whose richer TrackerStatusModule remains the hardware adapter there.
bool jarnsenDisplayOwnsScreen();
bool jarnsenDisplayStockUiActive();
void jarnsenDisplayRequestFocus();
bool jarnsenDisplayHandleFrameStep(bool next);
// Maps the physical short press on one-button Unified Core boards to the
// Tracker-style "next page / next menu item" action. Multi-input boards such
// as Wio Tracker L1 keep their directional input behavior.
bool jarnsenDisplayHandlePrimaryPress();
bool jarnsenDisplayHandleSelect();
bool jarnsenDisplayHandleBack();
