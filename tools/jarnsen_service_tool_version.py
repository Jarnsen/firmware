#!/usr/bin/env python3
import argparse
import json
import subprocess
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "SERVICE_TOOL_VERSION.json"


def load_config():
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        cfg = json.load(handle)
    required = {"major", "minor", "patch", "channel", "start_date", "start_sequence", "timezone"}
    missing = sorted(required.difference(cfg))
    if missing:
        raise SystemExit(f"SERVICE_TOOL_VERSION.json missing keys: {', '.join(missing)}")
    return cfg


def commit_days(timezone: ZoneInfo, start: date):
    proc = subprocess.run(
        ["git", "log", "--format=%cI", "HEAD"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    days = set()
    for raw in proc.stdout.splitlines():
        raw = raw.strip()
        if not raw:
            continue
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone)
        if stamp.date() >= start:
            days.add(stamp.date())
    return sorted(days)


def resolve_version(cfg):
    base = f"v{int(cfg['major'])}.{int(cfg['minor'])}.{int(cfg['patch'])}"
    channel = str(cfg["channel"]).strip().lower()
    if channel in {"final", "stable", "release", ""}:
        return base, []
    if channel not in {"alpha", "beta", "rc"}:
        raise SystemExit("SERVICE_TOOL_VERSION.json channel must be alpha, beta, rc or final")

    start = date.fromisoformat(str(cfg["start_date"]))
    timezone = ZoneInfo(str(cfg["timezone"]))
    days = commit_days(timezone, start)
    if not days:
        raise SystemExit(f"No commits found on or after version start date {start.isoformat()}")

    sequence = int(cfg["start_sequence"]) + len(days) - 1
    if sequence < 1:
        raise SystemExit("Resolved prerelease sequence must be >= 1")
    return f"{base}-{channel}.{sequence}", days


def main():
    parser = argparse.ArgumentParser(description="Resolve the JARNSEN-SERVICE-TOOL daily prerelease version")
    parser.add_argument("--json", action="store_true", dest="as_json", help="print version details as JSON")
    args = parser.parse_args()

    cfg = load_config()
    version, days = resolve_version(cfg)
    if args.as_json:
        print(json.dumps({
            "version": version,
            "channel": cfg["channel"],
            "start_date": cfg["start_date"],
            "timezone": cfg["timezone"],
            "work_days": [item.isoformat() for item in days],
        }, indent=2))
    else:
        print(version)


if __name__ == "__main__":
    main()
