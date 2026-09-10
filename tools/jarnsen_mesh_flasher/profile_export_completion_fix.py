from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Iterable

import yaml


_INSTALLED = False
_EXPORT_STABLE_SECONDS = 0.75
_POLL_SECONDS = 0.10
_SERIAL_SETTLE_SECONDS = 0.25


def _emit(message: str) -> None:
    try:
        import diagnostics
        diagnostics._emit(message)
    except Exception:
        pass


def _ui(services: Any, message: str) -> None:
    callback = getattr(services, "_jarnsen_ui_log_callback", None)
    if callable(callback):
        try:
            callback(str(message))
        except Exception:
            pass


def _export_target(args: Iterable[str]) -> Path | None:
    argv = [str(value) for value in args]
    try:
        index = argv.index("--export-config")
    except ValueError:
        return None
    if index + 1 >= len(argv):
        return None
    value = str(argv[index + 1] or "").strip()
    return Path(value) if value else None


def _export_state(path: Path) -> tuple[bool, tuple[int, int] | None]:
    try:
        stat = path.stat()
        if stat.st_size < 20:
            return False, None
        data = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
        if not isinstance(data, dict) or not data:
            return False, None
        return True, (int(stat.st_size), int(stat.st_mtime_ns))
    except Exception:
        return False, None


def _stop_process(proc: subprocess.Popen[str]) -> str:
    if proc.poll() is not None:
        return "already-exited"
    try:
        proc.terminate()
        proc.wait(timeout=1.5)
        return "terminate"
    except Exception:
        try:
            proc.kill()
            proc.wait(timeout=1.5)
            return "kill"
        except Exception:
            return "kill-failed"


def _reader(stream: Any, sink: list[str], done: threading.Event) -> None:
    try:
        if stream is not None:
            for line in stream:
                sink.append(str(line))
    finally:
        done.set()


def _run_export_helper(
    services: Any,
    tool: str,
    args: Iterable[str],
    *,
    timeout: int,
    check: bool,
) -> subprocess.CompletedProcess[str]:
    argv = [str(value) for value in args]
    target = _export_target(argv)
    if target is None:
        raise ValueError("export target missing")

    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.unlink(missing_ok=True)
    except Exception:
        pass

    cmd = services.helper_command() + [str(tool), *argv]
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    _emit(
        f"PROFILE EXPORT WATCH START target={str(target)!r} timeout={timeout}s "
        "artifact-authoritative=1 stuck-cli-kill=1"
    )
    _ui(services, f"PROFILVERGLEICH · Node-Konfiguration exportieren · {target.name}")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
        startupinfo=services._startupinfo(),
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    stdout_done = threading.Event()
    stderr_done = threading.Event()
    threading.Thread(
        target=_reader,
        args=(proc.stdout, stdout_lines, stdout_done),
        name="profile-export-stdout",
        daemon=True,
    ).start()
    threading.Thread(
        target=_reader,
        args=(proc.stderr, stderr_lines, stderr_done),
        name="profile-export-stderr",
        daemon=True,
    ).start()

    started = time.monotonic()
    stable_signature: tuple[int, int] | None = None
    stable_since: float | None = None
    accepted = False
    accepted_reason = ""
    timed_out = False

    while True:
        now = time.monotonic()
        valid, signature = _export_state(target)
        if valid and signature is not None:
            if signature != stable_signature:
                stable_signature = signature
                stable_since = now
            else:
                stable_for = now - (stable_since or now)
                output_now = "".join(stdout_lines)
                marker_seen = "Exported configuration to" in output_now
                if marker_seen or stable_for >= _EXPORT_STABLE_SECONDS:
                    accepted = True
                    accepted_reason = "marker" if marker_seen else "stable-valid-yaml"
                    break
        else:
            stable_signature = None
            stable_since = None

        if proc.poll() is not None:
            break
        if now - started >= max(1, int(timeout)):
            timed_out = True
            break
        time.sleep(_POLL_SECONDS)

    stop_action = ""
    if accepted and proc.poll() is None:
        stop_action = _stop_process(proc)
    elif timed_out and proc.poll() is None:
        stop_action = _stop_process(proc)

    stdout_done.wait(1.5)
    stderr_done.wait(1.5)
    for stream in (proc.stdout, proc.stderr):
        try:
            if stream is not None:
                stream.close()
        except Exception:
            pass
    stdout = "".join(stdout_lines)
    stderr = "".join(stderr_lines)

    if stop_action in {"terminate", "kill"}:
        time.sleep(_SERIAL_SETTLE_SECONDS)

    if timed_out and not accepted:
        valid, _signature = _export_state(target)
        if valid:
            accepted = True
            accepted_reason = "valid-at-timeout"

    elapsed = time.monotonic() - started
    if accepted:
        try:
            size = target.stat().st_size
        except Exception:
            size = 0
        _emit(
            f"PROFILE EXPORT ARTIFACT COMPLETE target={str(target)!r} bytes={size} "
            f"elapsed={elapsed:.2f}s helper_alive={int(bool(stop_action))} "
            f"action={stop_action or 'normal-exit'} reason={accepted_reason} "
            f"serial-settle={int(_SERIAL_SETTLE_SECONDS * 1000)}ms"
        )
        _ui(
            services,
            f"PROFILVERGLEICH · Export vollständig · {size} Bytes · "
            f"{elapsed:.1f}s · CLI sauber freigegeben",
        )
        return subprocess.CompletedProcess(cmd, 0, stdout, stderr)

    if timed_out:
        _emit(
            f"PROFILE EXPORT TIMEOUT target={str(target)!r} elapsed={elapsed:.2f}s "
            f"action={stop_action or 'none'} valid-artifact=0"
        )
        raise subprocess.TimeoutExpired(cmd, timeout, output=stdout, stderr=stderr)

    returncode = int(proc.wait(timeout=2))
    if check and returncode != 0:
        details = (stderr or stdout or "").strip()
        raise services.FlasherError(
            details or f"{tool} fehlgeschlagen (Exit {returncode})"
        )
    return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)


def install(services: Any) -> None:
    global _INSTALLED
    if _INSTALLED or getattr(services, "_jarnsen_profile_export_completion_fix", False):
        return
    _INSTALLED = True

    base_run_helper = services.run_helper

    def run_helper(
        tool: str,
        args: Iterable[str],
        *,
        timeout: int = 60,
        check: bool = True,
    ):
        argv = [str(value) for value in args]
        if str(tool).casefold() == "meshtastic" and _export_target(argv) is not None:
            return _run_export_helper(
                services,
                tool,
                argv,
                timeout=timeout,
                check=check,
            )
        return base_run_helper(tool, argv, timeout=timeout, check=check)

    services.run_helper = run_helper
    services._jarnsen_profile_export_completion_fix = True
    services._jarnsen_profile_export_artifact_authoritative = True
    _emit(
        "PROFILE EXPORT COMPLETION FIX installed export-config-popen=1 "
        "valid-yaml-artifact-authoritative=1 stable-file-watch=1 "
        "stuck-helper-terminate=1 serial-settle=250ms non-export-delegate=1"
    )
