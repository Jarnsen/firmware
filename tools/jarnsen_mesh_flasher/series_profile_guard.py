from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

from profile_catalog import (
    board_for_profile,
    copy_profile_assignment,
    profile_board_text,
    profiles_for_board,
    register_profile,
)
from profile_utils import format_summary, summary_from_profile_file


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _root() -> Any | None:
    try:
        import tkinter as tk

        return getattr(tk, "_default_root", None)
    except Exception:
        return None


def _ui_call(root: Any, callback: Callable[[], Any], timeout: float = 300.0) -> Any:
    if threading.current_thread() is threading.main_thread():
        return callback()

    done = threading.Event()
    box: dict[str, Any] = {}

    def runner() -> None:
        try:
            box["value"] = callback()
        except BaseException as exc:  # propagate to serial worker
            box["error"] = exc
        finally:
            done.set()

    root.after(0, runner)
    if not done.wait(timeout):
        raise RuntimeError("Zeitüberschreitung bei der Serien-Profilabfrage.")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _update_profile_ui(root: Any, path: Path) -> None:
    summary = summary_from_profile_file(path)
    if hasattr(root, "profile_path_var"):
        root.profile_path_var.set(str(path))
    if hasattr(root, "profile_summary_var"):
        root.profile_summary_var.set(format_summary(summary))
    if summary.long_name and hasattr(root, "long_name_var"):
        root.long_name_var.set(summary.long_name)
    if summary.short_name and hasattr(root, "short_name_var"):
        root.short_name_var.set(summary.short_name)
    if hasattr(root, "_append_log"):
        root._append_log(
            "Serienprofil aktiv · "
            f"{path.name} · Board={profile_board_text(path)} · "
            f"Rolle={summary.role or '–'} · Long={summary.long_name or '–'} · Short={summary.short_name or '–'}"
        )


def _manual_board(root: Any, services: Any, info_text: str) -> str | None:
    # Only offer manual confirmation when the node actually returned useful
    # Meshtastic-ish information. Blank/unresponsive serial links must not be
    # converted into a guessed board.
    upper = (info_text or "").upper()
    evidence = any(token in upper for token in ("OWNER", "METADATA", "FIRMWARE", "MESHTASTIC", "NODE"))
    if not evidence:
        return None

    from tkinter import messagebox

    answer = _ui_call(
        root,
        lambda: messagebox.askyesnocancel(
            "Serienflash · Board bestätigen",
            "Das Board konnte aus den seriellen Daten nicht eindeutig erkannt werden.\n\n"
            "JA  = Heltec Wireless Tracker V1.1\n"
            "NEIN = Heltec V3\n"
            "ABBRECHEN = Serienflash stoppen\n\n"
            "Welches Board ist angeschlossen?",
            parent=root,
        ),
    )
    if answer is None:
        _emit("SERIES BOARD MANUAL cancelled")
        return None
    board_key = "tracker" if answer else "repeater"
    _emit(f"SERIES BOARD MANUAL confirmed={board_key!r}")
    return board_key


def _choose_profile(root: Any, services: Any, board_key: str, *, force: bool) -> bool:
    from tkinter import filedialog, messagebox

    board_label = str(services.BOARD_PROFILES[board_key]["label"])
    active = services.PATHS.active_profile
    active_board = board_for_profile(active)
    last_board = str(getattr(root, "series_last_board", "") or "")
    changed = bool(last_board and last_board != board_key)
    index = int(getattr(root, "series_count", 0)) + 1

    state_key = (index, board_key)
    if getattr(root, "_series_profile_guard_state", None) == state_key:
        return True

    if not force and not changed and active.exists() and active_board == board_key:
        root._series_profile_guard_state = state_key
        _emit(
            f"SERIES PROFILE MATCH index={index} board={board_key!r} active={active.name!r}"
        )
        return True

    known = profiles_for_board(board_key)
    known_text = "\n".join(f"  • {path.name}" for path in known[:8]) or "  • noch keines eindeutig zugeordnet"
    previous_label = (
        str(services.BOARD_PROFILES[last_board]["label"])
        if last_board in services.BOARD_PROFILES
        else "–"
    )
    active_label = (
        str(services.BOARD_PROFILES[active_board]["label"])
        if active_board in services.BOARD_PROFILES
        else "nicht zugeordnet"
    )

    reason = (
        f"Boardwechsel erkannt: {previous_label} → {board_label}."
        if changed
        else f"Das aktive Profil passt nicht eindeutig zu {board_label}."
    )

    proceed = _ui_call(
        root,
        lambda: messagebox.askokcancel(
            f"Serie #{index} · Profil für Board wählen",
            f"{reason}\n\n"
            f"Erkanntes Board: {board_label}\n"
            f"Aktives Profil: {active.name if active.exists() else 'keines'}\n"
            f"Profil-Board: {active_label}\n\n"
            f"Bekannte Profile für dieses Board:\n{known_text}\n\n"
            "Jetzt das Profil auswählen, das für dieses Board verwendet werden soll.",
            parent=root,
        ),
    )
    if not proceed:
        _emit(f"SERIES PROFILE SELECTION cancelled index={index} board={board_key!r}")
        return False

    while True:
        filename = _ui_call(
            root,
            lambda: filedialog.askopenfilename(
                title=f"Profil für {board_label} auswählen",
                initialdir=str(services.PATHS.profiles),
                filetypes=[
                    ("Meshtastic Profil", "*.yaml *.yml *.cfg"),
                    ("Alle Dateien", "*.*"),
                ],
                parent=root,
            ),
        )
        if not filename:
            _emit(f"SERIES PROFILE FILEDIALOG cancelled index={index} board={board_key!r}")
            return False

        source = Path(filename)
        assigned = board_for_profile(source)
        if assigned and assigned != board_key:
            wrong_label = str(services.BOARD_PROFILES[assigned]["label"])
            _ui_call(
                root,
                lambda: messagebox.showerror(
                    "Falsches Profil für Board",
                    f"{source.name}\n\nist als Profil für {wrong_label} hinterlegt, "
                    f"angeschlossen ist aber {board_label}.\n\n"
                    "Bitte ein anderes Profil auswählen.",
                    parent=root,
                ),
            )
            _emit(
                f"SERIES PROFILE REJECT wrong-board file={source.name!r} assigned={assigned!r} detected={board_key!r}"
            )
            continue

        summary = summary_from_profile_file(source)
        if not assigned:
            accept = _ui_call(
                root,
                lambda: messagebox.askyesno(
                    "Profil noch keinem Board zugeordnet",
                    f"{source.name}\n\nhat noch keine Board-Zuordnung.\n\n"
                    f"Dieses Profil dauerhaft {board_label} zuordnen?",
                    parent=root,
                ),
            )
            if not accept:
                continue
            register_profile(source, board_key, summary, source="series-manual-assignment")

        selected = services.import_profile_file(source)
        # import_profile_file keeps active-profile.yaml as the internal restore
        # copy. Mirror the selected profile's board assignment to that copy.
        copy_profile_assignment(source, services.PATHS.active_profile)
        if board_for_profile(services.PATHS.active_profile) != board_key:
            register_profile(
                services.PATHS.active_profile,
                board_key,
                summary,
                source=f"active-from:{source.name}",
            )

        _ui_call(root, lambda: _update_profile_ui(root, source))
        root._series_profile_guard_state = state_key
        _emit(
            f"SERIES PROFILE SELECTED index={index} board={board_key!r} file={source.name!r} returned={str(selected)!r}"
        )
        return True


def install(services: Any) -> None:
    base_detect = services.detect_board_from_text

    def detect_board_from_text(text: str) -> str | None:
        board_key = base_detect(text)
        root = _root()
        if root is None or not bool(getattr(root, "series_active", False)):
            return board_key

        if not board_key:
            board_key = _manual_board(root, services, text)
            if not board_key:
                return None

        last_board = str(getattr(root, "series_last_board", "") or "")
        active_board = board_for_profile(services.PATHS.active_profile)
        force = bool(last_board and last_board != board_key) or active_board != board_key
        if not _choose_profile(root, services, board_key, force=force):
            # Returning None makes the existing safety path stop before erase.
            setattr(root, "_series_profile_guard_cancelled", True)
            return None
        setattr(root, "_series_profile_guard_cancelled", False)
        return board_key

    services.detect_board_from_text = detect_board_from_text
    _emit("SERIES PROFILE GUARD installed: board/profile match required before series flash")
