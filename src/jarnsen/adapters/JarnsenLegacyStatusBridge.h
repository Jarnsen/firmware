#pragma once

namespace jarnsen
{

// Transitional adapter while board policies still own some runtime state.
// Safe to call repeatedly from service/display entry points.
void ensureLegacyStatusBridge();

} // namespace jarnsen
