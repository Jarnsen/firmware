#!/usr/bin/env python3
"""Build-time integration hooks for the dedicated Tracker V1.1 drone profile.

Drone code stays isolated under src/drone. This patch only touches upstream
hotspots where compile-time hooks are required: PowerFSM, RadioLibInterface and
NimbleBluetooth. Every replacement is exact and fails the build if an upstream
change invalidates an anchor.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, got {count}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# PowerFSM: the airborne role is always awake even when VBUS disappears.
# ---------------------------------------------------------------------------
power_path = ROOT / "src/PowerFSM.cpp"
power = power_path.read_text(encoding="utf-8")
power = replace_once(
    power,
    "static bool isPowered()\n{\n",
    "static bool isPowered()\n{\n"
    "#if defined(HELTEC_TRACKER_V1_1) && defined(JARNSEN_DRONE_REPEATER_BUILD)\n"
    "    // Dedicated airborne profile: LoRa RX and GNSS must never enter a\n"
    "    // sleep state just because VBUS disappears. Real USB/battery source\n"
    "    // changes are monitored separately by DronePowerMonitor.\n"
    "    return true;\n"
    "#endif\n",
    "PowerFSM drone always-awake hook",
)
power = replace_once(
    power,
    "#if defined(HELTEC_TRACKER_V1_1)\n"
    "    return config.device.role == meshtastic_Config_DeviceConfig_Role_TAK ||\n"
    "           config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER;\n",
    "#if defined(HELTEC_TRACKER_V1_1)\n"
    "#if defined(JARNSEN_DRONE_REPEATER_BUILD)\n"
    "    // Drone policy owns BLE and display even though its role is ROUTER_LATE.\n"
    "    return true;\n"
    "#else\n"
    "    return config.device.role == meshtastic_Config_DeviceConfig_Role_TAK ||\n"
    "           config.device.role == meshtastic_Config_DeviceConfig_Role_TAK_TRACKER;\n"
    "#endif\n",
    "PowerFSM drone interactive ownership",
)
power_path.write_text(power, encoding="utf-8")

# ---------------------------------------------------------------------------
# RadioLib: count real RX/TX/relay traffic and feed Mesh Health.
# ---------------------------------------------------------------------------
radio_path = ROOT / "src/mesh/RadioLibInterface.cpp"
radio = radio_path.read_text(encoding="utf-8")
radio = replace_once(
    radio,
    "#endif\n#include <pb_decode.h>\n",
    "#endif\n"
    "#if defined(HELTEC_TRACKER_V1_1) && defined(JARNSEN_DRONE_REPEATER_BUILD)\n"
    "#include \"drone/DroneMeshHealth.h\"\n"
    "#include \"drone/DronePowerMonitor.h\"\n"
    "#endif\n"
    "#include <pb_decode.h>\n",
    "RadioLib drone includes",
)
radio = replace_once(
    radio,
    "        txGood++;\n"
    "        if (!isFromUs(p))\n"
    "            txRelay++;\n"
    "        printPacket(\"Completed sending\", p);\n",
    "        txGood++;\n"
    "        const bool relayPacket = !isFromUs(p);\n"
    "        if (relayPacket)\n"
    "            txRelay++;\n"
    "#if defined(HELTEC_TRACKER_V1_1) && defined(JARNSEN_DRONE_REPEATER_BUILD)\n"
    "        dronePowerMonitorNoteRadioTx(relayPacket);\n"
    "#endif\n"
    "        printPacket(\"Completed sending\", p);\n",
    "RadioLib drone TX counter",
)
radio = replace_once(
    radio,
    "            addReceiveMetadata(mp);\n\n"
    "            mp->which_payload_variant =\n",
    "            addReceiveMetadata(mp);\n"
    "#if defined(HELTEC_TRACKER_V1_1) && defined(JARNSEN_DRONE_REPEATER_BUILD)\n"
    "            droneMeshHealthOnRadioPacket(*mp);\n"
    "#endif\n\n"
    "            mp->which_payload_variant =\n",
    "RadioLib drone RX observer",
)
radio_path.write_text(radio, encoding="utf-8")

# ---------------------------------------------------------------------------
# NimBLE: shared diagnostic characteristics + otaBTupdate handoff.
# ---------------------------------------------------------------------------
nimble_path = ROOT / "src/nimble/NimbleBluetooth.cpp"
nimble = nimble_path.read_text(encoding="utf-8")
nimble = replace_once(
    nimble,
    "#include \"sleep.h\"\n#if HAS_SCREEN\n",
    "#include \"sleep.h\"\n"
    "#if defined(HELTEC_TRACKER_V1_1) && defined(JARNSEN_DRONE_REPEATER_BUILD)\n"
    "#include \"MeshtasticOTA.h\"\n"
    "#include \"drone/DroneDiagnosticLog.h\"\n"
    "#include \"vehicle/JarnsenBuildInfo.h\"\n"
    "#endif\n"
    "#if HAS_SCREEN\n",
    "NimBLE drone includes",
)

callbacks = r'''
#if defined(HELTEC_TRACKER_V1_1) && defined(JARNSEN_DRONE_REPEATER_BUILD)
static bool decodeDroneOtaHash(const uint8_t *text, uint8_t *hash)
{
    auto nibble = [](uint8_t value) -> int {
        if (value >= '0' && value <= '9') return value - '0';
        if (value >= 'a' && value <= 'f') return value - 'a' + 10;
        if (value >= 'A' && value <= 'F') return value - 'A' + 10;
        return -1;
    };
    for (size_t index = 0; index < 32; ++index) {
        const int high = nibble(text[index * 2]);
        const int low = nibble(text[index * 2 + 1]);
        if (high < 0 || low < 0)
            return false;
        hash[index] = (uint8_t)((high << 4) | low);
    }
    return true;
}

static const char *droneOtaStatus()
{
    if (powerStatus && powerStatus->getHasBattery() && !powerStatus->getHasUSB() &&
        powerStatus->getBatteryChargePercent() > 0 && powerStatus->getBatteryChargePercent() < 25)
        return "LOW_POWER:DRONE";
    const esp_partition_t *partition = MeshtasticOTA::getAppPartition();
    static esp_app_desc_t description;
    if (!partition || !MeshtasticOTA::getAppDesc(partition, &description))
        return "NO_LOADER:DRONE";
    if (!MeshtasticOTA::checkOTACapability(&description, METHOD_OTA_BLE))
        return "NO_BT_OTA:DRONE";
    static char status[40];
    snprintf(status, sizeof(status), "OTA_OK:DRONE:%.8s", JARNSEN_BUILD_SHA);
    return status;
}

static const char *prepareDroneBleOta(const uint8_t *hashText)
{
    uint8_t hash[32] = {};
    if (!decodeDroneOtaHash(hashText, hash))
        return "BAD_HASH";
    if (powerStatus && powerStatus->getHasBattery() && !powerStatus->getHasUSB() &&
        powerStatus->getBatteryChargePercent() > 0 && powerStatus->getBatteryChargePercent() < 25)
        return "LOW_POWER";
    const esp_partition_t *partition = MeshtasticOTA::getAppPartition();
    static esp_app_desc_t description;
    if (!partition || !MeshtasticOTA::getAppDesc(partition, &description))
        return "NO_LOADER";
    if (!MeshtasticOTA::checkOTACapability(&description, METHOD_OTA_BLE))
        return "NO_BT_OTA";
    MeshtasticOTA::saveConfig(&config.network, meshtastic_OTAMode_OTA_BLE, hash);
    if (!MeshtasticOTA::trySwitchToOTA())
        return "SWITCH_ERR";
    rebootAtMsec = millis() + 3000UL;
    LOG_INFO("Drone Bluetooth firmware update prepared; rebooting to otaBTupdate");
    return "OTA_READY";
}

class DroneDiagControlCallback : public BLECharacteristicCallbacks
{
    void onWrite(BLECharacteristic *characteristic) override
    {
        const uint8_t *data = characteristic->getData();
        const size_t length = characteristic->getLength();
        if (meshtasticTrackerBleActivity)
            meshtasticTrackerBleActivity();
        const char *status = "ERROR";
        if (length == 5 && memcmp(data, "START", 5) == 0) {
            status = droneDiagStartBleExport() ? "READY" : "ERROR";
        } else if (length == 6 && memcmp(data, "CANCEL", 6) == 0) {
            droneDiagCancelBleExport();
            status = "IDLE";
        } else if (length == 4 && memcmp(data, "INFO", 4) == 0) {
            static char info[40];
            snprintf(info, sizeof(info), "DRONE:%.8s", JARNSEN_BUILD_SHA);
            status = info;
        } else if (length == 9 && memcmp(data, "OTASTATUS", 9) == 0) {
            status = droneOtaStatus();
        } else if (length == 70 && memcmp(data, "OTABT ", 6) == 0) {
            status = prepareDroneBleOta(data + 6);
        }
        characteristic->setValue((const uint8_t *)status, strlen(status));
    }
};

class DroneDiagDataCallback : public BLECharacteristicCallbacks
{
    void onRead(BLECharacteristic *characteristic) override
    {
        uint8_t buffer[180] = {};
        const size_t length = droneDiagReadBleExport(buffer, sizeof(buffer));
        if (meshtasticTrackerBleActivity)
            meshtasticTrackerBleActivity();
        characteristic->setValue(buffer, length);
    }
};
#endif

'''
nimble = replace_once(
    nimble,
    "class BluetoothPhoneAPI : public PhoneAPI, public concurrency::OSThread\n",
    callbacks + "class BluetoothPhoneAPI : public PhoneAPI, public concurrency::OSThread\n",
    "NimBLE drone callbacks",
)
nimble = replace_once(
    nimble,
    "static void resetBleSessionState()\n{\n",
    "static void resetBleSessionState()\n{\n"
    "#if defined(HELTEC_TRACKER_V1_1) && defined(JARNSEN_DRONE_REPEATER_BUILD)\n"
    "    droneDiagCancelBleExport();\n"
    "#endif\n",
    "NimBLE drone session cleanup",
)
service = r'''
#if defined(HELTEC_TRACKER_V1_1) && defined(JARNSEN_DRONE_REPEATER_BUILD)
    uint32_t droneControlProperties = BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_READ |
                                      BLECharacteristic::PROPERTY_WRITE_ENC | BLECharacteristic::PROPERTY_READ_ENC;
    uint32_t droneDataProperties = BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_READ_ENC;
    if (config.bluetooth.mode != meshtastic_Config_BluetoothConfig_PairingMode_NO_PIN) {
        droneControlProperties |= BLECharacteristic::PROPERTY_WRITE_AUTHEN | BLECharacteristic::PROPERTY_READ_AUTHEN;
        droneDataProperties |= BLECharacteristic::PROPERTY_READ_AUTHEN;
    }
    BLECharacteristic *droneDiagControl = bleService->createCharacteristic(JARNSEN_DIAG_CONTROL_UUID, droneControlProperties);
    BLECharacteristic *droneDiagData = bleService->createCharacteristic(JARNSEN_DIAG_DATA_UUID, droneDataProperties);
    static DroneDiagControlCallback droneDiagControlCallback;
    static DroneDiagDataCallback droneDiagDataCallback;
    droneDiagControl->setCallbacks(&droneDiagControlCallback);
    droneDiagData->setCallbacks(&droneDiagDataCallback);
#endif

'''
nimble = replace_once(
    nimble,
    "    bleService->start();\n",
    service + "    bleService->start();\n",
    "NimBLE drone diagnostic service",
)
nimble_path.write_text(nimble, encoding="utf-8")

print("Drone runtime hooks applied: always-awake + radio observability + BLE diagnostics/OTA")
