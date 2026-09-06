#pragma once

// Shared runtime ownership bridge for the JARNSEN five-page display.
// These functions are no-ops on unsupported boards and on the Heltec Tracker
// V1.1, whose richer TrackerStatusModule remains the hardware adapter there.
bool jarnsenDisplayOwnsScreen();
bool jarnsenDisplayStockUiActive();
void jarnsenDisplayRequestFocus();
bool jarnsenDisplayHandleFrameStep(bool next);
bool jarnsenDisplayHandleSelect();
bool jarnsenDisplayHandleBack();
