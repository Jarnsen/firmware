from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProfileSummary:
    long_name: str = ""
    short_name: str = ""
    role: str = ""

    def with_fallback(self, other: "ProfileSummary") -> "ProfileSummary":
        return ProfileSummary(
            long_name=self.long_name or other.long_name,
            short_name=self.short_name or other.short_name,
            role=self.role or other.role,
        )


def _clean(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1]
    return text.strip()


def summary_from_info_text(text: str) -> ProfileSummary:
    text = text or ""

    long_name = ""
    short_name = ""
    role = ""

    match = re.search(r'"longName"\s*:\s*"([^"]*)"', text)
    if match:
        long_name = match.group(1).strip()

    match = re.search(r'"shortName"\s*:\s*"([^"]*)"', text)
    if match:
        short_name = match.group(1).strip()

    owner = re.search(r"(?m)^Owner:\s*(.*?)\s*\((.*?)\)\s*$", text)
    if owner:
        long_name = long_name or owner.group(1).strip()
        short_name = short_name or owner.group(2).strip()

    match = re.search(r'"role"\s*:\s*"([^"]+)"', text)
    if match:
        role = match.group(1).strip()

    return ProfileSummary(long_name=long_name, short_name=short_name, role=role)


def _find_role(mapping: Any) -> str:
    if not isinstance(mapping, dict):
        return ""

    config = mapping.get("config")
    if isinstance(config, dict):
        device = config.get("device")
        if isinstance(device, dict) and device.get("role") is not None:
            return _clean(device.get("role"))

    device = mapping.get("device")
    if isinstance(device, dict) and device.get("role") is not None:
        return _clean(device.get("role"))

    return ""


def summary_from_profile_file(path: Path) -> ProfileSummary:
    text = path.read_text(encoding="utf-8", errors="replace")
    long_name = ""
    short_name = ""
    role = ""

    try:
        import yaml

        data = yaml.safe_load(text) or {}
        if isinstance(data, dict):
            long_name = _clean(
                data.get("owner")
                or data.get("long_name")
                or data.get("longName")
            )
            short_name = _clean(
                data.get("owner_short")
                or data.get("short_name")
                or data.get("shortName")
            )
            role = _find_role(data)
    except Exception:
        pass

    if not long_name:
        match = re.search(r"(?mi)^\s*owner\s*:\s*(.+?)\s*$", text)
        if match:
            long_name = _clean(match.group(1))

    if not short_name:
        match = re.search(r"(?mi)^\s*owner_short\s*:\s*(.+?)\s*$", text)
        if match:
            short_name = _clean(match.group(1))

    if not role:
        match = re.search(r"(?mi)^\s*role\s*:\s*(.+?)\s*$", text)
        if match:
            role = _clean(match.group(1))

    return ProfileSummary(long_name=long_name, short_name=short_name, role=role)


def format_summary(summary: ProfileSummary) -> str:
    long_name = summary.long_name or "–"
    short_name = summary.short_name or "–"
    role = summary.role or "–"
    return f"Long Name: {long_name}   ·   Short: {short_name}   ·   Rolle: {role}"
