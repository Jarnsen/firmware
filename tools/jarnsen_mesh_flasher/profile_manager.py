from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import customtkinter as ctk
from tkinter import messagebox

from profile_catalog import (
    board_for_profile,
    copy_profile_assignment,
    profile_board_text,
    register_profile,
)
from profile_utils import ProfileSummary, format_summary, summary_from_info_text, summary_from_profile_file


PROFILE_SUFFIXES = {".yaml", ".yml", ".cfg"}
LEGACY_MASTER_RE = re.compile(r"^master-(\d{8}-\d{6})\.(?:ya?ml|cfg)$", re.IGNORECASE)


@dataclass(frozen=True)
class ProfileRecord:
    path: Path
    summary: ProfileSummary
    board_key: str | None
    modified: datetime


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _filename_part(value: str, fallback: str) -> str:
    text = (value or "").strip() or fallback
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", text)
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-+", "-", text).strip(" .-_")
    return text[:72] or fallback


def stable_profile_name(summary: ProfileSummary, suffix: str = ".yaml") -> str:
    """Normal profile name: ROLE__LONG-NAME__SHORT.yaml (no timestamp)."""
    role = _filename_part(summary.role, "ROLLE-UNBEKANNT")
    long_name = _filename_part(summary.long_name, "LONG-UNBEKANNT")
    short_name = _filename_part(summary.short_name, "SHORT-UNBEKANNT")
    ext = suffix.lower() if suffix.startswith(".") else f".{suffix.lower()}"
    return f"{role}__{long_name}__{short_name}{ext}"


def archive_name(path: Path, *, stamp: str | None = None) -> str:
    stamp = stamp or datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{path.stem}__{stamp}{path.suffix.lower()}"


def _unique_archive_path(archive_dir: Path, filename: str) -> Path:
    candidate = archive_dir / filename
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    counter = 2
    while True:
        candidate = archive_dir / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def archive_existing(path: Path, archive_dir: Path, *, stamp: str | None = None) -> Path | None:
    path = Path(path)
    if not path.exists():
        return None
    archive_dir.mkdir(parents=True, exist_ok=True)
    destination = _unique_archive_path(archive_dir, archive_name(path, stamp=stamp))
    shutil.move(str(path), str(destination))
    _emit(f"PROFILE ARCHIVE OLD current={path.name!r} archived={destination.name!r}")
    return destination


def store_exported_profile(
    raw_path: Path,
    summary: ProfileSummary,
    board_key: str | None,
    services: Any,
    *,
    source: str,
) -> Path:
    """Promote a raw master export to the stable visible profile and archive the previous revision."""
    raw_path = Path(raw_path)
    profiles = services.PATHS.profiles
    archive_dir = profiles / "archive"
    profiles.mkdir(parents=True, exist_ok=True)
    archive_dir.mkdir(parents=True, exist_ok=True)

    target = profiles / stable_profile_name(summary, raw_path.suffix or ".yaml")
    if target.exists() and target.resolve() != raw_path.resolve():
        archive_existing(target, archive_dir)

    if raw_path.resolve() != target.resolve():
        if target.exists():
            target.unlink()
        shutil.move(str(raw_path), str(target))

    shutil.copy2(target, services.PATHS.active_profile)

    if board_key in services.BOARD_PROFILES:
        register_profile(target, board_key, summary, source=source)
        register_profile(
            services.PATHS.active_profile,
            board_key,
            summary,
            source=f"active-from:{target.name}",
        )

    _emit(
        "PROFILE STORE CURRENT "
        f"file={target.name!r} board={board_key!r} role={summary.role!r} "
        f"long={summary.long_name!r} short={summary.short_name!r}"
    )
    return target


def migrate_internal_active_profile(services: Any) -> None:
    """Move legacy active-profile.yaml to the hidden/internal .active-profile.yaml working copy."""
    profiles = services.PATHS.profiles
    old = profiles / "active-profile.yaml"
    new = services.PATHS.active_profile
    if old == new:
        return
    try:
        if old.exists() and not new.exists():
            shutil.move(str(old), str(new))
            _emit(f"PROFILE MIGRATE ACTIVE old={old.name!r} new={new.name!r}")
        elif old.exists() and new.exists():
            old.unlink()
            _emit(f"PROFILE MIGRATE ACTIVE removed-legacy={old.name!r}")
    except Exception as exc:
        _emit(f"PROFILE MIGRATE ACTIVE ERROR type={type(exc).__name__} message={exc}")


def migrate_legacy_master_profiles(services: Any) -> None:
    """Convert unambiguous master-YYYY... exports to one stable current file plus archive history."""
    profiles = services.PATHS.profiles
    archive_dir = profiles / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    groups: dict[str, list[tuple[Path, ProfileSummary, str | None, str]]] = {}
    for path in profiles.iterdir():
        if not path.is_file():
            continue
        match = LEGACY_MASTER_RE.match(path.name)
        if not match:
            continue
        try:
            summary = summary_from_profile_file(path)
        except Exception:
            continue
        # Never guess a permanent filename from incomplete metadata.
        if not (summary.role and summary.long_name and summary.short_name):
            _emit(f"PROFILE MIGRATE LEGACY SKIP incomplete={path.name!r}")
            continue
        stable = stable_profile_name(summary, path.suffix)
        groups.setdefault(stable.casefold(), []).append(
            (path, summary, board_for_profile(path), match.group(1))
        )

    for _key, items in groups.items():
        items.sort(key=lambda item: item[3], reverse=True)
        newest_path, newest_summary, newest_board, newest_stamp = items[0]
        target = profiles / stable_profile_name(newest_summary, newest_path.suffix)

        if not target.exists():
            shutil.move(str(newest_path), str(target))
            if newest_board in services.BOARD_PROFILES:
                register_profile(target, newest_board, newest_summary, source="legacy-migration")
            _emit(f"PROFILE MIGRATE LEGACY CURRENT old={newest_path.name!r} new={target.name!r}")
        else:
            destination = _unique_archive_path(
                archive_dir,
                archive_name(target, stamp=newest_stamp),
            )
            shutil.move(str(newest_path), str(destination))
            _emit(f"PROFILE MIGRATE LEGACY ARCHIVE old={newest_path.name!r} new={destination.name!r}")

        for path, _summary, _board, stamp in items[1:]:
            destination = _unique_archive_path(
                archive_dir,
                f"{target.stem}__{stamp}{path.suffix.lower()}",
            )
            shutil.move(str(path), str(destination))
            _emit(f"PROFILE MIGRATE LEGACY ARCHIVE old={path.name!r} new={destination.name!r}")


def list_profile_records(services: Any, board_key: str | None = None) -> list[ProfileRecord]:
    records: list[ProfileRecord] = []
    internal_names = {
        services.PATHS.active_profile.name.casefold(),
        "active-profile.yaml",
    }
    for path in services.PATHS.profiles.iterdir():
        if not path.is_file() or path.suffix.lower() not in PROFILE_SUFFIXES:
            continue
        if path.name.casefold() in internal_names or path.name.startswith("."):
            continue
        try:
            summary = summary_from_profile_file(path)
        except Exception as exc:
            _emit(f"PROFILE MANAGER SKIP file={path.name!r} error={exc}")
            continue
        assigned = board_for_profile(path)
        if board_key and assigned and assigned != board_key:
            continue
        try:
            modified = datetime.fromtimestamp(path.stat().st_mtime)
        except Exception:
            modified = datetime.fromtimestamp(0)
        records.append(ProfileRecord(path, summary, assigned, modified))

    records.sort(key=lambda item: item.modified, reverse=True)
    return records


def open_profile_folder(services: Any) -> None:
    folder = services.PATHS.profiles
    folder.mkdir(parents=True, exist_ok=True)
    try:
        if os.name == "nt":
            os.startfile(str(folder))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
    except Exception as exc:
        messagebox.showerror("Profilordner", f"Profilordner konnte nicht geöffnet werden.\n\n{exc}")


def _board_label(services: Any, board_key: str | None) -> str:
    if board_key in services.BOARD_PROFILES:
        return str(services.BOARD_PROFILES[board_key]["label"])
    return "nicht zugeordnet"


def select_profile_dialog(
    root: Any,
    services: Any,
    *,
    board_key: str | None = None,
    title: str = "JARNSEN MESH · Profil auswählen",
) -> Path | None:
    """Modal in-app profile manager. Returns the selected visible profile path."""
    records = list_profile_records(services, board_key=board_key)
    selected: dict[str, Path | None] = {"path": None}

    window = ctk.CTkToplevel(root)
    window.title(title)
    window.geometry("900x560")
    window.minsize(760, 440)
    window.transient(root)

    header = ctk.CTkFrame(window, fg_color="transparent")
    header.pack(fill="x", padx=22, pady=(20, 12))
    ctk.CTkLabel(
        header,
        text="Profile",
        font=ctk.CTkFont(size=24, weight="bold"),
    ).pack(side="left")
    subtitle = "Gespeicherte Grundeinstellungen"
    if board_key in services.BOARD_PROFILES:
        subtitle += f" · {_board_label(services, board_key)}"
    ctk.CTkLabel(
        header,
        text=subtitle,
        font=ctk.CTkFont(size=12),
        text_color=("gray40", "gray65"),
    ).pack(side="left", padx=(12, 0), pady=(7, 0))

    columns = ctk.CTkFrame(window, fg_color=("gray88", "gray19"), corner_radius=10)
    columns.pack(fill="x", padx=22, pady=(0, 6))
    for col, text, width in (
        (0, "Rolle", 150),
        (1, "Long Name", 250),
        (2, "Short", 80),
        (3, "Board", 210),
        (4, "Geändert", 115),
    ):
        columns.grid_columnconfigure(col, weight=1 if col in (1, 3) else 0, minsize=width)
        ctk.CTkLabel(
            columns,
            text=text,
            font=ctk.CTkFont(size=11, weight="bold"),
            anchor="w",
        ).grid(row=0, column=col, sticky="ew", padx=10, pady=8)
    columns.grid_columnconfigure(5, minsize=95)

    list_frame = ctk.CTkScrollableFrame(window, fg_color="transparent")
    list_frame.pack(fill="both", expand=True, padx=18, pady=(0, 10))
    for col in range(6):
        list_frame.grid_columnconfigure(col, weight=1 if col in (1, 3) else 0)

    def choose(path: Path) -> None:
        selected["path"] = path
        window.destroy()

    if not records:
        ctk.CTkLabel(
            list_frame,
            text="Noch keine passenden gespeicherten Profile vorhanden.",
            font=ctk.CTkFont(size=13),
            text_color=("gray40", "gray65"),
        ).grid(row=0, column=0, columnspan=6, sticky="w", padx=10, pady=24)
    else:
        for row_index, record in enumerate(records):
            values = (
                record.summary.role or "–",
                record.summary.long_name or "–",
                record.summary.short_name or "–",
                _board_label(services, record.board_key),
                record.modified.strftime("%d.%m. %H:%M"),
            )
            widths = (150, 250, 80, 210, 115)
            for col, (value, width) in enumerate(zip(values, widths)):
                ctk.CTkLabel(
                    list_frame,
                    text=value,
                    anchor="w",
                    width=width,
                    font=ctk.CTkFont(size=12),
                ).grid(row=row_index, column=col, sticky="ew", padx=8, pady=6)
            ctk.CTkButton(
                list_frame,
                text="Auswählen",
                width=90,
                height=30,
                command=lambda path=record.path: choose(path),
            ).grid(row=row_index, column=5, padx=8, pady=5)

    footer = ctk.CTkFrame(window, fg_color="transparent")
    footer.pack(fill="x", padx=22, pady=(0, 18))
    ctk.CTkButton(
        footer,
        text="Profilordner öffnen",
        fg_color=("gray72", "gray28"),
        hover_color=("gray65", "gray35"),
        command=lambda: open_profile_folder(services),
    ).pack(side="left")
    ctk.CTkLabel(
        footer,
        text=f"Ordner: {services.PATHS.profiles}",
        text_color=("gray40", "gray65"),
        font=ctk.CTkFont(size=10),
    ).pack(side="left", padx=(12, 0))
    ctk.CTkButton(
        footer,
        text="Abbrechen",
        width=110,
        fg_color=("gray72", "gray28"),
        hover_color=("gray65", "gray35"),
        command=window.destroy,
    ).pack(side="right")

    window.protocol("WM_DELETE_WINDOW", window.destroy)
    window.after(100, window.focus_force)
    window.grab_set()
    root.wait_window(window)
    return selected["path"]


def activate_profile(source: Path, root: Any, services: Any, *, status_prefix: str = "Profil geladen") -> Path:
    source = Path(source)
    services.import_profile_file(source)
    summary = summary_from_profile_file(source)

    if hasattr(root, "profile_path_var"):
        root.profile_path_var.set(str(source))
    if hasattr(root, "profile_summary_var"):
        root.profile_summary_var.set(format_summary(summary))
    if summary.long_name and hasattr(root, "long_name_var"):
        root.long_name_var.set(summary.long_name)
    if summary.short_name and hasattr(root, "short_name_var"):
        root.short_name_var.set(summary.short_name)
    if hasattr(root, "_append_log"):
        root._append_log(
            f"{status_prefix} · {source.name} · Board={profile_board_text(source)} · "
            f"Rolle={summary.role or '–'} · Long={summary.long_name or '–'} · Short={summary.short_name or '–'}"
        )
    if hasattr(root, "_set_status"):
        root._set_status(
            f"{status_prefix} · {summary.long_name or source.stem} · Rolle {summary.role or 'unbekannt'}"
        )
    return source


def choose_profile_for_app(root: Any, services: Any) -> None:
    try:
        source = select_profile_dialog(root, services)
        if source is None:
            return
        activate_profile(source, root, services)
    except Exception as exc:
        if hasattr(root, "_show_error"):
            root._show_error(exc)
        else:
            messagebox.showerror("JARNSEN MESH Flasher", str(exc), parent=root)


def read_master_profile_for_app(root: Any, services: Any) -> None:
    """Replacement for the old master button so the visible path is the named profile, never .active-profile."""
    device = root._selected_device() if hasattr(root, "_selected_device") else None
    if not device:
        messagebox.showwarning("Kein Gerät", "Bitte zuerst einen Master-Node verbinden.", parent=root)
        return
    if bool(getattr(root, "busy", False)):
        return
    root._set_busy(True)

    def worker() -> None:
        try:
            root._set_status(f"Grundeinstellungen von {device.port} einlesen …")
            path = services.export_profile(device.port)
            summary = summary_from_profile_file(path).with_fallback(
                summary_from_info_text(device.model_text)
            )

            def update() -> None:
                root.profile_path_var.set(str(path))
                root.profile_summary_var.set(format_summary(summary))
                if summary.long_name:
                    root.long_name_var.set(summary.long_name)
                if summary.short_name:
                    root.short_name_var.set(summary.short_name)

            root.after(0, update)
            if hasattr(root, "_append_log"):
                root._append_log(
                    f"Master {device.port} gespeichert · {path.name} · Rolle={summary.role or '–'} · "
                    f"Long={summary.long_name or '–'} · Short={summary.short_name or '–'}"
                )
            root._set_status(
                f"Profil gespeichert · {path.name} · Rolle {summary.role or 'unbekannt'}"
            )
        except Exception as exc:
            root._show_error(exc)
        finally:
            root._set_busy(False)

    threading.Thread(target=worker, daemon=True).start()
