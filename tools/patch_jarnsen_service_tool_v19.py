"""v1.9 release marker and position-map validation for the shared Service Tool.

Runs after the v1.8 patcher. The position-map implementation lives in the shared
source so both Tracker V1.1 and Heltec V3 use exactly the same parser and UI.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "1.9.0"


def patch(source: str) -> str:
    source = re.sub(
        r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{APP_VERSION}"', source, count=1
    )
    source = source.replace('APP_VERSION != "1.8.0"', 'APP_VERSION != "1.9.0"')
    source = source.replace(
        "App-Version ist nicht v1.8.0", "App-Version ist nicht v1.9.0"
    )

    required = (
        'APP_VERSION = "1.9.0"',
        "def parse_track_points(",
        "def update_track_points(self)",
        "def fit_track_map(self)",
        "def zoom_track_map(self, factor: float)",
        "def render_track_map(self)",
        "Positionskarte",
        "Positionsverlauf wird nicht korrekt gelesen",
        "def reset_transfer_progress(self)",
    )
    for marker in required:
        if marker not in source:
            raise SystemExit(f"missing v1.9 marker: {marker}")
    return source


def main() -> None:
    target = Path(
        sys.argv[1] if len(sys.argv) > 1 else "tools/JARNSEN_NODE_SERVICE_TOOL.py"
    )
    source = target.read_text(encoding="utf-8")
    target.write_text(patch(source), encoding="utf-8")
    print("Service tool patched to v1.9.0: movement-filtered position map")


if __name__ == "__main__":
    main()
