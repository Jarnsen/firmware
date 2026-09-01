#!/usr/bin/env python3
"""Resolve the next Jarnsen Service Tool prerelease version.

The prerelease sequence is based on successfully published, versioned EXE assets
in the rolling Service Tool release.  A failed or cancelled CI run therefore does
not consume a beta/alpha/rc number.  This module intentionally uses only the
Python standard library so it also works in the portable Windows CI runtime.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "SERVICE_TOOL_VERSION.json"
DEFAULT_REPOSITORY = "Jarnsen/firmware"


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        cfg = json.load(handle)
    required = {
        "major",
        "minor",
        "patch",
        "channel",
        "start_sequence",
        "release_tag",
        "asset_prefix",
    }
    missing = sorted(required.difference(cfg))
    if missing:
        raise SystemExit(f"SERVICE_TOOL_VERSION.json missing keys: {', '.join(missing)}")
    return cfg


def _request_json(url: str) -> dict[str, Any] | None:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Jarnsen-Service-Tool-Version-Resolver",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = str(os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=20.0) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # A missing rolling release is valid for the very first prerelease.
        if exc.code == 404:
            return None
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise SystemExit(f"GitHub release lookup failed: HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise SystemExit(f"GitHub release lookup failed: {type(exc).__name__}: {exc}") from exc


def published_sequences(cfg: dict[str, Any]) -> list[int]:
    repository = str(os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPOSITORY).strip()
    if "/" not in repository:
        raise SystemExit("GITHUB_REPOSITORY must be in owner/repository form")
    tag = str(cfg["release_tag"]).strip()
    encoded_tag = urllib.parse.quote(tag, safe="")
    url = f"https://api.github.com/repos/{repository}/releases/tags/{encoded_tag}"
    release = _request_json(url)
    if not release:
        return []

    base = f"{int(cfg['major'])}.{int(cfg['minor'])}.{int(cfg['patch'])}"
    channel = str(cfg["channel"]).strip().lower()
    prefix = re.escape(str(cfg["asset_prefix"]).strip())
    pattern = re.compile(
        rf"^{prefix}-v{re.escape(base)}-{re.escape(channel)}\.(\d+)\.exe$",
        re.IGNORECASE,
    )
    sequences: set[int] = set()
    for asset in release.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        match = pattern.match(str(asset.get("name") or ""))
        if match:
            sequences.add(int(match.group(1)))
    return sorted(sequences)


def resolve_version(cfg: dict[str, Any]) -> tuple[str, list[int], int | None]:
    base = f"{int(cfg['major'])}.{int(cfg['minor'])}.{int(cfg['patch'])}"
    channel = str(cfg["channel"]).strip().lower()
    if channel in {"final", "stable", "release", ""}:
        return base, [], None
    if channel not in {"alpha", "beta", "rc"}:
        raise SystemExit("SERVICE_TOOL_VERSION.json channel must be alpha, beta, rc or final")

    published = published_sequences(cfg)
    start = max(1, int(cfg["start_sequence"]))
    sequence = max(published, default=start - 1) + 1
    if sequence < start:
        sequence = start
    return f"{base}-{channel}.{sequence}", published, sequence


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resolve the next JARNSEN-SERVICE-TOOL successful-publish prerelease version"
    )
    parser.add_argument("--json", action="store_true", dest="as_json", help="print version details as JSON")
    args = parser.parse_args()

    cfg = load_config()
    version, published, sequence = resolve_version(cfg)
    if args.as_json:
        print(
            json.dumps(
                {
                    "version": version,
                    "channel": cfg["channel"],
                    "release_tag": cfg["release_tag"],
                    "published_sequences": published,
                    "next_sequence": sequence,
                    "policy": "successful-publish",
                },
                indent=2,
            )
        )
    else:
        print(version)


if __name__ == "__main__":
    main()
