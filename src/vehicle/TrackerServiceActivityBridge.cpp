#include "configuration.h"

#if defined(HELTEC_TRACKER_V1_1) && defined(VEHICLE_MOTION_WAKE_PIN) && !MESHTASTIC_EXCLUDE_GPS

#include "vehicle/TrackerCommonPolicy.h"

// NimBLE reports only meaningful (non-empty) client traffic through this weak
// hook. Bind it to the Tracker service policy so an active log download,
// Liveview or normal PhoneAPI exchange keeps the service window awake instead
// of being cut off by the idle timeout.
extern "C" void meshtasticTrackerBleActivity()
{
    trackerCommonBleActivity();
}

// PowerFSM emits EVENT_CONTACT_FROM_PHONE for normal Bluetooth PhoneAPI
// traffic. Route that signal through the same activity counter. The Tracker
// policy deliberately applies a small burst threshold before it refreshes the
// service idle timer, so passive connections/polling do not keep the node awake
// forever.
extern "C" void meshtasticVehiclePhoneContact()
{
    trackerCommonBleActivity();
}

#endif
