"""v2.1.5: deterministic advanced pane, central selected/all BLE logs and V3 BLE->WLAN handover."""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "2.1.5"


def method_span(text: str, name: str) -> tuple[int, int]:
    start = text.find(f"    def {name}(")
    if start < 0:
        raise SystemExit(f"method {name} not found")
    next_method = text.find("\n    def ", start + 1)
    next_decorator = text.find("\n    @", start + 1)
    candidates = [value for value in (next_method, next_decorator) if value >= 0]
    return start, min(candidates) if candidates else len(text)


def replace_method(text: str, name: str, updater) -> str:
    start, end = method_span(text, name)
    return text[:start] + updater(text[start:end]) + text[end:]


def insert_before_method(text: str, name: str, code: str) -> str:
    start, _ = method_span(text, name)
    return text[:start] + code.rstrip() + "\n\n" + text[start:]


def patch(source: str) -> str:
    source = re.sub(r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{APP_VERSION}"', source, count=1)
    source = source.replace('APP_VERSION != "2.1.4"', 'APP_VERSION != "2.1.5"')
    source = source.replace("App-Version ist nicht v2.1.4", "App-Version ist nicht v2.1.5")

    # v2.1.4 used one toggle function for both opening and closing.  Direct
    # Bluetooth/USB actions can change pane visibility independently of the old
    # boolean, so make open/close absolute operations and let toggle only dispatch.
    def replace_toggle(_method: str) -> str:
        return r'''    def _advanced_controls_visible(self) -> bool:
        if self.body_pane is None or self.controls_host is None:
            return False
        try:
            return str(self.controls_host) in {str(item) for item in self.body_pane.panes()}
        except tk.TclError:
            return False

    def open_advanced_controls(self) -> None:
        if self.body_pane is None or self.controls_host is None:
            return
        try:
            if not self._advanced_controls_visible():
                self.body_pane.insert(0, self.controls_host, weight=0)
            self.advanced_visible = True
            self.advanced_button.configure(text="Erweitert schließen")
            if hasattr(self, "advanced_close_button"):
                self.advanced_close_button.configure(text="← Erweitert schließen")
            self.update_idletasks()
            tool_log("ADVANCED_CONTROLS", state="open", panes="|".join(str(p) for p in self.body_pane.panes()))
        except tk.TclError as exc:
            tool_log_exception("open_advanced_controls", exc)

    def close_advanced_controls(self) -> None:
        if self.body_pane is None or self.controls_host is None:
            return
        try:
            # Forget the actual pane unconditionally.  Do not depend on the
            # historical advanced_visible flag; that was the v2.1.4 trap.
            for pane in tuple(self.body_pane.panes()):
                if str(pane) == str(self.controls_host):
                    self.body_pane.forget(pane)
                    break
            if self._advanced_controls_visible():
                self.body_pane.forget(self.controls_host)
            self.advanced_visible = False
            self.advanced_button.configure(text="Erweitert öffnen")
            self.update_idletasks()
            tool_log("ADVANCED_CONTROLS", state="closed", panes="|".join(str(p) for p in self.body_pane.panes()))
        except tk.TclError as exc:
            tool_log_exception("close_advanced_controls", exc)

    def toggle_advanced_controls(self) -> None:
        if self._advanced_controls_visible():
            self.close_advanced_controls()
        else:
            self.open_advanced_controls()
'''

    source = replace_method(source, "toggle_advanced_controls", replace_toggle)

    def patch_workflow(method: str) -> str:
        old = '''                command=self.toggle_advanced_controls,\n                style="Primary.TButton",\n'''
        new = '''                command=self.close_advanced_controls,\n                style="Primary.TButton",\n'''
        # Only the in-pane blue close button has Primary.TButton at this point.
        if "self.advanced_close_button" in method and "command=self.close_advanced_controls" not in method:
            if method.count(old) != 1:
                raise SystemExit("v2.1.5 advanced close-button command anchor not found")
            method = method.replace(old, new, 1)
        return method

    source = replace_method(source, "_install_workflow_ui", patch_workflow)

    for method_name in ("open_bluetooth_tools", "open_serial_tools", "add_new_node", "open_usb_recovery"):
        def make_open_absolute(method: str) -> str:
            old = '''        if not self.advanced_visible:\n            self.toggle_advanced_controls()\n'''
            if old in method:
                method = method.replace(old, "        self.open_advanced_controls()\n", 1)
            return method
        source = replace_method(source, method_name, make_open_absolute)

    if "    def _ble_log_candidates(self)" not in source:
        helpers = r'''    def _selected_ble_identity_tokens(self) -> list[str]:
        tokens: list[str] = []
        if self.node_logs and isinstance(self.node_logs[-1].get("metrics"), dict):
            metrics = self.node_logs[-1]["metrics"]
            for key in ("long_name", "short_name"):
                value = str(metrics.get(key) or "").strip()
                if len(value) >= 2:
                    tokens.append(value.lower())
        node_id = str(self.selected_node_id or "").strip().lstrip("!")
        if len(node_id) >= 4:
            tokens.append(node_id.lower())
            tokens.append(node_id[-4:].lower())
        return list(dict.fromkeys(tokens))

    def _ble_label_matches_selected(self, label: str) -> bool:
        lowered = str(label).lower()
        return any(token in lowered for token in self._selected_ble_identity_tokens())

    def _ble_log_candidates(self) -> list[tuple[str, object]]:
        candidates: list[tuple[str, object]] = []
        for label, device in self.ble_map.items():
            if label.startswith("[BLE] ") or label.startswith("[OTA] "):
                continue
            candidates.append((label, device))
        return candidates

    def _show_ble_targets(self, targets: list[tuple[str, object]]) -> None:
        labels = list(self.ble_map)
        wanted = {label for label, _device in targets}
        with contextlib.suppress(tk.TclError):
            self.ble_device.selection_clear(0, "end")
            first = None
            for index, label in enumerate(labels):
                if label in wanted:
                    self.ble_device.selection_set(index)
                    if first is None:
                        first = index
            if first is not None:
                self.ble_device.see(first)
'''
        source = insert_before_method(source, "start_ble_download", helpers)

    def patch_start_download(method: str) -> str:
        old = '''        ble_devices = self.selected_ble_devices()\n        if not ble_devices:\n            messagebox.showerror(\n                "Kein Bluetooth-Gerät",\n                "Bitte zuerst Bluetooth-Nodes suchen und mindestens einen Node markieren.",\n            )\n            return\n'''
        if old not in method:
            raise SystemExit("v2.1.5 start_ble_download target anchor not found")
        new = r'''        candidates = self._ble_log_candidates()
        if not candidates:
            messagebox.showerror(
                "Keine Bluetooth-Node",
                "Es ist aktuell keine passende Jarnsen-Node per Bluetooth erreichbar. Bitte Nodes suchen und erneut versuchen.",
            )
            return

        matching = [(label, device) for label, device in candidates if self._ble_label_matches_selected(label)]
        if len(candidates) > 1:
            selected_name = self._preferred_ble_name().strip() or self.selected_node_id or "ausgewählte Node"
            tool_log(
                "BLE_MULTI_DOWNLOAD_PROMPT_V215",
                candidates=len(candidates),
                matching=len(matching),
                selected=selected_name,
            )
            choice = messagebox.askyesnocancel(
                "Mehrere Bluetooth-Nodes erreichbar",
                f"{len(candidates)} Nodes sind aktuell per Bluetooth erreichbar.\n\n"
                "Ja = nur die im zentralen Node-Dropdown ausgewählte Node herunterladen\n"
                "Nein = Logs von allen aktuell erreichbaren Nodes nacheinander herunterladen\n"
                "Abbrechen = nichts herunterladen\n\n"
                "Nicht erreichbare oder ausfallende Nodes werden bei 'Alle' übersprungen.",
            )
            if choice is None:
                tool_log("BLE_MULTI_DOWNLOAD_CHOICE_V215", choice="cancel")
                return
            if choice:
                if len(matching) != 1:
                    tool_log("BLE_MULTI_DOWNLOAD_CHOICE_V215", choice="selected-not-found", matches=len(matching))
                    messagebox.showwarning(
                        "Ausgewählte Node nicht erreichbar",
                        "Die im zentralen Node-Dropdown ausgewählte Node konnte unter den aktuellen Bluetooth-Treffern nicht eindeutig gefunden werden. Es wurde nichts von einer anderen Node geladen.",
                    )
                    self.open_advanced_controls()
                    self.show_controls_page("Bluetooth")
                    return
                ble_devices = matching
                tool_log("BLE_MULTI_DOWNLOAD_CHOICE_V215", choice="selected", node=matching[0][0])
            else:
                ble_devices = candidates
                tool_log("BLE_MULTI_DOWNLOAD_CHOICE_V215", choice="all", count=len(ble_devices))
        else:
            ble_devices = candidates
            # With only one reachable Node, never silently download the wrong
            # known Node when another one is selected centrally.
            if self._selected_ble_identity_tokens() and not matching:
                messagebox.showwarning(
                    "Ausgewählte Node nicht erreichbar",
                    "Die einzige erreichbare Bluetooth-Node passt nicht zur zentral ausgewählten Node. Es wurde nichts heruntergeladen.",
                )
                self.open_advanced_controls()
                self.show_controls_page("Bluetooth")
                return

        self._show_ble_targets(ble_devices)
'''
        return method.replace(old, new, 1)

    source = replace_method(source, "start_ble_download", patch_start_download)

    def replace_continue(_method: str) -> str:
        return r'''    def _continue_smart_action(self) -> None:
        action = self.pending_smart_action
        if not action or (self.worker and self.worker.is_alive()):
            return

        # Log targets are resolved centrally by start_ble_download().  This is
        # what guarantees the selected-vs-all popup also for the direct BLE button.
        if action == "download" and self.ble_map:
            self.pending_smart_action = ""
            self.start_ble_download()
            return

        if self._select_preferred_ble_device():
            self.pending_smart_action = ""
            if action == "download":
                self.start_ble_download()
            elif action == "live":
                self.notebook.select(self.live_tab)
                self.toggle_live()
            elif action == "update":
                self.notebook.select(self.firmware_tab)
                self.start_ble_update()
            elif action == "wlan":
                self.start_service_wlan_handover()
            return

        if self.ble_map:
            self.pending_smart_action = ""
            self.open_advanced_controls()
            self.show_controls_page("Bluetooth")
            self.notebook.select(self.service_tab)
            self.status_level = "warning"
            if action == "wlan":
                self.status.configure(text="Die zentral ausgewählte Node ist per Bluetooth nicht erreichbar – WLAN wurde nicht gestartet")
            else:
                self.status.configure(text="Mehrere Nodes gefunden – bitte den gewünschten Bluetooth-Node prüfen")
            self._update_status_badge()
            return

        if BLE_AVAILABLE and getattr(self, "ble_scan_button", None) is not None and str(self.ble_scan_button.cget("state")) == "disabled":
            return

        self.pending_smart_action = ""
        if action == "download" and self.port.get() and self.port.get() in self.port_map:
            self.start_download()
            return
        if action == "live":
            self.open_advanced_controls()
            self.show_controls_page("Bluetooth")
            self.status_level = "warning"
            self.status.configure(text="Keine passende BLE-Node gefunden – Service am Gerät öffnen und erneut suchen")
            self._update_status_badge()
            return
        if action == "wlan":
            self.status_level = "warning"
            self.status.configure(text="WLAN-Service konnte nicht gestartet werden – ausgewählte V3-Node ist per BLE nicht erreichbar")
            self._update_status_badge()
            messagebox.showwarning(
                "WLAN-Service",
                "Die ausgewählte V3-Node ist aktuell nicht per Bluetooth erreichbar. Servicefenster am V3 öffnen und erneut versuchen.",
            )
            return
        self.open_usb_recovery()
        if action == "update":
            self.status_level = "warning"
            self.status.configure(text="Keine passende BLE-Node gefunden – USB / Recovery für Firmwareupdate geöffnet")
'''

    source = replace_method(source, "_continue_smart_action", replace_continue)

    wlan_methods = r'''    def start_service_wlan_handover(self) -> None:
        if not BLE_AVAILABLE:
            messagebox.showerror("WLAN-Service", "Bluetooth-Unterstützung ist in dieser App nicht verfügbar.")
            return
        if self.worker and self.worker.is_alive():
            return
        metrics = self.node_logs[-1].get("metrics", {}) if self.node_logs else {}
        device_code = str(metrics.get("device") or "") if isinstance(metrics, dict) else ""
        if device_code and device_code != "HELTEC_V3_REPEATER":
            messagebox.showinfo(
                "WLAN-Service",
                "Der automatische BLE→WLAN-Fernstart ist derzeit für den Heltec V3 vorgesehen.",
            )
            return
        selected = self.selected_ble_devices()
        if len(selected) != 1:
            messagebox.showwarning(
                "WLAN-Service",
                "Die zentral ausgewählte V3-Node konnte keinem einzelnen Bluetooth-Treffer zugeordnet werden.",
            )
            return
        label, ble_device = selected[0]
        self.stop_event.clear()
        self.cancel_button.configure(state="normal")
        self.status_level = "normal"
        self.status.configure(text=f"{label}: BLE→WLAN-Übergabe wird gestartet …")
        self._update_status_badge()
        tool_log("WLAN_HANDOVER_START", node=label)
        self.worker = threading.Thread(
            target=self._service_wlan_worker,
            args=(label, ble_device),
            daemon=True,
        )
        self.worker.start()

    def _service_wlan_worker(self, label: str, ble_device: object) -> None:
        try:
            response = asyncio.run(self._service_wlan_handover_async(ble_device))
            tool_log("WLAN_HANDOVER_ACK", node=label, response=response)
            self.events.put(("wlan_handover_done", label))
        except Exception as exc:
            tool_log_exception("wlan_handover", exc)
            self.events.put(("wlan_handover_error", str(exc)))
        finally:
            self.events.put(("done", None))

    async def _service_wlan_handover_async(self, ble_device: object) -> str:
        client = BleakClient(
            ble_device,
            timeout=30.0,
            pair=False,
            winrt={"use_cached_services": False},
        )
        await client.connect()
        try:
            await client.write_gatt_char(JARNSEN_DIAG_CONTROL_UUID, b"WLANSTART", response=True)
            response = bytes(await client.read_gatt_char(JARNSEN_DIAG_CONTROL_UUID)).decode(
                "ascii", "replace"
            ).strip()
            if response == "LOCKED":
                raise RuntimeError(
                    "V3 hat den WLAN-Start abgelehnt. Servicefenster am Node öffnen und erneut versuchen."
                )
            if response != "WLAN_ACK":
                raise RuntimeError(
                    "Die installierte V3-Firmware unterstützt den sicheren BLE→WLAN-Fernstart noch nicht "
                    f"({response or '--'})."
                )
            # Firmware confirms first, then deliberately disconnects BLE after a
            # short guard and starts the WLAN worker. A remote disconnect here is success.
            await asyncio.sleep(0.9)
            return response
        finally:
            with contextlib.suppress(Exception):
                await client.disconnect()
'''

    if "    def start_service_wlan_handover(self)" not in source:
        source = insert_before_method(source, "open_service_wlan", wlan_methods)

    def replace_open_wlan(_method: str) -> str:
        return r'''    def open_service_wlan(self) -> None:
        if self.worker and self.worker.is_alive():
            self.status_level = "warning"
            self.status.configure(text="Ein anderer Vorgang läuft bereits")
            self._update_status_badge()
            return
        self.status_level = "normal"
        self.status.configure(text="WLAN-Service: ausgewählte V3-Node wird per Bluetooth angesprochen …")
        self._update_status_badge()
        self._queue_smart_ble_action("wlan")
'''

    source = replace_method(source, "open_service_wlan", replace_open_wlan)

    def patch_events(method: str) -> str:
        if "wlan_handover_done" in method:
            return method
        anchor = '''                elif kind == "done":\n'''
        if method.count(anchor) != 1:
            raise SystemExit("v2.1.5 event-pump done anchor not found")
        addition = r'''                elif kind == "wlan_handover_done":
                    self.status_level = "success"
                    self.status.configure(text="V3 hat BLE beendet und startet den WLAN-Service")
                    self._update_status_badge()
                    self.set_result(
                        "WLAN-Service am V3 wurde über Bluetooth angefordert.\n\n"
                        "Der V3 trennt BLE absichtlich und startet anschließend seinen Access Point.\n"
                        "Mit dem WLAN Jarnsen-V3-… verbinden · Passwort 24011980 · danach http://192.168.4.1 öffnen."
                    )
                    if sys.platform == "win32":
                        with contextlib.suppress(OSError):
                            os.startfile("ms-settings:network-wifi")  # type: ignore[attr-defined]
                    messagebox.showinfo(
                        "WLAN-Service gestartet",
                        "BLE→WLAN-Übergabe bestätigt.\n\n"
                        "Der V3 trennt Bluetooth und startet jetzt den Service-Access-Point.\n"
                        "WLAN: Jarnsen-V3-…\nPasswort: 24011980\nAdresse: 192.168.4.1",
                    )
                elif kind == "wlan_handover_error":
                    self.status_level = "warning"
                    self.status.configure(text="WLAN-Service konnte nicht gestartet werden")
                    self._update_status_badge()
                    messagebox.showwarning("WLAN-Service", str(value))
'''
        return method.replace(anchor, addition + anchor, 1)

    source = replace_method(source, "_pump_events", patch_events)

    required = (
        'APP_VERSION = "2.1.5"',
        "def open_advanced_controls(self)",
        "def close_advanced_controls(self)",
        "command=self.close_advanced_controls",
        "BLE_MULTI_DOWNLOAD_PROMPT_V215",
        "nur die im zentralen Node-Dropdown ausgewählte Node herunterladen",
        "Logs von allen aktuell erreichbaren Nodes nacheinander herunterladen",
        "def start_service_wlan_handover(self)",
        'b"WLANSTART"',
        '"WLAN_ACK"',
        'kind == "wlan_handover_done"',
        'os.startfile("ms-settings:network-wifi")',
    )
    for marker in required:
        if marker not in source:
            raise SystemExit(f"missing v2.1.5 marker: {marker}")
    return source


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "tools/JARNSEN_NODE_SERVICE_TOOL.py")
    target.write_text(patch(target.read_text(encoding="utf-8")), encoding="utf-8")
    print("Service tool v2.1.5: deterministic advanced pane + selected/all BLE logs + V3 WLAN handover")


if __name__ == "__main__":
    main()
