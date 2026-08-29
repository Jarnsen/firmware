"""v2.1.33: admin-style node dashboard and reliable automatic BLE log queue."""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "2.1.33"


def method_span(text: str, name: str) -> tuple[int, int]:
    normal = text.find(f"    def {name}(")
    asynchronous = text.find(f"    async def {name}(")
    starts = [value for value in (normal, asynchronous) if value >= 0]
    if not starts:
        raise SystemExit(f"v2.1.33 method {name} not found")
    start = min(starts)
    candidates = [
        value
        for value in (
            text.find("\n    def ", start + 1),
            text.find("\n    async def ", start + 1),
            text.find("\n    @", start + 1),
        )
        if value >= 0
    ]
    return start, min(candidates) if candidates else len(text)


def replace_method(text: str, name: str, replacement: str) -> str:
    start, end = method_span(text, name)
    return text[:start] + replacement.rstrip() + "\n" + text[end:]


def patch(source: str) -> str:
    if "PATCH_V2133_ADMIN_BLE_RELIABILITY" in source:
        return source

    source = re.sub(r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{APP_VERSION}"', source, count=1)
    source = source.replace('APP_VERSION != "2.1.32"', 'APP_VERSION != "2.1.33"')
    source = source.replace("App-Version ist nicht v2.1.32", "App-Version ist nicht v2.1.33")
    source = source.replace("AUTO_BLE_SCAN_SECONDS = 5 * 60", "AUTO_BLE_SCAN_SECONDS = 30")
    constant_anchor = "AUTO_BLE_SCAN_SECONDS = 30\n"
    if "DEFAULT_BT_PIN_V2133" not in source:
        if source.count(constant_anchor) != 1:
            raise SystemExit("v2.1.33 BLE constant anchor not found")
        source = source.replace(
            constant_anchor,
            constant_anchor + 'AUTO_BLE_BUSY_RETRY_SECONDS_V2133 = 3\nDEFAULT_BT_PIN_V2133 = "240180"\n',
            1,
        )

    render_start, _render_end = method_span(source, "render_dashboard")
    helpers = r'''    # PATCH_V2133_ADMIN_BLE_RELIABILITY
    def _trace_v2133(self, text: object) -> None:
        stamp = now_local().strftime("%H:%M:%S")
        self.events.put(("auto_ble_trace_v2133", f"{stamp}  {text}"))

    def _auto_ble_retry_fire_v2133(self) -> None:
        self._auto_ble_retry_after_v2133 = None
        self.auto_ble_refresh_v2132(False)

    @staticmethod
    def _ble_address_int_v2133(device: object) -> int:
        compact = re.sub(r"[^0-9A-Fa-f]", "", str(getattr(device, "address", "") or ""))
        if len(compact) != 12:
            raise RuntimeError("Bluetooth-Adresse kann für Windows-Kopplung nicht ausgewertet werden")
        return int(compact, 16)

    async def _windows_pair_fixed_pin_v2133(self, device: object, label: str = "") -> str:
        if sys.platform != "win32":
            return "nicht-Windows"
        from winrt.windows.devices.bluetooth import BluetoothLEDevice
        from winrt.windows.devices.enumeration import (
            DeviceInformation,
            DevicePairingKinds,
            DevicePairingProtectionLevel,
            DevicePairingResultStatus,
        )

        requester = await BluetoothLEDevice.from_bluetooth_address_async(
            self._ble_address_int_v2133(device)
        )
        if requester is None:
            raise RuntimeError("Windows konnte das BLE-Gerät nicht öffnen")
        try:
            info = await DeviceInformation.create_from_id_async(requester.device_information.id)
            if info.pairing.is_paired:
                return "bereits gekoppelt"
            if not info.pairing.can_pair:
                raise RuntimeError("Windows meldet das Gerät als nicht koppelbar")
            custom = info.pairing.custom
            ceremonies = (
                DevicePairingKinds.CONFIRM_ONLY
                | DevicePairingKinds.PROVIDE_PIN
                | DevicePairingKinds.DISPLAY_PIN
                | DevicePairingKinds.CONFIRM_PIN_MATCH
            )

            def requested(_sender: object, args: object) -> None:
                kind = args.pairing_kind
                if kind == DevicePairingKinds.PROVIDE_PIN:
                    args.accept(DEFAULT_BT_PIN_V2133)
                else:
                    args.accept()

            token = custom.add_pairing_requested(requested)
            try:
                result = await custom.pair_with_protection_level_async(
                    ceremonies, DevicePairingProtectionLevel.ENCRYPTION_AND_AUTHENTICATION
                )
                if result.status == DevicePairingResultStatus.PROTECTION_LEVEL_COULD_NOT_BE_MET:
                    result = await custom.pair_with_protection_level_async(
                        ceremonies, DevicePairingProtectionLevel.ENCRYPTION
                    )
            finally:
                custom.remove_pairing_requested(token)
            if result.status not in (
                DevicePairingResultStatus.PAIRED,
                DevicePairingResultStatus.ALREADY_PAIRED,
            ):
                raise RuntimeError(f"Windows-Kopplung fehlgeschlagen: {result.status.name}")
            return "mit PIN 240180 gekoppelt"
        finally:
            requester.close()

    async def _ensure_ble_pairing_v2133(self, device: object, label: str = "") -> None:
        if sys.platform != "win32":
            return
        state = await self._windows_pair_fixed_pin_v2133(device, label)
        self._trace_v2133(f"{label}: {state}")

    def _node_is_due_v2133(self, node_id: str) -> bool:
        latest = self.repository.latest_log(node_id)
        if not latest:
            return True
        stamp = str(latest.get("captured_at") or "").strip()
        if not stamp:
            return True
        try:
            captured = dt.datetime.fromisoformat(stamp)
            if captured.tzinfo is None:
                captured = captured.replace(tzinfo=now_local().tzinfo)
            return (now_local() - captured.astimezone()).total_seconds() >= AUTO_BLE_SYNC_SECONDS
        except Exception:
            return True

    def _selected_node_ids_v2133(self) -> list[str]:
        states = getattr(self, "node_selection_v2133", {})
        return [node_id for node_id, variable in states.items() if bool(variable.get())]

    def _update_batch_bar_v2133(self) -> None:
        selected = self._selected_node_ids_v2133()
        if hasattr(self, "batch_selected_label_v2133"):
            self.batch_selected_label_v2133.configure(text=f"{len(selected)} ausgewählt")

    def _select_visible_nodes_v2133(self) -> None:
        states = getattr(self, "node_selection_v2133", {})
        for node_id in getattr(self, "visible_node_ids_v2133", []):
            variable = states.get(node_id)
            if variable is not None:
                variable.set(True)
        self._update_batch_bar_v2133()

    def _clear_node_selection_v2133(self) -> None:
        for variable in getattr(self, "node_selection_v2133", {}).values():
            variable.set(False)
        self._update_batch_bar_v2133()

    def _clear_other_selection_v2133(self, keep_node_id: str) -> None:
        for node_id, variable in getattr(self, "node_selection_v2133", {}).items():
            variable.set(node_id == keep_node_id)
        self._update_batch_bar_v2133()

    def _ble_entries_for_nodes_v2133(self, node_ids: list[str]) -> tuple[list[tuple[str, object]], list[str]]:
        wanted = {normalize_node_id(value) for value in node_ids if normalize_node_id(value)}
        found: list[tuple[str, object]] = []
        matched: set[str] = set()
        for label, device in getattr(self, "ble_map", {}).items():
            node_id = self._ble_node_id_v2132(device)
            if node_id in wanted:
                found.append((label, device))
                matched.add(node_id)
        return found, sorted(wanted - matched)

    def _select_ble_entries_v2133(self, entries: list[tuple[str, object]]) -> None:
        if not hasattr(self, "ble_device"):
            return
        labels = list(getattr(self, "ble_map", {}))
        wanted = {label for label, _device in entries}
        self.ble_device.selection_clear(0, "end")
        for index, label in enumerate(labels):
            if label in wanted:
                self.ble_device.selection_set(index)

    def batch_log_download_v2133(self, node_ids: list[str] | None = None) -> None:
        ids = list(node_ids or self._selected_node_ids_v2133())
        if not ids:
            messagebox.showinfo("Mehrfachbearbeitung", "Bitte mindestens eine Node auswählen.")
            return
        entries, missing = self._ble_entries_for_nodes_v2133(ids)
        if missing:
            self._trace_v2133(
                f"Für {len(missing)} ausgewählte Node(s) fehlt aktuell eine sichtbare BLE-Zuordnung"
            )
        if not entries:
            messagebox.showinfo(
                "BLE-Logs",
                "Keine der ausgewählten Nodes ist aktuell über BLE zugeordnet/sichtbar. "
                "Die automatische BLE-Prüfung wurde gestartet.",
            )
            self.auto_ble_refresh_v2132(False)
            return
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("BLE-Logs", "Ein anderer Vorgang läuft noch.")
            return
        self.stop_event.clear()
        self.set_transfer_progress(None, "BLE-Logwarteschlange", True)
        self.worker = threading.Thread(target=self._ble_download_worker, args=(entries,), daemon=True)
        self.worker.start()

    def batch_ota_v2133(self) -> None:
        ids = self._selected_node_ids_v2133()
        if not ids:
            messagebox.showinfo("Mehrfachbearbeitung", "Bitte mindestens eine Node auswählen.")
            return
        entries, missing = self._ble_entries_for_nodes_v2133(ids)
        if missing:
            messagebox.showwarning(
                "Firmware über BLE",
                f"{len(missing)} ausgewählte Node(s) sind aktuell nicht über BLE sichtbar/zugeordnet.",
            )
        if not entries:
            return
        self._select_ble_entries_v2133(entries)
        self.start_ble_update()

    async def _wake_entries_async_v2133(self, entries: list[tuple[str, object]]) -> tuple[int, list[str]]:
        completed = 0
        failures: list[str] = []
        for label, device in entries:
            try:
                await self._ensure_ble_pairing_v2133(device, label)
                async with BleakClient(
                    device, timeout=45.0, pair=False, winrt={"use_cached_services": False}
                ) as client:
                    await client.write_gatt_char(JARNSEN_LIVE_CONTROL_UUID, b"WAKE", response=True)
                completed += 1
                self._trace_v2133(f"{label}: Wake gesendet")
            except Exception as exc:
                failures.append(f"{label}: {exc}")
                self._trace_v2133(f"{label}: Wake fehlgeschlagen · {exc}")
        return completed, failures

    def batch_wake_v2133(self) -> None:
        ids = self._selected_node_ids_v2133()
        entries, missing = self._ble_entries_for_nodes_v2133(ids)
        if not ids:
            messagebox.showinfo("Mehrfachbearbeitung", "Bitte mindestens eine Node auswählen.")
            return
        if not entries:
            messagebox.showinfo("Wakeup", "Keine ausgewählte Node ist aktuell über BLE sichtbar.")
            return
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("Wakeup", "Ein anderer Vorgang läuft noch.")
            return

        def worker() -> None:
            try:
                completed, failures = asyncio.run(self._wake_entries_async_v2133(entries))
                detail = f"Wakeup: {completed}/{len(entries)} erfolgreich"
                if missing:
                    detail += f" · {len(missing)} nicht sichtbar"
                if failures:
                    detail += "\n" + "\n".join(failures)
                    self.events.put(("status_warning", detail))
                else:
                    self.events.put(("status_success", detail))
            finally:
                self.events.put(("done", None))

        self.stop_event.clear()
        self.worker = threading.Thread(target=worker, daemon=True)
        self.worker.start()

    def batch_live_v2133(self) -> None:
        ids = self._selected_node_ids_v2133()
        if len(ids) != 1:
            messagebox.showinfo("Live", "Für Live bitte genau eine Node auswählen.")
            return
        entries, missing = self._ble_entries_for_nodes_v2133(ids)
        if missing or len(entries) != 1:
            messagebox.showinfo("Live", "Diese Node ist aktuell nicht über BLE sichtbar/zugeordnet.")
            return
        self._select_ble_entries_v2133(entries)
        self.notebook.select(self.live_tab)
        self.toggle_live()

    def batch_service_v2133(self) -> None:
        ids = self._selected_node_ids_v2133()
        if len(ids) != 1:
            messagebox.showinfo(
                "Grunddaten / Service",
                "Für Grunddaten und Profile bitte genau eine Ziel-Node auswählen. "
                "Mehrfach-Log, OTA, Wakeup und Löschen können direkt gesammelt ausgeführt werden.",
            )
            return
        self.open_node_from_tile_v2132(ids[0], "service")

    def batch_delete_v2133(self) -> None:
        ids = self._selected_node_ids_v2133()
        if not ids:
            messagebox.showinfo("Mehrfachbearbeitung", "Bitte mindestens eine Node auswählen.")
            return
        if self._delete_node_ids_v2131(ids):
            self._clear_node_selection_v2133()
            self.refresh_all_nodes_overview()

    def _filter_sort_rows_v2133(self, rows: list[object]) -> list[object]:
        query = self.node_search_var_v2133.get().strip().lower() if hasattr(self, "node_search_var_v2133") else ""
        filter_name = self.node_filter_var_v2133.get() if hasattr(self, "node_filter_var_v2133") else "Alle"
        prepared: list[tuple[object, dict[str, object], bool, bool, bool, str]] = []
        for row in rows:
            node_id = normalize_node_id(str(row["node_id"] or ""))
            latest = self.repository.latest_log(node_id)
            metrics = latest.get("metrics", {}) if latest else {}
            if not isinstance(metrics, dict):
                metrics = {}
            name = str(metrics.get("long_name") or row["long_name"] or node_id)
            short = str(metrics.get("short_name") or row["short_name"] or "")
            device_key = str(row["device"] or metrics.get("device") or "")
            ble = self.repository.ble_status_for_node_v2132(node_id)
            due = self._node_is_due_v2133(node_id)
            warnings = int(metrics.get("warning_count") or 0) > 0
            battery = metrics.get("battery_pct")
            low = isinstance(battery, (int, float)) and float(battery) <= 20
            build = str(latest.get("build") or "") if latest else ""
            github_state, _detail, github_level = self.firmware_state(device_key, build)
            update = github_level == "warning" or "Update" in github_state
            haystack = f"{name} {short} {node_id} {device_key}".lower()
            if query and query not in haystack:
                continue
            if filter_name == "Tracker" and device_key != "HELTEC_TRACKER_V1.1":
                continue
            if filter_name == "V3" and device_key != "HELTEC_V3_REPEATER":
                continue
            if filter_name == "BLE sichtbar" and not ble:
                continue
            if filter_name == "Log fällig" and not due:
                continue
            if filter_name == "Updates" and not update:
                continue
            if filter_name == "Hinweise" and not (warnings or low):
                continue
            if filter_name == "Archiv" and not int(row["archived"] or 0):
                continue
            if filter_name != "Archiv" and int(row["archived"] or 0) and not self.show_archived_var.get():
                continue
            prepared.append((row, metrics, due, warnings or low, update, name))
        sort_name = self.node_sort_var_v2133.get() if hasattr(self, "node_sort_var_v2133") else "Status"
        if sort_name == "Name":
            prepared.sort(key=lambda item: item[5].lower())
        elif sort_name == "Akku":
            prepared.sort(key=lambda item: float(item[1].get("battery_pct") or -1), reverse=True)
        elif sort_name == "Letzter Log":
            prepared.sort(key=lambda item: str((self.repository.latest_log(normalize_node_id(str(item[0]["node_id"] or ""))) or {}).get("captured_at") or ""), reverse=True)
        else:
            prepared.sort(key=lambda item: (not item[3], not item[4], not item[2], item[5].lower()))
        return [item[0] for item in prepared]

'''
    source = source[:render_start] + helpers.rstrip() + "\n\n" + source[render_start:]

    auto_refresh = r'''    def auto_ble_refresh_v2132(self, force: bool = False) -> None:
        if not BLE_AVAILABLE:
            return
        enabled = getattr(self, "auto_ble_enabled_v2132", None)
        if enabled is not None and not bool(enabled.get()) and not force:
            return
        if self.worker and self.worker.is_alive():
            if hasattr(self, "auto_ble_status_v2132"):
                self.auto_ble_status_v2132.configure(text="BLE-Automatik wartet · Vorgang läuft")
            if not force and not getattr(self, "_auto_ble_retry_after_v2133", None):
                self._auto_ble_retry_after_v2133 = self.after(
                    int(AUTO_BLE_BUSY_RETRY_SECONDS_V2133 * 1000), self._auto_ble_retry_fire_v2133
                )
            return
        self.stop_event.clear()
        self._trace_v2133("Automatische BLE-Prüfung gestartet")
        if hasattr(self, "auto_ble_status_v2132"):
            self.auto_ble_status_v2132.configure(text="BLE-Automatik: suche Nodes …")
        self.worker = threading.Thread(
            target=self._auto_ble_scan_worker_v2132, args=(force,), daemon=True
        )
        self.worker.start()
'''
    source = replace_method(source, "auto_ble_refresh_v2132", auto_refresh)

    auto_timer = r'''    def _auto_ble_timer_v2132(self) -> None:
        self.auto_ble_refresh_v2132(False)
        self._auto_ble_after_v2132 = self.after(
            int(AUTO_BLE_SCAN_SECONDS * 1000), self._auto_ble_timer_v2132
        )
'''
    source = replace_method(source, "_auto_ble_timer_v2132", auto_timer)

    auto_worker = r'''    def _auto_ble_scan_worker_v2132(self, force: bool = False) -> None:
        delegated = False
        try:
            devices = asyncio.run(BleakScanner.discover(timeout=8.0, return_adv=True))
            found: dict[str, object] = {}
            due: list[tuple[str, object]] = []
            skipped = 0
            compatible = 0
            for device, advertisement in devices.values():
                name = str(device.name or "Unbenannter JARN-MESH Node")
                service_uuids = {str(value).lower() for value in (advertisement.service_uuids or [])}
                if MESH_SERVICE_UUID.lower() in service_uuids:
                    compatible += 1
                    label = f"{name} - {device.address}"
                    found[label] = device
                    key = self._ble_identity_key_v2132(device)
                    mapping = self.repository.ble_mapping_v2132(key) if key else None
                    self.repository.mark_ble_seen_v2132(key, label)
                    known_id = normalize_node_id(str(mapping.get("node_id") or "")) if mapping else ""
                    is_due = self._auto_ble_due_v2132(device, force)
                    if is_due:
                        due.append((label, device))
                        reason = "Erstdownload" if not known_id else ("erzwungen" if force else "Log fällig")
                        self._set_ble_device_state_v2132(device, f"Warteschlange · {reason}")
                        self._trace_v2133(f"{label}: {reason} → Queue")
                    else:
                        skipped += 1
                        self._set_ble_device_state_v2132(device, "Aktuell · kein Download nötig")
                        self._trace_v2133(f"{label}: Log jünger als 15 min → übersprungen")
                elif OTABT_SERVICE_UUID.lower() in service_uuids:
                    found[f"[OTA] {name} - {device.address}"] = device
            self.events.put(("ble_devices", (found, len(devices))))
            self.events.put(("auto_ble_status_v2132", (compatible, len(due), skipped)))
            if due and not self.stop_event.is_set():
                self.events.put(("status", f"BLE-Automatik: {len(due)} Node(s) fällig · Download startet"))
                self._trace_v2133(f"Download-Warteschlange startet mit {len(due)} Node(s)")
                delegated = True
                self._ble_download_worker(due)
                return
            self.events.put(("status_success", f"BLE-Automatik: {compatible} kompatible Node(s) geprüft · {skipped} aktuell"))
            self._trace_v2133(f"Prüfung fertig · {compatible} kompatibel · kein Download fällig")
        except Exception as exc:
            self._trace_v2133(f"BLE-Prüfung fehlgeschlagen · {type(exc).__name__}: {exc}")
            self.events.put(("status_warning", f"BLE-Automatik derzeit nicht verfügbar: {exc}"))
        finally:
            if not delegated:
                self.events.put(("done", None))
'''
    source = replace_method(source, "_auto_ble_scan_worker_v2132", auto_worker)

    ble_worker = r'''    def _ble_download_worker(self, ble_devices: list[tuple[str, object]]) -> None:
        failures: list[str] = []
        completed = 0
        held: list[tuple[int, str, object]] = []
        requested_total = len(ble_devices)
        ready: list[tuple[str, object]] = []
        try:
            for label, ble_device in ble_devices:
                if self.stop_event.is_set():
                    break
                self._set_ble_device_state_v2132(ble_device, "Bluetooth wird authentifiziert …")
                self._trace_v2133(f"{label}: Kopplung/Authentifizierung prüfen")
                try:
                    asyncio.run(self._ensure_ble_pairing_v2133(ble_device, label))
                    ready.append((label, ble_device))
                except Exception as exc:
                    key = self._ble_identity_key_v2132(ble_device)
                    self.repository.mark_ble_seen_v2132(key, label, str(exc))
                    self._set_ble_device_state_v2132(ble_device, f"BLE-Fehler · {exc}")
                    failures.append(f"{label}: Kopplung fehlgeschlagen: {exc}")
                    self._trace_v2133(f"{label}: Kopplung fehlgeschlagen · {exc}")

            total = len(ready)
            if not total:
                return

            if total > 1:
                for index, (label, ble_device) in enumerate(ready, start=1):
                    if self.stop_event.is_set():
                        break
                    self.events.put(("status", f"Reserviere Node {index}/{total}: {label}"))
                    try:
                        asyncio.run(self._set_ble_queue_hold_async(ble_device, True))
                        held.append((index, label, ble_device))
                    except Exception as exc:
                        failures.append(f"{label}: Warteschlangen-Reservierung fehlgeschlagen: {exc}")
                        self._set_ble_device_state_v2132(ble_device, f"BLE-Fehler · {exc}")
                        self._trace_v2133(f"{label}: HOLD fehlgeschlagen · {exc}")
                queue_entries = list(held)
            else:
                queue_entries = [(1, ready[0][0], ready[0][1])]

            for entry in queue_entries:
                index, label, ble_device = entry
                queue_hold_active = entry in held
                if self.stop_event.is_set():
                    break
                try:
                    self._set_ble_device_state_v2132(ble_device, "Log wird geladen …")
                    self._trace_v2133(f"{label}: Logdownload gestartet")
                    asyncio.run(
                        self._ble_download_async(
                            ble_device, index, total, label,
                            release_queue_hold=queue_hold_active,
                        )
                    )
                    completed += 1
                    self._trace_v2133(f"{label}: Logdownload erfolgreich")
                    if queue_hold_active and entry in held:
                        held.remove(entry)
                except Exception as exc:
                    key = self._ble_identity_key_v2132(ble_device)
                    self.repository.mark_ble_seen_v2132(key, label, str(exc))
                    failures.append(f"{label}: {exc}")
                    self._set_ble_device_state_v2132(ble_device, f"BLE-Fehler · {exc}")
                    self._trace_v2133(f"{label}: Logdownload fehlgeschlagen · {exc}")
                    if queue_hold_active:
                        try:
                            asyncio.run(self._set_ble_queue_hold_async(ble_device, False))
                            if entry in held:
                                held.remove(entry)
                        except Exception:
                            pass
        except Exception as exc:
            failures.append(f"Warteschlange: {exc}")
            self._trace_v2133(f"Warteschlange fehlgeschlagen · {exc}")
        finally:
            for _index, label, ble_device in list(held):
                try:
                    asyncio.run(self._set_ble_queue_hold_async(ble_device, False))
                except Exception as exc:
                    failures.append(f"{label}: Bluetooth-Freigabe nicht bestätigt ({exc})")
            if self.stop_event.is_set():
                self.events.put(("status_warning", f"Download abgebrochen · {completed}/{requested_total} abgeschlossen"))
            elif failures:
                self.events.put(("queue_result", (completed, requested_total, failures)))
            else:
                self.events.put(("status_success", f"DONE · {completed}/{requested_total} Node-Logs gespeichert"))
            self.events.put(("done", None))
'''
    source = replace_method(source, "_ble_download_worker", ble_worker)

    render_tiles = r'''    def render_node_tiles_v2132(self) -> None:
        host = getattr(self, "node_tiles_host_v2132", None)
        if host is None:
            return
        for child in host.winfo_children():
            child.destroy()
        try:
            rows = self.repository.list_nodes(self.show_archived_var.get())
        except Exception:
            rows = []
        rows = self._filter_sort_rows_v2133(rows)
        self.visible_node_ids_v2133 = [normalize_node_id(str(row["node_id"] or "")) for row in rows]
        width = max(640, int(getattr(self, "node_tiles_canvas_v2132").winfo_width() or 640))
        columns = 4 if width >= 1500 else (3 if width >= 1080 else (2 if width >= 720 else 1))
        palette = THEMES.get(self.theme.get(), THEMES["Modern"])
        states = getattr(self, "node_sync_state_v2132", {})
        selections = getattr(self, "node_selection_v2133", {})
        if not isinstance(states, dict):
            states = {}
        if not isinstance(selections, dict):
            selections = {}
            self.node_selection_v2133 = selections
        for column in range(columns):
            host.columnconfigure(column, weight=1, uniform="node-tile-v2133")

        ble_visible = due_count = issue_count = update_count = 0
        for index, row in enumerate(rows):
            node_id = normalize_node_id(str(row["node_id"] or ""))
            latest = self.repository.latest_log(node_id)
            metrics = latest.get("metrics", {}) if latest else {}
            if not isinstance(metrics, dict):
                metrics = {}
            device_key = str(row["device"] or metrics.get("device") or "")
            device = "Tracker V1.1" if device_key == "HELTEC_TRACKER_V1.1" else ("Heltec V3" if device_key == "HELTEC_V3_REPEATER" else DEVICE_NAMES.get(device_key, device_key or "--"))
            name = str(metrics.get("long_name") or row["long_name"] or node_id)
            short_name = str(metrics.get("short_name") or row["short_name"] or "")
            battery_value = metrics.get("battery_pct")
            battery = f"{float(battery_value):.0f} %" if isinstance(battery_value, (int, float)) else "--"
            firmware = str(latest.get("firmware") or "--") if latest else "--"
            build = str(latest.get("build") or "") if latest else ""
            firmware_text = f"{firmware} · {build[:8]}" if build else firmware
            github_state, _github_detail, github_level = self.firmware_state(device_key, build)
            warning_count = int(metrics.get("warning_count") or 0)
            low_battery = isinstance(battery_value, (int, float)) and float(battery_value) <= 20
            ble_state = self.repository.ble_status_for_node_v2132(node_id)
            due = self._node_is_due_v2133(node_id)
            update = github_level == "warning" or "Update" in github_state
            if ble_state: ble_visible += 1
            if due: due_count += 1
            if warning_count or low_battery: issue_count += 1
            if update: update_count += 1

            if node_id not in selections:
                selections[node_id] = tk.BooleanVar(value=False)
            border = palette["error"] if warning_count or low_battery else (palette["warning"] if update or due else palette["panel_alt"])
            card = tk.Frame(host, bg=palette["panel"], highlightbackground=border, highlightthickness=1, bd=0)
            card.grid(row=index // columns, column=index % columns, sticky="nsew", padx=7, pady=7)
            tk.Frame(card, bg=border, height=5).pack(fill="x")

            header = tk.Frame(card, bg=palette["panel"])
            header.pack(fill="x", padx=11, pady=(9, 3))
            ttk.Checkbutton(header, variable=selections[node_id], command=self._update_batch_bar_v2133).pack(side="left", padx=(0, 5))
            title = tk.Frame(header, bg=palette["panel"])
            title.pack(side="left", fill="x", expand=True)
            tk.Label(title, text=name, bg=palette["panel"], fg=palette["fg"], font=(palette["font"], 12, "bold"), anchor="w").pack(fill="x")
            tk.Label(title, text=f"{short_name or '--'} · {node_id}", bg=palette["panel"], fg=palette["muted"], font=(palette["font"], 8), anchor="w").pack(fill="x")
            ttk.Button(header, text="✎", width=3, command=lambda value=node_id: self.open_node_actions_v2132(value)).pack(side="right")

            chips = tk.Frame(card, bg=palette["panel"])
            chips.pack(fill="x", padx=11, pady=(2, 7))
            def chip(text: str, background: str) -> None:
                tk.Label(chips, text=text, bg=background, fg="#ffffff" if background != palette["warning"] else "#222222", font=(palette["font"], 8, "bold"), padx=7, pady=2).pack(side="left", padx=(0, 4))
            chip(device.replace("Heltec ", ""), palette["accent"])
            chip("BLE" if ble_state else "offline", palette["success"] if ble_state else palette["muted"])
            if due: chip("Log fällig", palette["warning"])
            else: chip("Log aktuell", palette["success"])
            if update: chip("Update", palette["warning"])
            if warning_count or low_battery: chip("Hinweis", palette["error"])

            metrics_row = tk.Frame(card, bg=palette["panel"])
            metrics_row.pack(fill="x", padx=9, pady=(0, 7))
            facts = (
                ("AKKU", battery),
                ("FIRMWARE", firmware_text),
                ("LETZTER LOG", self._format_v2132_time(latest.get("captured_at") if latest else "")),
            )
            for col, (caption, value) in enumerate(facts):
                box = tk.Frame(metrics_row, bg=palette["panel_alt"], bd=0)
                box.grid(row=0, column=col, sticky="nsew", padx=2)
                metrics_row.columnconfigure(col, weight=1, uniform="facts-v2133")
                tk.Label(box, text=caption, bg=palette["panel_alt"], fg=palette["muted"], font=(palette["font"], 7, "bold")).pack(anchor="w", padx=7, pady=(5, 0))
                tk.Label(box, text=value, bg=palette["panel_alt"], fg=palette["fg"], font=(palette["font"], 9, "bold"), anchor="w", wraplength=max(100, int(width / columns / 3) - 20)).pack(fill="x", padx=7, pady=(1, 5))

            sync_text = str(states.get(node_id) or "")
            if not sync_text:
                sync_text = f"BLE zuletzt {self._format_v2132_time(ble_state.get('last_seen'))}" if ble_state else "Keine aktuelle BLE-Zuordnung"
            tk.Label(card, text=sync_text, bg=palette["panel"], fg=palette["muted"], font=(palette["font"], 8), anchor="w", wraplength=max(260, int(width / columns) - 40)).pack(fill="x", padx=11, pady=(0, 7))

            actions = ttk.Frame(card)
            actions.pack(fill="x", padx=9, pady=(0, 9))
            ttk.Button(actions, text="Öffnen", command=lambda value=node_id: self.open_node_from_tile_v2132(value), style="Primary.TButton").pack(side="left", fill="x", expand=True)
            ttk.Button(actions, text="Log", command=lambda value=node_id: self.batch_log_download_v2133([value])).pack(side="left", padx=(5, 0))
            ttk.Button(actions, text="Live", command=lambda value=node_id: (self._clear_other_selection_v2133(value), self.batch_live_v2133())).pack(side="left", padx=(5, 0))

        if hasattr(self, "dashboard_visible_var_v2133"):
            self.dashboard_visible_var_v2133.set(str(len(rows)))
            self.dashboard_ble_var_v2133.set(str(ble_visible))
            self.dashboard_due_var_v2133.set(str(due_count))
            self.dashboard_issue_var_v2133.set(str(issue_count + update_count))
        if not rows:
            ttk.Label(host, text="Keine Nodes für diesen Filter. Suche/Filter zurücksetzen oder BLE prüfen.", style="Section.TLabel").grid(row=0, column=0, sticky="w", padx=12, pady=18)
        canvas = getattr(self, "node_tiles_canvas_v2132", None)
        if canvas is not None:
            self.after_idle(lambda: canvas.configure(scrollregion=canvas.bbox("all")))
        self._update_batch_bar_v2133()
'''
    source = replace_method(source, "render_node_tiles_v2132", render_tiles)

    workflow_start, workflow_end = method_span(source, "_install_workflow_ui")
    workflow = source[workflow_start:workflow_end]
    body_anchor = '        self.node_tiles_body_v2132.pack(fill="both", expand=True)\n'
    if "dashboard_toolbar_v2133" not in workflow:
        if body_anchor not in workflow:
            raise SystemExit("v2.1.33 node tile body anchor not found")
        admin_ui = body_anchor + r'''        self.node_selection_v2133 = {}
        self.visible_node_ids_v2133 = []
        self._auto_ble_retry_after_v2133 = None
        self.dashboard_toolbar_v2133 = ttk.LabelFrame(
            self.node_tiles_body_v2132, text="Nodeverwaltung", padding=(10, 7)
        )
        self.dashboard_toolbar_v2133.pack(fill="x", pady=(0, 7))
        toolbar_top = ttk.Frame(self.dashboard_toolbar_v2133)
        toolbar_top.pack(fill="x")
        ttk.Label(toolbar_top, text="Nodeübersicht", style="Section.TLabel").pack(side="left")
        ttk.Label(toolbar_top, text="Automatische Erkennung · BLE-Logs · Firmware · Service", style="Subtitle.TLabel").pack(side="left", padx=(10, 0))
        ttk.Button(toolbar_top, text="↻ Aktualisieren", command=self.refresh_all_nodes_overview).pack(side="right")
        ttk.Button(toolbar_top, text="◉ BLE jetzt prüfen", command=lambda: self.auto_ble_refresh_v2132(False), style="Primary.TButton").pack(side="right", padx=(0, 6))

        filters = ttk.Frame(self.dashboard_toolbar_v2133)
        filters.pack(fill="x", pady=(8, 0))
        ttk.Label(filters, text="Suche").pack(side="left")
        self.node_search_var_v2133 = tk.StringVar(value="")
        search_entry = ttk.Entry(filters, textvariable=self.node_search_var_v2133, width=28)
        search_entry.pack(side="left", padx=(5, 12))
        ttk.Label(filters, text="Status").pack(side="left")
        self.node_filter_var_v2133 = tk.StringVar(value="Alle")
        filter_box = ttk.Combobox(filters, state="readonly", textvariable=self.node_filter_var_v2133, width=15, values=("Alle", "BLE sichtbar", "Log fällig", "Updates", "Hinweise", "Tracker", "V3", "Archiv"))
        filter_box.pack(side="left", padx=(5, 12))
        ttk.Label(filters, text="Sortierung").pack(side="left")
        self.node_sort_var_v2133 = tk.StringVar(value="Status")
        sort_box = ttk.Combobox(filters, state="readonly", textvariable=self.node_sort_var_v2133, width=14, values=("Status", "Name", "Akku", "Letzter Log"))
        sort_box.pack(side="left", padx=(5, 0))
        self.node_search_var_v2133.trace_add("write", lambda *_args: self.render_node_tiles_v2132())
        filter_box.bind("<<ComboboxSelected>>", lambda _event: self.render_node_tiles_v2132())
        sort_box.bind("<<ComboboxSelected>>", lambda _event: self.render_node_tiles_v2132())

        stats = ttk.Frame(self.dashboard_toolbar_v2133)
        stats.pack(fill="x", pady=(8, 0))
        self.dashboard_visible_var_v2133 = tk.StringVar(value="0")
        self.dashboard_ble_var_v2133 = tk.StringVar(value="0")
        self.dashboard_due_var_v2133 = tk.StringVar(value="0")
        self.dashboard_issue_var_v2133 = tk.StringVar(value="0")
        for stat_index, (title, variable) in enumerate((("Sichtbar", self.dashboard_visible_var_v2133), ("BLE erkannt", self.dashboard_ble_var_v2133), ("Log fällig", self.dashboard_due_var_v2133), ("Updates / Hinweise", self.dashboard_issue_var_v2133))):
            card = ttk.LabelFrame(stats, text=title, padding=(8, 3))
            card.grid(row=0, column=stat_index, sticky="nsew", padx=(0 if stat_index == 0 else 4, 0))
            stats.columnconfigure(stat_index, weight=1, uniform="admin-stats-v2133")
            ttk.Label(card, textvariable=variable, style="Section.TLabel", anchor="center").pack(fill="x")

        batch = ttk.Frame(self.dashboard_toolbar_v2133)
        batch.pack(fill="x", pady=(8, 0))
        ttk.Label(batch, text="Mehrfachbearbeitung", style="Status.TLabel").pack(side="left")
        self.batch_selected_label_v2133 = ttk.Label(batch, text="0 ausgewählt", style="Subtitle.TLabel")
        self.batch_selected_label_v2133.pack(side="left", padx=(8, 10))
        ttk.Button(batch, text="Sichtbare auswählen", command=self._select_visible_nodes_v2133).pack(side="left")
        ttk.Button(batch, text="Auswahl leeren", command=self._clear_node_selection_v2133).pack(side="left", padx=(4, 10))
        ttk.Button(batch, text="Logs laden", command=self.batch_log_download_v2133, style="Primary.TButton").pack(side="left")
        ttk.Button(batch, text="OTA", command=self.batch_ota_v2133).pack(side="left", padx=(4, 0))
        ttk.Button(batch, text="Wake", command=self.batch_wake_v2133).pack(side="left", padx=(4, 0))
        ttk.Button(batch, text="Live", command=self.batch_live_v2133).pack(side="left", padx=(4, 0))
        ttk.Button(batch, text="Profil / Service", command=self.batch_service_v2133).pack(side="left", padx=(4, 0))
        ttk.Button(batch, text="Löschen …", command=self.batch_delete_v2133).pack(side="right")

        activity = ttk.Frame(self.dashboard_toolbar_v2133)
        activity.pack(fill="x", pady=(8, 0))
        ttk.Label(activity, text="Aktivität", style="Subtitle.TLabel").pack(anchor="w")
        self.auto_ble_trace_list_v2133 = tk.Listbox(activity, height=3, activestyle="none")
        self.auto_ble_trace_list_v2133.pack(fill="x")
'''
        workflow = workflow.replace(body_anchor, admin_ui, 1)
    if "self.notebook.select(self.all_nodes_tab)" not in workflow:
        workflow = workflow.rstrip() + '\n        self.after(350, lambda: self.notebook.select(self.all_nodes_tab))\n'
    source = source[:workflow_start] + workflow + source[workflow_end:]

    pump_start, pump_end = method_span(source, "_pump_events")
    pump = source[pump_start:pump_end]
    done_anchor = '                elif kind == "done":\n'
    if 'kind == "auto_ble_trace_v2133"' not in pump:
        if done_anchor not in pump:
            raise SystemExit("v2.1.33 event pump anchor not found")
        event_code = r'''                elif kind == "auto_ble_trace_v2133":
                    if hasattr(self, "auto_ble_trace_list_v2133"):
                        self.auto_ble_trace_list_v2133.insert("end", str(value))
                        while self.auto_ble_trace_list_v2133.size() > 60:
                            self.auto_ble_trace_list_v2133.delete(0)
                        self.auto_ble_trace_list_v2133.see("end")
'''
        pump = pump.replace(done_anchor, event_code + done_anchor, 1)
    scan_done_anchor = '                elif kind == "ble_scan_done":\n                    self.ble_scan_button.configure(state="normal")\n'
    if "manual scan -> auto sync v2133" not in pump and scan_done_anchor in pump:
        pump = pump.replace(scan_done_anchor, scan_done_anchor + '                    # manual scan -> auto sync v2133\n                    if getattr(self, "auto_ble_enabled_v2132", None) is not None and self.auto_ble_enabled_v2132.get():\n                        self.after(350, lambda: self.auto_ble_refresh_v2132(False))\n', 1)
    source = source[:pump_start] + pump + source[pump_end:]

    theme_start, theme_end = method_span(source, "apply_theme")
    theme = source[theme_start:theme_end]
    if "admin notebook v2133" not in theme:
        theme = theme.rstrip() + r'''
        # admin notebook v2133
        self.style.configure("TNotebook.Tab", padding=(12, 7), font=(font, 9, "bold"))
        self.style.map(
            "TNotebook.Tab",
            background=[("selected", accent), ("active", palette["panel_alt"])],
            foreground=[("selected", "#FFFFFF" if name != "Matrix" else "#001A05")],
        )
''' + "\n"
        source = source[:theme_start] + theme + source[theme_end:]

    source += "\n# PATCH_V2133_ADMIN_BLE_RELIABILITY\n"
    required = (
        'APP_VERSION = "2.1.33"',
        'DEFAULT_BT_PIN_V2133 = "240180"',
        'def _windows_pair_fixed_pin_v2133',
        'def batch_log_download_v2133',
        'dashboard_toolbar_v2133',
        'auto_ble_trace_v2133',
        'PATCH_V2133_ADMIN_BLE_RELIABILITY',
    )
    missing = [marker for marker in required if marker not in source]
    if missing:
        raise SystemExit("v2.1.33 validation failed: " + ", ".join(missing))
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v2133.py <source.py>")
    path = Path(sys.argv[1])
    path.write_text(patch(path.read_text(encoding="utf-8")), encoding="utf-8")
    print("Applied Service Tool v2.1.33: admin dashboard + reliable automatic BLE log queue")


if __name__ == "__main__":
    main()
