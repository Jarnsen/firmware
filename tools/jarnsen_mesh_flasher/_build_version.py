from advanced_flasher import install as install_advanced_flasher
from manual_board_fallback import install as install_manual_board_fallback
from profile_runtime_efficiency import install as install_profile_runtime_efficiency
from radio_profile_existing_slot_reuse import (
    install as install_radio_profile_existing_slot_reuse,
)
from runtime_config import configure_runtime
from windows_branding import configure_windows_branding
from windows_usb_fallback import install as install_windows_usb_fallback

APP_VERSION = "1.0.0-alpha.2 · Build DEV"

configure_windows_branding()
configure_runtime()
install_profile_runtime_efficiency(__import__("services"))
install_radio_profile_existing_slot_reuse(__import__("services"))
install_manual_board_fallback(__import__("services"))
install_advanced_flasher(__import__("services"))
install_windows_usb_fallback()
