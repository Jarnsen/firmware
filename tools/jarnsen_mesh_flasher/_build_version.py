from runtime_config import configure_runtime
from windows_branding import configure_windows_branding
from windows_usb_fallback import install as install_windows_usb_fallback
from manual_board_fallback import install as install_manual_board_fallback
from radio_profiles import install as install_radio_profiles
from radio_profiles_ui import install as install_radio_profiles_ui

APP_VERSION = "1.0.0-alpha.2 · Build DEV"

configure_windows_branding()
configure_runtime()
_services = __import__("services")
install_manual_board_fallback(_services)
install_windows_usb_fallback()
install_radio_profiles(_services)
install_radio_profiles_ui(_services)
