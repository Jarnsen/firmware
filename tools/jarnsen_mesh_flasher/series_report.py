from __future__ import annotations

import json
import threading
import types
from datetime import datetime
from pathlib import Path
from typing import Any


_INSTALLED = False


def _emit(message: str) -> None:
    try:
        import diagnostics
        diagnostics._emit(message)
    except Exception:
        pass


class SeriesReportManager:
    def __init__(self, services: Any) -> None:
        self.services = services
        self.root = Path(services.PATHS.root) / "series-reports"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._session: dict[str, Any] | None = None
        self._path: Path | None = None

    def _new_session(self) -> dict[str, Any]:
        now = datetime.now()
        session_id = now.strftime("%Y%m%d-%H%M%S")
        self._path = self.root / f"series-{session_id}.json"
        self._session = {
            "schema": 1,
            "session_id": session_id,
            "started_at": now.isoformat(timespec="seconds"),
            "updated_at": now.isoformat(timespec="seconds"),
            "attempts": [],
            "success": 0,
            "failed": 0,
        }
        self._save()
        return self._session

    def _ensure(self, index: int) -> dict[str, Any]:
        with self._lock:
            if self._session is None or (index == 1 and self._session.get("attempts")):
                return self._new_session()
            return self._session

    def _save(self) -> None:
        with self._lock:
            if self._session is None or self._path is None:
                return
            self._session["updated_at"] = datetime.now().isoformat(timespec="seconds")
            temp = self._path.with_suffix(".tmp")
            temp.write_text(json.dumps(self._session, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temp.replace(self._path)

    def begin(self, index: int, port: str, board_key: str, long_name: str, short_name: str) -> dict[str, Any]:
        session = self._ensure(index)
        attempt = {
            "index": int(index),
            "port": str(port),
            "board_key": str(board_key),
            "board_label": str(self.services.BOARD_PROFILES.get(board_key, {}).get("label") or board_key),
            "long_name": str(long_name),
            "short_name": str(short_name),
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "finished_at": "",
            "status": "running",
            "firmware": "",
            "backup": "",
            "identity": "",
            "error": "",
            "resume": None,
        }
        with self._lock:
            session["attempts"].append(attempt)
        self._save()
        _emit(f"SERIES REPORT BEGIN session={session['session_id']} index={index} port={port} board={board_key!r}")
        return attempt

    def success(self, attempt: dict[str, Any], result: tuple[Any, Any, Any]) -> None:
        bundle, backup, identity = result
        attempt.update(
            status="success",
            finished_at=datetime.now().isoformat(timespec="seconds"),
            firmware=str(getattr(bundle, "display_name", "") or getattr(bundle, "artifact_name", "")),
            backup=str(backup or ""),
            identity=str(identity or ""),
        )
        with self._lock:
            if self._session is not None:
                self._session["success"] = sum(1 for item in self._session["attempts"] if item.get("status") == "success")
                self._session["failed"] = sum(1 for item in self._session["attempts"] if item.get("status") == "failed")
        self._save()
        _emit(f"SERIES REPORT SUCCESS index={attempt['index']} port={attempt['port']}")

    def fail(self, attempt: dict[str, Any], exc: BaseException) -> None:
        resume = None
        try:
            resume = self.services.flash_transaction_resume_plan(attempt.get("port"))
        except Exception:
            pass
        attempt.update(
            status="failed",
            finished_at=datetime.now().isoformat(timespec="seconds"),
            error=f"{type(exc).__name__}: {exc}",
            resume=resume,
        )
        with self._lock:
            if self._session is not None:
                self._session["success"] = sum(1 for item in self._session["attempts"] if item.get("status") == "success")
                self._session["failed"] = sum(1 for item in self._session["attempts"] if item.get("status") == "failed")
        self._save()
        _emit(
            f"SERIES REPORT FAIL index={attempt['index']} port={attempt['port']} "
            f"resume={resume!r} error={attempt['error'][:500]!r}"
        )

    def summary(self) -> dict[str, Any]:
        with self._lock:
            if self._session is not None:
                return json.loads(json.dumps(self._session))
        candidates = sorted(self.root.glob("series-*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not candidates:
            return {"schema": 1, "session_id": "", "attempts": [], "success": 0, "failed": 0}
        try:
            data = json.loads(candidates[0].read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}


def install(services: Any) -> None:
    """Persist one report row for every series-flash attempt without changing flow semantics."""
    global _INSTALLED
    if _INSTALLED or getattr(services, "_jarnsen_series_report_v1", False):
        return
    _INSTALLED = True

    manager = SeriesReportManager(services)
    services.series_reports = manager
    services.series_report_summary = manager.summary
    services._jarnsen_series_report_v1 = True

    try:
        import customtkinter as ctk
        original_root_init = ctk.CTk.__init__

        def root_init(app: Any, *args: Any, **kwargs: Any) -> None:
            original_root_init(app, *args, **kwargs)

            def patch_app(attempt_no: int = 0) -> None:
                if getattr(app, "_jarnsen_series_report_ui_hook", False):
                    return
                original_perform = getattr(app, "_perform_flash", None)
                if not callable(original_perform):
                    if attempt_no < 20:
                        try:
                            app.after(120, lambda: patch_app(attempt_no + 1))
                        except Exception:
                            pass
                    return

                def perform_flash(
                    app_self: Any,
                    port: str,
                    board_key: str,
                    long_name: str,
                    short_name: str,
                    *,
                    series_index: int | None = None,
                    strict_preflight: bool = False,
                ):
                    if series_index is None:
                        return original_perform(
                            port, board_key, long_name, short_name,
                            series_index=series_index, strict_preflight=strict_preflight,
                        )
                    report_attempt = manager.begin(series_index, port, board_key, long_name, short_name)
                    try:
                        result = original_perform(
                            port, board_key, long_name, short_name,
                            series_index=series_index, strict_preflight=strict_preflight,
                        )
                    except Exception as exc:
                        manager.fail(report_attempt, exc)
                        raise
                    manager.success(report_attempt, result)
                    return result

                app._perform_flash = types.MethodType(perform_flash, app)
                app._jarnsen_series_report_ui_hook = True
                _emit("SERIES REPORT app-hook ready perform-flash=1")

            try:
                app.after(650, patch_app)
            except Exception:
                pass

        ctk.CTk.__init__ = root_init
    except Exception as exc:
        _emit(f"SERIES REPORT UI hook skipped type={type(exc).__name__} message={exc}")

    _emit("SERIES REPORT installed json=1 per-attempt=1 success-fail=1 transaction-resume=1")
