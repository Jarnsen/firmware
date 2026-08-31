#include "jarnsen/core/service/JarnsenServiceModel.h"

namespace jarnsen
{
namespace
{

constexpr PeripheralCapabilities noPeripherals{};
constexpr PeripheralCapabilities trackerReferencePeripherals{false, true, false};
constexpr PeripheralCapabilities externalGpsOnly{true, false, false};

constexpr NodeServiceDescriptor trackerService = trackerV11ServiceDescriptor();
constexpr NodeServiceDescriptor v3Service = heltecV3ServiceDescriptor();
constexpr NodeServiceDescriptor v4Service = heltecV4ServiceDescriptor();
constexpr NodeServiceDescriptor wioService = seeedWioTrackerL1ServiceDescriptor();
constexpr NodeServiceDescriptor tbeamService = lilygoTBeamServiceDescriptor();
constexpr NodeServiceDescriptor tbeamSupremeService = lilygoTBeamSupremeServiceDescriptor();

static_assert(trackerService.profile.hardware.kind == HardwareKind::BOARD_HELTEC_TRACKER_V11,
              "Tracker service descriptor must keep the hardware identity");
static_assert(v3Service.profile.hardware.kind == HardwareKind::BOARD_HELTEC_V3,
              "V3 service descriptor must keep the hardware identity");
static_assert(v4Service.profile.hardware.kind == HardwareKind::BOARD_HELTEC_V4,
              "V4 service descriptor must keep the hardware identity");
static_assert(wioService.profile.hardware.kind == HardwareKind::BOARD_SEEED_WIO_TRACKER_L1,
              "Wio service descriptor must keep the hardware identity");
static_assert(tbeamService.profile.hardware.kind == HardwareKind::BOARD_LILYGO_TBEAM,
              "T-Beam service descriptor must keep the hardware identity");
static_assert(tbeamSupremeService.profile.hardware.kind == HardwareKind::BOARD_LILYGO_TBEAM_SUPREME,
              "T-Beam Supreme service descriptor must keep the hardware identity");

static_assert(trackerService.update.configured(), "Tracker service must retain its existing update channel during migration");
static_assert(v3Service.update.configured(), "V3 service must retain its existing update channel during migration");
static_assert(!v4Service.update.configured(), "V4 update channel must remain disabled until it is explicitly validated");
static_assert(!wioService.update.configured(), "Wio update channel must remain disabled until it is explicitly validated");
static_assert(!tbeamService.update.configured(), "T-Beam update channel must remain disabled until it is explicitly validated");
static_assert(!tbeamSupremeService.update.configured(),
              "T-Beam Supreme update channel must remain disabled until it is explicitly validated");

constexpr NodeStatusSnapshot trackerStatus =
    makeNodeStatusSnapshot(trackerService, trackerReferencePeripherals, DeviceRole::TAK_TRACKER, true);
static_assert(serviceHasGps(trackerStatus) && serviceHasWifi(trackerStatus) && serviceHasBluetooth(trackerStatus),
              "Tracker common service snapshot must expose its effective connectivity and GPS");
static_assert(statusRoleSupported(trackerStatus, DeviceRole::TAK_TRACKER),
              "Tracker service snapshot must allow TAK Tracker");
static_assert(statusRoleSupported(trackerStatus, DeviceRole::DRONE_REPEATER),
              "Tracker service snapshot must preserve validated Drone Repeater availability");
static_assert(activeRoleIsValid(trackerStatus), "Tracker TAK Tracker reference role must be valid");

constexpr NodeStatusSnapshot v3BaseStatus = makeNodeStatusSnapshot(v3Service, noPeripherals, DeviceRole::TAK_REPEATER, true);
static_assert(!serviceHasGps(v3BaseStatus), "V3 base service snapshot must not invent GPS");
static_assert(serviceHasWifi(v3BaseStatus) && serviceHasBluetooth(v3BaseStatus),
              "V3 service recovery transports must remain available without GPS");
static_assert(!statusRoleSupported(v3BaseStatus, DeviceRole::TAK_TRACKER),
              "V3 without GPS must not expose TAK Tracker through the service model");
static_assert(activeRoleIsValid(v3BaseStatus), "V3 TAK Repeater reference role must remain valid");

constexpr NodeStatusSnapshot v3GpsStatus =
    makeNodeStatusSnapshot(v3Service, externalGpsOnly, DeviceRole::TAK_TRACKER, true);
static_assert(serviceHasGps(v3GpsStatus), "Configured external GPS must flow into the common V3 service snapshot");
static_assert(statusRoleSupported(v3GpsStatus, DeviceRole::TAK_TRACKER),
              "V3 with external GPS must expose TAK Tracker through the service model");
static_assert(!statusRoleSupported(v3GpsStatus, DeviceRole::DRONE_REPEATER),
              "External GPS must not unlock Drone Repeater through the service model");
static_assert(activeRoleIsValid(v3GpsStatus), "V3 TAK Tracker must be valid once effective GPS exists");

constexpr NodeStatusSnapshot invalidV3Drone =
    makeNodeStatusSnapshot(v3Service, externalGpsOnly, DeviceRole::DRONE_REPEATER, true);
static_assert(!activeRoleIsValid(invalidV3Drone),
              "The common status layer must identify unsupported persisted/runtime roles");

} // namespace
} // namespace jarnsen
