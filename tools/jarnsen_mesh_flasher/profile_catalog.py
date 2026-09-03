from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from profile_utils import ProfileSummary, summary_from_profile_file
from services import BOARD_PROFILES, PATHS


CATALOG_FILE = PATHS.profiles / "profile-catalog.json"


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _key(path: Path) -> str:
    try:
        return str(path.resolve()).casefold()
    except Exception:
        return str(path.absolute()).casefold()


def _load() -> dict[str, Any]:
    try:
        data = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("version", 1)
            data.setdefault("profiles", {})
            return data
    except Exception:
        pass
    return {"version": 1, "profiles": {}}


def _save(data: dict[str, Any]) -> None:
    PATHS.profiles.mkdir(parents=True, exist_ok=True)
    temp = CATALOG_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(CATALOG_FILE)


def register_profile(
    path: Path,
    board_key: str,
    summary: ProfileSummary | None = None,
    *,
    source: str = "manual",
) -> None:
    path = Path(path)
    if board_key not in BOARD_PROFILES:
        raise ValueError(f"Unknown board key: {board_key}")
    summary = summary or (summary_from_profile_file(path) if path.exists() else ProfileSummary())
    data = _load()
    profiles = data.setdefault("profiles", {})
    profiles[_key(path)] = {
        "path": str(path),
        "filename": path.name,
        "board_key": board_key,
        "board_label": BOARD_PROFILES[board_key]["label"],
        "role": summary.role,
        "long_name": summary.long_name,
        "short_name": summary.short_name,
        "source": source,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    _save(data)
    _emit(
        "PROFILE CATALOG REGISTER "
        f"file={path.name!r} board={board_key!r} role={summary.role!r} "
        f"long={summary.long_name!r} short={summary.short_name!r} source={source!r}"
    )


def entry_for_profile(path: Path) -> dict[str, Any] | None:
    data = _load()
    entry = data.get("profiles", {}).get(_key(Path(path)))
    return dict(entry) if isinstance(entry, dict) else None


def board_for_profile(path: Path) -> str | None:
    entry = entry_for_profile(path)
    if not entry:
        return None
    board_key = str(entry.get("board_key") or "")
    return board_key if board_key in BOARD_PROFILES else None


def copy_profile_assignment(source: Path, destination: Path) -> None:
    entry = entry_for_profile(source)
    if not entry:
        return
    board_key = str(entry.get("board_key") or "")
    if board_key not in BOARD_PROFILES:
        return
    summary = summary_from_profile_file(destination) if destination.exists() else ProfileSummary(
        long_name=str(entry.get("long_name") or ""),
        short_name=str(entry.get("short_name") or ""),
        role=str(entry.get("role") or ""),
    )
    register_profile(destination, board_key, summary, source=f"copy:{Path(source).name}")


def profiles_for_board(board_key: str) -> list[Path]:
    data = _load()
    found: list[tuple[str, Path]] = []
    for entry in data.get("profiles", {}).values():
        if not isinstance(entry, dict) or entry.get("board_key") != board_key:
            continue
        path = Path(str(entry.get("path") or ""))
        if not path.exists() or path.name == PATHS.active_profile.name:
            continue
        found.append((str(entry.get("updated_at") or ""), path))
    found.sort(key=lambda item: item[0], reverse=True)
    return [path for _stamp, path in found]


def profile_board_text(path: Path) -> str:
    board_key = board_for_profile(path)
    if not board_key:
        return "nicht zugeordnet"
    return str(BOARD_PROFILES[board_key]["label"])
