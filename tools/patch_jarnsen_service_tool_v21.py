"""v2.1.0 usability pass: 1080p overview, all-node dashboard, OSM/Topo position map."""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "2.1.0"


def method_span(text: str, name: str) -> tuple[int, int]:
    start = text.find(f"    def {name}(")
    if start < 0:
        raise SystemExit(f"method {name} not found")
    next_method = text.find("\n    def ", start + 1)
    return start, next_method if next_method >= 0 else len(text)


def replace_method(text: str, name: str, updater) -> str:
    start, end = method_span(text, name)
    return text[:start] + updater(text[start:end]) + text[end:]


def insert_before_method(text: str, name: str, code: str) -> str:
    start, _ = method_span(text, name)
    return text[:start] + code.rstrip() + "\n\n" + text[start:]


def patch(source: str) -> str:
    source = re.sub(r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{APP_VERSION}"', source, count=1)
    source = source.replace('APP_VERSION != "2.0.1"', 'APP_VERSION != "2.1.0"')
    source = source.replace("App-Version ist nicht v2.0.1", "App-Version ist nicht v2.1.0")

    if "ONLINE_MAP_AVAILABLE" not in source:
        anchor = "\nPROTOCOLS = ("
        block = r'''
try:
    import tkintermapview

    ONLINE_MAP_AVAILABLE = True
except ImportError:
    tkintermapview = None
    ONLINE_MAP_AVAILABLE = False
'''
        if source.count(anchor) != 1:
            raise SystemExit("online-map import anchor not found")
        source = source.replace(anchor, "\n" + block.strip() + anchor, 1)

    def patch_build_ui(method: str) -> str:
        old = '        self.dashboard_canvas.pack(fill="both", expand=True)\n'
        if "self.dashboard_scrollbar" not in method:
            new = '''        self.dashboard_canvas.pack(side="left", fill="both", expand=True)\n        self.dashboard_scrollbar = ttk.Scrollbar(\n            overview_body, orient="vertical", command=self.dashboard_canvas.yview\n        )\n        self.dashboard_scrollbar.pack(side="right", fill="y")\n        self.dashboard_canvas.configure(yscrollcommand=self.dashboard_scrollbar.set)\n        self.dashboard_canvas.bind(\n            "<MouseWheel>",\n            lambda event: self.dashboard_canvas.yview_scroll(\n                int(-event.delta / 120) if event.delta else 0, "units"\n            ),\n            add="+",\n        )\n'''
            if method.count(old) != 1:
                raise SystemExit("dashboard scroll anchor not found")
            method = method.replace(old, new, 1)
        return method

    source = replace_method(source, "_build_ui", patch_build_ui)

    def patch_render_dashboard(method: str) -> str:
        old = '''        columns = 3 if available_width >= 1050 else (2 if available_width >= 700 else 1)\n        card_wrap = max(250, int(available_width / columns) - 70)\n'''
        new = '''        if available_width >= 1450:\n            columns = 4\n        elif available_width >= 1000:\n            columns = 3\n        elif available_width >= 680:\n            columns = 2\n        else:\n            columns = 1\n        compact = columns >= 4\n        card_wrap = max(220, int(available_width / columns) - (48 if compact else 70))\n'''
        if old in method:
            method = method.replace(old, new, 1)
        elif "compact = columns >= 4" not in method:
            raise SystemExit("dashboard column anchor not found")

        substitutions = (
            (
                '                padx=12 if ios else 9,\n                pady=10 if ios else 7,\n',
                '                padx=8 if compact else (12 if ios else 9),\n                pady=6 if compact else (10 if ios else 7),\n',
            ),
            (
                '                font=(palette["font"], 14 if ios else 13, "bold"),\n',
                '                font=(palette["font"], 12 if compact else (14 if ios else 13), "bold"),\n',
            ),
            (
                '                        9,\n                    ),\n                    wraplength=card_wrap,\n',
                '                        8 if compact else 9,\n                    ),\n                    wraplength=card_wrap,\n',
            ),
        )
        for old_part, new_part in substitutions:
            if new_part not in method:
                if old_part not in method:
                    raise SystemExit("dashboard compact-layout anchor not found")
                method = method.replace(old_part, new_part, 1)
        return method

    source = replace_method(source, "render_dashboard", patch_render_dashboard)

    def patch_workflow_ui(method: str) -> str:
        tab_anchor = '''        self.service_tab = ttk.Frame(self.notebook, padding=12)\n        self.firmware_tab = ttk.Frame(self.notebook, padding=12)\n        self.notebook.add(self.service_tab, text="Service")\n        self.notebook.add(self.firmware_tab, text="Firmware")\n'''
        if "self.all_nodes_tab" not in method:
            replacement = '''        self.all_nodes_tab = ttk.Frame(self.notebook, padding=10)\n        self.service_tab = ttk.Frame(self.notebook, padding=12)\n        self.firmware_tab = ttk.Frame(self.notebook, padding=12)\n        self.notebook.add(self.all_nodes_tab, text="Alle Nodes")\n        self.notebook.add(self.service_tab, text="Service")\n        self.notebook.add(self.firmware_tab, text="Firmware")\n'''
            if method.count(tab_anchor) != 1:
                raise SystemExit("all-nodes tab anchor not found")
            method = method.replace(tab_anchor, replacement, 1)

        old_order = '''        order = (\n            self.overview_tab,\n            self.service_tab,\n            self.track_tab,\n            self.firmware_tab,\n            self.history_tab,\n            self.trends_tab,\n            self.live_tab,\n            self.serial_tab,\n            self.details_tab,\n        )\n'''
        new_order = '''        order = (\n            self.all_nodes_tab,\n            self.overview_tab,\n            self.service_tab,\n            self.track_tab,\n            self.firmware_tab,\n            self.history_tab,\n            self.trends_tab,\n            self.live_tab,\n            self.serial_tab,\n            self.details_tab,\n        )\n'''
        if "self.all_nodes_tab,\n            self.overview_tab" not in method:
            if method.count(old_order) != 1:
                raise SystemExit("all-nodes notebook order anchor not found")
            method = method.replace(old_order, new_order, 1)

        label_anchor = '        self.notebook.tab(self.overview_tab, text="Übersicht")\n'
        if 'self.notebook.tab(self.all_nodes_tab, text="Alle Nodes")' not in method:
            replacement = (
                '        self.notebook.tab(self.all_nodes_tab, text="Alle Nodes")\n'
                '        self.notebook.tab(self.overview_tab, text="Node-Übersicht")\n'
            )
            if method.count(label_anchor) != 1:
                raise SystemExit("all-nodes label anchor not found")
            method = method.replace(label_anchor, replacement, 1)

        service_anchor = '        ttk.Label(self.service_tab, text="Schnellaktionen", style="Section.TLabel").pack(anchor="w")\n'
        if "self.all_nodes_tree = ttk.Treeview" not in method:
            all_nodes_ui = r'''        all_header = ttk.Frame(self.all_nodes_tab)
        all_header.pack(fill="x", pady=(0, 8))
        self.all_nodes_summary = ttk.Label(
            all_header, text="Nodes werden geladen …", style="Section.TLabel"
        )
        self.all_nodes_summary.pack(side="left", fill="x", expand=True)
        ttk.Button(all_header, text="+ Node", command=self.add_new_node).pack(side="right")
        ttk.Button(
            all_header, text="GitHub prüfen", command=self.refresh_firmware_status
        ).pack(side="right", padx=(0, 6))
        ttk.Button(
            all_header, text="Aktualisieren", command=self.refresh_all_nodes_overview
        ).pack(side="right", padx=(0, 6))

        self.all_nodes_tree = ttk.Treeview(
            self.all_nodes_tab,
            columns=("name", "device", "id", "battery", "firmware", "github", "last", "position", "warning"),
            show="headings",
            selectmode="browse",
            height=15,
        )
        for column, label, width, stretch in (
            ("name", "Node", 185, True),
            ("device", "Typ", 85, False),
            ("id", "Node-ID", 105, False),
            ("battery", "Akku", 72, False),
            ("firmware", "Firmware / Build", 150, True),
            ("github", "GitHub", 105, False),
            ("last", "Letzter Log", 145, False),
            ("position", "Position / Status", 140, True),
            ("warning", "Hinweis", 80, False),
        ):
            self.all_nodes_tree.heading(column, text=label)
            self.all_nodes_tree.column(column, width=width, stretch=stretch)
        self.all_nodes_tree.pack(fill="both", expand=True)
        self.all_nodes_tree.bind("<Double-1>", self.open_all_nodes_selected)
        all_footer = ttk.Frame(self.all_nodes_tab)
        all_footer.pack(fill="x", pady=(7, 0))
        ttk.Label(
            all_footer,
            text="Doppelklick öffnet die Node-Übersicht. Werte stammen aus dem jeweils letzten gespeicherten Log.",
            style="Subtitle.TLabel",
        ).pack(side="left", fill="x", expand=True)
        ttk.Button(
            all_footer, text="Ausgewählte Node öffnen", command=self.open_all_nodes_selected
        ).pack(side="right")

'''
            if method.count(service_anchor) != 1:
                raise SystemExit("all-nodes UI insertion anchor not found")
            method = method.replace(service_anchor, all_nodes_ui + service_anchor, 1)

        map_anchor = '        self.position_status_label.pack(fill="x", pady=(0, 6), before=self.track_canvas)\n'
        if "self.map_layer = ttk.Combobox" not in method:
            map_ui = map_anchor + r'''        self.map_toolbar = ttk.Frame(self.track_tab)
        self.map_toolbar.pack(fill="x", pady=(0, 6), before=self.track_canvas)
        ttk.Label(self.map_toolbar, text="Karte").pack(side="left")
        self.map_layer = ttk.Combobox(
            self.map_toolbar,
            state="readonly",
            values=("OpenStreetMap", "Topografisch", "Schema") if ONLINE_MAP_AVAILABLE else ("Schema",),
            width=18,
        )
        self.map_layer.set("OpenStreetMap" if ONLINE_MAP_AVAILABLE else "Schema")
        self.map_layer.pack(side="left", padx=(6, 8))
        self.map_layer.bind("<<ComboboxSelected>>", self.set_map_layer)
        self.map_point_count = ttk.Label(
            self.map_toolbar, text="", style="Subtitle.TLabel"
        )
        self.map_point_count.pack(side="left")
        self.map_attribution = ttk.Label(
            self.map_toolbar,
            text="Online-Karte benötigt Internet" if ONLINE_MAP_AVAILABLE else "Online-Karte nicht verfügbar · Schema aktiv",
            style="Subtitle.TLabel",
        )
        self.map_attribution.pack(side="right")
        if ONLINE_MAP_AVAILABLE:
            self.online_map = tkintermapview.TkinterMapView(
                self.track_tab, width=900, height=520, corner_radius=0
            )
            self.online_map.pack(fill="both", expand=True, before=self.track_canvas)
            self.track_canvas.pack_forget()
            self.set_map_layer()
'''
            if method.count(map_anchor) != 1:
                raise SystemExit("online-map UI anchor not found")
            method = method.replace(map_anchor, map_ui, 1)

        refresh_anchor = '        self.refresh_node_selector()\n        self.refresh_workflow_header()\n'
        if "self.refresh_all_nodes_overview()" not in method:
            if method.count(refresh_anchor) != 1:
                raise SystemExit("all-nodes initial refresh anchor not found")
            method = method.replace(
                refresh_anchor,
                '        self.refresh_node_selector()\n        self.refresh_all_nodes_overview()\n        self.refresh_workflow_header()\n',
                1,
            )
        return method

    source = replace_method(source, "_install_workflow_ui", patch_workflow_ui)

    if "    def refresh_all_nodes_overview(self)" not in source:
        helpers = r'''    def refresh_all_nodes_overview(self) -> None:
        if not hasattr(self, "all_nodes_tree"):
            return
        for item in self.all_nodes_tree.get_children():
            self.all_nodes_tree.delete(item)
        try:
            rows = self.repository.list_nodes(self.show_archived_var.get())
        except Exception:
            rows = []
        tracker_count = 0
        v3_count = 0
        update_count = 0
        warning_count = 0
        low_battery_count = 0
        for row in rows:
            node_id = str(row["node_id"])
            device_key = str(row["device"] or "")
            if device_key == "HELTEC_TRACKER_V1.1":
                tracker_count += 1
                device = "Tracker"
            elif device_key == "HELTEC_V3_REPEATER":
                v3_count += 1
                device = "V3"
            else:
                device = DEVICE_NAMES.get(device_key, device_key or "--")
            latest = self.repository.latest_log(node_id)
            metrics = latest.get("metrics", {}) if latest else {}
            if not isinstance(metrics, dict):
                metrics = {}
            name = str(metrics.get("long_name") or row["long_name"] or node_id)
            if row["archived"]:
                name += " (archiviert)"
            battery_value = metrics.get("battery_pct")
            battery = f"{float(battery_value):.0f} %" if isinstance(battery_value, (int, float)) else "--"
            if isinstance(battery_value, (int, float)) and float(battery_value) <= 20:
                low_battery_count += 1
            firmware = str(latest.get("firmware") or "--") if latest else "--"
            build = str(latest.get("build") or "") if latest else ""
            firmware_build = f"{firmware} · {build[:8]}" if build else firmware
            github_state, _github_detail, github_level = self.firmware_state(device_key, build)
            if github_level == "warning" or "Update" in github_state:
                update_count += 1
            captured = str(latest.get("captured_at") or "--").replace("T", " ") if latest else "--"
            position_state = str(metrics.get("position_state") or "")
            if position_state:
                position = {
                    "moving": "Bewegung",
                    "stabilizing": "Stabilisierung",
                    "stationary": "Stationär",
                }.get(position_state, position_state)
                live_count = int(metrics.get("live_positions") or 0)
                if live_count:
                    position += f" · {live_count} live"
            else:
                positions = metrics.get("positions")
                position = f"{int(positions)} Position(en)" if isinstance(positions, (int, float)) else "--"
            warnings = int(metrics.get("warning_count") or 0)
            if warnings or (isinstance(battery_value, (int, float)) and float(battery_value) <= 20):
                warning_count += 1
            warning = str(warnings) if warnings else ("Akku" if isinstance(battery_value, (int, float)) and float(battery_value) <= 20 else "--")
            self.all_nodes_tree.insert(
                "", "end", iid=node_id,
                values=(name, device, node_id, battery, firmware_build, github_state, captured, position, warning),
            )
        self.all_nodes_summary.configure(
            text=(
                f"{len(rows)} Nodes · {tracker_count} Tracker · {v3_count} V3 · "
                f"{update_count} Update(s) · {warning_count} Hinweis(e) · {low_battery_count} Akku ≤20 %"
            )
        )

    def open_all_nodes_selected(self, _event: object | None = None) -> None:
        if not hasattr(self, "all_nodes_tree"):
            return
        selected = self.all_nodes_tree.selection()
        if not selected:
            return
        node_id = str(selected[0])
        if hasattr(self, "node_tree") and self.node_tree.exists(node_id):
            self.node_tree.selection_set(node_id)
            self.node_tree.focus(node_id)
            self.node_tree.see(node_id)
            self.on_node_selected()
            self.notebook.select(self.overview_tab)

    def set_map_layer(self, _event: object | None = None) -> None:
        layer = self.map_layer.get() if hasattr(self, "map_layer") else "Schema"
        if layer == "Schema" or not ONLINE_MAP_AVAILABLE or not hasattr(self, "online_map"):
            if hasattr(self, "online_map"):
                self.online_map.pack_forget()
            if hasattr(self, "track_canvas") and not self.track_canvas.winfo_ismapped():
                self.track_canvas.pack(fill="both", expand=True, before=self.track_info)
            if hasattr(self, "map_attribution"):
                self.map_attribution.configure(text="Schema · offline")
            self.render_track_map()
            return
        if hasattr(self, "track_canvas"):
            self.track_canvas.pack_forget()
        if not self.online_map.winfo_ismapped():
            self.online_map.pack(fill="both", expand=True, before=self.track_info)
        if layer == "Topografisch":
            self.online_map.set_tile_server(
                "https://a.tile.opentopomap.org/{z}/{x}/{y}.png", max_zoom=17
            )
            self.map_attribution.configure(text="© OpenStreetMap-Mitwirkende · OpenTopoMap (CC-BY-SA)")
        else:
            self.online_map.set_tile_server(
                "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png", max_zoom=19
            )
            self.map_attribution.configure(text="© OpenStreetMap-Mitwirkende")
        self.sync_online_map(fit=True)

    def fit_online_map(self) -> None:
        if not ONLINE_MAP_AVAILABLE or not hasattr(self, "online_map") or not self.track_points:
            return
        coordinates = [
            (float(point["latitude"]), float(point["longitude"])) for point in self.track_points
        ]
        latitudes = [item[0] for item in coordinates]
        longitudes = [item[1] for item in coordinates]
        if len(coordinates) == 1 or (
            max(latitudes) - min(latitudes) < 0.00002
            and max(longitudes) - min(longitudes) < 0.00002
        ):
            self.online_map.set_position(coordinates[-1][0], coordinates[-1][1])
            self.online_map.set_zoom(18)
            return
        self.online_map.fit_bounding_box(
            (max(latitudes), min(longitudes)),
            (min(latitudes), max(longitudes)),
        )

    def sync_online_map(self, fit: bool = False) -> None:
        if not ONLINE_MAP_AVAILABLE or not hasattr(self, "online_map"):
            return
        if hasattr(self, "map_layer") and self.map_layer.get() == "Schema":
            return
        self.online_map.delete_all_marker()
        self.online_map.delete_all_path()
        total = len(self.track_points)
        if not total:
            if hasattr(self, "map_point_count"):
                self.map_point_count.configure(text="Keine Trackpunkte")
            return
        coordinates = [
            (float(point["latitude"]), float(point["longitude"])) for point in self.track_points
        ]
        path_step = max(1, (total + 1499) // 1500)
        path_coordinates = coordinates[::path_step]
        if path_coordinates[-1] != coordinates[-1]:
            path_coordinates.append(coordinates[-1])
        if len(path_coordinates) >= 2:
            self.online_map.set_path(path_coordinates, width=4)

        marker_step = max(1, (total + 299) // 300)
        marker_indices = list(range(0, total, marker_step))
        if 0 not in marker_indices:
            marker_indices.insert(0, 0)
        if total - 1 not in marker_indices:
            marker_indices.append(total - 1)
        marker_indices = sorted(set(marker_indices))
        for index in marker_indices:
            point = self.track_points[index]
            if index == 0:
                text = "Start"
            elif index == total - 1:
                text = "Letzter Punkt"
            elif total <= 80:
                text = str(index + 1)
            else:
                text = ""
            marker = self.online_map.set_marker(
                float(point["latitude"]),
                float(point["longitude"]),
                text=text,
                command=lambda _marker, selected=index: self.show_track_point(selected),
            )
            marker.data = index
        if hasattr(self, "map_point_count"):
            suffix = "" if len(marker_indices) == total else f" · {len(marker_indices)} Marker"
            self.map_point_count.configure(text=f"{total} Punkte · volle Route{suffix}")
        if fit:
            self.fit_online_map()
'''
        source = insert_before_method(source, "open_usb_recovery", helpers)

    def patch_refresh_nodes(method: str) -> str:
        if "self.refresh_all_nodes_overview()" in method:
            return method
        return method.rstrip() + '\n        if hasattr(self, "all_nodes_tree"):\n            self.refresh_all_nodes_overview()\n'

    source = replace_method(source, "refresh_nodes", patch_refresh_nodes)

    def patch_update_track_points(method: str) -> str:
        if "self.sync_online_map" in method:
            return method
        return method.rstrip() + '\n        if hasattr(self, "online_map"):\n            self.sync_online_map(fit=True)\n'

    source = replace_method(source, "update_track_points", patch_update_track_points)

    def patch_fit_track_map(method: str) -> str:
        if "self.fit_online_map()" in method:
            return method
        first_line_end = method.find("\n") + 1
        addition = '''        if (\n            hasattr(self, "online_map")\n            and hasattr(self, "map_layer")\n            and self.map_layer.get() != "Schema"\n        ):\n            self.fit_online_map()\n'''
        return method[:first_line_end] + addition + method[first_line_end:]

    source = replace_method(source, "fit_track_map", patch_fit_track_map)

    def patch_on_node_selected(method: str) -> str:
        if "self.refresh_all_nodes_overview()" in method:
            return method
        return method.rstrip() + '\n        if hasattr(self, "all_nodes_tree"):\n            self.refresh_all_nodes_overview()\n'

    source = replace_method(source, "on_node_selected", patch_on_node_selected)

    selftest_pos = source.find("def packaged_self_test(")
    if selftest_pos < 0:
        raise SystemExit("packaged_self_test not found")
    if '"refresh_all_nodes_overview"' not in source[selftest_pos:]:
        anchor = '        for method_name in (\n'
        pos = source.find(anchor, selftest_pos)
        if pos < 0:
            raise SystemExit("v2.1 self-test method-list anchor not found")
        insert_at = pos + len(anchor)
        source = source[:insert_at] + (
            '            "refresh_all_nodes_overview",\n'
            '            "open_all_nodes_selected",\n'
            '            "set_map_layer",\n'
            '            "fit_online_map",\n'
            '            "sync_online_map",\n'
        ) + source[insert_at:]

    required = (
        'APP_VERSION = "2.1.0"',
        "ONLINE_MAP_AVAILABLE",
        "self.dashboard_scrollbar",
        "compact = columns >= 4",
        "self.all_nodes_tab",
        "self.all_nodes_tree = ttk.Treeview",
        'self.notebook.tab(self.overview_tab, text="Node-Übersicht")',
        "def refresh_all_nodes_overview(self)",
        "def open_all_nodes_selected(self",
        "self.map_layer = ttk.Combobox",
        '"OpenStreetMap", "Topografisch", "Schema"',
        "def sync_online_map(self, fit: bool = False)",
        "opentopomap.org",
        "openstreetmap.org",
    )
    for marker in required:
        if marker not in source:
            raise SystemExit(f"missing v2.1 marker: {marker}")
    return source


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "tools/JARNSEN_NODE_SERVICE_TOOL.py")
    target.write_text(patch(target.read_text(encoding="utf-8")), encoding="utf-8")
    print("Service tool v2.1.0: 1080p dashboard + all nodes + OSM/Topo map")


if __name__ == "__main__":
    main()
