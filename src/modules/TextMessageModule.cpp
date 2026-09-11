#include "TextMessageModule.h"
#include "MeshService.h"
#include "MessageStore.h"
#include "NodeDB.h"
#include "PowerFSM.h"
#include "buzz.h"
#include "configuration.h"
#include "graphics/Screen.h"
#include "graphics/SharedUIDisplay.h"
#include "graphics/draw/MessageRenderer.h"
#include "main.h"
TextMessageModule *textMessageModule;

ProcessMessage TextMessageModule::handleReceived(const meshtastic_MeshPacket &mp)
{
#if defined(DEBUG_PORT) && !defined(DEBUG_MUTE)
    auto &p = mp.decoded;
    LOG_INFO("Received text msg from=0x%08x, id=0x%08x, msg=%.*s", mp.from, mp.id, p.payload.size, p.payload.bytes);
#endif
    // add packet ID to the rolling list of packets
    textPacketList[textPacketListIndex] = mp.id;
    textPacketListIndex = (textPacketListIndex + 1) % TEXT_PACKET_LIST_SIZE;

    IF_SCREEN(
        // Guard against running in MeshtasticUI or with no screen
        if (config.display.displaymode != meshtastic_Config_DisplayConfig_DisplayMode_COLOR) {
            // Store in the central message history
            const StoredMessage *sm = messageStore.tryAddFromPacket(mp);
            if (!sm)
                return ProcessMessage::CONTINUE;

            // Pass message to renderer (banner + thread switching + scroll reset)
            // Use the global Screen singleton to retrieve the current OLED display
            auto *display = screen ? screen->getDisplayDevice() : nullptr;
            graphics::MessageRenderer::handleNewMessage(display, *sm, mp);
        })
    // Only trigger screen wake if configuration allows it
    if (shouldWakeOnReceivedMessage()) {
        powerFSM.trigger(EVENT_RECEIVED_MSG);
    }

    // Notify any observers (e.g. external modules that care about packets)
    notifyObservers(&mp);

    return ProcessMessage::CONTINUE; // Let others look at this message also if they want
}


bool TextMessageModule::sendLocalBroadcast(const char *message, uint8_t channel)
{
    if (!message || !message[0] || !service)
        return false;
    meshtastic_MeshPacket *packet = allocDataPacket();
    if (!packet)
        return false;
    packet->to = NODENUM_BROADCAST;
    packet->channel = channel;
    packet->want_ack = false;
    packet->decoded.dest = NODENUM_BROADCAST;
    size_t length = strlen(message);
    if (length > sizeof(packet->decoded.payload.bytes))
        length = sizeof(packet->decoded.payload.bytes);
    packet->decoded.payload.size = length;
    memcpy(packet->decoded.payload.bytes, message, length);
    service->sendToMesh(packet, RX_SRC_LOCAL, true);
    return true;
}

bool TextMessageModule::wantPacket(const meshtastic_MeshPacket *p)
{
    return MeshService::isTextPayload(p);
}

bool TextMessageModule::recentlySeen(uint32_t id)
{
    for (size_t i = 0; i < TEXT_PACKET_LIST_SIZE; i++) {
        if (textPacketList[i] != 0 && textPacketList[i] == id) {
            return true;
        }
    }
    return false;
}
