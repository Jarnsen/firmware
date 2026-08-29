"""v2.1.31: bootstrap virgin nodes, comfortable deletion, and same-name history merging."""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "2.1.31"


def method_span(text: str, name: str) -> tuple[int, int]:
    normal = text.find(f"    def {name}(")
    asynchronous = text.find(f"    async def {name}(")
    starts = [value for value in (normal, asynchronous) if value >= 0]
    if not starts:
        raise SystemExit(f"v2.1.31 method {name} not found")
    start = min(starts)
    next_method = text.find("\n    def ", start + 1)
    next_async = text.find("\n    async def ", start + 1)
    next_decorator = text.find("\n    @", start + 1)
    candidates = [value for value in (next_method, next_async, next_decorator) if value >= 0]
    return start, min(candidates) if candidates else len(text)


def class_span(text: str, name: str) -> tuple[int, int]:
    start = text.find(f"class {name}:")
    if start < 0:
        raise SystemExit(f"v2.1.31 class {name} not found")
    next_class = text.find("\nclass ", start + 1)
    return start, next_class if next_class >= 0 else len(text)


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"v2.1.31 {label}: expected one anchor, got {count}")
    return text.replace(old, new, 1)


def replace_method(text: str, name: str, replacement: str) -> str:
    start, end = method_span(text, name)
    return text[:start] + replacement.rstrip() + "\n" + text[end:]


def patch(source: str) -> str:
    if "PATCH_V2131_NODE_LIFECYCLE" in source:
        return source

    source = re.sub(r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{APP_VERSION}"', source, count=1)
    source = source.replace('APP_VERSION != "2.1.30"', 'APP_VERSION != "2.1.31"')
    source = source.replace("App-Version ist nicht v2.1.30", "App-Version ist nicht v2.1.31")

    # --- Persistent aliasing: an old physical Node-ID can belong to the same
    # logical node after replacement/reset. Raw files remain untouched; the DB
    # remembers the alias so a later rescan does not split the history again.
    repo_start, repo_end = class_span(source, "NodeRepository")
    repo = source[repo_start:repo_end]
    schema_start, schema_end = method_span(repo, "_create_management_schema")
    schema = repo[schema_start:schema_end]
    if "CREATE TABLE IF NOT EXISTS node_aliases" not in schema:
        schema = schema.rstrip() + r'''
            connection.execute("""
                CREATE TABLE IF NOT EXISTS node_aliases (
                    alias_node_id TEXT PRIMARY KEY,
                    canonical_node_id TEXT NOT NULL,
                    long_name TEXT NOT NULL DEFAULT '',
                    short_name TEXT NOT NULL DEFAULT '',
                    merged_at TEXT NOT NULL
                )
            """)
''' + "\n"
        repo = repo[:schema_start] + schema + repo[schema_end:]

    if "    def canonical_node_id_v2131(" not in repo:
        insert_at = repo.find("    def update_managed_from_log(")
        if insert_at < 0:
            raise SystemExit("v2.1.31 repository insertion anchor not found")
        repo_helpers = r'''    def canonical_node_id_v2131(self, node_id: str) -> str:
        current = normalize_node_id(node_id)
        if not current:
            return ""
        with contextlib.closing(self._connect()) as connection, connection:
            seen: set[str] = set()
            for _ in range(16):
                if current in seen:
                    break
                seen.add(current)
                row = connection.execute(
                    "SELECT canonical_node_id FROM node_aliases WHERE alias_node_id=?",
                    (current,),
                ).fetchone()
                if not row:
                    break
                target = normalize_node_id(str(row[0] or ""))
                if not target or target == current:
                    break
                current = target
        return current

    def same_name_nodes_v2131(
        self, long_name: str, short_name: str, exclude_node_id: str = ""
    ) -> list[dict[str, object]]:
        long_name = str(long_name or "").strip()
        short_name = str(short_name or "").strip()
        exclude = normalize_node_id(exclude_node_id)
        if not long_name or not short_name:
            return []
        with contextlib.closing(self._connect()) as connection, connection:
            rows = list(connection.execute(
                """SELECT n.node_id,n.long_name,n.short_name,n.device,n.first_seen,n.last_seen,
                          COUNT(l.id) AS log_count
                   FROM nodes n LEFT JOIN logs l ON l.node_id=n.node_id
                   WHERE lower(trim(n.long_name))=lower(trim(?))
                     AND lower(trim(n.short_name))=lower(trim(?))
                     AND n.node_id<>?
                   GROUP BY n.node_id
                   ORDER BY n.last_seen DESC""",
                (long_name, short_name, exclude),
            ))
        return [dict(row) for row in rows]

    def merge_node_history_v2131(self, old_node_id: str, new_node_id: str) -> int:
        old_id = normalize_node_id(old_node_id)
        new_id = normalize_node_id(new_node_id)
        if not old_id or not new_id or old_id == new_id:
            return 0
        now = now_local().isoformat(timespec="seconds")
        with contextlib.closing(self._connect()) as connection, connection:
            old_row = connection.execute(
                "SELECT * FROM nodes WHERE node_id=?", (old_id,)
            ).fetchone()
            new_row = connection.execute(
                "SELECT * FROM nodes WHERE node_id=?", (new_id,)
            ).fetchone()
            if old_row is None or new_row is None:
                return 0
            log_count = int(connection.execute(
                "SELECT COUNT(*) FROM logs WHERE node_id=?", (old_id,)
            ).fetchone()[0])
            old_first = str(old_row["first_seen"] or "")
            old_last = str(old_row["last_seen"] or "")
            if old_first:
                connection.execute(
                    "UPDATE nodes SET first_seen=CASE WHEN first_seen='' OR first_seen>? THEN ? ELSE first_seen END WHERE node_id=?",
                    (old_first, old_first, new_id),
                )
            if old_last:
                connection.execute(
                    "UPDATE nodes SET last_seen=CASE WHEN last_seen<? THEN ? ELSE last_seen END WHERE node_id=?",
                    (old_last, old_last, new_id),
                )
            connection.execute("UPDATE logs SET node_id=? WHERE node_id=?", (new_id, old_id))
            with contextlib.suppress(sqlite3.Error):
                connection.execute("UPDATE firmware_events SET node_id=? WHERE node_id=?", (new_id, old_id))
            with contextlib.suppress(sqlite3.Error):
                connection.execute("DELETE FROM managed_nodes WHERE node_id=?", (old_id,))
            connection.execute(
                "UPDATE node_aliases SET canonical_node_id=? WHERE canonical_node_id=?",
                (new_id, old_id),
            )
            connection.execute(
                """INSERT INTO node_aliases(alias_node_id,canonical_node_id,long_name,short_name,merged_at)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(alias_node_id) DO UPDATE SET
                     canonical_node_id=excluded.canonical_node_id,
                     long_name=excluded.long_name,
                     short_name=excluded.short_name,
                     merged_at=excluded.merged_at""",
                (old_id, new_id, str(old_row["long_name"] or ""), str(old_row["short_name"] or ""), now),
            )
            connection.execute("DELETE FROM nodes WHERE node_id=?", (old_id,))
        return log_count

'''
        repo = repo[:insert_at] + repo_helpers + repo[insert_at:]

    delete_records = r'''    def delete_records(self, node_id: str) -> None:
        normalized = normalize_node_id(node_id)
        if not normalized:
            return
        with contextlib.closing(self._connect()) as connection, connection:
            with contextlib.suppress(sqlite3.Error):
                connection.execute("DELETE FROM firmware_events WHERE node_id=?", (normalized,))
            with contextlib.suppress(sqlite3.Error):
                connection.execute("DELETE FROM managed_nodes WHERE node_id=?", (normalized,))
            with contextlib.suppress(sqlite3.Error):
                connection.execute(
                    "DELETE FROM node_aliases WHERE alias_node_id=? OR canonical_node_id=?",
                    (normalized, normalized),
                )
            connection.execute("DELETE FROM nodes WHERE node_id=?", (normalized,))
'''
    repo = replace_method(repo, "delete_records", delete_records)

    import_start, import_end = method_span(repo, "import_payload")
    import_method = repo[import_start:import_end]
    import_method = replace_once(
        import_method,
        '        node_id = str(metrics.get("node_id") or "")\n        if not node_id or not str(metrics.get("device") or "").startswith("HELTEC_"):\n',
        '        raw_node_id = normalize_node_id(str(metrics.get("node_id") or ""))\n'
        '        node_id = self.canonical_node_id_v2131(raw_node_id)\n'
        '        if node_id and node_id != raw_node_id:\n'
        '            metrics["source_node_id"] = raw_node_id\n'
        '            metrics["node_id"] = node_id\n'
        '        if not node_id or not str(metrics.get("device") or "").startswith("HELTEC_"):\n',
        "canonical import",
    )
    repo = repo[:import_start] + import_method + repo[import_end:]
    source = source[:repo_start] + repo + source[repo_end:]

    # --- Virgin-node provisioning. The old flow required a working Meshtastic
    # connection before it would even reach the serial flasher. A never-used or
    # non-Meshtastic board therefore timed out. Now a failed pre-flash handshake
    # falls back to the hardware type stored in the selected profile, flashes the
    # correct JARN-MESH image, then performs the full factory reset on that newly
    # flashed firmware before applying the profile.
    provision_worker = r'''    def _config_profile_provision_worker(self, slot: int, profile: dict[str,object], port: str) -> None:
        interface = None
        verify_interface = None
        try:
            identity = self._serial_port_identity(port)
            identity_key = self._serial_identity_key(identity)
            profile_device_code = self._device_code_from_hw_text(str(profile.get("source_hw") or ""))
            device_code = ""
            expected_device = ""
            reset_port = port
            pre_reset_done = False

            self.events.put(("status", f"Grundprofil {slot+1}: Hardware auf {port} erkennen"))
            try:
                interface, node = self._open_config_profile_interface(("USB", port, port))
                device_code = self._detect_connected_device_code(interface, profile)
                expected_device = str(HARDWARE_PROFILES[device_code]["device"])
                source_hw, _ = self._config_profile_metadata(interface)
                tool_log(
                    "PROVISION_IDENTIFY_V2119", slot=slot+1, port=port,
                    device_code=device_code, hw=source_hw or "--",
                    usb_identity=identity_key or "--", mode="running-firmware",
                )
                if self.stop_event.is_set():
                    raise RuntimeError("Einrichtung abgebrochen")
                self.events.put(("progress_detail", (8, "Full Device Reset", False)))
                self.events.put(("status", f"{HARDWARE_PROFILES[device_code]['label']}: Full Device Reset"))
                node.factoryReset(full=True)
                pre_reset_done = True
                time.sleep(1.0)
                with contextlib.suppress(Exception):
                    interface.close()
                interface = None
                reset_port = self._wait_for_matching_serial_port(identity, port, 75.0)
            except Exception as identify_exc:
                with contextlib.suppress(Exception):
                    if interface is not None:
                        interface.close()
                interface = None
                if self.stop_event.is_set():
                    raise RuntimeError("Einrichtung abgebrochen") from identify_exc
                if not profile_device_code:
                    raise RuntimeError(
                        "Die Node antwortet noch nicht als Meshtastic-Gerät und der Hardwaretyp "
                        "ist im gewählten Grundprofil nicht eindeutig hinterlegt. Bitte ein "
                        "Tracker- bzw. V3-Grundprofil verwenden."
                    ) from identify_exc
                device_code = profile_device_code
                expected_device = str(HARDWARE_PROFILES[device_code]["device"])
                tool_log(
                    "PROVISION_BOOTSTRAP_V2131", slot=slot+1, port=port,
                    device_code=device_code, usb_identity=identity_key or "--",
                    error_type=type(identify_exc).__name__, error=identify_exc,
                )
                self.events.put((
                    "progress_detail",
                    (8, f"Keine nutzbare Firmware erkannt · {HARDWARE_PROFILES[device_code]['label']} aus Profil", False),
                ))
                self.events.put((
                    "status",
                    f"{HARDWARE_PROFILES[device_code]['label']}: unbespielte Node wird direkt per USB initialisiert",
                ))
                with contextlib.suppress(Exception):
                    reset_port = self._wait_for_matching_serial_port(identity, port, 12.0)

            if self.stop_event.is_set():
                raise RuntimeError("Einrichtung abgebrochen")
            self.events.put(("progress_detail", (18, "Neueste Firmware von GitHub prüfen", False)))
            firmware, loader, manifest = self._download_serial_bundle(device_code)
            source_sha = str(manifest.get("source_sha") or "").lower()
            with tempfile.TemporaryDirectory() as temporary:
                directory = pathlib.Path(temporary)
                firmware_path = directory / "firmware.update.bin"
                loader_path = directory / "otaBTupdate.bin"
                firmware_path.write_bytes(firmware)
                loader_path.write_bytes(loader)
                self.events.put(("progress_detail", (30, "ESP32-S3 prüfen", False)))
                self._run_esptool(["--chip", "esp32s3", "--port", reset_port, "chip-id"])
                if self.stop_event.is_set():
                    raise RuntimeError("Einrichtung abgebrochen")
                self.events.put(("progress_detail", (42, "Firmware + otaBTupdate seriell flashen", False)))
                self._run_esptool([
                    "--chip", "esp32s3", "--port", reset_port, "--baud", "460800",
                    "--before", "default-reset", "--after", "hard-reset", "write-flash",
                    "0x10000", str(firmware_path), "0x340000", str(loader_path),
                ])
                self.events.put(("progress_detail", (66, "OTA-Bootwahl zurücksetzen", False)))
                self._run_esptool([
                    "--chip", "esp32s3", "--port", reset_port,
                    "--before", "default-reset", "--after", "hard-reset",
                    "erase-region", "0xE000", "0x2000",
                ])

            flashed_port = self._wait_for_matching_serial_port(identity, reset_port, 90.0)
            self.events.put(("progress_detail", (72, "Node nach Flash wiederfinden", False)))
            verify_interface, verify_node = self._open_config_profile_interface(("USB", flashed_port, flashed_port))
            detected = self._detect_connected_device_code(verify_interface, profile)
            if detected != device_code:
                raise RuntimeError(f"Hardwareprüfung nach Flash fehlgeschlagen: {detected} statt {device_code}")

            if not pre_reset_done:
                self.events.put(("progress_detail", (74, "Full Device Reset auf neuer Firmware", False)))
                tool_log(
                    "PROVISION_POSTFLASH_RESET_V2131", slot=slot+1, port=flashed_port,
                    device_code=device_code,
                )
                verify_node.factoryReset(full=True)
                time.sleep(1.2)
                with contextlib.suppress(Exception):
                    verify_interface.close()
                verify_interface = None
                flashed_port = self._wait_for_matching_serial_port(identity, flashed_port, 75.0)
                verify_interface, _verify_node = self._open_config_profile_interface(("USB", flashed_port, flashed_port))
                detected = self._detect_connected_device_code(verify_interface, profile)
                if detected != device_code:
                    raise RuntimeError(
                        f"Hardwareprüfung nach Bootstrap-Werkreset fehlgeschlagen: {detected} statt {device_code}"
                    )

            with contextlib.suppress(Exception):
                if verify_interface is not None:
                    verify_interface.close()
            verify_interface = None
            context = {
                "slot": slot,
                "profile_name": str(profile.get("name") or f"Profil {slot+1}"),
                "port": flashed_port,
                "device_code": device_code,
                "device": expected_device,
                "source_sha": source_sha,
                "usb_identity": identity,
            }
            tool_log(
                "PROVISION_FLASH_OK_V2119", slot=slot+1, port=flashed_port,
                device_code=device_code, build=source_sha[:8] or "--",
                bootstrap=not pre_reset_done,
            )
            self.events.put(("provision_ready_for_profile", context))
        except Exception as exc:
            tool_log(
                "PROVISION_ERROR_V2119", slot=slot+1, port=port,
                error_type=type(exc).__name__, error=exc,
            )
            self.events.put(("provision_error", str(exc)))
        finally:
            with contextlib.suppress(Exception):
                if interface is not None:
                    interface.close()
            with contextlib.suppress(Exception):
                if verify_interface is not None:
                    verify_interface.close()
'''
    source = replace_method(source, "_config_profile_provision_worker", provision_worker)

    # --- Comfortable node management + same-name merge prompt after a completed
    # reset/provision cycle.
    render_start, _render_end = method_span(source, "render_dashboard")
    app_helpers = r'''    def _delete_node_ids_v2131(self, node_ids: list[str]) -> bool:
        ids: list[str] = []
        for value in node_ids:
            normalized = normalize_node_id(str(value or ""))
            if normalized and normalized not in ids:
                ids.append(normalized)
        if not ids:
            return False
        paths: list[pathlib.Path] = []
        names: list[str] = []
        for node_id in ids:
            logs = self.repository.logs_for_node(node_id)
            for item in logs:
                path = pathlib.Path(str(item["path"]))
                if path.exists() and path not in paths:
                    paths.append(path)
            row = next((dict(item) for item in self.repository.list_nodes(include_archived=True) if str(item["node_id"]) == node_id), None)
            label = str((row or {}).get("long_name") or node_id)
            names.append(f"{label} ({node_id})")
        if paths and (not RECYCLE_AVAILABLE or send2trash is None):
            messagebox.showerror(
                "Node löschen",
                "Die Papierkorb-Unterstützung fehlt in dieser App-Ausgabe. Die Logdateien wurden nicht gelöscht.",
            )
            return False
        preview = "\n".join(f"• {name}" for name in names[:8])
        if len(names) > 8:
            preview += f"\n• … und {len(names) - 8} weitere"
        if not messagebox.askyesno(
            "Node(s) endgültig aus dem Tool löschen",
            f"{len(ids)} Node(s) und {len(paths)} zugehörige Logdatei(en) löschen?\n\n"
            f"{preview}\n\n"
            "Die Logdateien werden in den Windows-Papierkorb verschoben. "
            "Die Node-Einträge, Firmware-Historie und Zusammenführungs-Aliase werden aus der Tool-Datenbank entfernt.",
        ):
            return False
        try:
            for path in paths:
                send2trash(str(path))
            for node_id in ids:
                self.repository.delete_records(node_id)
            tool_log("NODE_DELETE_V2131", nodes=len(ids), logs=len(paths), ids=",".join(ids))
        except Exception as exc:
            messagebox.showerror("Node löschen", f"Löschen nicht vollständig ausgeführt: {exc}")
            return False
        if normalize_node_id(str(getattr(self, "selected_node_id", "") or "")) in ids:
            self.selected_node_id = ""
            self.node_logs = []
            self.last_payload = None
            self.last_output = None
        self.refresh_nodes()
        with contextlib.suppress(Exception):
            self.refresh_all_nodes_overview()
        return True

    def open_node_manager_v2131(self) -> None:
        win = tk.Toplevel(self)
        win.title("Nodes verwalten / löschen")
        win.transient(self)
        win.geometry("880x520")
        body = ttk.Frame(win, padding=12)
        body.pack(fill="both", expand=True)
        ttk.Label(
            body,
            text="Mehrere Nodes direkt auswählen. Entf löscht die Auswahl inklusive Logdateien in den Windows-Papierkorb.",
            style="Subtitle.TLabel",
            wraplength=820,
        ).pack(fill="x", pady=(0, 8))
        tree = ttk.Treeview(
            body,
            columns=("long", "short", "id", "device", "logs", "state"),
            show="headings",
            selectmode="extended",
            height=15,
        )
        headings = {
            "long": "Long Name", "short": "Short", "id": "Node-ID",
            "device": "Hardware", "logs": "Logs", "state": "Status",
        }
        widths = {"long": 220, "short": 80, "id": 130, "device": 140, "logs": 60, "state": 110}
        for key, title in headings.items():
            tree.heading(key, text=title)
            tree.column(key, width=widths[key], stretch=key in ("long", "device", "state"))
        tree.pack(fill="both", expand=True)

        def refill() -> None:
            for item in tree.get_children():
                tree.delete(item)
            for row_obj in self.repository.list_nodes(include_archived=True):
                row = dict(row_obj)
                node_id = str(row.get("node_id") or "")
                management = self.repository.management_for_node(node_id) or {}
                tree.insert(
                    "", "end", iid=node_id,
                    values=(
                        row.get("long_name") or "--",
                        row.get("short_name") or "--",
                        node_id,
                        DEVICE_NAMES.get(str(row.get("device") or ""), row.get("device") or "--"),
                        int(row.get("log_count") or 0),
                        management.get("status") or ("Archiviert" if int(row.get("archived") or 0) else "--"),
                    ),
                )

        def delete_selected(_event=None) -> None:
            selected = list(tree.selection())
            if not selected:
                messagebox.showinfo("Nodes verwalten", "Bitte mindestens eine Node markieren.", parent=win)
                return
            if self._delete_node_ids_v2131(selected):
                refill()

        footer = ttk.Frame(body)
        footer.pack(fill="x", pady=(8, 0))
        ttk.Button(footer, text="Schließen", command=win.destroy).pack(side="right")
        ttk.Button(footer, text="Markierte Node(s) löschen …", command=delete_selected).pack(side="right", padx=(0, 6))
        ttk.Button(footer, text="Neu einlesen", command=lambda: (self.rescan_logs(), refill())).pack(side="left")
        tree.bind("<Delete>", delete_selected)
        refill()

    def _offer_same_name_history_merge_v2131(self, snapshot: dict[str, object]) -> None:
        node_id = normalize_node_id(str(snapshot.get("node_id") or ""))
        long_name = str(snapshot.get("long_name") or "").strip()
        short_name = str(snapshot.get("short_name") or "").strip()
        if not node_id or not long_name or not short_name:
            return
        matches = self.repository.same_name_nodes_v2131(long_name, short_name, node_id)
        if not matches:
            return
        details = []
        for row in matches[:6]:
            details.append(f"• {row.get('node_id')} · {int(row.get('log_count') or 0)} Log(s)")
        if len(matches) > 6:
            details.append(f"• … und {len(matches) - 6} weitere")
        text = "\n".join(details)
        if not messagebox.askyesno(
            "Vorherige Node-Historie gefunden",
            f"Für den gerade neu eingerichteten Namen\n\n"
            f"Long Name: {long_name}\nShort Name: {short_name}\n\n"
            f"existieren bereits ältere Node-Einträge mit anderer Node-ID:\n{text}\n\n"
            "Sollen deren Logs mit dieser neuen Node zusammengeführt werden?\n\n"
            "Danach erscheint in der Node-Datenbank nur noch ein Eintrag mit diesem Long/Short Name. "
            "Die ursprünglichen Logdateien bleiben unverändert; das Tool merkt sich die alten Node-IDs als Historien-Aliase.",
        ):
            tool_log(
                "NODE_HISTORY_MERGE_DECLINED_V2131", node_id=node_id,
                long_name=long_name, short_name=short_name, matches=len(matches),
            )
            return
        merged_logs = 0
        merged_nodes = 0
        for row in matches:
            old_id = str(row.get("node_id") or "")
            count = self.repository.merge_node_history_v2131(old_id, node_id)
            merged_logs += int(count)
            merged_nodes += 1
        self.repository.scan_logs()
        self.selected_node_id = node_id
        self.node_logs = self.repository.logs_for_node(node_id)
        self.refresh_nodes()
        with contextlib.suppress(Exception):
            self.refresh_history_view()
        with contextlib.suppress(Exception):
            self.refresh_all_nodes_overview()
        tool_log(
            "NODE_HISTORY_MERGED_V2131", node_id=node_id,
            merged_nodes=merged_nodes, merged_logs=merged_logs,
            long_name=long_name, short_name=short_name,
        )
        messagebox.showinfo(
            "Node-Historie zusammengeführt",
            f"{merged_nodes} ältere Node-Eintrag/Einträge und {merged_logs} Log(s) wurden "
            f"der aktuellen Node {node_id} zugeordnet.\n\nIn der Node-Datenbank bleibt nur der aktuelle Eintrag sichtbar.",
        )
'''
    source = source[:render_start] + app_helpers.rstrip() + "\n\n" + source[render_start:]

    delete_method = r'''    def delete_node(self) -> None:
        if not self.selected_node_id:
            messagebox.showinfo("Node löschen", "Bitte zuerst eine Node auswählen.")
            return
        self._delete_node_ids_v2131([self.selected_node_id])
'''
    source = replace_method(source, "delete_node", delete_method)

    build_start, build_end = method_span(source, "_build_ui")
    build = source[build_start:build_end]
    delete_button_anchor = '''        ttk.Button(node_actions, text="Löschen …", command=self.delete_node).pack(\n            side="left", fill="x", expand=True, padx=(5, 0)\n        )\n'''
    delete_button_replacement = delete_button_anchor + '''        self.node_tree.bind("<Delete>", lambda _event: self.delete_node())\n        ttk.Button(\n            nodes,\n            text="Nodes verwalten / mehrfach löschen …",\n            command=self.open_node_manager_v2131,\n        ).pack(fill="x", pady=(4, 0))\n'''
    build = replace_once(build, delete_button_anchor, delete_button_replacement, "node manager UI")
    source = source[:build_start] + build + source[build_end:]

    pump_start, pump_end = method_span(source, "_pump_events")
    pump = source[pump_start:pump_end]
    merge_anchor = 'self.set_transfer_progress(100, "Neuinstallation + Profil abgeschlossen", False); self.refresh_all_nodes_overview(); messagebox.showinfo("Node neu eingerichtet",'
    merge_replacement = 'self.set_transfer_progress(100, "Neuinstallation + Profil abgeschlossen", False); self._offer_same_name_history_merge_v2131(dict(snapshot)); self.refresh_all_nodes_overview(); messagebox.showinfo("Node neu eingerichtet",'
    pump = replace_once(pump, merge_anchor, merge_replacement, "provision merge hook")
    source = source[:pump_start] + pump + source[pump_end:]

    source += "\n# PATCH_V2131_NODE_LIFECYCLE\n"
    required = (
        'APP_VERSION = "2.1.31"',
        "CREATE TABLE IF NOT EXISTS node_aliases",
        "def canonical_node_id_v2131",
        "def merge_node_history_v2131",
        "PROVISION_BOOTSTRAP_V2131",
        "PROVISION_POSTFLASH_RESET_V2131",
        "Nodes verwalten / mehrfach löschen",
        "NODE_DELETE_V2131",
        "Vorherige Node-Historie gefunden",
        "NODE_HISTORY_MERGED_V2131",
        "self._offer_same_name_history_merge_v2131(dict(snapshot))",
        "PATCH_V2131_NODE_LIFECYCLE",
    )
    missing = [marker for marker in required if marker not in source]
    if missing:
        raise SystemExit("v2.1.31 validation failed: " + ", ".join(missing))
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v2131.py <source.py>")
    path = Path(sys.argv[1])
    path.write_text(patch(path.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"Patched {path} to v{APP_VERSION}: virgin bootstrap + node delete/merge lifecycle")


if __name__ == "__main__":
    main()
