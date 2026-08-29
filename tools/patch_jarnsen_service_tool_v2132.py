"""v2.1.32: tile-first node dashboard and automatic BLE log maintenance."""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "2.1.32"


def method_span(text: str, name: str) -> tuple[int, int]:
    normal = text.find(f"    def {name}(")
    asynchronous = text.find(f"    async def {name}(")
    starts = [value for value in (normal, asynchronous) if value >= 0]
    if not starts:
        raise SystemExit(f"v2.1.32 method {name} not found")
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


def class_span(text: str, name: str) -> tuple[int, int]:
    start = text.find(f"class {name}:")
    if start < 0:
        raise SystemExit(f"v2.1.32 class {name} not found")
    candidates = [
        value
        for value in (
            text.find("\nclass ", start + 1),
            text.find("\ndef ", start + 1),
        )
        if value >= 0
    ]
    return start, min(candidates) if candidates else len(text)


def replace_method(text: str, name: str, replacement: str) -> str:
    start, end = method_span(text, name)
    return text[:start] + replacement.rstrip() + "\n" + text[end:]


def patch(source: str) -> str:
    if "PATCH_V2132_TILE_BLE_AUTOMATION" in source:
        return source

    source = re.sub(r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{APP_VERSION}"', source, count=1)
    source = source.replace('APP_VERSION != "2.1.31"', 'APP_VERSION != "2.1.32"')
    source = source.replace("App-Version ist nicht v2.1.31", "App-Version ist nicht v2.1.32")

    if "AUTO_BLE_SYNC_SECONDS" not in source:
        anchor = 'OTABT_STALL_SECONDS = 180.0\n'
        if source.count(anchor) != 1:
            raise SystemExit("v2.1.32 AUTO_BLE_SYNC_SECONDS anchor not found")
        source = source.replace(
            anchor,
            anchor + "AUTO_BLE_SYNC_SECONDS = 15 * 60\nAUTO_BLE_SCAN_SECONDS = 5 * 60\n",
            1,
        )

    repo_start, repo_end = class_span(source, "NodeRepository")
    repo = source[repo_start:repo_end]
    schema_start, schema_end = method_span(repo, "_create_management_schema")
    schema = repo[schema_start:schema_end]
    if "CREATE TABLE IF NOT EXISTS ble_node_map" not in schema:
        schema = schema.rstrip() + r'''
            connection.execute("""
                CREATE TABLE IF NOT EXISTS ble_node_map (
                    identity_key TEXT PRIMARY KEY,
                    node_id TEXT NOT NULL DEFAULT '',
                    display_name TEXT NOT NULL DEFAULT '',
                    last_seen TEXT NOT NULL DEFAULT '',
                    last_sync TEXT NOT NULL DEFAULT '',
                    last_error TEXT NOT NULL DEFAULT ''
                )
            """)
''' + "\n"
        repo = repo[:schema_start] + schema + repo[schema_end:]

    if "    def ble_mapping_v2132(" not in repo:
        insert_at = repo.find("    def update_managed_from_log(")
        if insert_at < 0:
            raise SystemExit("v2.1.32 repository helper anchor not found")
        repo_helpers = r'''    def ble_mapping_v2132(self, identity_key: str) -> dict[str, object] | None:
        key = str(identity_key or "").strip().lower()
        if not key:
            return None
        with contextlib.closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT identity_key,node_id,display_name,last_seen,last_sync,last_error FROM ble_node_map WHERE identity_key=?",
                (key,),
            ).fetchone()
        if not row:
            return None
        data = dict(row)
        node_id = self.canonical_node_id_v2131(str(data.get("node_id") or ""))
        if node_id:
            data["node_id"] = node_id
        return data

    def remember_ble_identity_v2132(
        self, identity_key: str, node_id: str, display_name: str = ""
    ) -> None:
        key = str(identity_key or "").strip().lower()
        canonical = self.canonical_node_id_v2131(node_id)
        if not key or not canonical:
            return
        now = now_local().isoformat(timespec="seconds")
        with contextlib.closing(self._connect()) as connection, connection:
            connection.execute(
                """INSERT INTO ble_node_map(identity_key,node_id,display_name,last_seen,last_sync,last_error)
                   VALUES(?,?,?,?,?, '')
                   ON CONFLICT(identity_key) DO UPDATE SET
                     node_id=excluded.node_id,
                     display_name=CASE WHEN excluded.display_name<>'' THEN excluded.display_name ELSE ble_node_map.display_name END,
                     last_seen=excluded.last_seen,
                     last_sync=excluded.last_sync,
                     last_error=''""",
                (key, canonical, str(display_name or ""), now, now),
            )

    def mark_ble_seen_v2132(
        self, identity_key: str, display_name: str = "", error: str = ""
    ) -> None:
        key = str(identity_key or "").strip().lower()
        if not key:
            return
        now = now_local().isoformat(timespec="seconds")
        with contextlib.closing(self._connect()) as connection, connection:
            connection.execute(
                """INSERT INTO ble_node_map(identity_key,node_id,display_name,last_seen,last_sync,last_error)
                   VALUES(?, '', ?, ?, '', ?)
                   ON CONFLICT(identity_key) DO UPDATE SET
                     display_name=CASE WHEN excluded.display_name<>'' THEN excluded.display_name ELSE ble_node_map.display_name END,
                     last_seen=excluded.last_seen,
                     last_error=excluded.last_error""",
                (key, str(display_name or ""), now, str(error or "")),
            )

    def ble_status_for_node_v2132(self, node_id: str) -> dict[str, object] | None:
        canonical = self.canonical_node_id_v2131(node_id)
        if not canonical:
            return None
        with contextlib.closing(self._connect()) as connection, connection:
            row = connection.execute(
                """SELECT identity_key,node_id,display_name,last_seen,last_sync,last_error
                   FROM ble_node_map WHERE node_id=? ORDER BY last_seen DESC LIMIT 1""",
                (canonical,),
            ).fetchone()
        return dict(row) if row else None

'''
        repo = repo[:insert_at] + repo_helpers + repo[insert_at:]

    delete_start, delete_end = method_span(repo, "delete_records")
    delete_method = repo[delete_start:delete_end]
    cleanup_anchor = '            connection.execute("DELETE FROM nodes WHERE node_id=?", (normalized,))\n'
    if "DELETE FROM ble_node_map" not in delete_method:
        if cleanup_anchor not in delete_method:
            raise SystemExit("v2.1.32 delete_records anchor not found")
        delete_method = delete_method.replace(
            cleanup_anchor,
            '            with contextlib.suppress(sqlite3.Error):\n'
            '                connection.execute("DELETE FROM ble_node_map WHERE node_id=?", (normalized,))\n'
            + cleanup_anchor,
            1,
        )
        repo = repo[:delete_start] + delete_method + repo[delete_end:]
    source = source[:repo_start] + repo + source[repo_end:]

    render_start, _render_end = method_span(source, "render_dashboard")
    helpers = r'''    # PATCH_V2132_TILE_BLE_AUTOMATION
    @staticmethod
    def _format_v2132_time(value: object) -> str:
        text = str(value or "").replace("T", " ")
        return text[:19] if text else "--"

    def _ble_identity_key_v2132(self, device: object) -> str:
        address = str(getattr(device, "address", "") or "").strip().lower()
        if address:
            return f"addr:{address}"
        suffix = self._ble_identity_suffix(device)
        if suffix:
            return f"suffix:{suffix}"
        name = str(getattr(device, "name", "") or "").strip().lower()
        return f"name:{name}" if name else ""

    def _ble_node_id_v2132(self, device: object) -> str:
        key = self._ble_identity_key_v2132(device)
        mapping = self.repository.ble_mapping_v2132(key) if key else None
        return normalize_node_id(str(mapping.get("node_id") or "")) if mapping else ""

    def _set_ble_device_state_v2132(self, device: object, state: str) -> None:
        node_id = self._ble_node_id_v2132(device)
        if not node_id:
            return
        states = getattr(self, "node_sync_state_v2132", None)
        if not isinstance(states, dict):
            states = {}
            self.node_sync_state_v2132 = states
        states[node_id] = str(state)
        self.events.put(("node_cards_refresh_v2132", None))

    def _remember_ble_payload_v2132(
        self, device: object, label: str, payload: bytes
    ) -> None:
        try:
            snapshot = snapshot_metrics(payload)
            node_id = normalize_node_id(str(snapshot.get("node_id") or ""))
            key = self._ble_identity_key_v2132(device)
            if not node_id or not key:
                return
            self.repository.remember_ble_identity_v2132(key, node_id, label)
            states = getattr(self, "node_sync_state_v2132", None)
            if not isinstance(states, dict):
                states = {}
                self.node_sync_state_v2132 = states
            states[node_id] = "Aktuell · Log synchronisiert"
            self.events.put(("node_cards_refresh_v2132", None))
        except Exception as exc:
            tool_log("BLE_IDENTITY_V2132", error_type=type(exc).__name__, error=exc)

    def _auto_ble_due_v2132(self, device: object, force: bool = False) -> bool:
        if force:
            return True
        node_id = self._ble_node_id_v2132(device)
        if not node_id:
            return True
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
            age = (now_local() - captured.astimezone()).total_seconds()
            return age >= AUTO_BLE_SYNC_SECONDS
        except Exception:
            return True

    def open_node_from_tile_v2132(self, node_id: str, target: str = "overview") -> None:
        normalized = normalize_node_id(node_id)
        if not normalized or not hasattr(self, "node_tree") or not self.node_tree.exists(normalized):
            return
        self.selected_node_id = normalized
        self.node_tree.selection_set(normalized)
        self.node_tree.focus(normalized)
        self.node_tree.see(normalized)
        self.on_node_selected()
        destinations = {
            "overview": getattr(self, "overview_tab", None),
            "service": getattr(self, "service_tab", None),
            "firmware": getattr(self, "firmware_tab", None),
            "history": getattr(self, "history_tab", None),
        }
        destination = destinations.get(target) or destinations["overview"]
        if destination is not None:
            self.notebook.select(destination)

    def open_node_actions_v2132(self, node_id: str) -> None:
        normalized = normalize_node_id(node_id)
        if not normalized:
            return
        latest = self.repository.latest_log(normalized)
        metrics = latest.get("metrics", {}) if latest else {}
        if not isinstance(metrics, dict):
            metrics = {}
        name = str(metrics.get("long_name") or normalized)
        win = tk.Toplevel(self)
        win.title(f"Node bearbeiten · {name}")
        win.transient(self)
        win.resizable(False, False)
        body = ttk.Frame(win, padding=16)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=name, style="Section.TLabel").pack(anchor="w")
        ttk.Label(
            body,
            text=f"{normalized} · {DEVICE_NAMES.get(str(metrics.get('device') or ''), str(metrics.get('device') or '--'))}",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(2, 12))

        def go(target: str) -> None:
            self.open_node_from_tile_v2132(normalized, target)
            win.destroy()

        ttk.Button(body, text="Node öffnen", command=lambda: go("overview"), style="Primary.TButton").pack(fill="x")
        ttk.Button(body, text="Grunddaten / Service bearbeiten", command=lambda: go("service")).pack(fill="x", pady=(6, 0))
        ttk.Button(body, text="Firmware", command=lambda: go("firmware")).pack(fill="x", pady=(6, 0))
        ttk.Button(body, text="Log-Historie", command=lambda: go("history")).pack(fill="x", pady=(6, 0))

        def delete_this() -> None:
            if self._delete_node_ids_v2131([normalized]):
                win.destroy()

        ttk.Separator(body).pack(fill="x", pady=12)
        ttk.Button(body, text="Node löschen …", command=delete_this).pack(fill="x")
        ttk.Button(body, text="Schließen", command=win.destroy).pack(fill="x", pady=(6, 0))

    def _resize_node_tiles_v2132(self, event: tk.Event) -> None:
        if not hasattr(self, "node_tiles_canvas_v2132"):
            return
        self.node_tiles_canvas_v2132.itemconfigure(self.node_tiles_window_v2132, width=event.width)
        self.after_idle(self.render_node_tiles_v2132)

    def render_node_tiles_v2132(self) -> None:
        host = getattr(self, "node_tiles_host_v2132", None)
        if host is None:
            return
        for child in host.winfo_children():
            child.destroy()
        try:
            rows = self.repository.list_nodes(self.show_archived_var.get())
        except Exception:
            rows = []
        width = max(640, int(getattr(self, "node_tiles_canvas_v2132").winfo_width() or 640))
        columns = 4 if width >= 1500 else (3 if width >= 1050 else (2 if width >= 700 else 1))
        palette = THEMES.get(self.theme.get(), THEMES["Modern"])
        states = getattr(self, "node_sync_state_v2132", {})
        if not isinstance(states, dict):
            states = {}
        for column in range(columns):
            host.columnconfigure(column, weight=1, uniform="node-tile-v2132")
        for index, row in enumerate(rows):
            node_id = normalize_node_id(str(row["node_id"] or ""))
            latest = self.repository.latest_log(node_id)
            metrics = latest.get("metrics", {}) if latest else {}
            if not isinstance(metrics, dict):
                metrics = {}
            device_key = str(row["device"] or metrics.get("device") or "")
            device = "Tracker" if device_key == "HELTEC_TRACKER_V1.1" else ("V3" if device_key == "HELTEC_V3_REPEATER" else DEVICE_NAMES.get(device_key, device_key or "--"))
            name = str(metrics.get("long_name") or row["long_name"] or node_id)
            battery_value = metrics.get("battery_pct")
            battery = f"{float(battery_value):.0f} %" if isinstance(battery_value, (int, float)) else "--"
            firmware = str(latest.get("firmware") or "--") if latest else "--"
            build = str(latest.get("build") or "") if latest else ""
            firmware_text = f"{firmware} · {build[:8]}" if build else firmware
            github_state, _github_detail, github_level = self.firmware_state(device_key, build)
            warning_count = int(metrics.get("warning_count") or 0)
            low_battery = isinstance(battery_value, (int, float)) and float(battery_value) <= 20
            border = palette["error"] if warning_count or low_battery else (palette["warning"] if github_level == "warning" or "Update" in github_state else palette["accent"])
            card = tk.Frame(
                host,
                bg=palette["panel"],
                highlightbackground=border,
                highlightcolor=border,
                highlightthickness=2,
                bd=0,
            )
            card.grid(row=index // columns, column=index % columns, sticky="nsew", padx=7, pady=7)
            header = tk.Frame(card, bg=palette["panel"])
            header.pack(fill="x", padx=12, pady=(10, 4))
            tk.Label(
                header,
                text=name + (" · archiviert" if int(row["archived"] or 0) else ""),
                bg=palette["panel"], fg=palette["fg"],
                font=(palette["font"], 12, "bold"), anchor="w",
            ).pack(side="left", fill="x", expand=True)
            ttk.Button(header, text="✎", width=3, command=lambda value=node_id: self.open_node_actions_v2132(value)).pack(side="right")
            tk.Label(
                card,
                text=f"{device} · {node_id}",
                bg=palette["panel"], fg=palette["muted"],
                font=(palette["font"], 9), anchor="w",
            ).pack(fill="x", padx=12)
            facts = (
                f"Akku        {battery}\n"
                f"Firmware    {firmware_text}\n"
                f"GitHub      {github_state}\n"
                f"Letzter Log {self._format_v2132_time(latest.get('captured_at') if latest else '')}"
            )
            tk.Label(
                card, text=facts, justify="left", anchor="w",
                bg=palette["panel"], fg=palette["fg"],
                font=(palette["mono"], 9),
            ).pack(fill="x", padx=12, pady=(8, 4))
            ble_state = self.repository.ble_status_for_node_v2132(node_id)
            sync_text = str(states.get(node_id) or "")
            if not sync_text:
                if ble_state:
                    sync_text = f"BLE erkannt · Sync {self._format_v2132_time(ble_state.get('last_sync'))}"
                else:
                    sync_text = "BLE noch nicht automatisch zugeordnet"
            tk.Label(
                card, text=sync_text, justify="left", anchor="w",
                bg=palette["panel"], fg=palette["muted"],
                font=(palette["font"], 9), wraplength=max(250, int(width / columns) - 50),
            ).pack(fill="x", padx=12, pady=(4, 8))
            actions = ttk.Frame(card)
            actions.pack(fill="x", padx=10, pady=(0, 10))
            ttk.Button(actions, text="Öffnen", command=lambda value=node_id: self.open_node_from_tile_v2132(value)).pack(side="left", fill="x", expand=True)
            ttk.Button(actions, text="Bearbeiten", command=lambda value=node_id: self.open_node_actions_v2132(value)).pack(side="left", fill="x", expand=True, padx=(6, 0))
        if not rows:
            ttk.Label(host, text="Noch keine Nodes gespeichert. BLE-Automatik oder USB-Log erkennt sie automatisch.", style="Section.TLabel").grid(row=0, column=0, sticky="w", padx=12, pady=18)
        canvas = getattr(self, "node_tiles_canvas_v2132", None)
        if canvas is not None:
            self.after_idle(lambda: canvas.configure(scrollregion=canvas.bbox("all")))

    def auto_ble_refresh_v2132(self, force: bool = False) -> None:
        if not BLE_AVAILABLE:
            return
        enabled = getattr(self, "auto_ble_enabled_v2132", None)
        if enabled is not None and not bool(enabled.get()) and not force:
            return
        if self.worker and self.worker.is_alive():
            if hasattr(self, "auto_ble_status_v2132"):
                self.auto_ble_status_v2132.configure(text="Automatik wartet · anderer Vorgang läuft")
            return
        self.stop_event.clear()
        if hasattr(self, "auto_ble_status_v2132"):
            self.auto_ble_status_v2132.configure(text="Automatik: suche BLE-Nodes …")
        self.worker = threading.Thread(
            target=self._auto_ble_scan_worker_v2132,
            args=(force,),
            daemon=True,
        )
        self.worker.start()

    def _auto_ble_timer_v2132(self) -> None:
        self.auto_ble_refresh_v2132(False)
        self._auto_ble_after_v2132 = self.after(
            int(AUTO_BLE_SCAN_SECONDS * 1000), self._auto_ble_timer_v2132
        )

    def _auto_ble_scan_worker_v2132(self, force: bool = False) -> None:
        delegated = False
        try:
            devices = asyncio.run(BleakScanner.discover(timeout=8.0, return_adv=True))
            found: dict[str, object] = {}
            due: list[tuple[str, object]] = []
            skipped = 0
            for device, advertisement in devices.values():
                name = str(device.name or "Unbenannter JARN-MESH Node")
                service_uuids = {str(value).lower() for value in (advertisement.service_uuids or [])}
                if MESH_SERVICE_UUID.lower() in service_uuids:
                    label = f"{name} - {device.address}"
                    found[label] = device
                    key = self._ble_identity_key_v2132(device)
                    self.repository.mark_ble_seen_v2132(key, label)
                    if self._auto_ble_due_v2132(device, force):
                        due.append((label, device))
                        self._set_ble_device_state_v2132(device, "Warteschlange · Logprüfung fällig")
                    else:
                        skipped += 1
                        self._set_ble_device_state_v2132(device, "Aktuell · kein Download nötig")
                elif OTABT_SERVICE_UUID.lower() in service_uuids:
                    found[f"[OTA] {name} - {device.address}"] = device
            self.events.put(("ble_devices", (found, len(devices))))
            self.events.put(("auto_ble_status_v2132", (len(found), len(due), skipped)))
            if due and not self.stop_event.is_set():
                self.events.put(("status", f"BLE-Automatik: {len(due)} Node(s) fällig · Queue startet nacheinander"))
                delegated = True
                self._ble_download_worker(due)
                return
            self.events.put(("status_success", f"BLE-Automatik: {len(found)} Node(s) geprüft · kein Logdownload nötig"))
        except Exception as exc:
            self.events.put(("status_warning", f"BLE-Automatik derzeit nicht verfügbar: {exc}"))
        finally:
            if not delegated:
                self.events.put(("done", None))

'''
    source = source[:render_start] + helpers.rstrip() + "\n\n" + source[render_start:]

    workflow_start, workflow_end = method_span(source, "_install_workflow_ui")
    workflow = source[workflow_start:workflow_end]
    tree_anchor = '        self.all_nodes_tree.pack(fill="both", expand=True)\n'
    if "self.node_tiles_canvas_v2132" not in workflow:
        if tree_anchor not in workflow:
            raise SystemExit("v2.1.32 all-nodes tree anchor not found")
        tile_ui = tree_anchor + r'''        self.all_nodes_tree.pack_forget()
        self.node_tiles_body_v2132 = ttk.Frame(self.all_nodes_tab)
        self.node_tiles_body_v2132.pack(fill="both", expand=True)
        self.node_tiles_canvas_v2132 = tk.Canvas(self.node_tiles_body_v2132, highlightthickness=0)
        self.node_tiles_scrollbar_v2132 = ttk.Scrollbar(
            self.node_tiles_body_v2132, orient="vertical", command=self.node_tiles_canvas_v2132.yview
        )
        self.node_tiles_canvas_v2132.configure(yscrollcommand=self.node_tiles_scrollbar_v2132.set)
        self.node_tiles_scrollbar_v2132.pack(side="right", fill="y")
        self.node_tiles_canvas_v2132.pack(side="left", fill="both", expand=True)
        self.node_tiles_host_v2132 = ttk.Frame(self.node_tiles_canvas_v2132)
        self.node_tiles_window_v2132 = self.node_tiles_canvas_v2132.create_window(
            (0, 0), window=self.node_tiles_host_v2132, anchor="nw"
        )
        self.node_tiles_host_v2132.bind(
            "<Configure>",
            lambda _event: self.node_tiles_canvas_v2132.configure(
                scrollregion=self.node_tiles_canvas_v2132.bbox("all")
            ),
        )
        self.node_tiles_canvas_v2132.bind("<Configure>", self._resize_node_tiles_v2132)
        self.node_tiles_canvas_v2132.bind(
            "<MouseWheel>",
            lambda event: self.node_tiles_canvas_v2132.yview_scroll(
                int(-event.delta / 120) if event.delta else 0, "units"
            ),
            add="+",
        )
'''
        workflow = workflow.replace(tree_anchor, tile_ui, 1)

    summary_anchor = '        self.all_nodes_summary.pack(side="left", fill="x", expand=True)\n'
    if "self.auto_ble_enabled_v2132" not in workflow:
        if summary_anchor not in workflow:
            raise SystemExit("v2.1.32 all-nodes header anchor not found")
        auto_header = summary_anchor + r'''        self.auto_ble_enabled_v2132 = tk.BooleanVar(value=True)
        self.auto_ble_status_v2132 = ttk.Label(
            all_header, text="BLE-Automatik bereit", style="Subtitle.TLabel"
        )
        self.auto_ble_status_v2132.pack(side="left", padx=(10, 6))
        ttk.Checkbutton(
            all_header, text="Auto BLE", variable=self.auto_ble_enabled_v2132
        ).pack(side="right", padx=(4, 0))
        ttk.Button(
            all_header, text="BLE prüfen", command=lambda: self.auto_ble_refresh_v2132(False)
        ).pack(side="right", padx=(4, 0))
'''
        workflow = workflow.replace(summary_anchor, auto_header, 1)

    workflow = workflow.replace(
        '        self.notebook.tab(self.all_nodes_tab, text="Alle Nodes")\n',
        '        self.notebook.tab(self.all_nodes_tab, text="Nodeübersicht")\n',
        1,
    )
    workflow = workflow.replace(
        '        self.notebook.tab(self.overview_tab, text="Node-Übersicht")\n',
        '        self.notebook.tab(self.overview_tab, text="Node-Details")\n',
        1,
    )
    workflow = workflow.replace(
        '            text="Doppelklick öffnet die Node-Übersicht. Werte stammen aus dem jeweils letzten gespeicherten Log.",\n',
        '            text="Kachel öffnen oder über ✎ bearbeiten. Mehrfachlöschen bleibt über die Node-Verwaltung verfügbar.",\n',
        1,
    )
    workflow = workflow.replace(
        '            all_footer, text="Ausgewählte Node öffnen", command=self.open_all_nodes_selected\n',
        '            all_footer, text="Nodes verwalten / mehrfach löschen …", command=self.open_node_manager_v2131\n',
        1,
    )
    if "self._auto_ble_timer_v2132" not in workflow:
        workflow = workflow.rstrip() + r'''
        self.node_sync_state_v2132 = {}
        self.after(1600, lambda: self.auto_ble_refresh_v2132(False))
        self._auto_ble_after_v2132 = self.after(
            int(AUTO_BLE_SCAN_SECONDS * 1000), self._auto_ble_timer_v2132
        )
''' + "\n"
    source = source[:workflow_start] + workflow + source[workflow_end:]

    refresh_start, refresh_end = method_span(source, "refresh_all_nodes_overview")
    refresh = source[refresh_start:refresh_end]
    if "self.render_node_tiles_v2132()" not in refresh:
        refresh = refresh.rstrip() + "\n        self.render_node_tiles_v2132()\n"
        source = source[:refresh_start] + refresh + source[refresh_end:]

    theme_start, theme_end = method_span(source, "apply_theme")
    theme = source[theme_start:theme_end]
    if "render_node_tiles_v2132" not in theme:
        theme = theme.rstrip() + r'''
        if hasattr(self, "node_tiles_host_v2132"):
            self.after_idle(self.render_node_tiles_v2132)
''' + "\n"
        source = source[:theme_start] + theme + source[theme_end:]

    for method_name in ("_set_ble_queue_hold_async", "_ble_download_async", "_live_async", "_verify_updated_firmware"):
        start, end = method_span(source, method_name)
        method = source[start:end]
        method = method.replace("pair=False,", "pair=True,", 1)
        source = source[:start] + method + source[end:]

    update_start, update_end = method_span(source, "_ble_update_fleet_async")
    update_method = source[update_start:update_end]
    if "pair=not label.startswith" not in update_method:
        update_method = update_method.replace(
            "                    pair=False,\n",
            '                    pair=not label.startswith("[OTA]"),\n',
            1,
        )
        source = source[:update_start] + update_method + source[update_end:]

    open_bt_start, open_bt_end = method_span(source, "open_windows_bluetooth")
    open_bt = source[open_bt_start:open_bt_end]
    open_bt = open_bt.replace(
        'text="Node jetzt in Windows koppeln; danach BLE-Log erneut laden"',
        'text="Falls Windows fragt: Node mit PIN 240180 koppeln; danach läuft BLE automatisch weiter"',
        1,
    )
    source = source[:open_bt_start] + open_bt + source[open_bt_end:]

    ble_async_start, ble_async_end = method_span(source, "_ble_download_async")
    ble_async = source[ble_async_start:ble_async_end]
    finish_anchor = "        self._finish_payload(\n            payload,\n"
    if "_remember_ble_payload_v2132" not in ble_async:
        if finish_anchor not in ble_async:
            raise SystemExit("v2.1.32 BLE payload anchor not found")
        ble_async = ble_async.replace(
            finish_anchor,
            '        self._remember_ble_payload_v2132(ble_device, label, payload)\n'
            + finish_anchor,
            1,
        )
        source = source[:ble_async_start] + ble_async + source[ble_async_end:]

    ble_worker_start, ble_worker_end = method_span(source, "_ble_download_worker")
    ble_worker = source[ble_worker_start:ble_worker_end]
    call_anchor = "                    asyncio.run(\n                        self._ble_download_async(\n"
    if "Log wird geladen" not in ble_worker:
        if call_anchor not in ble_worker:
            raise SystemExit("v2.1.32 BLE queue call anchor not found")
        ble_worker = ble_worker.replace(
            call_anchor,
            '                    self._set_ble_device_state_v2132(ble_device, "Log wird geladen …")\n'
            + call_anchor,
            1,
        )
        source = source[:ble_worker_start] + ble_worker + source[ble_worker_end:]

    pump_start, pump_end = method_span(source, "_pump_events")
    pump = source[pump_start:pump_end]
    done_anchor = '                elif kind == "done":\n'
    if 'kind == "auto_ble_status_v2132"' not in pump:
        if done_anchor not in pump:
            raise SystemExit("v2.1.32 event pump anchor not found")
        custom_events = r'''                elif kind == "auto_ble_status_v2132":
                    found, due, skipped = value
                    if hasattr(self, "auto_ble_status_v2132"):
                        self.auto_ble_status_v2132.configure(
                            text=f"BLE: {found} erkannt · {due} fällig · {skipped} aktuell"
                        )
                    self.render_node_tiles_v2132()
                elif kind == "node_cards_refresh_v2132":
                    self.render_node_tiles_v2132()
'''
        pump = pump.replace(done_anchor, custom_events + done_anchor, 1)
        source = source[:pump_start] + pump + source[pump_end:]

    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v2132.py <source.py>")
    path = Path(sys.argv[1])
    path.write_text(patch(path.read_text(encoding="utf-8")), encoding="utf-8")
    print("Applied Service Tool v2.1.32: tile dashboard + automatic BLE log maintenance")


if __name__ == "__main__":
    main()
