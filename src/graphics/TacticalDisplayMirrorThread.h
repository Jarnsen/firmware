#pragma once

#if defined(HAS_TACTICAL_DISPLAY_MIRROR) && HAS_TACTICAL_DISPLAY_MIRROR && HAS_SCREEN

#include "concurrency/OSThread.h"

namespace graphics
{
class TacticalDisplayMirrorThread : public concurrency::OSThread
{
  public:
    TacticalDisplayMirrorThread();

  protected:
    int32_t runOnce() override;
};
} // namespace graphics

#endif
