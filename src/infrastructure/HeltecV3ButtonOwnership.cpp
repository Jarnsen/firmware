#include "configuration.h"

#ifdef _VARIANT_HELTEC_V3

#include "input/ButtonThread.h"
#include "mesh/MeshModule.h"
#include "sleep.h"

#if HAS_BUTTON && defined(BUTTON_PIN)
extern ButtonThread *UserButtonThread;
#endif

static bool v3ButtonOwnerRoleEnabled()
{
    return config.device.role == meshtastic_Config_DeviceConfig_Role_ROUTER_LATE ||
           config.device.role == meshtastic_Config_DeviceConfig_Role_REPEATER;
}

class HeltecV3ButtonOwnershipModule : public MeshModule, public Observer<esp_sleep_wakeup_cause_t>
{
  public:
    HeltecV3ButtonOwnershipModule() : MeshModule("v3-button-owner") {}

    void setup() override
    {
        MeshModule::setup();
        if (!v3ButtonOwnerRoleEnabled())
            return;

#ifdef BUTTON_PIN
        pinMode(BUTTON_PIN, INPUT_PULLUP);
#endif

#if HAS_BUTTON && defined(BUTTON_PIN)
        // InputBroker creates the normal OneButton GPIO ISR before lateInitVariant.
        // Our V3 repeater service polls GPIO0 itself and uses ESP GPIO wake, so
        // keeping that ISR installed only creates a second owner and can deadlock
        // inside OneButton::tick() while BLE/display work is starting.
        if (UserButtonThread) {
            UserButtonThread->detachButtonInterrupts();
            UserButtonThread->disable();
            LOG_INFO("Heltec V3 repeater: generic Meshtastic UserButton disabled; "
                     "GPIO0 exclusively owned by service policy");
        }
#endif

        observe(&notifyLightSleepEnd);
    }

  protected:
    bool wantPacket(const meshtastic_MeshPacket *) override { return false; }

    int onNotify(esp_sleep_wakeup_cause_t) override
    {
        if (!v3ButtonOwnerRoleEnabled())
            return 0;

#if HAS_BUTTON && defined(BUTTON_PIN)
        // ButtonThread's own light-sleep observer reattaches its CHANGE ISR even
        // after the thread is disabled. We register later in setup(), so remove
        // that ISR again immediately after every wake. ESP GPIO wake configured
        // by HeltecV3RepeaterPolicy remains independent of attachInterrupt().
        if (UserButtonThread)
            UserButtonThread->detachButtonInterrupts();
#endif
        return 0;
    }
};

// MeshModule static construction is supported; setup() runs only after the
// normal firmware objects exist, which is exactly when UserButtonThread is safe
// to detach/disable.
static HeltecV3ButtonOwnershipModule heltecV3ButtonOwnershipModule;

#endif // _VARIANT_HELTEC_V3
