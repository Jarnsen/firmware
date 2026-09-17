"""Harden Tracker V1.1 Full-Lock GPIO0 -> PIN transition.

The first Full-Lock patch called Screen::showNumberPicker() directly from the
TAK policy worker.  That method mutates UI state and immediately renders, so it
must not be driven from the separate GPIO polling thread.  This follow-up keeps
the physical button detection in the TAK worker, but only seeds the PIN picker
state there and wakes the Screen worker.  The actual draw then happens in the
normal Screen context.

This post-transform is intentionally narrow and idempotent.  It runs after
patch_jarnsen_tracker_full_lock_ui.py and changes only the Tracker TAK locked
first-press branch.
"""
from pathlib import Path

TAK = Path("src/vehicle/HeltecTrackerV11TakLeaderPolicy.cpp")
text = TAK.read_text(encoding="utf-8")

if "JARNSEN_TRACKER_TAK_PIN_QUEUE_V2" in text:
    print("Tracker Full Lock GPIO0 PIN queue v2 already applied")
    raise SystemExit(0)

if "JARNSEN_TRACKER_TAK_FULL_LOCK_BUTTON" not in text:
    print("Tracker Full Lock TAK transform not present; v2 post-transform skipped")
    raise SystemExit(0)

old = r'''                        if (!pinActive && screen) {
                            screen->showNumberPicker("PIN", 0, 6, false, [](uint32_t pin) {
                                (void)jarnsen::serviceSecurityUnlock(pin);
                                if (screen)
                                    screen->runNow();
                            });
                            leaderOpenedServiceThisPress = true;
                        }
'''

new = r'''                        if (!pinActive && screen) {
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

count = text.count(old)
if count != 1:
    raise SystemExit(f"Tracker TAK PIN transition: expected one old block, got {count}")

text = text.replace(old, new, 1)

for marker in (
    "JARNSEN_TRACKER_TAK_PIN_QUEUE_V2",
    'alertBannerMessage, "PIN"',
    "current_notification_type =\n                                graphics::notificationTypeEnum::number_picker;",
    "screen->runNow();",
):
    if marker not in text:
        raise SystemExit(f"Tracker TAK PIN queue v2 validation failed: {marker}")

TAK.write_text(text, encoding="utf-8")
print("Tracker V1.1 Full Lock GPIO0 -> queued PIN UI transition applied")
