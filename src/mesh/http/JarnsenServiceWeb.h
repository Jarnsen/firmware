#pragma once

#include "configuration.h"

#if defined(ARCH_ESP32) && HAS_WIFI && (defined(_VARIANT_HELTEC_V3) || defined(HELTEC_TRACKER_V1_1))

bool jarnsenServiceWebStart();
bool jarnsenServiceWebRequestStart();
void jarnsenServiceWebStop();
void jarnsenServiceWebPump();
bool jarnsenServiceWebActive();
const char *jarnsenServiceWebSsid();
const char *jarnsenServiceWebPassword();
const char *jarnsenServiceWebAddress();
const char *jarnsenServiceWebLastError();

#if defined(_VARIANT_HELTEC_V3) && defined(JARNSEN_SERVICE_WEB_DEFER_FROM_UI)
#define jarnsenServiceWebStart() jarnsenServiceWebRequestStart()
#endif

#else

inline bool jarnsenServiceWebStart()
{
    return false;
}
inline bool jarnsenServiceWebRequestStart()
{
    return false;
}
inline void jarnsenServiceWebStop() {}
inline void jarnsenServiceWebPump() {}
inline bool jarnsenServiceWebActive()
{
    return false;
}
inline const char *jarnsenServiceWebSsid()
{
    return "--";
}
inline const char *jarnsenServiceWebPassword()
{
    return "24011980";
}
inline const char *jarnsenServiceWebAddress()
{
    return "192.168.4.1";
}
inline const char *jarnsenServiceWebLastError()
{
    return "WLAN nicht verfügbar";
}

#endif
