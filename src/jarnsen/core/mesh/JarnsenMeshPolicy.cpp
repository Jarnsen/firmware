#include "jarnsen/core/mesh/JarnsenMeshPolicy.h"

namespace jarnsen
{
namespace
{

constexpr MeshPolicyState emptyState{};
constexpr MeshPolicyResult fallbackResult = normalizeMeshPolicy(emptyState, 0, true);
static_assert(fallbackResult.corrected, "Empty mesh state must be normalized");
static_assert(fallbackResult.state.positionBroadcastSecs == MESH_POLICY_DEFAULT_POSITION_INTERVAL_SECS,
              "Mesh policy must provide the default position interval");
static_assert(fallbackResult.state.positionSmartEnabled, "Mesh policy must force smart position broadcast on");
static_assert(fallbackResult.state.neighborEnabled && fallbackResult.state.neighborTransmitOverLora,
              "Mesh policy must apply the desired neighbor state consistently");
static_assert(fallbackResult.state.neighborUpdateInterval == MESH_POLICY_MIN_NEIGHBOR_INTERVAL_SECS,
              "Mesh policy must enforce the minimum neighbor interval");

constexpr MeshPolicyState validState{3600U, true, false, false, 21600U};
constexpr MeshPolicyResult unchangedResult = normalizeMeshPolicy(validState, 1800U, false);
static_assert(!unchangedResult.corrected, "Already-normalized mesh state must remain unchanged");

} // namespace
} // namespace jarnsen
