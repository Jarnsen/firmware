from pathlib import Path

POWER_PATH = Path("src/PowerFSM.cpp")
SCREEN_PATH = Path("src/graphics/Screen.cpp")

power = POWER_PATH.read_text()
screen = SCREEN_PATH.read_text()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"{label}: already applied")
        return text
    if old not in text:
        raise SystemExit(f"{label}: anchor not found")
    print(f"{label}: applied")
    return text.replace(old, new, 1)


# The Heltec Tracker V1.1 uses ESP32-S3 Hardware CDC/JTAG as Serial
# (ARDUINO_USB_CDC_ON_BOOT=1, ARDUINO_USB_MODE=1). The battery/power monitor
# does not report this host connection as USB power on this board, so
# powerStatus->getHasUSB() is not a valid proxy for an open serial console.
# Serial::operator bool() is the Arduino HWCDC connection state and therefore
# directly tells us whether a host currently has the CDC port open.
power = replace_once(
    power,
    '''static bool trackerUsbKeepsCpuAwake()\n{\n#if defined(HELTEC_TRACKER_V1_1)\n    return trackerOwnsInteractiveOutputs() && powerStatus && powerStatus->getHasUSB();\n#else\n    return false;\n#endif\n}\n''',
    '''static bool trackerUsbKeepsCpuAwake()\n{\n#if defined(HELTEC_TRACKER_V1_1)\n    bool nativeSerialConnected = false;\n#if defined(ARDUINO_USB_CDC_ON_BOOT) && ARDUINO_USB_CDC_ON_BOOT\n    nativeSerialConnected = (bool)Serial;\n#endif\n    return trackerOwnsInteractiveOutputs() &&\n           (nativeSerialConnected || (powerStatus && powerStatus->getHasUSB()));\n#else\n    return false;\n#endif\n}\n''',
    "Tracker native USB CDC sleep veto",
)

# TrackerStatusModule::requestTrackerFocus() calls setFrames(FOCUS_MODULE).
# The old Tracker ownership guard returned before setFrames() could build any
# normal/module frames after the boot logo, leaving the boot frame as the only
# frame forever. Allow the explicit FOCUS_MODULE request to perform the first
# frame build. Once showingNormalScreen is true, subsequent native page cycling
# and rebuilds are also allowed.
screen = replace_once(
    screen,
    '''    // Once the genuine boot screen has ended, TAK/TAK_TRACKER expose only\n    // their local service frame. Suppress all stock carousel rebuilds.\n    if (bootScreenComplete && trackerOwnsScreenAfterBoot())\n        return;\n''',
    '''    // After the boot logo, TAK/TAK_TRACKER keep the display dark until\n    // GPIO0 opens the service window. The explicit tracker FOCUS_MODULE request\n    // must still be allowed to build the native Meshtastic frame set; otherwise\n    // the one boot frame remains installed forever and showNextFrame() has\n    // nowhere to go. Once normal frames exist, permit normal native page cycling.\n    if (bootScreenComplete && trackerOwnsScreenAfterBoot() && !showingNormalScreen && focus != FOCUS_MODULE)\n        return;\n''',
    "Tracker post-boot native frame build",
)

for needle in [
    'nativeSerialConnected = (bool)Serial;',
    'nativeSerialConnected || (powerStatus && powerStatus->getHasUSB())',
    'focus != FOCUS_MODULE',
    'showNextFrame() has',
]:
    if needle not in power and needle not in screen:
        raise SystemExit(f"Tracker USB/UI verification failed: {needle}")

POWER_PATH.write_text(power)
SCREEN_PATH.write_text(screen)
