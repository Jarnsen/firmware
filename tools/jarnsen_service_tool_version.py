#!/usr/bin/env python3
"""Resolve the Jarnsen Service Tool prerelease version from the commit calendar day.

This mirrors the JARNSEN-MESH daily-version idea: the product owns a SemVer base,
channel, start date, start sequence and timezone.  Every commit on the same local
calendar day resolves to the same prerelease number; a later calendar day advances
the sequence deterministically.  Failed builds and reruns therefore never consume
extra version numbers.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "SERVICE_TOOL_VERSION.json"


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        cfg = json.load(handle)
    required = {
        "major",
        "minor",
        "patch",
        "channel",
        "start_date",
        "start_sequence",
        "timezone",
    }
    missing = sorted(required.difference(cfg))
    if missing:
        raise SystemExit(f"SERVICE_TOOL_VERSION.json missing keys: {', '.join(missing)}")
    return cfg


def _parse_datetime(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise SystemExit(f"Commit timestamp has no timezone: {value}")
    return parsed


def commit_datetime() -> datetime:
    explicit = str(os.environ.get("JARNSEN_VERSION_DATETIME") or "").strip()
    if explicit:
        return _parse_datetime(explicit)

    sha = str(os.environ.get("GITHUB_SHA") or "HEAD").strip() or "HEAD"
    try:
        result = subprocess.run(
            ["git", "show", "-s", "--format=%cI", sha],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"Unable to resolve commit timestamp for {sha}: {exc}") from exc
    value = result.stdout.strip()
    if not value:
        raise SystemExit(f"Git returned no commit timestamp for {sha}")
    return _parse_datetime(value)


def resolve_version(cfg: dict[str, Any], when: datetime | None = None) -> tuple[str, date, int | None]:
    base = f"{int(cfg['major'])}.{int(cfg['minor'])}.{int(cfg['patch'])}"
    channel = str(cfg["channel"]).strip().lower()
    if channel in {"final", "stable", "release", ""}:
        local_day = (when or commit_datetime()).astimezone(ZoneInfo(str(cfg["timezone"]))).date()
        return base, local_day, None
    if channel not in {"alpha", "beta", "rc"}:
        raise SystemExit("SERVICE_TOOL_VERSION.json channel must be alpha, beta, rc or final")

    try:
        tz = ZoneInfo(str(cfg["timezone"]))
    except Exception as exc:
        raise SystemExit(f"Invalid timezone in SERVICE_TOOL_VERSION.json: {cfg['timezone']}") from exc
    try:
        start_day = date.fromisoformat(str(cfg["start_date"]))
    except ValueError as exc:
        raise SystemExit("SERVICE_TOOL_VERSION.json start_date must be YYYY-MM-DD") from exc

    local_day = (when or commit_datetime()).astimezone(tz).date()
    delta_days = (local_day - start_day).days
    if delta_days < 0:
        raise SystemExit(
            f"Commit day {local_day.isoformat()} precedes configured start_date {start_day.isoformat()}"
        )
    start_sequence = max(1, int(cfg["start_sequence"]))
    sequence = start_sequence + delta_days
    return f"{base}-{channel}.{sequence}", local_day, sequence


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve JARNSEN-SERVICE-TOOL day-based prerelease version")
    parser.add_argument("--json", action="store_true", dest="as_json", help="print version details as JSON")
    parser.add_argument("--datetime", help="override commit timestamp with an ISO-8601 timestamp")
    args = parser.parse_args()

    cfg = load_config()
    when = _parse_datetime(args.datetime) if args.datetime else None
    version, local_day, sequence = resolve_version(cfg, when)
    if args.as_json:
        print(
            json.dumps(
                {
                    "version": version,
                    "channel": cfg["channel"],
                    "commit_day": local_day.isoformat(),
                    "start_date": cfg["start_date"],
                    "start_sequence": int(cfg["start_sequence"]),
                    "timezone": cfg["timezone"],
                    "sequence": sequence,
                    "policy": "commit-day",
                },
                indent=2,
            )
        )
    else:
        print(version)


if __name__ == "__main__":
    main()
