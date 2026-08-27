"""v2.1.7: satellite/hybrid map layers and jump to latest visible track point."""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "2.1.7"


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
    source = source.replace('APP_VERSION != "2.1.6"', 'APP_VERSION != "2.1.7"')
    source = source.replace("App-Version ist nicht v2.1.6", "App-Version ist nicht v2.1.7")

    def patch_workflow_ui(method: str) -> str:
        old_values = '            values=("OpenStreetMap", "Topografisch", "Schema") if ONLINE_MAP_AVAILABLE else ("Schema",),\n'
        new_values = '            values=("OpenStreetMap", "Topografisch", "Satellit", "Hybrid", "Schema") if ONLINE_MAP_AVAILABLE else ("Schema",),\n'
        if new_values not in method:
            if old_values not in method:
                raise SystemExit("v2.1.7 map layer values anchor not found")
            method = method.replace(old_values, new_values, 1)

        if 'text="Zum letzten Punkt"' not in method:
            anchor = '        self.map_point_count.pack(side="left")\n'
            addition = '''        self.map_point_count.pack(side="left")\n        ttk.Button(\n            self.map_toolbar,\n            text="Zum letzten Punkt",\n            command=self.jump_to_last_track_point,\n        ).pack(side="left", padx=(10, 0))\n'''
            if anchor not in method:
                raise SystemExit("v2.1.7 last-point button anchor not found")
            method = method.replace(anchor, addition, 1)
        return method

    source = replace_method(source, "_install_workflow_ui", patch_workflow_ui)

    def replace_set_map_layer(_method: str) -> str:
        return r'''    def set_map_layer(self, _event: object | None = None) -> None:
        layer = self.map_layer.get() if hasattr(self, "map_layer") else "Schema"
        if layer == "Schema" or not ONLINE_MAP_AVAILABLE or not hasattr(self, "online_map"):
            if hasattr(self, "online_map"):
                self.online_map.pack_forget()
            if hasattr(self, "track_canvas") and not self.track_canvas.winfo_ismapped():
                self.track_canvas.pack(fill="both", expand=True, before=self.track_info)
            if hasattr(self, "map_attribution"):
                self.map_attribution.configure(text="Schema · offline")
            self.render_track_map()
            tool_log("MAP_LAYER_V217", layer="Schema")
            return

        if hasattr(self, "track_canvas"):
            self.track_canvas.pack_forget()
        if not self.online_map.winfo_ismapped():
            self.online_map.pack(fill="both", expand=True, before=self.track_info)

        # TkinterMapView caches rendered tiles only by z/x/y. Always set the
        # overlay first and then call set_tile_server(), because set_tile_server
        # clears that cache. This prevents stale hybrid labels after a layer
        # switch and cleanly removes the overlay for non-hybrid layers.
        if layer == "Hybrid":
            self.online_map.set_overlay_tile_server(
                "https://who.maptiles.arcgis.com/arcgis/rest/services/World_Hybrid_Overlay/MapServer/tile/{z}/{y}/{x}"
            )
            self.online_map.set_tile_server(
                "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                max_zoom=19,
            )
            self.map_attribution.configure(text="Esri World Imagery · Hybrid-Referenz")
        else:
            self.online_map.set_overlay_tile_server(None)
            if layer == "Satellit":
                self.online_map.set_tile_server(
                    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                    max_zoom=19,
                )
                self.map_attribution.configure(text="Esri World Imagery")
            elif layer == "Topografisch":
                self.online_map.set_tile_server(
                    "https://a.tile.opentopomap.org/{z}/{x}/{y}.png", max_zoom=17
                )
                self.map_attribution.configure(
                    text="© OpenStreetMap-Mitwirkende · OpenTopoMap (CC-BY-SA)"
                )
            else:
                self.online_map.set_tile_server(
                    "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png", max_zoom=19
                )
                self.map_attribution.configure(text="© OpenStreetMap-Mitwirkende")

        self.sync_online_map(fit=True)
        tool_log("MAP_LAYER_V217", layer=layer)
'''

    source = replace_method(source, "set_map_layer", replace_set_map_layer)

    if "    def jump_to_last_track_point(self)" not in source:
        helper = r'''    def jump_to_last_track_point(self) -> None:
        points = list(getattr(self, "track_points", []))
        if not points:
            if hasattr(self, "track_info"):
                self.track_info.configure(
                    text="Für den aktuellen Kartenfilter sind keine Trackpunkte vorhanden."
                )
            tool_log("TRACK_JUMP_LAST_V217", result="no-points")
            return

        index = len(points) - 1
        point = points[index]
        self.show_track_point(index)
        layer = self.map_layer.get() if hasattr(self, "map_layer") else "Schema"
        if (
            ONLINE_MAP_AVAILABLE
            and layer != "Schema"
            and hasattr(self, "online_map")
        ):
            latitude = float(point["latitude"])
            longitude = float(point["longitude"])
            self.online_map.set_position(latitude, longitude)
            max_zoom = int(getattr(self.online_map, "max_zoom", 19) or 19)
            self.online_map.set_zoom(min(18, max_zoom))
        tool_log(
            "TRACK_JUMP_LAST_V217",
            result="ok",
            layer=layer,
            index=index,
            epoch=int(point.get("epoch") or 0),
        )
'''
        source = insert_before_method(source, "fit_online_map", helper)

    required = (
        'APP_VERSION = "2.1.7"',
        '"Satellit", "Hybrid", "Schema"',
        'text="Zum letzten Punkt"',
        'def jump_to_last_track_point(self)',
        'World_Imagery/MapServer/tile/{z}/{y}/{x}',
        'World_Hybrid_Overlay/MapServer/tile/{z}/{y}/{x}',
        'MAP_LAYER_V217',
        'TRACK_JUMP_LAST_V217',
    )
    missing = [item for item in required if item not in source]
    if missing:
        raise SystemExit("v2.1.7 validation failed: " + ", ".join(missing))
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v217.py <source.py>")
    path = Path(sys.argv[1])
    source = path.read_text(encoding="utf-8")
    patched = patch(source)
    path.write_text(patched, encoding="utf-8")
    print(f"Patched {path} to v{APP_VERSION}")


if __name__ == "__main__":
    main()
