#pragma once

namespace jarnsen
{

// Installs the JARNSEN node-state sync module once. Every JARNSEN role keeps a
// bounded position cache; responders are elected by role so a repeater answers
// before TAK/Tracker peers and duplicate cache floods are suppressed.
void nodeStateSyncInit();

} // namespace jarnsen
