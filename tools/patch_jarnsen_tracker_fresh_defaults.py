"""Tracker V1.1 build-time fixes.

Applies only Tracker-specific source changes during the Tracker workflow:
- fixes the USB diagnostic writer's char*/uint8_t* calls,
- installs TAK_TRACKER / EU_868 / hop 7 / RX boosted gain / LOCAL_ONLY only for a truly
  missing config file (fresh flash),
- applies the same Tracker defaults after an explicit factory reset,
- leaves saved/upgrade configs untouched.
"""

from pathlib import Path

DIAG = Path("src/vehicle/TrackerDiagnosticLog.cpp")
NODEDB = Path("src/mesh/NodeDB.cpp")

# --- USB diagnostic export compile fix ---------------------------------------------------------------
diag = DIAG.read_text(encoding="utf-8")
for old, new in (
    ("writeSerialAll(usbHeader, usbHeaderLength, false)",
     "writeSerialAll((const uint8_t *)usbHeader, usbHeaderLength, false)"),
    ("writeSerialAll(usbFooter, usbFooterLength, false)",
     "writeSerialAll((const uint8_t *)usbFooter, usbFooterLength, false)"),
):
    if new not in diag:
        if diag.count(old) != 1:
            raise SystemExit(f"Tracker USB export cast anchor not found exactly once: {old}")
        diag = diag.replace(old, new, 1)

for marker in (
    "writeSerialAll((const uint8_t *)usbHeader, usbHeaderLength, false)",
    "writeSerialAll((const uint8_t *)usbFooter, usbFooterLength, false)",
):
    if marker not in diag:
        raise SystemExit(f"missing Tracker USB export cast marker: {marker}")

DIAG.write_text(diag, encoding="utf-8")

# --- Fresh Tracker defaults -------------------------------------------------------------------------
source = NODEDB.read_text(encoding="utf-8")

fresh_flag_anchor = """    migrationSavePending = false;
    configDecodeFailed = false;

    meshtastic_Config_SecurityConfig backupSecurity = meshtastic_Config_SecurityConfig_init_zero;
"""
fresh_flag_new = """    migrationSavePending = false;
    configDecodeFailed = false;

#if defined(HELTEC_TRACKER_V1_1) && defined(FSCom)
    // True only when the persisted config file is genuinely absent.  This is
    // deliberately not an NVS firmware-version marker: an OTA/update must never
    // overwrite an already configured Tracker.
    bool trackerV11FreshConfigDefaults = false;
#endif

    meshtastic_Config_SecurityConfig backupSecurity = meshtastic_Config_SecurityConfig_init_zero;
"""
if "bool trackerV11FreshConfigDefaults = false;" not in source:
    if source.count(fresh_flag_anchor) != 1:
        raise SystemExit("Tracker fresh-default flag anchor not found exactly once")
    source = source.replace(fresh_flag_anchor, fresh_flag_new, 1)

config_load_anchor = """    state = loadProto(configFileName, meshtastic_LocalConfig_size, sizeof(meshtastic_LocalConfig), &meshtastic_LocalConfig_msg,
                      &config);
"""
config_load_new = """#if defined(HELTEC_TRACKER_V1_1) && defined(FSCom)
    spiLock->lock();
    const bool trackerV11ConfigFileMissing = !FSCom.exists(configFileName);
    spiLock->unlock();
#endif
    state = loadProto(configFileName, meshtastic_LocalConfig_size, sizeof(meshtastic_LocalConfig), &meshtastic_LocalConfig_msg,
                      &config);
"""
if "const bool trackerV11ConfigFileMissing" not in source:
    if source.count(config_load_anchor) != 1:
        raise SystemExit("Tracker config-load anchor not found exactly once")
    source = source.replace(config_load_anchor, config_load_new, 1)

first_boot_anchor = """    } else if (state != LoadFileResult::LOAD_SUCCESS) {
        // No decodable config to work with: the file is absent (first boot) or could not be opened (OTHER_FAILURE
        // / NO_FILESYSTEM). Unlike DECODE_FAILED there are no usable contents to protect, so install defaults.
        installDefaultConfig();
    } else if (config.version < DEVICESTATE_MIN_VER) {
"""
first_boot_new = """    } else if (state != LoadFileResult::LOAD_SUCCESS) {
        // No decodable config to work with: the file is absent (first boot) or could not be opened (OTHER_FAILURE
        // / NO_FILESYSTEM). Unlike DECODE_FAILED there are no usable contents to protect, so install defaults.
        installDefaultConfig();
#if defined(HELTEC_TRACKER_V1_1) && defined(FSCom)
        if (trackerV11ConfigFileMissing) {
            config.device.role = meshtastic_Config_DeviceConfig_Role_TAK_TRACKER;
            config.device.rebroadcast_mode = meshtastic_Config_DeviceConfig_RebroadcastMode_LOCAL_ONLY;
            config.lora.region = meshtastic_Config_LoRaConfig_RegionCode_EU_868;
            config.lora.hop_limit = 7;
            config.lora.sx126x_rx_boosted_gain = true;
            trackerV11FreshConfigDefaults = true;
            LOG_INFO("Tracker V1.1 fresh defaults: TAK_TRACKER, EU_868, hop_limit=7, rx_boosted_gain=on, rebroadcast=LOCAL_ONLY");
        }
#endif
    } else if (config.version < DEVICESTATE_MIN_VER) {
"""
if "Tracker V1.1 fresh defaults: TAK_TRACKER" not in source:
    if source.count(first_boot_anchor) != 1:
        raise SystemExit("Tracker first-boot config anchor not found exactly once")
    source = source.replace(first_boot_anchor, first_boot_new, 1)

module_anchor = """    if (state != LoadFileResult::LOAD_SUCCESS) {
        installDefaultModuleConfig(); // Our in RAM copy might now be corrupt
    } else {
        if (moduleConfig.version < DEVICESTATE_MIN_VER) {
            LOG_WARN("moduleConfig %d is old, discard", moduleConfig.version);
            installDefaultModuleConfig();
        } else {
            LOG_INFO("Loaded saved moduleConfig version %d", moduleConfig.version);
        }
    }

    // Always-on traffic management: a device that has NEVER configured TMM
"""
module_new = """    if (state != LoadFileResult::LOAD_SUCCESS) {
        installDefaultModuleConfig(); // Our in RAM copy might now be corrupt
    } else {
        if (moduleConfig.version < DEVICESTATE_MIN_VER) {
            LOG_WARN("moduleConfig %d is old, discard", moduleConfig.version);
            installDefaultModuleConfig();
        } else {
            LOG_INFO("Loaded saved moduleConfig version %d", moduleConfig.version);
        }
    }

#if defined(HELTEC_TRACKER_V1_1) && defined(FSCom)
    if (trackerV11FreshConfigDefaults) {
        // Role defaults touch both LocalConfig and ModuleConfig, so apply them
        // only after ModuleConfig has been initialized, then persist this one
        // fresh-install transaction. Re-assert LOCAL_ONLY afterwards so role
        // defaults can never replace the requested Tracker rebroadcast policy.
        installRoleDefaults(meshtastic_Config_DeviceConfig_Role_TAK_TRACKER);
        config.device.rebroadcast_mode = meshtastic_Config_DeviceConfig_RebroadcastMode_LOCAL_ONLY;
        saveToDisk(SEGMENT_CONFIG | SEGMENT_MODULECONFIG);
    }
#endif

    // Always-on traffic management: a device that has NEVER configured TMM
"""
if "if (trackerV11FreshConfigDefaults)" not in source:
    if source.count(module_anchor) != 1:
        raise SystemExit("Tracker module-default anchor not found exactly once")
    source = source.replace(module_anchor, module_new, 1)

factory_anchor = """    installDefaultConfig(!eraseBleBonds); // Also preserve the private key if we're not erasing BLE bonds
    installDefaultModuleConfig();
    installDefaultChannels();
    // third, write everything to disk
"""
factory_new = """    installDefaultConfig(!eraseBleBonds); // Also preserve the private key if we're not erasing BLE bonds
    installDefaultModuleConfig();
#if defined(HELTEC_TRACKER_V1_1)
    config.device.role = meshtastic_Config_DeviceConfig_Role_TAK_TRACKER;
    config.lora.region = meshtastic_Config_LoRaConfig_RegionCode_EU_868;
    config.lora.hop_limit = 7;
    config.lora.sx126x_rx_boosted_gain = true;
    installRoleDefaults(meshtastic_Config_DeviceConfig_Role_TAK_TRACKER);
    config.device.rebroadcast_mode = meshtastic_Config_DeviceConfig_RebroadcastMode_LOCAL_ONLY;
    LOG_INFO("Tracker V1.1 factory defaults: TAK_TRACKER, EU_868, hop_limit=7, rx_boosted_gain=on, rebroadcast=LOCAL_ONLY");
#endif
    installDefaultChannels();
    // third, write everything to disk
"""
if "Tracker V1.1 factory defaults: TAK_TRACKER" not in source:
    if source.count(factory_anchor) != 1:
        raise SystemExit("Tracker factory-reset anchor not found exactly once")
    source = source.replace(factory_anchor, factory_new, 1)

for marker in (
    "meshtastic_Config_DeviceConfig_Role_TAK_TRACKER",
    "meshtastic_Config_DeviceConfig_RebroadcastMode_LOCAL_ONLY",
    "meshtastic_Config_LoRaConfig_RegionCode_EU_868",
    "config.lora.hop_limit = 7;",
    "config.lora.sx126x_rx_boosted_gain = true;",
    "trackerV11ConfigFileMissing",
    "trackerV11FreshConfigDefaults",
):
    if marker not in source:
        raise SystemExit(f"missing Tracker fresh-default marker: {marker}")

NODEDB.write_text(source, encoding="utf-8")
print("Tracker V1.1 fresh defaults (TAK_TRACKER/EU_868/hop7/RX boost/LOCAL_ONLY) and USB export compile fix applied")
