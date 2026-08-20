#!/usr/bin/env python3
"""Build a compact Jarnsen Tactical map package for Ludwigshafen-Friesenheim.

The script downloads selected OpenStreetMap ways through the public Overpass API,
simplifies them and writes a deterministic line-based .jtmap file. It uses only
Python's standard library.
"""

from __future__ import annotations

import argparse
import http.client
import json
import math
import pathlib
import ssl
import urllib.parse
from dataclasses import dataclass
from typing import Iterable, Sequence

OVERPASS_HOST = "overpass-api.de"
OVERPASS_PATH = "/api/interpreter"
# South, west, north, east. Includes Friesenheim and a small surrounding buffer.
DEFAULT_BBOX = (49.4750, 8.3850, 49.5205, 8.4495)

HIGHWAY_LEVEL = {
    "motorway": 1,
    "trunk": 1,
    "primary": 1,
    "secondary": 2,
    "tertiary": 2,
    "residential": 3,
    "unclassified": 3,
    "service": 4,
    "living_street": 4,
    "cycleway": 4,
    "footway": 5,
    "path": 5,
    "track": 5,
}


@dataclass(frozen=True)
class Point:
    lat: float
    lon: float


def perpendicular_distance(point: Point, start: Point, end: Point) -> float:
    if start == end:
        return math.hypot(point.lat - start.lat, point.lon - start.lon)
    dx = end.lon - start.lon
    dy = end.lat - start.lat
    numerator = abs(
        dy * point.lon - dx * point.lat + end.lon * start.lat - end.lat * start.lon
    )
    denominator = math.hypot(dx, dy)
    return numerator / denominator


def simplify(points: Sequence[Point], tolerance: float) -> list[Point]:
    if len(points) <= 2:
        return list(points)
    max_distance = 0.0
    index = 0
    for i in range(1, len(points) - 1):
        distance = perpendicular_distance(points[i], points[0], points[-1])
        if distance > max_distance:
            index = i
            max_distance = distance
    if max_distance <= tolerance:
        return [points[0], points[-1]]
    left = simplify(points[: index + 1], tolerance)
    right = simplify(points[index:], tolerance)
    return left[:-1] + right


def overpass_query(bbox: tuple[float, float, float, float]) -> str:
    south, west, north, east = bbox
    box = f"{south},{west},{north},{east}"
    return f"""
[out:json][timeout:90];
(
  way[highway]({box});
  way[railway=rail]({box});
  way[waterway]({box});
  way[natural=water]({box});
  way[leisure=park]({box});
);
out geom;
""".strip()


def fetch_osm(bbox: tuple[float, float, float, float]) -> dict:
    payload = urllib.parse.urlencode({"data": overpass_query(bbox)}).encode("utf-8")
    tls_context = ssl.create_default_context()
    connection = http.client.HTTPSConnection(  # nosemgrep: python.lang.security.audit.httpsconnection-detected.httpsconnection-detected
        OVERPASS_HOST, timeout=120, context=tls_context
    )
    try:
        connection.request(
            "POST",
            OVERPASS_PATH,
            body=payload,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "Jarnsen-Tactical-JTMap-Builder/0.1",
            },
        )
        response = connection.getresponse()
        if response.status != http.HTTPStatus.OK:
            raise RuntimeError(
                f"Overpass API returned HTTP {response.status} {response.reason}"
            )
        return json.loads(response.read().decode("utf-8"))
    finally:
        connection.close()


def layer_for(tags: dict[str, str]) -> tuple[str, int] | None:
    highway = tags.get("highway")
    if highway in HIGHWAY_LEVEL:
        return "road", HIGHWAY_LEVEL[highway]
    if tags.get("railway") == "rail":
        return "rail", 2
    if "waterway" in tags or tags.get("natural") == "water":
        return "water", 2
    if tags.get("leisure") == "park":
        return "park", 4
    return None


def quantize(point: Point, bbox: tuple[float, float, float, float]) -> tuple[int, int]:
    south, west, north, east = bbox
    x = round((point.lon - west) / (east - west) * 65535)
    y = round((north - point.lat) / (north - south) * 65535)
    return max(0, min(65535, x)), max(0, min(65535, y))


def iter_features(data: dict, bbox: tuple[float, float, float, float]) -> Iterable[str]:
    tolerance = 0.000025  # roughly 2-3 metres at this latitude
    for element in data.get("elements", []):
        tags = element.get("tags", {})
        layer = layer_for(tags)
        geometry = element.get("geometry") or []
        if layer is None or len(geometry) < 2:
            continue
        points = [Point(float(item["lat"]), float(item["lon"])) for item in geometry]
        points = simplify(points, tolerance)
        if len(points) < 2:
            continue
        kind, level = layer
        name = tags.get("name", "").replace("|", " ").replace("\n", " ")[:40]
        packed = ";".join(
            f"{x},{y}" for x, y in (quantize(point, bbox) for point in points)
        )
        yield f"F|{kind}|{level}|{name}|{packed}"


def write_jtmap(
    output: pathlib.Path, bbox: tuple[float, float, float, float], data: dict
) -> int:
    features = sorted(set(iter_features(data, bbox)))
    south, west, north, east = bbox
    lines = [
        "JTMAP|1",
        "NAME|Ludwigshafen-Friesenheim",
        "SOURCE|OpenStreetMap contributors",
        f"BBOX|{south:.6f}|{west:.6f}|{north:.6f}|{east:.6f}",
        "COORDS|U16_NORMALIZED",
        *features,
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return len(features)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the Friesenheim JTMap package from OpenStreetMap."
    )
    parser.add_argument(
        "--output", type=pathlib.Path, default=pathlib.Path("friesenheim-v1.jtmap")
    )
    args = parser.parse_args()

    data = fetch_osm(DEFAULT_BBOX)
    feature_count = write_jtmap(args.output, DEFAULT_BBOX, data)
    print(
        f"Created {args.output} with {feature_count} vector features ({args.output.stat().st_size} bytes)."
    )


if __name__ == "__main__":
    main()
