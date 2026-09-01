#!/usr/bin/env python3
"""Resolve Service Tool prerelease version from the last successful release.

Failed builds keep the same prerelease number. Once a build succeeds and publishes
jarnsen-service-tool-latest, the next source change advances beta/alpha/rc by one.
Uses only the Python standard library so portable CI Python needs no tzdata.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "SERVICE_TOOL_VERSION.json"


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        cfg = json.load(handle)
    required = {"major", "minor", "patch", "channel", "start_sequence", "release_tag"}
    missing = sorted(required.difference(cfg))
    if missing:
        raise SystemExit(f"SERVICE_TOOL_VERSION.json missing keys: {', '.join(missing)}")
    return cfg


def _released_sequence(cfg: dict[str, Any]) -> int | None:
    repository = str(os.environ.get("GITHUB_REPOSITORY") or "").strip()
    if not repository:
        return None
    tag = str(cfg.get("release_tag") or "jarnsen-service-tool-latest").strip()
    url = f"https://api.github.com/repos/{repository}/releases/tags/{tag}"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "jarnsen-service-tool-version"}
    token = str(os.environ.get("GITHUB_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=10) as response:
            release = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError):
        return None

    base = f"{int(cfg['major'])}.{int(cfg['minor'])}.{int(cfg['patch'])}"
    channel = str(cfg["channel"]).strip().lower()
    text = " ".join(str(release.get(key) or "") for key in ("name", "tag_name", "body"))
    match = re.search(rf"v?{re.escape(base)}-{re.escape(channel)}\.(\d+)\b", text, re.IGNORECASE)
    return int(match.group(1)) if match else None


def resolve_version(cfg: dict[str, Any]) -> tuple[str, int | None, int | None]:
    base = f"{int(cfg['major'])}.{int(cfg['minor'])}.{int(cfg['patch'])}"
    channel = str(cfg["channel"]).strip().lower()
    if channel in {"final", "stable", "release", ""}:
        return base, None, None
    if channel not in {"alpha", "beta", "rc"}:
        raise SystemExit("SERVICE_TOOL_VERSION.json channel must be alpha, beta, rc or final")

    floor = max(1, int(cfg["start_sequence"]))
    released = _released_sequence(cfg)
    # The configured floor is the currently active prerelease. A successful
    # published build at or above that floor advances the next source build.
    sequence = floor if released is None or released < floor else released + 1
    return f"{base}-{channel}.{sequence}", sequence, released


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve JARNSEN-SERVICE-TOOL prerelease version")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    cfg = load_config()
    version, sequence, released = resolve_version(cfg)
    if args.as_json:
        print(json.dumps({
            "version": version,
            "channel": cfg["channel"],
            "sequence": sequence,
            "last_successful_release_sequence": released,
            "floor_sequence": int(cfg["start_sequence"]),
            "policy": "advance-after-successful-published-release",
        }, indent=2))
    else:
        print(version)


if __name__ == "__main__":
    main()
