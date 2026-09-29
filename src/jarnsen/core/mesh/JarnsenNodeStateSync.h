#pragma once

#include <cstdint>

namespace jarnsen
{

// Installs the JARNSEN node-state sync module once. Every JARNSEN role keeps a
// bounded position cache; responders are elected by role so a repeater answers
// before TAK/Tracker peers and duplicate cache floods are suppressed.
void nodeStateSyncInit();

// FINAL_POS confirmation is deliberately separate from native Meshtastic ACK:
// broadcast packets cannot request a native ACK. The source asks JARNSEN peers
// whether the exact mesh packet ID made it into their position cache.
bool nodeStateSyncRequestPositionReceipt(uint32_t packetId);
bool nodeStateSyncPositionReceiptConfirmed(uint32_t packetId);
void nodeStateSyncCancelPositionReceipt();

} // namespace jarnsen
