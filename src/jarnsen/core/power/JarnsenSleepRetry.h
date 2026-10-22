#pragma once

#include "mesh/Throttle.h"

#include <cstdint>

namespace jarnsen
{

class SleepStartRetryGate
{
  public:
    bool ready() const { return !failed_ || !Throttle::isWithinTimespanMs(failedAtMs_, 250U); }

    void recordResult(int result, uint32_t nowMs)
    {
        failed_ = result != 0;
        failedAtMs_ = nowMs;
    }

  private:
    bool failed_ = false;
    uint32_t failedAtMs_ = 0;
};

} // namespace jarnsen
