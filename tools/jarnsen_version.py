#!/usr/bin/env python3
import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "VERSION.json"


def load_config():
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        cfg = json.load(handle)
    required = {"major", "minor", "patch", "channel", "start_sequence"}
    missing = sorted(required.difference(cfg))
    if missing:
        raise SystemExit(f"VERSION.json missing keys: {', '.join(missing)}")
    return cfg


def published_sequences(prefix: str):
    proc = subprocess.run(
        ["git", "tag", "--list", f"{prefix}*"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    sequences = set()
    for raw in proc.stdout.splitlines():
        tag = raw.strip()
        if not tag.startswith(prefix):
            continue
        suffix = tag[len(prefix):]
        if not suffix.isdigit():
            continue
        sequence = int(suffix)
        if sequence >= 1:
            sequences.add(sequence)
    return sorted(sequences)


def resolve_version(cfg):
    base = f"v{int(cfg['major'])}.{int(cfg['minor'])}.{int(cfg['patch'])}"
    channel = str(cfg["channel"]).strip().lower()
    if channel in {"final", "stable", "release", ""}:
        return base, []
    if channel not in {"alpha", "beta", "rc"}:
        raise SystemExit("VERSION.json channel must be alpha, beta, rc or final")

    start_sequence = int(cfg["start_sequence"])
    if start_sequence < 1:
        raise SystemExit("VERSION.json start_sequence must be >= 1")

    prefix = f"{base}-{channel}."
    sequences = published_sequences(prefix)
    previous = max(sequences, default=start_sequence - 1)
    sequence = max(start_sequence, previous + 1)
    return f"{prefix}{sequence}", sequences


def main():
    parser = argparse.ArgumentParser(description="Resolve the next JARNSEN-MESH prerelease candidate")
    parser.add_argument("--json", action="store_true", dest="as_json", help="print version details as JSON")
    args = parser.parse_args()

    cfg = load_config()
    version, sequences = resolve_version(cfg)
    if args.as_json:
        print(json.dumps({
            "version": version,
            "channel": cfg["channel"],
            "start_sequence": cfg["start_sequence"],
            "published_sequences": sequences,
            "policy": cfg.get("policy", ""),
        }, indent=2))
    else:
        print(version)


if __name__ == "__main__":
    main()
