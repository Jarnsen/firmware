from pathlib import Path
import shutil

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

# Build #139 exposed a textual anchor bug in the stock-UI patch: the pretty
# Position patch contained two identical 54px draw lines, so the later span
# replacement stopped at the first one and left half of the old function behind.
# Make the first (temporary candidate-position) line unique. The next patch then
# replaces the complete function body and the final rendered stock UI is unchanged.
pretty_path = Path("scripts/apply_v3_pretty_menu_timeout_fix.py")
pretty = pretty_path.read_text()
anchor = "drawCenteredLine(display, x, 54 + y, line);"
if pretty.count(anchor) < 2:
    raise SystemExit("V3 stock UI compile repair: expected two 54px anchors")
pretty = pretty.replace(anchor, "drawCenteredLine(display, x, 53 + y, line);", 1)
pretty_path.write_text(pretty)
print("V3 stock UI compile repair ready: final Position span anchor is now unambiguous")

# V3 and Tracker intentionally share one diagnostic-log wire protocol. The PC
# downloader also understands both legacy marker pairs for older flashed builds.
diag_path = Path("src/infrastructure/HeltecV3DiagnosticLog.cpp")
diag = diag_path.read_text()
diag = diag.replace("===V3_LOG_BEGIN===", "===JARNSEN_DIAG_LOG_BEGIN===")
diag = diag.replace("===V3_LOG_END===", "===JARNSEN_DIAG_LOG_END===")
old_header = '        Serial.printf("# bytes=%u\\r\\n", (unsigned)exportTotalBytes);\n'
new_header = '        Serial.print("# device=HELTEC_V3_REPEATER\\r\\n");\n        Serial.printf("# bytes=%u\\r\\n", (unsigned)exportTotalBytes);\n'
if new_header not in diag:
    if old_header not in diag:
        raise SystemExit("V3 diagnostic protocol header anchor not found")
    diag = diag.replace(old_header, new_header, 1)
for needle in ["===JARNSEN_DIAG_LOG_BEGIN===", "===JARNSEN_DIAG_LOG_END===", "# device=HELTEC_V3_REPEATER"]:
    if needle not in diag:
        raise SystemExit(f"V3 shared diagnostic protocol missing: {needle}")
diag_path.write_text(diag)
print("V3 shared diagnostic log protocol ready")

# Put the exact same downloader package into the V3 artifact. Collect firmware
# later adds BIN/ELF files to this directory without deleting these extras.
artifact = Path("artifact")
artifact.mkdir(parents=True, exist_ok=True)
for source in [
    Path("tools/diagnostic_log_download.py"),
    Path("tools/diagnostic_log_download.bat"),
    Path("tools/README-DIAGNOSTIC-LOG.txt"),
]:
    if not source.exists():
        raise SystemExit(f"V3 artifact extra missing: {source}")
    shutil.copy2(source, artifact / source.name)
    print(f"V3 artifact extra: {source.name}")
