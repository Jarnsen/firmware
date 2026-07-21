#include "TacticalDisplayMirrorThread.h"

#if defined(HAS_TACTICAL_DISPLAY_MIRROR) && HAS_TACTICAL_DISPLAY_MIRROR && HAS_SCREEN

#include "TacticalDisplayMirror.h"
#include "graphics/Screen.h"
#include "main.h"

namespace graphics
{
TacticalDisplayMirrorThread::TacticalDisplayMirrorThread() : concurrency::OSThread("display-mirror", 250) {}

int32_t TacticalDisplayMirrorThread::runOnce()
{
    if (screen != nullptr && screen->isScreenOn()) {
        mirrorDisplayFrame(screen->getDisplayDevice());
    }
    return 250;
}
} // namespace graphics

#endif
