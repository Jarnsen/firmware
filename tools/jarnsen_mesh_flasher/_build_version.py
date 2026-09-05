from runtime_config import configure_runtime
from windows_branding import configure_windows_branding
from windows_usb_fallback import install as install_windows_usb_fallback

APP_VERSION = "1.0.0-alpha.2 · Build DEV"

configure_windows_branding()
configure_runtime()
install_windows_usb_fallback()
