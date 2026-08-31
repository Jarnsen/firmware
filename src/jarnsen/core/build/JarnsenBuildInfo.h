#pragma once

// JARNSEN-MESH has one product/version identity across all hardware builds.
// CI injects JarnsenBuildGenerated.h from the centrally resolved VERSION.json
// policy. Local builds without generated metadata intentionally use a local
// fallback instead of duplicating the release version string here.
#if __has_include("jarnsen/core/build/JarnsenBuildGenerated.h")
#include "jarnsen/core/build/JarnsenBuildGenerated.h"
#endif

#ifndef JARNSEN_FIRMWARE_PRODUCT
#define JARNSEN_FIRMWARE_PRODUCT "JARNSEN-MESH"
#endif

#ifndef JARNSEN_FIRMWARE_SEMVER
#define JARNSEN_FIRMWARE_SEMVER "v0.0.0-local"
#endif

#ifndef JARNSEN_BOOT_HARDWARE
#define JARNSEN_BOOT_HARDWARE "JARNSEN NODE"
#endif

#ifndef JARNSEN_BUILD_SHA
#define JARNSEN_BUILD_SHA "local"
#endif

#ifndef JARNSEN_BUILD_NUMBER
#define JARNSEN_BUILD_NUMBER 0
#endif

namespace jarnsen
{
namespace build
{

inline constexpr const char *productName = JARNSEN_FIRMWARE_PRODUCT;
inline constexpr const char *version = JARNSEN_FIRMWARE_SEMVER;
inline constexpr const char *hardwareName = JARNSEN_BOOT_HARDWARE;
inline constexpr const char *gitSha = JARNSEN_BUILD_SHA;
inline constexpr unsigned long buildNumber = JARNSEN_BUILD_NUMBER;

} // namespace build
} // namespace jarnsen
