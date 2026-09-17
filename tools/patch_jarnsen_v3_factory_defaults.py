"""Apply Heltec V3 defaults only on a genuinely fresh config or explicit factory reset.

This patch is V3-only.  It deliberately keys first-boot detection off the
absence of the persisted config file, never a firmware/build version marker, so
normal firmware and OTA updates preserve every existing user setting.
"""
from pathlib import Path

TARGET = Path("src/mesh/NodeDB.cpp")


def once(source: str, old: str, new: str, label: str) -> str:
    if new in source:
        return source
    if source.count(old) != 1:
        raise SystemExit(f"{label} anchor not found exactly once")
    return source.replace(old, new, 1)


source = TARGET.read_text(encoding="utf-8")

# One process-local flag is enough: NodeDB is instantiated once.  The flag is
# reset on every loadFromDisk() and can become true only when the actual config
# file is absent.
state_anchor = "static uint8_t ourMacAddr[6];\n"
state_new = state_anchor + "\n#if defined(_VARIANT_HELTEC_V3)\nstatic bool v3FreshConfigDefaultsPending = false;\n#endif\n"
source = once(source, state_anchor, state_new, "V3 fresh-default state")

load_reset_anchor = "    migrationSavePending = false;\n    configDecodeFailed = false;\n"
load_reset_new = load_reset_anchor + "#if defined(_VARIANT_HELTEC_V3)\n    v3FreshConfigDefaultsPending = false;\n#endif\n"
source = once(source, load_reset_anchor, load_reset_new, "V3 fresh-default load reset")

# Detect a true first install from filesystem state before loading LocalConfig.
# A present-but-undecodable config is explicitly NOT a fresh install.
config_load_anchor = '''    state = loadProto(configFileName, meshtastic_LocalConfig_size, sizeof(meshtastic_LocalConfig), &meshtastic_LocalConfig_msg,
                      &config);
'''
config_load_new = '''#if defined(_VARIANT_HELTEC_V3)
#ifdef FSCom
    {
        concurrency::LockGuard guard(spiLock);
        v3FreshConfigDefaultsPending = !FSCom.exists(configFileName);
    }
#endif
#endif

    state = loadProto(configFileName, meshtastic_LocalConfig_size, sizeof(meshtastic_LocalConfig), &meshtastic_LocalConfig_msg,
                      &config);
'''
source = once(source, config_load_anchor, config_load_new, "V3 missing-config detection")

# loadFromDisk() has already loaded or initialized ModuleConfig when the
# constructor continues here.  That makes this the safe point to invoke
# installRoleDefaults(ROUTER_LATE), whose role policy changes telemetry module
# defaults.  Existing configs never enter this block.
ctor_anchor = '''    loadFromDisk();
    cleanupMeshDB();
'''
ctor_new = '''    loadFromDisk();
    cleanupMeshDB();

#if defined(_VARIANT_HELTEC_V3)
    if (v3FreshConfigDefaultsPending && !configDecodeFailed) {
        config.device.role = meshtastic_Config_DeviceConfig_Role_ROUTER_LATE;
        config.lora.region = meshtastic_Config_LoRaConfig_RegionCode_EU_868;
        config.lora.hop_limit = 7;
        config.lora.sx126x_rx_boosted_gain = true;
        config.device.rebroadcast_mode = meshtastic_Config_DeviceConfig_RebroadcastMode_LOCAL_ONLY;
        installRoleDefaults(config.device.role);
        owner.role = config.device.role;
        LOG_INFO("Heltec V3 fresh config: ROUTER_LATE EU_868 hop=7 rx-boost=1 rebroadcast=LOCAL_ONLY");
    }
#endif
'''
source = once(source, ctor_anchor, ctor_new, "V3 fresh-default application")

# Explicit factory reset removes /prefs and immediately writes defaults again,
# so it cannot rely on the next boot's missing-file check.  Apply the same V3
# values after ModuleConfig has been initialized and before the existing single
# saveToDisk() call.
factory_anchor = '''    installDefaultConfig(!eraseBleBonds); // Also preserve the private key if we're not erasing BLE bonds
    installDefaultModuleConfig();
    installDefaultChannels();
'''
factory_new = '''    installDefaultConfig(!eraseBleBonds); // Also preserve the private key if we're not erasing BLE bonds
    installDefaultModuleConfig();
#if defined(_VARIANT_HELTEC_V3)
    config.device.role = meshtastic_Config_DeviceConfig_Role_ROUTER_LATE;
    config.lora.region = meshtastic_Config_LoRaConfig_RegionCode_EU_868;
    config.lora.hop_limit = 7;
    config.lora.sx126x_rx_boosted_gain = true;
    config.device.rebroadcast_mode = meshtastic_Config_DeviceConfig_RebroadcastMode_LOCAL_ONLY;
    installRoleDefaults(config.device.role);
    owner.role = config.device.role;
#endif
    installDefaultChannels();
'''
source = once(source, factory_anchor, factory_new, "V3 factory-reset defaults")

# The constructor already performs one consolidated persistence pass at the end.
# Add ModuleConfig and DeviceState to that pass for a fresh V3 so the role's
# module settings and owner role are saved together with LocalConfig.
save_anchor = '''    sortMeshDB();
    saveToDisk(saveWhat);
'''
save_new = '''#if defined(_VARIANT_HELTEC_V3)
    if (v3FreshConfigDefaultsPending) {
        saveWhat |= SEGMENT_CONFIG | SEGMENT_MODULECONFIG | SEGMENT_DEVICESTATE;
        v3FreshConfigDefaultsPending = false;
    }
#endif
    sortMeshDB();
    saveToDisk(saveWhat);
'''
source = once(source, save_anchor, save_new, "V3 fresh-default persistence")

# Build-time verification requested for the V3 image.  These exact markers make
# the patch fail before PlatformIO starts if any of the five defaults disappear.
required = (
    "meshtastic_Config_DeviceConfig_Role_ROUTER_LATE",
    "meshtastic_Config_LoRaConfig_RegionCode_EU_868",
    "config.lora.hop_limit = 7;",
    "config.lora.sx126x_rx_boosted_gain = true;",
    "meshtastic_Config_DeviceConfig_RebroadcastMode_LOCAL_ONLY",
    "v3FreshConfigDefaultsPending = !FSCom.exists(configFileName);",
    "installRoleDefaults(config.device.role);",
    "SEGMENT_CONFIG | SEGMENT_MODULECONFIG | SEGMENT_DEVICESTATE",
)
for marker in required:
    if marker not in source:
        raise SystemExit(f"missing V3 factory-default marker: {marker}")

# Both true-fresh and explicit-factory-reset paths must contain every requested
# value; one occurrence would mean one of the two paths was accidentally lost.
for marker in (
    "config.device.role = meshtastic_Config_DeviceConfig_Role_ROUTER_LATE;",
    "config.lora.region = meshtastic_Config_LoRaConfig_RegionCode_EU_868;",
    "config.lora.hop_limit = 7;",
    "config.lora.sx126x_rx_boosted_gain = true;",
    "config.device.rebroadcast_mode = meshtastic_Config_DeviceConfig_RebroadcastMode_LOCAL_ONLY;",
):
    if source.count(marker) < 2:
        raise SystemExit(f"V3 default is not present in both fresh/reset paths: {marker}")

TARGET.write_text(source, encoding="utf-8")
print("Heltec V3 defaults verified: ROUTER_LATE, EU_868, hop_limit=7, rx_boosted_gain=true, LOCAL_ONLY (fresh/reset only)")
