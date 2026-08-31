#pragma once

// Compatibility facade for migration-only consumers. Platform selection now
// belongs to the hardware layer; new Core code must depend on the neutral
// NodeServiceDescriptor model instead of this header.
#include "jarnsen/hardware/JarnsenServicePlatform.h"
