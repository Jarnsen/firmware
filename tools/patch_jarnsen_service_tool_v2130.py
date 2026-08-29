"""v2.1.30: check firmware immediately after the automatic USB log download.

The firmware question belongs to the USB attach workflow, not to arbitrary
Dashboard refreshes.  The just-downloaded diagnostic payload is the source of
truth for device/build identification.  After the automatic log completes, the
Tool refreshes the GitHub firmware status and, only when that exact USB node is
behind the latest successful build, offers the existing safe USB updater.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "2.1.30"


def method_span(text: str, name: str) -> tuple[int, int]:
    normal = text.find(f"    def {name}(")
    asynchronous = text.find(f"    async def {name}(")
    starts = [value for value in (normal, asynchronous) if value >= 0]
    if not starts:
        raise SystemExit(f"v2.1.30 method {name} not found")
    start = min(starts)
    next_method = text.find("\n    def ", start + 1)
    next_async = text.find("\n    async def ", start + 1)
    next_decorator = text.find("\n    @", start + 1)
    candidates = [value for value in (next_method, next_async, next_decorator) if value >= 0]
    return start, min(candidates) if candidates else len(text)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"v2.1.30 {label}: expected one anchor, got {count}")
    return text.replace(old, new, 1)


def replace_method(text: str, name: str, updater) -> str:
    start, end = method_span(text, name)
    return text[:start] + updater(text[start:end]) + text[end:]


def patch(source: str) -> str:
    if "PATCH_V2130_AUTO_USB_FIRMWARE_CHECK" in source:
        return source

    source = re.sub(r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{APP_VERSION}"', source, count=1)
    source = source.replace('APP_VERSION != "2.1.29"', 'APP_VERSION != "2.1.30"')
    source = source.replace("App-Version ist nicht v2.1.29", "App-Version ist nicht v2.1.30")

    # v2.1.29 offered updates after every dashboard render.  Keep its optional
    # confirmation bypass for the actual updater, but disable the generic offer.
    generic_hook = (
        "        # v2.1.29: after every dashboard refresh, offer a newly detected firmware once.\n"
        "        self.after(100, self._offer_firmware_update_v2129)\n"
    )
    source = replace_once(source, generic_hook, "", "remove generic dashboard offer")

    # Capture the exact firmware identity from the successful automatic USB
    # download.  Do not derive this decision from old DB rows or a selected node.
    def patch_download(method: str) -> str:
        success = '''                        tool_log(\n                            "AUTO_USB_SUCCESS_V2125",\n                            port=port,\n                            attempt=retry_attempt,\n                            bytes=bytes_seen,\n                            duration_s=f"{time.monotonic() - attempt_started:.2f}",\n                        )\n                    return\n'''
        replacement = '''                        tool_log(\n                            "AUTO_USB_SUCCESS_V2125",\n                            port=port,\n                            attempt=retry_attempt,\n                            bytes=bytes_seen,\n                            duration_s=f"{time.monotonic() - attempt_started:.2f}",\n                        )\n                        payload_v2130 = bytes(captured)\n                        self._auto_usb_fw_pending_v2130 = {\n                            "port": port,\n                            "node_id": normalize_node_id(header_value(payload_v2130, b"node_id")),\n                            "long_name": header_value(payload_v2130, b"long_name"),\n                            "device": header_value(payload_v2130, b"device"),\n                            "firmware": jarnsen_firmware_label(payload_v2130),\n                            "build": header_value(payload_v2130, b"build").strip().lower(),\n                        }\n                        tool_log(\n                            "AUTO_USB_FW_PROBE_V2130",\n                            port=port,\n                            node_id=self._auto_usb_fw_pending_v2130.get("node_id") or "--",\n                            device=self._auto_usb_fw_pending_v2130.get("device") or "--",\n                            build=self._auto_usb_fw_pending_v2130.get("build") or "--",\n                        )\n                    return\n'''
        return replace_once(method, success, replacement, "auto USB success probe")

    source = replace_method(source, "_download_worker", patch_download)

    # The worker's existing 'done' event is already marshalled onto the Tk main
    # thread.  Start the network/version check from there instead of opening a
    # messagebox from the serial worker thread.
    done_anchor = '                elif kind == "done":\n'
    done_replacement = (
        done_anchor
        + '                    if getattr(self, "_auto_usb_fw_pending_v2130", None):\n'
        + '                        self.after(150, self._begin_auto_usb_firmware_check_v2130)\n'
    )
    source = replace_once(source, done_anchor, done_replacement, "done-event USB firmware hook")

    render_start, _render_end = method_span(source, "render_dashboard")
    helpers = r'''    def _begin_auto_usb_firmware_check_v2130(self) -> None:
        probe = getattr(self, "_auto_usb_fw_pending_v2130", None)
        if not isinstance(probe, dict) or not probe:
            return
        if getattr(self, "_auto_usb_fw_check_running_v2130", False):
            return
        self._auto_usb_fw_check_running_v2130 = True
        tool_log(
            "AUTO_USB_FW_CHECK_START_V2130",
            port=probe.get("port") or "--",
            node_id=probe.get("node_id") or "--",
            device=probe.get("device") or "--",
            build=probe.get("build") or "--",
        )
        # Always refresh here.  This makes USB attach -> log -> firmware check one
        # coherent workflow and avoids deciding from an old cached dashboard state.
        self.refresh_firmware_status()
        self.after(250, self._poll_auto_usb_firmware_check_v2130)

    def _poll_auto_usb_firmware_check_v2130(self) -> None:
        if getattr(self, "firmware_check_running", False):
            self.after(250, self._poll_auto_usb_firmware_check_v2130)
            return
        self._auto_usb_fw_check_running_v2130 = False
        self._offer_auto_usb_firmware_update_v2130()

    def _offer_auto_usb_firmware_update_v2130(self) -> None:
        probe = getattr(self, "_auto_usb_fw_pending_v2130", None)
        self._auto_usb_fw_pending_v2130 = None
        if not isinstance(probe, dict) or not probe:
            return

        port = str(probe.get("port") or "")
        device = str(probe.get("device") or "")
        build = str(probe.get("build") or "").strip().lower()
        firmware = str(probe.get("firmware") or "--")
        node_id = str(probe.get("node_id") or "")
        long_name = str(probe.get("long_name") or node_id or "Node")
        if not port or device not in FIRMWARE_WORKFLOWS or not build:
            tool_log(
                "AUTO_USB_FW_CHECK_SKIP_V2130",
                port=port or "--",
                node_id=node_id or "--",
                device=device or "--",
                build=build or "--",
                reason="missing-identity",
            )
            return

        state, detail, _level = self.firmware_state(device, build)
        if state != "Update":
            tool_log(
                "AUTO_USB_FW_CHECK_DONE_V2130",
                port=port,
                node_id=node_id or "--",
                device=device,
                build=build,
                state=state,
            )
            return

        label = DEVICE_NAMES.get(device, device)
        tool_log(
            "AUTO_USB_FW_UPDATE_AVAILABLE_V2130",
            port=port,
            node_id=node_id or "--",
            device=device,
            build=build,
        )
        install_now = messagebox.askyesno(
            "Firmwareupdate nach USB-Logdownload",
            f"Der automatische Logdownload von {long_name} ({label}) ist abgeschlossen.\n\n"
            f"Installiert: {firmware} [{build[:8]}]\n"
            f"{detail}\n\n"
            f"Soll die neue Firmware jetzt direkt über USB ({port}) installiert werden?",
        )
        if not install_now:
            tool_log(
                "AUTO_USB_FW_UPDATE_DECLINED_V2130",
                port=port,
                node_id=node_id or "--",
                device=device,
                build=build,
            )
            return

        # Bind the updater to exactly the physical COM port that just delivered
        # the log and to the hardware identity read from that same payload.
        self._select_serial_port_in_ui(port)
        if hasattr(self, "device"):
            self.device.set(label)
        tool_log(
            "AUTO_USB_FW_UPDATE_ACCEPTED_V2130",
            port=port,
            node_id=node_id or "--",
            device=device,
            build=build,
        )
        self.start_serial_update(skip_confirm_v2129=True)
'''
    source = source[:render_start] + helpers.rstrip() + "\n\n" + source[render_start:]

    source += "\n# PATCH_V2130_AUTO_USB_FIRMWARE_CHECK\n"
    required = (
        'APP_VERSION = "2.1.30"',
        "AUTO_USB_FW_PROBE_V2130",
        "def _begin_auto_usb_firmware_check_v2130(self)",
        "def _poll_auto_usb_firmware_check_v2130(self)",
        "def _offer_auto_usb_firmware_update_v2130(self)",
        "Firmwareupdate nach USB-Logdownload",
        "Soll die neue Firmware jetzt direkt über USB",
        "self.refresh_firmware_status()",
        "self.start_serial_update(skip_confirm_v2129=True)",
        "PATCH_V2130_AUTO_USB_FIRMWARE_CHECK",
    )
    missing = [marker for marker in required if marker not in source]
    if missing:
        raise SystemExit("v2.1.30 validation failed: " + ", ".join(missing))
    if "self.after(100, self._offer_firmware_update_v2129)" in source:
        raise SystemExit("v2.1.30 generic dashboard firmware offer still active")
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v2130.py <source.py>")
    path = Path(sys.argv[1])
    path.write_text(patch(path.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"Patched {path} to v{APP_VERSION}: USB attach log -> firmware check -> direct USB update offer")


if __name__ == "__main__":
    main()
