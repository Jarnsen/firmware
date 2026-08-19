#include "configuration.h"

#ifdef _VARIANT_HELTEC_WIRELESS_TRACKER

#include "GPS.h"
#include "GpioLogic.h"
#include "graphics/TFTDisplay.h"

#if defined(HELTEC_TRACKER_V1_1) && defined(VEHICLE_MOTION_WAKE_PIN) && !MESHTASTIC_EXCLUDE_GPS
void setupHeltecTrackerV11VehicleMotionTracker();
void setupVehicleServicePolicy();
#endif

// Heltec tracker specific init
void lateInitVariant()
{
    // LOG_DEBUG("Heltec tracker initVariant");

#ifndef MESHTASTIC_EXCLUDE_GPS
    GpioVirtPin *virtGpsEnable = gps ? gps->enablePin : new GpioVirtPin();
#else
    GpioVirtPin *virtGpsEnable = new GpioVirtPin();
#endif

#ifndef MESHTASTIC_EXCLUDE_SCREEN
    // On this board we are actually using the backlightEnable signal to already be controlling a physical enable to the
    // display controller.  But we'd _ALSO_ like to have that signal drive a virtual GPIO.  So nest it as needed.
    GpioVirtPin *virtScreenEnable = new GpioVirtPin();
    if (TFTDisplay::backlightEnable) {
        GpioPin *physScreenEnable = TFTDisplay::backlightEnable;
        GpioPin *splitter = new GpioSplitter(virtScreenEnable, physScreenEnable);
        TFTDisplay::backlightEnable = splitter;

        // Assume screen is initially powered
        splitter->set(true);
    }
#endif

#if defined(VEXT_ENABLE) && (!defined(MESHTASTIC_EXCLUDE_GPS) || !defined(MESHTASTIC_EXCLUDE_SCREEN))
    // If either the GPS or the screen is on, turn on the external power regulator
    GpioPin *hwEnable = new GpioHwPin(VEXT_ENABLE);
    new GpioBinaryTransformer(virtGpsEnable, virtScreenEnable, hwEnable, GpioBinaryTransformer::Or);
#endif

#if defined(HELTEC_TRACKER_V1_1) && defined(VEHICLE_MOTION_WAKE_PIN) && !MESHTASTIC_EXCLUDE_GPS
    setupHeltecTrackerV11VehicleMotionTracker();
    setupVehicleServicePolicy();
#endif
}

#endif