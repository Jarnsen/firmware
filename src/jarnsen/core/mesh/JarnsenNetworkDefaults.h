#pragma once

// Shared TAK Netz 26 defaults for JARNSEN boards. CI injects the fleet-wide
// AES-256 key at build time from a protected secret; do not commit its bytes.
#include "mesh/generated/meshtastic/config.pb.h"

#if defined(HELTEC_TRACKER_V1_1) || defined(HELTEC_V3) || defined(_VARIANT_HELTEC_V3) || \
    defined(HELTEC_V4) || defined(_VARIANT_HELTEC_V4) || defined(SEEED_WIO_TRACKER_L1) || \
    defined(TBEAM_V10) || defined(LILYGO_TBEAM_S3_CORE)
#define JARNSEN_NETWORK_TARGET_BOARD 1
#else
#define JARNSEN_NETWORK_TARGET_BOARD 0
#endif

#if JARNSEN_NETWORK_TARGET_BOARD
#include "JarnsenNetworkKey.generated.h"
#endif

namespace jarnsen
{
constexpr char TAK_NETWORK_PRIMARY_NAME[] = "TAK Netz 26";
constexpr uint32_t TAK_NETWORK_PRIMARY_ID = 4026805322U;
constexpr meshtastic_Config_LoRaConfig_RegionCode TAK_NETWORK_REGION =
    meshtastic_Config_LoRaConfig_RegionCode_EU_868;
constexpr meshtastic_Config_LoRaConfig_ModemPreset TAK_NETWORK_MODEM =
    meshtastic_Config_LoRaConfig_ModemPreset_MEDIUM_SLOW;
constexpr uint8_t TAK_NETWORK_HOPS = 7U;
constexpr int32_t TAK_NETWORK_TX_AUTO = 0;
constexpr uint32_t TAK_NETWORK_POSITION_PRECISION_BITS = 32U;
static_assert(sizeof(TAK_NETWORK_PRIMARY_NAME) <= 12U, "TAK Netz 26 must fit the Meshtastic 12-byte channel name");
} // namespace jarnsen
