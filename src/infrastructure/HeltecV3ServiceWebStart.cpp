#include "configuration.h"

#if defined(_VARIANT_HELTEC_V3) && HAS_WIFI

#include "concurrency/OSThread.h"
#include "infrastructure/HeltecV3DiagnosticLog.h"
#include "mesh/http/JarnsenServiceWeb.h"

#include <atomic>

namespace
{
std::atomic<bool> startRequested{false};

class V3ServiceWebStartWorker : public concurrency::OSThread
{
  public:
    V3ServiceWebStartWorker() : concurrency::OSThread("V3ServiceWebStart") {}

  protected:
    int32_t runOnce() override
    {
        if (!startRequested.exchange(false))
            return 250;

        if (jarnsenServiceWebActive())
            return 250;

        heltecV3DiagLog("WIFI_INIT", "deferred-start=1");
        heltecV3DiagLog("AP_START", "begin");
        const bool started = jarnsenServiceWebStart();
        if (started) {
            heltecV3DiagLog("AP_OK", "ssid=%s ip=%s", jarnsenServiceWebSsid(), jarnsenServiceWebAddress());
            heltecV3DiagLog("WEB_OK", "http=80");
        } else {
            heltecV3DiagLog("WIFI_FAIL", "%s", jarnsenServiceWebLastError()[0] ? jarnsenServiceWebLastError() : "start failed");
        }
        return 250;
    }
};

V3ServiceWebStartWorker *worker = nullptr;
} // namespace

bool jarnsenServiceWebRequestStart()
{
    if (jarnsenServiceWebActive())
        return true;

    heltecV3DiagLog("WIFI_REQ", "queued from service menu");
    startRequested.store(true);
    if (!worker)
        worker = new V3ServiceWebStartWorker();
    worker->setIntervalFromNow(50);
    return true;
}

#endif
