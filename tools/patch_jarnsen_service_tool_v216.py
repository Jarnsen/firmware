"""v2.1.6: honor manual BLE selection and add historical map day/range filters."""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "2.1.6"


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
    source = source.replace('APP_VERSION != "2.1.5"', 'APP_VERSION != "2.1.6"')
    source = source.replace("App-Version ist nicht v2.1.5", "App-Version ist nicht v2.1.6")

    # A user-selected BLE row is an explicit operator decision. v2.1.5 still
    # rejected it when the advertisement name differed from the stored mesh
    # long name. Preserve automatic safety, but let an explicit selection win.
    def patch_start_ble_download(method: str) -> str:
        anchor = '''        matching = [(label, device) for label, device in candidates if self._ble_label_matches_selected(label)]\n        if len(candidates) > 1:\n'''
        replacement = '''        matching = [(label, device) for label, device in candidates if self._ble_label_matches_selected(label)]\n        candidate_labels = {label for label, _device in candidates}\n        manual = [\n            (label, device)\n            for label, device in self.selected_ble_devices()\n            if label in candidate_labels\n        ]\n        if manual:\n            tool_log(\n                "BLE_MANUAL_SELECTION_V216",\n                count=len(manual),\n                labels="|".join(label for label, _device in manual),\n            )\n        if len(candidates) > 1:\n'''
        if anchor not in method:
            raise SystemExit("v2.1.6 BLE manual-selection anchor not found")
        method = method.replace(anchor, replacement, 1)

        old_choice = '''            if choice:\n                if len(matching) != 1:\n                    tool_log("BLE_MULTI_DOWNLOAD_CHOICE_V215", choice="selected-not-found", matches=len(matching))\n                    messagebox.showwarning(\n                        "Ausgewählte Node nicht erreichbar",\n                        "Die im zentralen Node-Dropdown ausgewählte Node konnte unter den aktuellen Bluetooth-Treffern nicht eindeutig gefunden werden. Es wurde nichts von einer anderen Node geladen.",\n                    )\n                    self.open_advanced_controls()\n                    self.show_controls_page("Bluetooth")\n                    return\n                ble_devices = matching\n                tool_log("BLE_MULTI_DOWNLOAD_CHOICE_V215", choice="selected", node=matching[0][0])\n'''
        new_choice = '''            if choice:\n                # Explicit operator selection has priority when advertisement\n                # names cannot be correlated to the stored mesh long name.\n                selected_target = manual if len(manual) == 1 else matching\n                if len(selected_target) != 1:\n                    tool_log(\n                        "BLE_MULTI_DOWNLOAD_CHOICE_V216",\n                        choice="selected-not-found",\n                        matches=len(matching),\n                        manual=len(manual),\n                    )\n                    messagebox.showwarning(\n                        "Ausgewählte Node nicht eindeutig",\n                        "Die zentral ausgewählte Node konnte keinem einzelnen BLE-Treffer sicher zugeordnet werden. Bitte im Bluetooth-Bereich genau eine erreichbare Node markieren und erneut 'Log herunterladen' wählen.",\n                    )\n                    self.open_advanced_controls()\n                    self.show_controls_page("Bluetooth")\n                    return\n                ble_devices = selected_target\n                tool_log(\n                    "BLE_MULTI_DOWNLOAD_CHOICE_V216",\n                    choice="selected-manual" if manual else "selected-auto",\n                    node=selected_target[0][0],\n                )\n'''
        if old_choice not in method:
            raise SystemExit("v2.1.6 BLE multi-choice block not found")
        method = method.replace(old_choice, new_choice, 1)

        old_single = '''        else:\n            ble_devices = candidates\n            # With only one reachable Node, never silently download the wrong\n            # known Node when another one is selected centrally.\n            if self._selected_ble_identity_tokens() and not matching:\n                messagebox.showwarning(\n                    "Ausgewählte Node nicht erreichbar",\n                    "Die einzige erreichbare Bluetooth-Node passt nicht zur zentral ausgewählten Node. Es wurde nichts heruntergeladen.",\n                )\n                self.open_advanced_controls()\n                self.show_controls_page("Bluetooth")\n                return\n\n        self._show_ble_targets(ble_devices)\n'''
        new_single = '''        else:\n            ble_devices = candidates\n            # If the one reachable node was explicitly marked by the user, use\n            # it even when its BLE advertisement name differs from the stored\n            # mesh long name. Without an explicit selection, retain the safety\n            # check so an unrelated nearby node is never chosen silently.\n            if self._selected_ble_identity_tokens() and not matching and not manual:\n                messagebox.showwarning(\n                    "Ausgewählte Node nicht erreichbar",\n                    "Die einzige erreichbare Bluetooth-Node passt nicht automatisch zur zentral ausgewählten Node. Bitte diese Node im Bluetooth-Bereich markieren und erneut versuchen.",\n                )\n                self.open_advanced_controls()\n                self.show_controls_page("Bluetooth")\n                return\n            if manual:\n                ble_devices = manual\n                tool_log("BLE_SINGLE_MANUAL_OVERRIDE_V216", node=manual[0][0])\n\n        self._show_ble_targets(ble_devices)\n'''
        if old_single not in method:
            raise SystemExit("v2.1.6 BLE single-device block not found")
        return method.replace(old_single, new_single, 1)

    source = replace_method(source, "start_ble_download", patch_start_ble_download)

    # Add a second compact toolbar row for historical time selection. Keep the
    # current map-layer toolbar unchanged so 1080p remains uncluttered.
    def patch_workflow_ui(method: str) -> str:
        if "self.map_time_mode" in method:
            return method
        anchor = '''        self.map_attribution.pack(side="right")\n        if ONLINE_MAP_AVAILABLE:\n'''
        addition = '''        self.map_attribution.pack(side="right")\n\n        self.map_filter_toolbar = ttk.Frame(self.track_tab)\n        self.map_filter_toolbar.pack(fill="x", pady=(0, 6), before=self.track_canvas)\n        ttk.Label(self.map_filter_toolbar, text="Zeitraum").pack(side="left")\n        self.map_time_mode = ttk.Combobox(\n            self.map_filter_toolbar,\n            state="readonly",\n            values=("Alle", "Tag", "Zeitraum"),\n            width=10,\n        )\n        self.map_time_mode.set("Alle")\n        self.map_time_mode.pack(side="left", padx=(6, 10))\n        self.map_time_mode.bind("<<ComboboxSelected>>", self.apply_track_time_filter)\n        ttk.Label(self.map_filter_toolbar, text="Tag").pack(side="left")\n        self.map_day = ttk.Combobox(self.map_filter_toolbar, state="readonly", width=12)\n        self.map_day.pack(side="left", padx=(5, 10))\n        self.map_day.bind("<<ComboboxSelected>>", self._select_track_day)\n        ttk.Label(self.map_filter_toolbar, text="Von").pack(side="left")\n        self.map_from = ttk.Entry(self.map_filter_toolbar, width=12)\n        self.map_from.pack(side="left", padx=(5, 8))\n        ttk.Label(self.map_filter_toolbar, text="Bis").pack(side="left")\n        self.map_to = ttk.Entry(self.map_filter_toolbar, width=12)\n        self.map_to.pack(side="left", padx=(5, 8))\n        ttk.Button(\n            self.map_filter_toolbar, text="Anwenden", command=self.apply_track_time_filter\n        ).pack(side="left")\n        ttk.Button(\n            self.map_filter_toolbar, text="Alle anzeigen", command=self.reset_track_time_filter\n        ).pack(side="left", padx=(6, 0))\n        self.map_filter_status = ttk.Label(\n            self.map_filter_toolbar, text="", style="Subtitle.TLabel"\n        )\n        self.map_filter_status.pack(side="right")\n\n        if ONLINE_MAP_AVAILABLE:\n'''
        if anchor not in method:
            raise SystemExit("v2.1.6 map filter toolbar anchor not found")
        return method.replace(anchor, addition, 1)

    source = replace_method(source, "_install_workflow_ui", patch_workflow_ui)

    if "    def _collect_track_history(self)" not in source:
        helpers = r'''    @staticmethod
    def _track_point_date(point: dict[str, object]) -> dt.date | None:
        try:
            epoch = int(point.get("epoch") or 0)
            if epoch <= 0:
                return None
            return dt.datetime.fromtimestamp(epoch).astimezone().date()
        except (OSError, OverflowError, TypeError, ValueError):
            return None

    def _collect_track_history(self) -> list[dict[str, object]]:
        unique: dict[tuple[int, int, int], dict[str, object]] = {}
        read_files = 0
        for log in self.node_logs if isinstance(self.node_logs, list) else []:
            path_text = str(log.get("path") or "") if isinstance(log, dict) else ""
            if not path_text:
                continue
            path = pathlib.Path(path_text)
            try:
                payload = path.read_bytes()
            except OSError:
                continue
            read_files += 1
            for point in parse_track_points(payload):
                key = (
                    int(point.get("epoch") or 0),
                    round(float(point["latitude"]) * 10_000_000),
                    round(float(point["longitude"]) * 10_000_000),
                )
                unique[key] = point
        # Include the currently loaded payload even when it has not yet been
        # persisted/indexed for any reason.
        for point in parse_track_points(self.last_payload):
            key = (
                int(point.get("epoch") or 0),
                round(float(point["latitude"]) * 10_000_000),
                round(float(point["longitude"]) * 10_000_000),
            )
            unique[key] = point
        points = sorted(
            unique.values(),
            key=lambda item: (
                int(item.get("epoch") or 0),
                float(item.get("latitude") or 0.0),
                float(item.get("longitude") or 0.0),
            ),
        )
        tool_log(
            "TRACK_HISTORY_V216",
            node=self.selected_node_id or "--",
            files=read_files,
            unique_points=len(points),
        )
        return points

    @staticmethod
    def _parse_track_filter_date(value: str) -> dt.date | None:
        value = value.strip()
        if not value:
            return None
        for pattern in ("%Y-%m-%d", "%d.%m.%Y"):
            try:
                return dt.datetime.strptime(value, pattern).date()
            except ValueError:
                pass
        return None

    def _refresh_track_filter_controls(self) -> None:
        if not hasattr(self, "map_time_mode"):
            return
        dates = sorted(
            {
                date.isoformat()
                for point in getattr(self, "all_track_points", [])
                if (date := self._track_point_date(point)) is not None
            }
        )
        self.map_day.configure(values=tuple(dates))
        if dates:
            if self.map_day.get() not in dates:
                self.map_day.set(dates[-1])
            if not self.map_from.get().strip():
                self.map_from.insert(0, dates[0])
            if not self.map_to.get().strip():
                self.map_to.insert(0, dates[-1])
        else:
            self.map_day.set("")

    def _select_track_day(self, _event: object | None = None) -> None:
        if not hasattr(self, "map_time_mode"):
            return
        self.map_time_mode.set("Tag")
        self.apply_track_time_filter()

    def reset_track_time_filter(self) -> None:
        if not hasattr(self, "map_time_mode"):
            return
        self.map_time_mode.set("Alle")
        self.apply_track_time_filter()

    def apply_track_time_filter(self, _event: object | None = None, fit: bool = True) -> None:
        all_points = list(getattr(self, "all_track_points", self.track_points))
        mode = self.map_time_mode.get() if hasattr(self, "map_time_mode") else "Alle"
        filtered = all_points
        detail = "Alle Tage"
        if mode == "Tag":
            selected = self._parse_track_filter_date(self.map_day.get()) if hasattr(self, "map_day") else None
            if selected is None:
                filtered = []
                detail = "Kein gültiger Tag"
            else:
                filtered = [point for point in all_points if self._track_point_date(point) == selected]
                detail = selected.strftime("%d.%m.%Y")
        elif mode == "Zeitraum":
            start = self._parse_track_filter_date(self.map_from.get()) if hasattr(self, "map_from") else None
            end = self._parse_track_filter_date(self.map_to.get()) if hasattr(self, "map_to") else None
            if start is None or end is None:
                messagebox.showwarning(
                    "Karten-Zeitraum",
                    "Bitte Von und Bis als JJJJ-MM-TT oder TT.MM.JJJJ eingeben.",
                )
                return
            if start > end:
                start, end = end, start
            filtered = [
                point
                for point in all_points
                if (date := self._track_point_date(point)) is not None and start <= date <= end
            ]
            detail = f"{start.strftime('%d.%m.%Y')} – {end.strftime('%d.%m.%Y')}"

        self.track_points = filtered
        self.track_view = None
        if hasattr(self, "map_filter_status"):
            self.map_filter_status.configure(
                text=f"{detail} · {len(filtered)}/{len(all_points)} Punkte"
            )
        if hasattr(self, "online_map") and hasattr(self, "map_layer") and self.map_layer.get() != "Schema":
            self.sync_online_map(fit=fit)
        else:
            if filtered and fit:
                self.fit_track_map()
            self.render_track_map()
        if filtered:
            self.show_track_point(len(filtered) - 1)
        elif hasattr(self, "track_info"):
            self.track_info.configure(text="Für den gewählten Zeitraum sind keine Trackpunkte vorhanden.")
        tool_log(
            "TRACK_FILTER_V216",
            mode=mode,
            detail=detail,
            shown=len(filtered),
            total=len(all_points),
        )
'''
        source = insert_before_method(source, "set_map_layer", helpers)

    def replace_update_track_points(_method: str) -> str:
        return r'''    def update_track_points(self) -> None:
        self.all_track_points = self._collect_track_history()
        self.track_points = list(self.all_track_points)
        self.track_view = None
        self._refresh_track_filter_controls()
        self.apply_track_time_filter(fit=True)
'''

    source = replace_method(source, "update_track_points", replace_update_track_points)

    # Show filtered count against the complete historical set in both online
    # map and schema toolbar status.
    def patch_sync_online_map(method: str) -> str:
        old = '''            suffix = "" if len(marker_indices) == total else f" · {len(marker_indices)} Marker"\n            self.map_point_count.configure(text=f"{total} Punkte · volle Route{suffix}")\n'''
        new = '''            suffix = "" if len(marker_indices) == total else f" · {len(marker_indices)} Marker"\n            history_total = len(getattr(self, "all_track_points", self.track_points))\n            count_text = f"{total}/{history_total}" if history_total != total else str(total)\n            self.map_point_count.configure(text=f"{count_text} Punkte · Route{suffix}")\n'''
        if old not in method:
            raise SystemExit("v2.1.6 map point-count anchor not found")
        return method.replace(old, new, 1)

    source = replace_method(source, "sync_online_map", patch_sync_online_map)

    required = (
        'APP_VERSION = "2.1.6"',
        'BLE_MANUAL_SELECTION_V216',
        'BLE_SINGLE_MANUAL_OVERRIDE_V216',
        'self.map_time_mode = ttk.Combobox',
        'values=("Alle", "Tag", "Zeitraum")',
        'def _collect_track_history(self)',
        'def apply_track_time_filter(',
        'TRACK_HISTORY_V216',
        'TRACK_FILTER_V216',
        'self.all_track_points = self._collect_track_history()',
    )
    for marker in required:
        if marker not in source:
            raise SystemExit(f"missing v2.1.6 marker: {marker}")
    return source


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "tools/JARNSEN_NODE_SERVICE_TOOL.py")
    target.write_text(patch(target.read_text(encoding="utf-8")), encoding="utf-8")
    print("Service tool v2.1.6: manual BLE selection + historical map time filters")


if __name__ == "__main__":
    main()
