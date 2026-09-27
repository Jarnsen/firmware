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


// Unified one-button interaction hook. Called on the raw physical down-edge
// before OneButton emits short/long semantics so wake/service behavior matches
// Tracker V1.1: first press wakes/opens service, release does not also navigate.
void jarnsenDisplayHandlePhysicalPressStart();

// Called by the generic ButtonThread immediately after a real Userbutton
// light-sleep wake. The wake press is consumed separately by ButtonThread.
void jarnsenDisplayHandleLightSleepButtonWake();
