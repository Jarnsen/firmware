"""v2.1.8: high-visibility START/ZIEL markers and conservative stationary-stop labels."""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "2.1.8"


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
    source = source.replace('APP_VERSION != "2.1.7"', 'APP_VERSION != "2.1.8"')
    source = source.replace("App-Version ist nicht v2.1.7", "App-Version ist nicht v2.1.8")

    if "    def _stationary_track_indices(self" not in source:
        helper = r'''    def _stationary_track_indices(self, points: list[dict[str, object]]) -> set[int]:
        """Return a small set of evidence-based stationary dwell points.

        TRACK_POINT breadcrumbs are movement-filtered. Therefore we only call a
        point STATIONAER when two chronological breadcrumbs are within 30 m and
        at least ten minutes apart. Nearby candidates are collapsed into one
        label so a parked vehicle does not cover the map in repeated markers.
        """
        if len(points) < 2:
            return set()
        candidates: list[int] = []
        for index in range(1, len(points)):
            previous = points[index - 1]
            current = points[index]
            try:
                previous_epoch = int(previous.get("epoch") or 0)
                current_epoch = int(current.get("epoch") or 0)
                if previous_epoch <= 0 or current_epoch <= previous_epoch:
                    continue
                dwell_seconds = current_epoch - previous_epoch
                if dwell_seconds < 600:
                    continue
                distance = geographic_distance_m(
                    float(previous["latitude"]),
                    float(previous["longitude"]),
                    float(current["latitude"]),
                    float(current["longitude"]),
                )
            except (KeyError, TypeError, ValueError):
                continue
            if distance <= 30.0:
                candidates.append(index)

        collapsed: list[int] = []
        for index in candidates:
            if not collapsed:
                collapsed.append(index)
                continue
            previous_index = collapsed[-1]
            try:
                distance = geographic_distance_m(
                    float(points[previous_index]["latitude"]),
                    float(points[previous_index]["longitude"]),
                    float(points[index]["latitude"]),
                    float(points[index]["longitude"]),
                )
                time_gap = abs(
                    int(points[index].get("epoch") or 0)
                    - int(points[previous_index].get("epoch") or 0)
                )
            except (KeyError, TypeError, ValueError):
                distance = 999999.0
                time_gap = 999999
            if distance <= 50.0 and time_gap <= 6 * 3600:
                collapsed[-1] = index
            else:
                collapsed.append(index)

        # Keep labels useful on long histories. START and ZIEL remain separate.
        return set(collapsed[-12:])
'''
        source = insert_before_method(source, "sync_online_map", helper)

    def replace_sync_online_map(_method: str) -> str:
        return r'''    def sync_online_map(self, fit: bool = False) -> None:
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

        stationary_indices = self._stationary_track_indices(self.track_points)
        marker_step = max(1, (total + 299) // 300)
        marker_indices = list(range(0, total, marker_step))
        marker_indices.extend(stationary_indices)
        marker_indices.extend((0, total - 1))
        marker_indices = sorted(set(index for index in marker_indices if 0 <= index < total))

        for index in marker_indices:
            point = self.track_points[index]
            marker_kwargs: dict[str, object] = {}
            if index == total - 1:
                # Intentionally very visible on light, dark, satellite and hybrid maps.
                text = "★ ZIEL · LETZTER PUNKT ★"
                marker_kwargs.update(
                    marker_color_circle="#FFD400",
                    marker_color_outside="#111111",
                    text_color="#111111",
                    font=("Segoe UI", 12, "bold"),
                )
            elif index == 0:
                text = "START"
                marker_kwargs.update(
                    marker_color_circle="#35C759",
                    marker_color_outside="#0B5D1E",
                    text_color="#0B3B16",
                    font=("Segoe UI", 10, "bold"),
                )
            elif index in stationary_indices:
                text = "STATIONÄR"
                marker_kwargs.update(
                    marker_color_circle="#4DA3FF",
                    marker_color_outside="#123D6A",
                    text_color="#102A43",
                    font=("Segoe UI", 10, "bold"),
                )
            elif total <= 80:
                text = str(index + 1)
            else:
                text = ""

            marker = self.online_map.set_marker(
                float(point["latitude"]),
                float(point["longitude"]),
                text=text,
                command=lambda _marker, selected=index: self.show_track_point(selected),
                **marker_kwargs,
            )
            marker.data = index

        if hasattr(self, "map_point_count"):
            suffix = "" if len(marker_indices) == total else f" · {len(marker_indices)} Marker"
            stationary_text = (
                f" · {len(stationary_indices)} stationär"
                if stationary_indices
                else ""
            )
            self.map_point_count.configure(
                text=f"{total} Punkte · volle Route{suffix}{stationary_text}"
            )
        if fit:
            self.fit_online_map()
        tool_log(
            "TRACK_MARKERS_V218",
            total=total,
            markers=len(marker_indices),
            stationary=len(stationary_indices),
        )
'''

    source = replace_method(source, "sync_online_map", replace_sync_online_map)

    required = (
        'APP_VERSION = "2.1.8"',
        'def _stationary_track_indices(self',
        '★ ZIEL · LETZTER PUNKT ★',
        'text = "START"',
        'text = "STATIONÄR"',
        'TRACK_MARKERS_V218',
        'marker_color_circle="#FFD400"',
    )
    missing = [item for item in required if item not in source]
    if missing:
        raise SystemExit("v2.1.8 validation failed: " + ", ".join(missing))
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v218.py <source.py>")
    path = Path(sys.argv[1])
    source = path.read_text(encoding="utf-8")
    patched = patch(source)
    path.write_text(patched, encoding="utf-8")
    print(f"Patched {path} to v{APP_VERSION}")


if __name__ == "__main__":
    main()
