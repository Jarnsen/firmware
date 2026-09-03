#!/usr/bin/env python3
"""Publish a JARNSEN-MESH prerelease using the GitHub REST API.

This intentionally avoids depending on the GitHub CLI on self-hosted runners.
The script creates the release/tag only after CI has verified the complete
firmware set, uploads every asset, and removes a partial release/tag if an
upload fails so the prerelease version is not consumed.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API_ROOT = "https://api.github.com"
API_VERSION = "2022-11-28"


class GitHubApiError(RuntimeError):
    pass


def request(token: str, method: str, url: str, *, data: bytes | None = None, content_type: str | None = None,
            allow_not_found: bool = False) -> tuple[int, bytes]:
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": API_VERSION,
        "User-Agent": "jarnsen-mesh-release-publisher",
    }
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if allow_not_found and exc.code == 404:
            return exc.code, body.encode()
        raise GitHubApiError(f"GitHub API {method} {url} failed with HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise GitHubApiError(f"GitHub API {method} {url} failed: {exc}") from exc


def api_url(repo: str, suffix: str) -> str:
    return f"{API_ROOT}/repos/{repo}/{suffix.lstrip('/')}"


def tag_exists(token: str, repo: str, version: str) -> bool:
    encoded = urllib.parse.quote(version, safe="")
    status, _ = request(token, "GET", api_url(repo, f"git/ref/tags/{encoded}"), allow_not_found=True)
    return status != 404


def delete_partial(token: str, repo: str, release_id: int | None, version: str) -> None:
    if release_id is not None:
        try:
            request(token, "DELETE", api_url(repo, f"releases/{release_id}"))
            print(f"Removed partial release id {release_id}", file=sys.stderr)
        except GitHubApiError as exc:
            print(f"Warning: could not remove partial release: {exc}", file=sys.stderr)

    encoded = urllib.parse.quote(version, safe="")
    try:
        status, _ = request(token, "DELETE", api_url(repo, f"git/refs/tags/{encoded}"), allow_not_found=True)
        if status != 404:
            print(f"Removed partial tag {version}", file=sys.stderr)
    except GitHubApiError as exc:
        print(f"Warning: could not remove partial tag: {exc}", file=sys.stderr)


def publish(args: argparse.Namespace) -> None:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise GitHubApiError("GH_TOKEN/GITHUB_TOKEN is unavailable")

    assets_dir = Path(args.assets_dir)
    notes_file = Path(args.notes_file)
    if not assets_dir.is_dir():
        raise GitHubApiError(f"Assets directory does not exist: {assets_dir}")
    assets = sorted(path for path in assets_dir.iterdir() if path.is_file())
    if not assets:
        raise GitHubApiError(f"No release assets found in {assets_dir}")
    if not notes_file.is_file():
        raise GitHubApiError(f"Release notes file does not exist: {notes_file}")
    if tag_exists(token, args.repo, args.version):
        raise GitHubApiError(f"Release tag already exists: {args.version}")

    payload = {
        "tag_name": args.version,
        "target_commitish": args.target,
        "name": args.title,
        "body": notes_file.read_text(encoding="utf-8"),
        "draft": False,
        "prerelease": "-" in args.version,
    }

    release_id: int | None = None
    try:
        _, response = request(
            token,
            "POST",
            api_url(args.repo, "releases"),
            data=json.dumps(payload).encode("utf-8"),
            content_type="application/json",
        )
        release = json.loads(response.decode("utf-8"))
        release_id = int(release["id"])
        upload_url = str(release["upload_url"]).split("{", 1)[0]
        print(f"Created {args.version} release id {release_id}; uploading {len(assets)} asset(s)")

        for asset in assets:
            content_type = mimetypes.guess_type(asset.name)[0] or "application/octet-stream"
            name = urllib.parse.quote(asset.name, safe="")
            data = asset.read_bytes()
            request(token, "POST", f"{upload_url}?name={name}", data=data, content_type=content_type)
            print(f"Uploaded {asset.name} ({len(data)} bytes)")
    except Exception:
        delete_partial(token, args.repo, release_id, args.version)
        raise

    print(f"Published {args.version} with {len(assets)} asset(s)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--notes-file", required=True)
    parser.add_argument("--assets-dir", required=True)
    return parser.parse_args()


if __name__ == "__main__":
    try:
        publish(parse_args())
    except Exception as exc:
        print(f"Release publication failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
