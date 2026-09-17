"""Harden Tracker V1.1 Full-Lock GPIO0 -> PIN transition.

The original Full-Lock transform called Screen::showNumberPicker() directly from
the TAK policy worker.  That is the wrong execution context: showNumberPicker()
mutates UI state and renders immediately.  This post-transform adds a dedicated
Screen command so the TAK GPIO worker only enqueues OPEN_PIN; the Screen worker
then opens and renders the six-digit PIN picker in its own context.

The transform runs after patch_jarnsen_tracker_full_lock_ui.py and is idempotent.
"""
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, got {count}")
    return text.replace(old, new, 1)


TAK = Path("src/vehicle/HeltecTrackerV11TakLeaderPolicy.cpp")
tak = TAK.read_text(encoding="utf-8")

if "JARNSEN_TRACKER_TAK_FULL_LOCK_BUTTON" not in tak:
    print("Tracker Full Lock TAK transform not present; queued PIN post-transform skipped")
    raise SystemExit(0)

if "JARNSEN_TRACKER_TAK_PIN_QUEUE_V3" in tak:
    print("Tracker Full Lock GPIO0 PIN command queue already applied")
    raise SystemExit(0)

# ---------------------------------------------------------------------------
# Add a dedicated command without renumbering any existing command value.
# ---------------------------------------------------------------------------
COMMANDS = Path("src/commands.h")
commands = COMMANDS.read_text(encoding="utf-8")
if "JARNSEN_FULL_LOCK_PIN_REQUEST" not in commands:
    commands = replace_once(
        commands,
        "    NOOP\n};",
        "    NOOP,\n    JARNSEN_FULL_LOCK_PIN_REQUEST\n};",
        "Screen command enum",
    )
COMMANDS.write_text(commands, encoding="utf-8")


# ---------------------------------------------------------------------------
# Public queue entry point on Screen. No UI state is touched by the caller.
# ---------------------------------------------------------------------------
SCREEN_H = Path("src/graphics/Screen.h")
screen_h = SCREEN_H.read_text(encoding="utf-8")
if "requestJarnsenFullLockPin" not in screen_h:
    anchor = "    void showNumberPicker(const char *message, uint32_t durationMs, uint8_t digits, bool useBase16,\n                          std::function<void(uint32_t)> bannerCallback);\n"
    replacement = anchor + "#if defined(HELTEC_TRACKER_V1_1)\n    // Thread-safe entry used by the TAK GPIO0 worker while Full Lock is active.\n    void requestJarnsenFullLockPin();\n#endif\n"
    screen_h = replace_once(screen_h, anchor, replacement, "Screen PIN queue declaration")
SCREEN_H.write_text(screen_h, encoding="utf-8")


# ---------------------------------------------------------------------------
# Queue producer + queue consumer. showNumberPicker() now executes only in the
# Screen worker when the command is drained in Screen::runOnce().
# ---------------------------------------------------------------------------
SCREEN_CPP = Path("src/graphics/Screen.cpp")
screen = SCREEN_CPP.read_text(encoding="utf-8")
if "JARNSEN_FULL_LOCK_PIN_QUEUE_HANDLER" not in screen:
    function_anchor = "// Called to trigger an arcade-style initials picker (see showNumberPicker for\n"
    producer = r'''#if defined(HELTEC_TRACKER_V1_1)
void Screen::requestJarnsenFullLockPin()
{
    // JARNSEN_FULL_LOCK_PIN_QUEUE_HANDLER
    ScreenCmd cmd{};
    cmd.cmd = Cmd::JARNSEN_FULL_LOCK_PIN_REQUEST;
    enqueueCmd(cmd);
}
#endif

'''
    screen = replace_once(screen, function_anchor, producer + function_anchor, "Screen PIN queue producer")

    switch_anchor = "        case Cmd::NOOP:\n            break;\n"
    switch_replacement = r'''        case Cmd::JARNSEN_FULL_LOCK_PIN_REQUEST:
#if defined(HELTEC_TRACKER_V1_1)
            // The TAK GPIO worker only queues this command. All picker state and
            // rendering therefore happen here, on the Screen worker.
            if (jarnsen::serviceSecurityLocked() && !jarnsenFullLockPinPickerActive()) {
                if (NotificationRenderer::isOverlayBannerShowing())
                    NotificationRenderer::resetBanner();
                showNumberPicker("PIN", 0, 6, false, [](uint32_t pin) {
                    (void)jarnsen::serviceSecurityUnlock(pin);
                    if (screen)
                        screen->runNow();
                });
                LOG_INFO("Full Lock: local PIN entry opened from queued GPIO0 request");
            }
#endif
            break;
        case Cmd::NOOP:
            break;
'''
    screen = replace_once(screen, switch_anchor, switch_replacement, "Screen PIN queue consumer")
SCREEN_CPP.write_text(screen, encoding="utf-8")


# ---------------------------------------------------------------------------
# Replace the TAK worker's direct UI call with one queue operation.
# Support both the original transform and the temporary v2 state so retries or
# an interrupted development checkout remain repairable.
# ---------------------------------------------------------------------------
original = r'''                        if (!pinActive && screen) {
                            screen->showNumberPicker("PIN", 0, 6, false, [](uint32_t pin) {
                                (void)jarnsen::serviceSecurityUnlock(pin);
                                if (screen)
                                    screen->runNow();
                            });
                            leaderOpenedServiceThisPress = true;
                        }
'''

temporary_v2 = r'''                        if (!pinActive && screen) {
                            // JARNSEN_TRACKER_TAK_PIN_QUEUE_V2
                            // Do not call Screen::showNumberPicker() from this TAK
                            // worker. Seed the picker atomically enough for the
                            // Screen worker, then wake that worker to perform the
                            // actual render in its own context.
                            if (graphics::NotificationRenderer::isOverlayBannerShowing())
                                graphics::NotificationRenderer::resetBanner();
                            strncpy(graphics::NotificationRenderer::alertBannerMessage, "PIN",
                                    sizeof(graphics::NotificationRenderer::alertBannerMessage) - 1);
                            graphics::NotificationRenderer::alertBannerMessage[
                                sizeof(graphics::NotificationRenderer::alertBannerMessage) - 1] = '\0';
                            graphics::NotificationRenderer::alertBannerUntil = 0;
                            graphics::NotificationRenderer::alertBannerCallback = [](int pin) {
                                (void)jarnsen::serviceSecurityUnlock((uint32_t)pin);
                                if (screen)
                                    screen->runNow();
                            };
                            graphics::NotificationRenderer::pauseBanner = false;
                            graphics::NotificationRenderer::curSelected = 0;
                            graphics::NotificationRenderer::current_notification_type =
                                graphics::notificationTypeEnum::number_picker;
                            graphics::NotificationRenderer::numDigits = 6U;
                            graphics::NotificationRenderer::currentNumber = 0U;
                            graphics::NotificationRenderer::inEvent.inputEvent = INPUT_BROKER_NONE;
                            graphics::NotificationRenderer::inEvent.source = "UserButton";
                            graphics::NotificationRenderer::inEvent.kbchar = 0;
                            graphics::NotificationRenderer::inEvent.touchX = 0;
                            graphics::NotificationRenderer::inEvent.touchY = 0;
                            screen->runNow();
                            LOG_INFO("TAK Full Lock: GPIO0 requested local PIN entry");
                            leaderOpenedServiceThisPress = true;
                        }
'''

queued = r'''                        if (!pinActive && screen) {
                            // JARNSEN_TRACKER_TAK_PIN_QUEUE_V3: GPIO0 never
                            // mutates display state directly. Queue the request
                            // for the Screen worker and consume this first press.
                            screen->requestJarnsenFullLockPin();
                            leaderOpenedServiceThisPress = true;
                        }
'''

if temporary_v2 in tak:
    tak = tak.replace(temporary_v2, queued, 1)
elif original in tak:
    tak = tak.replace(original, queued, 1)
else:
    raise SystemExit("Tracker TAK PIN transition block not found")

for marker in (
    "JARNSEN_TRACKER_TAK_PIN_QUEUE_V3",
    "screen->requestJarnsenFullLockPin();",
):
    if marker not in tak:
        raise SystemExit(f"Tracker TAK PIN queue validation failed: {marker}")
TAK.write_text(tak, encoding="utf-8")

for path, marker in (
    (COMMANDS, "JARNSEN_FULL_LOCK_PIN_REQUEST"),
    (SCREEN_H, "requestJarnsenFullLockPin"),
    (SCREEN_CPP, "JARNSEN_FULL_LOCK_PIN_QUEUE_HANDLER"),
):
    if marker not in path.read_text(encoding="utf-8"):
        raise SystemExit(f"Queued PIN validation failed in {path}: {marker}")

print("Tracker V1.1 Full Lock GPIO0 -> Screen command queue applied")
