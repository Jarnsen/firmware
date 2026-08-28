#!/usr/bin/env python3
"""Add the shared service-tool live-view surface to the drone build.

Runs after patch_drone_runtime.py. Keeps the permanent source delta small while
failing loudly if upstream Screen/NimBLE anchors change.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, got {count}")
    return text.replace(old, new, 1)


# Screen framebuffer access used by JarnsenLiveDisplay.
screen_h_path = ROOT / "src/graphics/Screen.h"
screen_h = screen_h_path.read_text(encoding="utf-8")
screen_h = replace_once(
    screen_h,
    "  public:\n    explicit Screen(ScanI2C::DeviceAddress, meshtastic_Config_DisplayConfig_OledType, OLEDDISPLAY_GEOMETRY);\n",
    "  public:\n"
    "    OLEDDisplay *getDisplayDevice() { return dispdev; }\n"
    "    explicit Screen(ScanI2C::DeviceAddress, meshtastic_Config_DisplayConfig_OledType, OLEDDISPLAY_GEOMETRY);\n",
    "Screen display accessor",
)
screen_h = replace_once(
    screen_h,
    "    bool isScreenOn() { return screenOn; }\n",
    "    bool isScreenOn() { return screenOn; }\n\n"
    "    // Render the current UI into the framebuffer for the authenticated\n"
    "    // service-tool mirror while the physical panel may remain off.\n"
    "    void renderForMirror();\n"
    "    uint8_t currentFrameIndex() { return ui ? ui->getUiState()->currentFrame : 255; }\n",
    "Screen mirror declarations",
)
screen_h_path.write_text(screen_h, encoding="utf-8")

screen_cpp_path = ROOT / "src/graphics/Screen.cpp"
screen_cpp = screen_cpp_path.read_text(encoding="utf-8")
screen_cpp = replace_once(
    screen_cpp,
    "    return (1000 / targetFramerate);\n}\n\n/* show a message that the SSL cert is being built\n",
    "    return (1000 / targetFramerate);\n}\n\n"
    "void Screen::renderForMirror()\n"
    "{\n"
    "    if (!useDisplay || !ui)\n"
    "        return;\n"
    "    updateUiFrame(ui);\n"
    "}\n\n"
    "/* show a message that the SSL cert is being built\n",
    "Screen mirror implementation",
)
screen_cpp_path.write_text(screen_cpp, encoding="utf-8")

# Shared BLE live-view protocol. patch_drone_runtime.py has already added the
# diagnostic callbacks at this point.
nimble_path = ROOT / "src/nimble/NimbleBluetooth.cpp"
nimble = nimble_path.read_text(encoding="utf-8")
nimble = replace_once(
    nimble,
    "#include \"MeshtasticOTA.h\"\n#include \"drone/DroneDiagnosticLog.h\"\n",
    "#include \"MeshtasticOTA.h\"\n"
    "#include \"JarnsenLiveDisplay.h\"\n"
    "#include \"drone/DroneDiagnosticLog.h\"\n",
    "NimBLE live include",
)

# Compatibility with the existing Tracker/V3 service tool. The drone never
# sleeps while the queue is held, so HOLD is intentionally a no-op acknowledgement.
nimble = replace_once(
    nimble,
    "        } else if (length == 6 && memcmp(data, \"CANCEL\", 6) == 0) {\n"
    "            droneDiagCancelBleExport();\n"
    "            status = \"IDLE\";\n"
    "        } else if (length == 4 && memcmp(data, \"INFO\", 4) == 0) {\n",
    "        } else if (length == 6 && memcmp(data, \"CANCEL\", 6) == 0) {\n"
    "            droneDiagCancelBleExport();\n"
    "            status = \"IDLE\";\n"
    "        } else if (length == 4 && memcmp(data, \"HOLD\", 4) == 0) {\n"
    "            status = \"HELD\";\n"
    "        } else if (length == 7 && memcmp(data, \"HOLDOTA\", 7) == 0) {\n"
    "            status = \"OTA_HELD\";\n"
    "        } else if (length == 7 && memcmp(data, \"RELEASE\", 7) == 0) {\n"
    "            status = \"IDLE\";\n"
    "        } else if (length == 5 && memcmp(data, \"CLEAR\", 5) == 0) {\n"
    "            droneDiagClear();\n"
    "            status = \"CLEARED\";\n"
    "        } else if (length == 4 && memcmp(data, \"INFO\", 4) == 0) {\n",
    "Drone diagnostic compatibility commands",
)

live_callbacks = r'''
#if defined(HELTEC_TRACKER_V1_1) && defined(JARNSEN_DRONE_REPEATER_BUILD)
static bool droneLiveSession = false;
static uint8_t droneLiveFrame[2048];
static size_t droneLiveFrameLength = 0;
static size_t droneLiveFrameOffset = 0;
static JarnsenLiveFrameInfo droneLiveFrameInfo;

class DroneLiveControlCallback : public BLECharacteristicCallbacks
{
    void onWrite(BLECharacteristic *characteristic) override
    {
        const uint8_t *data = characteristic->getData();
        const size_t length = characteristic->getLength();
        char command[16] = {};
        if (length >= sizeof(command)) {
            characteristic->setValue((const uint8_t *)"ERROR", 5);
            return;
        }
        memcpy(command, data, length);
        if (meshtasticTrackerBleActivity)
            meshtasticTrackerBleActivity();

        const char *status = "ACK";
        if (strcmp(command, "START") == 0) {
            droneLiveSession = true;
            jarnsenLiveSetActive(true);
            status = "READY";
        } else if (strcmp(command, "STOP") == 0) {
            droneLiveSession = false;
            jarnsenLiveSetActive(false);
            status = "IDLE";
        } else if (!droneLiveSession) {
            status = "LOCKED";
        } else if (strcmp(command, "FRAME") == 0) {
            droneLiveFrameOffset = 0;
            droneLiveFrameLength = 0;
            jarnsenLiveRequestRender();
        } else if (!jarnsenLiveHandleCommand(command)) {
            status = "ERROR";
        }
        characteristic->setValue((const uint8_t *)status, strlen(status));
    }
};

class DroneLiveDataCallback : public BLECharacteristicCallbacks
{
    void onRead(BLECharacteristic *characteristic) override
    {
        constexpr size_t headerLength = 12;
        constexpr size_t payloadCapacity = 180 - headerLength;
        uint8_t packet[180] = {};
        if (!droneLiveSession || !jarnsenLiveIsActive()) {
            characteristic->setValue(packet, 0);
            return;
        }
        if (droneLiveFrameOffset == 0 && droneLiveFrameLength == 0)
            droneLiveFrameLength = jarnsenLiveCapture(droneLiveFrame, sizeof(droneLiveFrame), droneLiveFrameInfo);
        if (droneLiveFrameOffset >= droneLiveFrameLength) {
            characteristic->setValue(packet, 0);
            return;
        }
        const size_t remaining = droneLiveFrameLength - droneLiveFrameOffset;
        const size_t payloadLength = remaining < payloadCapacity ? remaining : payloadCapacity;
        packet[0] = 'J';
        packet[1] = 'F';
        packet[2] = 1;
        packet[3] = droneLiveFrameInfo.screenOn ? 1 : 0;
        packet[4] = droneLiveFrameInfo.width;
        packet[5] = droneLiveFrameInfo.height;
        packet[6] = (uint8_t)(droneLiveFrameInfo.sequence & 0xff);
        packet[7] = (uint8_t)(droneLiveFrameInfo.sequence >> 8);
        packet[8] = (uint8_t)(droneLiveFrameOffset & 0xff);
        packet[9] = (uint8_t)(droneLiveFrameOffset >> 8);
        packet[10] = (uint8_t)(droneLiveFrameLength & 0xff);
        packet[11] = (uint8_t)(droneLiveFrameLength >> 8);
        memcpy(packet + headerLength, droneLiveFrame + droneLiveFrameOffset, payloadLength);
        droneLiveFrameOffset += payloadLength;
        if (meshtasticTrackerBleActivity)
            meshtasticTrackerBleActivity();
        characteristic->setValue(packet, headerLength + payloadLength);
    }
};
#endif

'''
nimble = replace_once(
    nimble,
    "class BluetoothPhoneAPI : public PhoneAPI, public concurrency::OSThread\n",
    live_callbacks + "class BluetoothPhoneAPI : public PhoneAPI, public concurrency::OSThread\n",
    "NimBLE live callbacks",
)

nimble = replace_once(
    nimble,
    "#if defined(HELTEC_TRACKER_V1_1) && defined(JARNSEN_DRONE_REPEATER_BUILD)\n"
    "    droneDiagCancelBleExport();\n"
    "#endif\n",
    "#if defined(HELTEC_TRACKER_V1_1) && defined(JARNSEN_DRONE_REPEATER_BUILD)\n"
    "    droneDiagCancelBleExport();\n"
    "    droneLiveSession = false;\n"
    "    jarnsenLiveSetActive(false);\n"
    "#endif\n",
    "NimBLE live cleanup",
)

service_anchor = r'''    BLECharacteristic *droneDiagControl = bleService->createCharacteristic(JARNSEN_DIAG_CONTROL_UUID, droneControlProperties);
    BLECharacteristic *droneDiagData = bleService->createCharacteristic(JARNSEN_DIAG_DATA_UUID, droneDataProperties);
    static DroneDiagControlCallback droneDiagControlCallback;
    static DroneDiagDataCallback droneDiagDataCallback;
    droneDiagControl->setCallbacks(&droneDiagControlCallback);
    droneDiagData->setCallbacks(&droneDiagDataCallback);
#endif

'''
service_replacement = r'''    BLECharacteristic *droneDiagControl = bleService->createCharacteristic(JARNSEN_DIAG_CONTROL_UUID, droneControlProperties);
    BLECharacteristic *droneDiagData = bleService->createCharacteristic(JARNSEN_DIAG_DATA_UUID, droneDataProperties);
    BLECharacteristic *droneLiveControl = bleService->createCharacteristic(JARNSEN_LIVE_CONTROL_UUID, droneControlProperties);
    BLECharacteristic *droneLiveData = bleService->createCharacteristic(JARNSEN_LIVE_DATA_UUID, droneDataProperties);
    static DroneDiagControlCallback droneDiagControlCallback;
    static DroneDiagDataCallback droneDiagDataCallback;
    static DroneLiveControlCallback droneLiveControlCallback;
    static DroneLiveDataCallback droneLiveDataCallback;
    droneDiagControl->setCallbacks(&droneDiagControlCallback);
    droneDiagData->setCallbacks(&droneDiagDataCallback);
    droneLiveControl->setCallbacks(&droneLiveControlCallback);
    droneLiveData->setCallbacks(&droneLiveDataCallback);
#endif

'''
nimble = replace_once(nimble, service_anchor, service_replacement, "NimBLE live service characteristics")
nimble_path.write_text(nimble, encoding="utf-8")

print("Drone live-view/service-tool compatibility hooks applied")
