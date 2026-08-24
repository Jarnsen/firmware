#pragma once

void trackerStatusRequestFocus();
void trackerStatusSetMotionActive(bool active);
bool trackerServiceMenuActive();
bool trackerServicePageVisible();
const char *trackerStatusCurrentPageText();
void trackerServiceMenuOpen();
void trackerServiceMenuShortPress();
void trackerServiceMenuSelect();
void trackerServiceMenuPump();
void trackerServiceMenuClose();
void trackerServiceMenuForceClose();
