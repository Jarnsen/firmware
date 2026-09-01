#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "FLASHER_VERSION.json"


def load_config() -> dict:
    with CONFIG.open("r", encoding="utf-8") as handle:
        cfg = json.load(handle)
    required = {"product", "major", "minor", "patch", "channel", "sequence"}
    missing = sorted(required.difference(cfg))
    if missing:
        raise SystemExit(f"FLASHER_VERSION.json missing keys: {', '.join(missing)}")
    return cfg


def resolve_version(cfg: dict) -> str:
    base = f"{int(cfg['major'])}.{int(cfg['minor'])}.{int(cfg['patch'])}"
    channel = str(cfg.get("channel") or "").strip().lower()
    if channel in {"", "final", "stable", "release"}:
        return base
    if channel not in {"alpha", "beta", "rc"}:
        raise SystemExit("FLASHER_VERSION.json channel must be alpha, beta, rc or final")
    sequence = max(1, int(cfg.get("sequence") or 1))
    return f"{base}-{channel}.{sequence}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve JARNSEN-MESH-FLASHER version")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    cfg = load_config()
    version = resolve_version(cfg)
    if args.as_json:
        print(json.dumps({
            "product": cfg["product"],
            "version": version,
            "channel": cfg["channel"],
            "sequence": cfg["sequence"],
            "policy": cfg.get("policy", "")
        }, indent=2))
    else:
        print(version)


if __name__ == "__main__":
    main()
