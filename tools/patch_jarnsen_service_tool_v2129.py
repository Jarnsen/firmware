"""v2.1.29: offer immediate firmware installation when a newer build is detected."""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "2.1.29"


def method_span(text: str, name: str) -> tuple[int, int]:
    normal = text.find(f"    def {name}(")
    asynchronous = text.find(f"    async def {name}(")
    starts = [value for value in (normal, asynchronous) if value >= 0]
    if not starts:
        raise SystemExit(f"v2.1.29 method {name} not found")
    start = min(starts)
    next_method = text.find("\n    def ", start + 1)
    next_async = text.find("\n    async def ", start + 1)
    next_decorator = text.find("\n    @", start + 1)
    candidates = [value for value in (next_method, next_async, next_decorator) if value >= 0]
    return start, min(candidates) if candidates else len(text)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"v2.1.29 {label}: expected one anchor, got {count}")
    return text.replace(old, new, 1)


def replace_method(text: str, name: str, updater) -> str:
    start, end = method_span(text, name)
    return text[:start] + updater(text[start:end]) + text[end:]


def patch(source: str) -> str:
    if "PATCH_V2129_DIRECT_FIRMWARE_OFFER" in source:
        return source

    source = re.sub(r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{APP_VERSION}"', source, count=1)
    source = source.replace('APP_VERSION != "2.1.28"', 'APP_VERSION != "2.1.29"')
    source = source.replace("App-Version ist nicht v2.1.28", "App-Version ist nicht v2.1.29")

    def make_confirm_optional(method: str, name: str, title: str) -> str:
        old_header = f"    def {name}(self) -> None:\n"
        new_header = f"    def {name}(self, skip_confirm_v2129: bool = False) -> None:\n"
        method = replace_once(method, old_header, new_header, f"{name} signature")
        old_confirm = f'        if not messagebox.askyesno(\n            "{title}",\n'
        new_confirm = f'        if not skip_confirm_v2129 and not messagebox.askyesno(\n            "{title}",\n'
        return replace_once(method, old_confirm, new_confirm, f"{name} confirmation")

    source = replace_method(
        source,
        "start_serial_update",
        lambda method: make_confirm_optional(method, "start_serial_update", "USB-Firmwareupdate"),
    )
    source = replace_method(
        source,
        "start_ble_update",
        lambda method: make_confirm_optional(method, "start_ble_update", "Bluetooth-Firmwareupdate"),
    )

    render_start, _render_end = method_span(source, "render_dashboard")
    helper = r'''    def _offer_firmware_update_v2129(self) -> None:
        """Ask once per node/release whether a detected update should be installed now."""
        if getattr(self, "_firmware_offer_active_v2129", False):
            return
        if getattr(self, "firmware_check_running", False):
            return
        if getattr(self, "worker", None) is not None and self.worker.is_alive():
            return

        node_id = str(getattr(self, "selected_node_id", "") or "")
        logs = getattr(self, "node_logs", None)
        if not node_id or not isinstance(logs, list) or not logs:
            return
        latest = logs[-1] if isinstance(logs[-1], dict) else {}
        metrics = latest.get("metrics") if isinstance(latest.get("metrics"), dict) else {}
        device = str(metrics.get("device") or latest.get("device") or "")
        build = str(metrics.get("build") or latest.get("build") or "").strip().lower()
        firmware = str(metrics.get("firmware") or latest.get("firmware") or "--")
        if device not in FIRMWARE_WORKFLOWS or not build:
            return

        state, detail, _level = self.firmware_state(device, build)
        if state != "Update":
            return

        release = self.firmware_releases.get(device)
        runs = release.get("runs", []) if isinstance(release, dict) else []
        newest = runs[0] if runs and isinstance(runs[0], dict) else {}
        release_key = str(
            newest.get("head_sha")
            or newest.get("sha")
            or newest.get("id")
            or newest.get("url")
            or detail
        )
        offer_key = f"{node_id}|{device}|{build}|{release_key}"
        seen = getattr(self, "_firmware_offer_seen_v2129", None)
        if not isinstance(seen, set):
            seen = set()
            self._firmware_offer_seen_v2129 = seen
        if offer_key in seen:
            return
        seen.add(offer_key)

        ble_devices = []
        if BLE_AVAILABLE:
            try:
                ble_devices = list(self.selected_ble_devices())
            except Exception:
                ble_devices = []
        try:
            port = str(self.selected_port() or "")
        except Exception:
            port = ""

        if len(ble_devices) == 1:
            transport = "Bluetooth (markierte Node)"
        elif port:
            transport = f"USB ({port})"
        elif len(ble_devices) > 1:
            transport = "Bluetooth (mehrere Nodes markiert)"
        else:
            transport = "noch kein Update-Transport ausgewählt"

        label = DEVICE_NAMES.get(device, device)
        long_name = str(metrics.get("long_name") or node_id)
        self._firmware_offer_active_v2129 = True
        try:
            install_now = messagebox.askyesno(
                "Firmwareupdate verfügbar",
                f"Für {long_name} ({label}) ist eine neuere Firmware verfügbar.\n\n"
                f"Aktuell: {firmware} [{build[:8]}]\n"
                f"{detail}\n\n"
                f"Installation über: {transport}\n\n"
                "Soll die neue Firmware jetzt direkt installiert werden?",
            )
        finally:
            self._firmware_offer_active_v2129 = False

        if not install_now:
            return

        # A single explicitly selected BLE node is the clearest node-to-transport
        # association. Otherwise use the currently selected physical USB port.
        if len(ble_devices) == 1:
            self.start_ble_update(skip_confirm_v2129=True)
            return
        if port:
            if hasattr(self, "device"):
                self.device.set(label)
            self.start_serial_update(skip_confirm_v2129=True)
            return

        if len(ble_devices) > 1:
            messagebox.showinfo(
                "Firmwareupdate bereit",
                "Bitte genau eine Bluetooth-Node markieren oder einen USB-Port auswählen. "
                "Danach kann das Update direkt gestartet werden.",
            )
        else:
            messagebox.showinfo(
                "Firmwareupdate bereit",
                "Bitte die Node per USB verbinden und den COM-Port auswählen oder die Node "
                "über Bluetooth suchen und markieren. Das Update bleibt als verfügbar angezeigt.",
            )
'''
    source = source[:render_start] + helper.rstrip() + "\n\n" + source[render_start:]

    def patch_render(method: str) -> str:
        anchor = "    def render_dashboard(self) -> None:\n"
        replacement = (
            anchor
            + "        # v2.1.29: after every dashboard refresh, offer a newly detected firmware once.\n"
            + "        self.after(100, self._offer_firmware_update_v2129)\n"
        )
        return replace_once(method, anchor, replacement, "render offer hook")

    source = replace_method(source, "render_dashboard", patch_render)
    source += "\n# PATCH_V2129_DIRECT_FIRMWARE_OFFER\n"

    required = (
        'APP_VERSION = "2.1.29"',
        "def _offer_firmware_update_v2129(self)",
        "Firmwareupdate verfügbar",
        "Soll die neue Firmware jetzt direkt installiert werden?",
        "start_ble_update(skip_confirm_v2129=True)",
        "start_serial_update(skip_confirm_v2129=True)",
        "skip_confirm_v2129: bool = False",
        "self.after(100, self._offer_firmware_update_v2129)",
        "PATCH_V2129_DIRECT_FIRMWARE_OFFER",
    )
    missing = [marker for marker in required if marker not in source]
    if missing:
        raise SystemExit("v2.1.29 validation failed: " + ", ".join(missing))
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v2129.py <source.py>")
    path = Path(sys.argv[1])
    path.write_text(patch(path.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"Patched {path} to v{APP_VERSION}: direct firmware install offer")


if __name__ == "__main__":
    main()
