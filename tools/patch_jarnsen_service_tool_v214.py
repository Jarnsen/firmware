"""v2.1.4: Bluetooth preflight/self-repair and always-closable advanced controls."""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "2.1.4"


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
    source = source.replace('APP_VERSION != "2.1.3"', 'APP_VERSION != "2.1.4"')
    source = source.replace("App-Version ist nicht v2.1.3", "App-Version ist nicht v2.1.4")

    # Add a close button inside the advanced pane itself. This remains visible
    # even if the top-row controls become tight at 1080p/DPI scaling.
    def patch_workflow_ui(method: str) -> str:
        if "self.advanced_close_button" not in method:
            anchor = '        self.advanced_button.pack(side="right")\n'
            addition = anchor + '''        if self.controls_host is not None and hasattr(self, "controls_canvas"):\n            self.advanced_close_button = ttk.Button(\n                self.controls_host,\n                text="← Erweitert schließen",\n                command=self.toggle_advanced_controls,\n                style="Primary.TButton",\n            )\n            self.advanced_close_button.pack(\n                side="top", fill="x", padx=4, pady=(4, 4), before=self.controls_canvas\n            )\n'''
            if method.count(anchor) != 1:
                raise SystemExit("advanced close-button anchor not found")
            method = method.replace(anchor, addition, 1)
        hide_anchor = '''                self.body_pane.forget(self.controls_host)\n                self.advanced_visible = False\n'''
        if 'self.advanced_button.configure(text="Erweitert öffnen")' not in method:
            if method.count(hide_anchor) != 1:
                raise SystemExit("advanced initial hide anchor not found")
            method = method.replace(
                hide_anchor,
                hide_anchor + '                self.advanced_button.configure(text="Erweitert öffnen")\n',
                1,
            )
        return method

    source = replace_method(source, "_install_workflow_ui", patch_workflow_ui)

    def replace_toggle(_method: str) -> str:
        return r'''    def toggle_advanced_controls(self) -> None:
        if self.body_pane is None or self.controls_host is None:
            return
        try:
            panes = {str(item) for item in self.body_pane.panes()}
            visible = str(self.controls_host) in panes
            if visible:
                self.body_pane.forget(self.controls_host)
                self.advanced_visible = False
                self.advanced_button.configure(text="Erweitert öffnen")
                tool_log("ADVANCED_CONTROLS", state="closed")
            else:
                self.body_pane.insert(0, self.controls_host, weight=0)
                self.advanced_visible = True
                self.advanced_button.configure(text="Erweitert schließen")
                if hasattr(self, "advanced_close_button"):
                    self.advanced_close_button.configure(text="← Erweitert schließen")
                tool_log("ADVANCED_CONTROLS", state="open")
        except tk.TclError as exc:
            tool_log_exception("toggle_advanced_controls", exc)
'''

    source = replace_method(source, "toggle_advanced_controls", replace_toggle)

    if "    def _windows_bluetooth_adapter_state(self)" not in source:
        helpers = r'''    def _windows_bluetooth_adapter_state(self) -> tuple[bool, str]:
        """Return whether Windows reports at least one healthy physical Bluetooth adapter."""
        if os.name != "nt":
            return True, "non-windows"
        command = (
            "$items=Get-PnpDevice -Class Bluetooth -PresentOnly -ErrorAction SilentlyContinue | "
            "Where-Object { ($_.InstanceId -like 'USB\\VID*' -or $_.FriendlyName -match 'Bluetooth.*Adapter|Wireless Bluetooth|Bluetooth Radio') }; "
            "if(-not $items){Write-Output 'NO_ADAPTER'; exit 3}; "
            "$ok=$items | Where-Object {$_.Status -eq 'OK'}; "
            "$items | ForEach-Object { Write-Output ($_.Status + '|' + $_.FriendlyName + '|' + $_.InstanceId) }; "
            "if(-not $ok){exit 4}"
        )
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True,
                text=True,
                timeout=12,
                creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
            )
            detail = (result.stdout or result.stderr or "").strip().replace("\r", " ").replace("\n", "; ")
            ok = result.returncode == 0
            tool_log("BLE_ADAPTER_STATE", ok=ok, rc=result.returncode, detail=detail or "--")
            return ok, detail or f"rc={result.returncode}"
        except Exception as exc:
            tool_log_exception("bluetooth_adapter_state", exc)
            # A failed diagnostic query must not itself disable BLE. The real
            # Bleak preflight below is still authoritative.
            return True, f"PnP-Abfrage nicht verfügbar: {exc}"

    def _soft_repair_bluetooth(self) -> bool:
        """Try a non-elevated Windows Bluetooth service refresh."""
        if os.name != "nt":
            return False
        self.events.put(("status", "Bluetooth-Schnittstelle reagiert nicht sauber · automatische Reparatur …"))
        command = (
            "$ErrorActionPreference='SilentlyContinue'; "
            "Get-Service -Name 'BluetoothUserService_*' | ForEach-Object { Restart-Service -Name $_.Name -Force }; "
            "Restart-Service -Name bthserv -Force; Start-Sleep -Milliseconds 900; "
            "Get-Service -Name bthserv | Select-Object -ExpandProperty Status"
        )
        try:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                capture_output=True,
                text=True,
                timeout=18,
                creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0)),
            )
            detail = (result.stdout or result.stderr or "").strip().replace("\r", " ").replace("\n", "; ")
            tool_log("BLE_AUTO_REPAIR_SOFT", rc=result.returncode, detail=detail or "--")
            return result.returncode == 0
        except Exception as exc:
            tool_log_exception("bluetooth_soft_repair", exc)
            return False

    def _elevated_repair_bluetooth(self) -> bool:
        """Restart the physical USB Bluetooth adapter and services via UAC when Windows is unhealthy."""
        if os.name != "nt":
            return False
        script = (
            "$ErrorActionPreference='SilentlyContinue'; "
            "Restart-Service -Name bthserv -Force; "
            "$a=Get-PnpDevice -Class Bluetooth -PresentOnly | Where-Object { "
            "$_.InstanceId -like 'USB\\VID*' -and $_.FriendlyName -match 'Bluetooth.*Adapter|Wireless Bluetooth|Bluetooth Radio' }; "
            "foreach($d in $a){ Disable-PnpDevice -InstanceId $d.InstanceId -Confirm:$false; "
            "Start-Sleep -Milliseconds 800; Enable-PnpDevice -InstanceId $d.InstanceId -Confirm:$false }; "
            "Start-Sleep -Seconds 2"
        )
        try:
            escaped = script.replace('"', '\\"')
            params = f'-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command "{escaped}"'
            rc = int(ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell.exe", params, None, 0))
            launched = rc > 32
            tool_log("BLE_AUTO_REPAIR_ELEVATED", launched=launched, shell_rc=rc)
            if launched:
                self.events.put(("status", "Bluetooth-Adapter wird von Windows neu gestartet …"))
                time.sleep(7.0)
            return launched
        except Exception as exc:
            tool_log_exception("bluetooth_elevated_repair", exc)
            return False

    @staticmethod
    def _ble_discover_once(timeout_s: float) -> dict[object, tuple[object, object]]:
        async def discover():
            return await asyncio.wait_for(
                BleakScanner.discover(timeout=timeout_s, return_adv=True),
                timeout=timeout_s + 4.0,
            )
        return asyncio.run(discover())
'''
        source = insert_before_method(source, "_ble_scan_worker", helpers)

    def replace_ble_worker(_method: str) -> str:
        return r'''    def _ble_scan_worker(self) -> None:
        started_at = time.monotonic()
        tool_log("BLE_PREFLIGHT_START")
        try:
            adapter_ok, adapter_detail = self._windows_bluetooth_adapter_state()
            if not adapter_ok:
                tool_log("BLE_PREFLIGHT_ADAPTER_UNHEALTHY", detail=adapter_detail)
                self._soft_repair_bluetooth()
                if not self._windows_bluetooth_adapter_state()[0]:
                    self._elevated_repair_bluetooth()

            self.events.put(("status", "Bluetooth wird geprüft und Nodes werden gesucht …"))
            scan_error: Exception | None = None
            try:
                devices = self._ble_discover_once(12.0)
            except Exception as exc:
                scan_error = exc
                devices = {}
                tool_log_exception("ble_preflight_scan", exc)

            # A successful Windows scan with zero *total* BLE advertisements is
            # suspicious. Refresh the user/service layer once, then retry. Zero
            # compatible Jarnsen Nodes is not considered a broken adapter when
            # other BLE advertisements are visible.
            if scan_error is not None or not devices:
                reason = "scan_error" if scan_error is not None else "zero_total_devices"
                tool_log("BLE_AUTO_REPAIR_TRIGGER", reason=reason)
                self._soft_repair_bluetooth()
                time.sleep(1.0)
                try:
                    devices = self._ble_discover_once(6.0)
                    scan_error = None
                except Exception as exc:
                    scan_error = exc
                    devices = {}
                    tool_log_exception("ble_scan_after_soft_repair", exc)

            if scan_error is not None:
                # Only escalate automatically on a real backend error, not just
                # because no nearby devices happen to be advertising.
                if self._elevated_repair_bluetooth():
                    try:
                        devices = self._ble_discover_once(10.0)
                        scan_error = None
                    except Exception as exc:
                        scan_error = exc
                        devices = {}
                        tool_log_exception("ble_scan_after_elevated_repair", exc)

            if scan_error is not None:
                raise RuntimeError(f"Windows-Bluetooth-Backend reagiert nicht: {scan_error}")

            verified: dict[str, object] = {}
            fallback: dict[str, object] = {}
            known_names: set[str] = set()
            with contextlib.suppress(Exception):
                for row in self.repository.list_nodes(True):
                    for value in (row["long_name"], row["short_name"]):
                        if value:
                            known_names.add(str(value).strip().lower())

            for device, advertisement in devices.values():
                advertised_name = str(getattr(advertisement, "local_name", "") or "").strip()
                device_name = str(getattr(device, "name", "") or "").strip()
                name = device_name or advertised_name or "Unbenanntes BLE-Gerät"
                address = str(getattr(device, "address", "--"))
                service_uuids = {
                    str(value).lower()
                    for value in (getattr(advertisement, "service_uuids", None) or [])
                }
                tool_log(
                    "BLE_DEVICE",
                    name=name,
                    address=address,
                    advertised_name=advertised_name or "--",
                    services=",".join(sorted(service_uuids)) or "--",
                    rssi=getattr(advertisement, "rssi", "--"),
                )
                if OTABT_SERVICE_UUID in service_uuids:
                    verified[f"[OTA] {name} - {address}"] = device
                elif MESH_SERVICE_UUID in service_uuids:
                    verified[f"{name} - {address}"] = device
                elif name != "Unbenanntes BLE-Gerät":
                    lowered = name.lower()
                    likely = (
                        any(candidate and candidate in lowered for candidate in known_names)
                        or any(token in lowered for token in ("meshtastic", "heltec", "tracker", "jarnsen", "v3"))
                    )
                    prefix = "[?] " if likely else "[BLE] "
                    fallback[f"{prefix}{name} - {address}"] = device

            found = verified if verified else fallback
            tool_log(
                "BLE_PREFLIGHT_OK",
                duration_s=f"{time.monotonic() - started_at:.2f}",
                total=len(devices),
                verified=len(verified),
                fallback=len(fallback),
                shown=len(found),
                adapter=adapter_detail,
            )
            self.events.put(("ble_devices", (found, len(devices))))
            if not devices:
                self.events.put((
                    "status_warning",
                    "Bluetooth-Schnittstelle antwortet, aber es wurden keine BLE-Geräte empfangen · V3-Servicefenster öffnen und erneut suchen",
                ))
            elif not verified and fallback:
                self.events.put((
                    "status_warning",
                    "Bluetooth ist funktionsfähig · keine Jarnsen-Service-UUID sichtbar; Prüfkandidaten werden angezeigt",
                ))
        except Exception as exc:
            tool_log_exception("ble_scan", exc)
            self.events.put((
                "error",
                "Bluetooth-Schnittstelle konnte auch nach automatischer Reparatur nicht verwendet werden: " + str(exc),
            ))
        finally:
            self.events.put(("ble_scan_done", None))
'''

    source = replace_method(source, "_ble_scan_worker", replace_ble_worker)

    required = (
        'APP_VERSION = "2.1.4"',
        'text="← Erweitert schließen"',
        'text="Erweitert öffnen"',
        'text="Erweitert schließen"',
        'def _windows_bluetooth_adapter_state(self)',
        'def _soft_repair_bluetooth(self)',
        'def _elevated_repair_bluetooth(self)',
        'def _ble_discover_once(',
        'BLE_PREFLIGHT_START',
        'BLE_AUTO_REPAIR_TRIGGER',
        'BLE_AUTO_REPAIR_SOFT',
        'BLE_AUTO_REPAIR_ELEVATED',
        'BLE_PREFLIGHT_OK',
    )
    for marker in required:
        if marker not in source:
            raise SystemExit(f"missing v2.1.4 marker: {marker}")
    return source


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "tools/JARNSEN_NODE_SERVICE_TOOL.py")
    target.write_text(patch(target.read_text(encoding="utf-8")), encoding="utf-8")
    print("Service tool v2.1.4: Bluetooth preflight/self-repair + reliable advanced close")


if __name__ == "__main__":
    main()
