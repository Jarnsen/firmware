#include "configuration.h"

#if defined(HELTEC_TRACKER_V1_1) && defined(VEHICLE_MOTION_WAKE_PIN)

#include "input/ButtonThread.h"
#include "mesh/MeshModule.h"
#include "sleep.h"

#if HAS_BUTTON && defined(BUTTON_PIN)
extern ButtonThread *UserButtonThread;
#endif

static bool takTrackerButtonOwnerEnabled()
{
    return config.device.role == meshtastic_Config_DeviceConfig_Role_TAK ||
           config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER;
}

class TakTrackerButtonOwnershipModule : public MeshModule, public Observer<esp_sleep_wakeup_cause_t>
{
  public:
    TakTrackerButtonOwnershipModule() : MeshModule("tak-tracker-button-owner") {}

    void setup() override
    {
        MeshModule::setup();
        if (!takTrackerButtonOwnerEnabled())
            return;

#ifdef BUTTON_PIN
        const uint8_t pin = config.device.button_gpio ? config.device.button_gpio : BUTTON_PIN;
        pinMode(pin, INPUT_PULLUP);
#endif

#if HAS_BUTTON && defined(BUTTON_PIN)
        if (UserButtonThread) {
            UserButtonThread->detachButtonInterrupts();
            UserButtonThread->disable();
            LOG_INFO("Tracker custom role: generic Meshtastic UserButton disabled; "
                     "GPIO0 exclusively owned by service UI");
        }
#endif

        observe(&notifyLightSleepEnd);
    }

  protected:
    bool wantPacket(const meshtastic_MeshPacket *) override { return false; }

    int onNotify(esp_sleep_wakeup_cause_t) override
    {
        if (!takTrackerButtonOwnerEnabled())
            return 0;
#if HAS_BUTTON && defined(BUTTON_PIN)
        if (UserButtonThread)
            UserButtonThread->detachButtonInterrupts();
#endif
        return 0;
    }
};

static TakTrackerButtonOwnershipModule takTrackerButtonOwnershipModule;

#endif // HELTEC_TRACKER_V1_1 && VEHICLE_MOTION_WAKE_PIN
