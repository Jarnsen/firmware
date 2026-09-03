from runtime_config import configure_runtime

APP_VERSION = "1.0.0-alpha.1 \u00b7 Build DEV"

configure_runtime()

try:
    import services
    from usb_log_download import install as install_usb_log_download

    install_usb_log_download(services)
except Exception:
    pass
