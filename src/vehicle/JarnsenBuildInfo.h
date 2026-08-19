#pragma once

#define JARNSEN_FIRMWARE_VERSION "JARN-MESH 1.1"

#if __has_include("JarnsenBuildGenerated.h")
#include "JarnsenBuildGenerated.h"
#endif

#ifndef JARNSEN_BUILD_SHA
#define JARNSEN_BUILD_SHA "local"
#endif
