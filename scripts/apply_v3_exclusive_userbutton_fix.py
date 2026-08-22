from pathlib import Path

BUTTON_PATH = Path("src/input/ButtonThread.cpp")
text = BUTTON_PATH.read_text()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        print(f"{label}: already applied")
        return text
    if old not in text:
        raise SystemExit(f"{label}: anchor not found")
    print(f"{label}: applied")
    return text.replace(old, new, 1)


# The V3 repeater owns GPIO0 itself. The normal Meshtastic ButtonThread is
# created by InputBroker after setupModules(), so trying to disable it from an
# early MeshModule races the initialization order. Make the generic path inert
# at its source instead: no polling/tick events and no hardware interrupt on the
# V3 repeater button pin. Other roles and other boards are unchanged.
text = replace_once(
    text,
    "using namespace concurrency;\n\n#if HAS_BUTTON\n#endif\n",
    "using namespace concurrency;\n\n"
    "static bool heltecV3OwnsButtonPin(int pin)\n"
    "{\n"
    "#if defined(_VARIANT_HELTEC_V3) && defined(BUTTON_PIN)\n"
    "    return pin == BUTTON_PIN &&\n"
    "           (config.device.role == meshtastic_Config_DeviceConfig_Role_ROUTER_LATE ||\n"
    "            config.device.role == meshtastic_Config_DeviceConfig_Role_REPEATER);\n"
    "#else\n"
    "    (void)pin;\n"
    "    return false;\n"
    "#endif\n"
    "}\n\n"
    "#if HAS_BUTTON\n#endif\n",
    "add V3 exclusive GPIO0 ownership helper",
)

text = replace_once(
    text,
    "int32_t ButtonThread::runOnce()\n{\n    // If the button is pressed we suppress CPU sleep until release\n",
    "int32_t ButtonThread::runOnce()\n{\n"
    "    // On the Heltec V3 repeater, GPIO0 belongs exclusively to the custom\n"
    "    // service/menu state machine. Do not let OneButton::tick() generate a\n"
    "    // second click/long-press path for the same physical button. Recheck\n"
    "    // once per second so a runtime role change can recover without reboot.\n"
    "    if (heltecV3OwnsButtonPin(_pinNum)) {\n"
    "        btnEvent = BUTTON_EVENT_NONE;\n"
    "        waitingForLongPress = false;\n"
    "        buttonWasPressed = false;\n"
    "        canSleep = true;\n"
    "        return 1000;\n"
    "    }\n\n"
    "    // If the button is pressed we suppress CPU sleep until release\n",
    "suppress generic V3 button polling path",
)

text = replace_once(
    text,
    "void ButtonThread::attachButtonInterrupts()\n{\n    // Interrupt for user button, during normal use. Improves responsiveness.\n",
    "void ButtonThread::attachButtonInterrupts()\n{\n"
    "    // The custom V3 repeater button code uses GPIO wake + polling. Never\n"
    "    // reattach the generic CHANGE ISR after light sleep for that same pin.\n"
    "    if (heltecV3OwnsButtonPin(_pinNum))\n"
    "        return;\n\n"
    "    // Interrupt for user button, during normal use. Improves responsiveness.\n",
    "suppress generic V3 button interrupt path",
)

BUTTON_PATH.write_text(text)
print("V3 GPIO0 ownership ready: generic UserButton polling + ISR suppressed for repeater roles")
