#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
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


def resolve_sequence(cfg: dict) -> int:
    fallback = max(1, int(cfg.get("sequence") or 1))
    mode = str(cfg.get("sequence_mode") or "manual").strip().lower()
    if mode in {"", "manual", "fixed"}:
        return fallback
    if mode != "github_run":
        raise SystemExit("FLASHER_VERSION.json sequence_mode must be manual or github_run")

    run_text = str(os.environ.get("GITHUB_RUN_NUMBER") or "").strip()
    if not run_text:
        return fallback
    try:
        run_number = int(run_text)
    except ValueError as exc:
        raise SystemExit("GITHUB_RUN_NUMBER must be an integer") from exc

    base_run = int(cfg.get("run_number_base") or 0)
    base_sequence = max(1, int(cfg.get("sequence_base") or fallback))
    if base_run < 1:
        raise SystemExit("FLASHER_VERSION.json run_number_base must be >= 1 for github_run mode")
    if run_number < base_run:
        return fallback
    return base_sequence + (run_number - base_run)


def resolve_version(cfg: dict) -> str:
    base = f"{int(cfg['major'])}.{int(cfg['minor'])}.{int(cfg['patch'])}"
    channel = str(cfg.get("channel") or "").strip().lower()
    if channel in {"", "final", "stable", "release"}:
        return base
    if channel not in {"alpha", "beta", "rc"}:
        raise SystemExit("FLASHER_VERSION.json channel must be alpha, beta, rc or final")
    sequence = resolve_sequence(cfg)
    return f"{base}-{channel}.{sequence}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve JARNSEN-MESH-FLASHER version")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()
    cfg = load_config()
    version = resolve_version(cfg)
    sequence = resolve_sequence(cfg)
    if args.as_json:
        print(json.dumps({
            "product": cfg["product"],
            "version": version,
            "channel": cfg["channel"],
            "sequence": sequence,
            "sequence_mode": cfg.get("sequence_mode", "manual"),
            "run_number_base": cfg.get("run_number_base"),
            "policy": cfg.get("policy", "")
        }, indent=2))
    else:
        print(version)


if __name__ == "__main__":
    main()
