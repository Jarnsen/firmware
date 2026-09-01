from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


_LOCK = threading.Lock()
_LOG_PATH: Path | None = None
_INSTALLED = False

_SENSITIVE = re.compile(
    r"(?i)(authorization|bearer|token|password|passwd|secret|private[_ -]?key|admin[_ -]?key|\bpsk\b)"
)


def _redact(text: Any) -> str:
    value = "" if text is None else str(text)
    lines: list[str] = []
    for line in value.splitlines() or [value]:
        if _SENSITIVE.search(line):
            if ":" in line:
                key = line.split(":", 1)[0]
                line = f"{key}: <redacted>"
            elif "=" in line:
                key = line.split("=", 1)[0]
                line = f"{key}=<redacted>"
            else:
                line = "<redacted sensitive line>"
        lines.append(line)
    return "\n".join(lines)


def _emit(message: str) -> None:
    if _LOG_PATH is None:
        return
    stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    thread = threading.current_thread().name
    line = f"[{stamp}] [DIAG:{thread}] {_redact(message)}"
    try:
        with _LOCK:
            with _LOG_PATH.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
    except Exception:
        pass


def _emit_block(title: str, text: Any, *, max_chars: int = 30000) -> None:
    value = _redact(text)
    if not value.strip():
        _emit(f"{title}: <empty>")
        return
    if len(value) > max_chars:
        value = value[:max_chars] + f"\n... <truncated, total {len(value)} chars>"
    _emit(f"{title}: BEGIN")
    for line in value.splitlines():
        _emit(f"{title}> {line}")
    _emit(f"{title}: END")


def _format_command(cmd: list[str]) -> str:
    safe: list[str] = []
    hide_next = False
    for arg in cmd:
        if hide_next:
            safe.append("<redacted>")
            hide_next = False
            continue
        low = str(arg).lower()
        safe.append(str(arg))
        if low in {"--token", "--password", "--psk", "--private-key", "--admin-key"}:
            hide_next = True
    return subprocess.list2cmdline(safe)


def _decode_timeout_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def install(services: Any, log_dir: Path) -> Path:
    global _INSTALLED, _LOG_PATH
    if _INSTALLED and _LOG_PATH is not None:
        return _LOG_PATH

    log_dir.mkdir(parents=True, exist_ok=True)
    _LOG_PATH = log_dir / f"flasher-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
    _INSTALLED = True

    # Force the GUI and the low-level diagnostics to use exactly the same file.
    services.PATHS.logs = log_dir
    services.make_log_file = lambda: _LOG_PATH

    original_run_helper = services.run_helper

    def detailed_run_helper(
        tool: str,
        args: Any,
        *,
        timeout: int = 60,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        cmd = services.helper_command() + [tool, *[str(a) for a in args]]
        command_text = _format_command(cmd)
        _emit(f"PROCESS START tool={tool} timeout={timeout}s check={check}")
        _emit(f"PROCESS CMD {command_text}")
        started = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd,
                text=True,
                capture_output=True,
                timeout=timeout,
                startupinfo=services._startupinfo(),
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except subprocess.TimeoutExpired as exc:
            elapsed = time.perf_counter() - started
            _emit(f"PROCESS TIMEOUT tool={tool} after={elapsed:.3f}s configured_timeout={timeout}s")
            _emit_block("TIMEOUT STDOUT", _decode_timeout_value(exc.stdout))
            _emit_block("TIMEOUT STDERR", _decode_timeout_value(exc.stderr))
            raise
        except Exception as exc:
            elapsed = time.perf_counter() - started
            _emit(f"PROCESS EXCEPTION tool={tool} after={elapsed:.3f}s type={type(exc).__name__} message={exc}")
            raise

        elapsed = time.perf_counter() - started
        _emit(f"PROCESS END tool={tool} exit={proc.returncode} duration={elapsed:.3f}s")
        _emit_block("STDOUT", proc.stdout)
        _emit_block("STDERR", proc.stderr)
        if check and proc.returncode != 0:
            details = (proc.stderr or proc.stdout or "").strip()
            _emit(f"PROCESS FAILURE tool={tool} exit={proc.returncode}")
            raise services.FlasherError(details or f"{tool} fehlgeschlagen (Exit {proc.returncode})")
        return proc

    services.run_helper = detailed_run_helper

    original_scan_devices = services.scan_devices

    def detailed_scan_devices(probe_timeout: int = 8):
        _emit(f"SERIAL SCAN START probe_timeout={probe_timeout}s")
        try:
            ports = list(services.list_ports.comports())
        except Exception as exc:
            _emit(f"SERIAL ENUMERATION ERROR type={type(exc).__name__} message={exc}")
            ports = []
        _emit(f"SERIAL ENUMERATION count={len(ports)}")
        for index, item in enumerate(ports, start=1):
            vid = f"0x{item.vid:04X}" if getattr(item, "vid", None) is not None else "-"
            pid = f"0x{item.pid:04X}" if getattr(item, "pid", None) is not None else "-"
            _emit(
                "SERIAL PORT "
                f"#{index} device={getattr(item, 'device', '')} "
                f"description={getattr(item, 'description', '')!r} "
                f"hwid={getattr(item, 'hwid', '')!r} VID={vid} PID={pid} "
                f"serial={getattr(item, 'serial_number', None)!r} "
                f"manufacturer={getattr(item, 'manufacturer', None)!r} "
                f"product={getattr(item, 'product', None)!r} "
                f"interface={getattr(item, 'interface', None)!r} "
                f"location={getattr(item, 'location', None)!r}"
            )
        started = time.perf_counter()
        try:
            result = original_scan_devices(probe_timeout=probe_timeout)
        except Exception as exc:
            _emit(f"SERIAL SCAN EXCEPTION type={type(exc).__name__} message={exc}")
            raise
        elapsed = time.perf_counter() - started
        _emit(f"SERIAL SCAN END duration={elapsed:.3f}s devices={len(result)}")
        for item in result:
            _emit(
                f"SERIAL RESULT port={item.port} description={item.description!r} "
                f"board_key={item.board_key!r} model_text_chars={len(item.model_text or '')}"
            )
            if item.model_text:
                _emit_block(f"SERIAL INFO {item.port}", item.model_text, max_chars=12000)
        return result

    services.scan_devices = detailed_scan_devices

    original_detect = services.detect_board_from_text

    def detailed_detect_board_from_text(text: str):
        detected = original_detect(text)
        _emit(f"BOARD DETECT input_chars={len(text or '')} result={detected!r}")
        return detected

    services.detect_board_from_text = detailed_detect_board_from_text

    original_wait_for_serial = services.wait_for_serial

    def detailed_wait_for_serial(port: str, timeout: int = 90) -> None:
        _emit(f"SERIAL WAIT START port={port} timeout={timeout}s")
        started = time.perf_counter()
        try:
            result = original_wait_for_serial(port, timeout=timeout)
        except Exception as exc:
            _emit(
                f"SERIAL WAIT FAILURE port={port} duration={time.perf_counter()-started:.3f}s "
                f"type={type(exc).__name__} message={exc}"
            )
            raise
        _emit(f"SERIAL WAIT END port={port} duration={time.perf_counter()-started:.3f}s")
        return result

    services.wait_for_serial = detailed_wait_for_serial

    client_cls = services.GitHubFirmwareClient
    original_init = client_cls.__init__
    original_resolve = client_cls.resolve_latest
    original_download = client_cls._download_zip

    def detailed_init(self) -> None:
        started = time.perf_counter()
        original_init(self)
        gh_path = shutil.which("gh")
        _emit(
            f"GITHUB CLIENT init duration={time.perf_counter()-started:.3f}s "
            f"auth={'available' if bool(self.token) else 'missing'} gh_cli={gh_path or '-'} repo={services.REPOSITORY}"
        )

    def detailed_get_json(self, url: str, **params) -> dict:
        safe_params = {key: value for key, value in params.items() if not _SENSITIVE.search(str(key))}
        _emit(f"GITHUB GET url={url} params={safe_params}")
        started = time.perf_counter()
        try:
            response = self.session.get(url, params=params, timeout=30)
        except Exception as exc:
            _emit(
                f"GITHUB GET EXCEPTION duration={time.perf_counter()-started:.3f}s "
                f"type={type(exc).__name__} message={exc}"
            )
            raise
        elapsed = time.perf_counter() - started
        _emit(
            f"GITHUB RESPONSE status={response.status_code} duration={elapsed:.3f}s "
            f"final_url={response.url} bytes={len(response.content)}"
        )
        if response.status_code >= 400:
            _emit_block("GITHUB ERROR BODY", response.text[:4000])
            raise services.FlasherError(
                f"GitHub API: HTTP {response.status_code} · {response.text[:220]}"
            )
        data = response.json()
        if isinstance(data, dict) and "workflow_runs" in data:
            runs = data.get("workflow_runs") or []
            _emit(f"GITHUB WORKFLOW_RUNS count={len(runs)} total_count={data.get('total_count')}")
            for run in runs[:50]:
                _emit(
                    "GITHUB RUN "
                    f"id={run.get('id')} number={run.get('run_number')} "
                    f"name={run.get('name')!r} branch={run.get('head_branch')!r} "
                    f"status={run.get('status')!r} conclusion={run.get('conclusion')!r} "
                    f"event={run.get('event')!r} path={run.get('path')!r}"
                )
        elif isinstance(data, dict) and "artifacts" in data:
            artifacts = data.get("artifacts") or []
            _emit(f"GITHUB ARTIFACTS count={len(artifacts)} total_count={data.get('total_count')}")
            for artifact in artifacts[:100]:
                _emit(
                    "GITHUB ARTIFACT "
                    f"id={artifact.get('id')} name={artifact.get('name')!r} "
                    f"expired={artifact.get('expired')} size={artifact.get('size_in_bytes')} "
                    f"created={artifact.get('created_at')!r}"
                )
        else:
            keys = list(data.keys()) if isinstance(data, dict) else []
            _emit(f"GITHUB JSON type={type(data).__name__} keys={keys[:30]}")
        return data

    def detailed_resolve_latest(self, board_key: str):
        profile = services.BOARD_PROFILES.get(board_key, {})
        branch = profile.get("branch")
        env = profile.get("pio_env")
        _emit(
            f"FIRMWARE RESOLVE START board_key={board_key!r} label={profile.get('label')!r} "
            f"branch={branch!r} pio_env={env!r} expected_artifact_prefix={'firmware-' + str(env) + '-' if env else '-'}"
        )
        started = time.perf_counter()
        try:
            bundle = original_resolve(self, board_key)
        except Exception as exc:
            _emit(
                f"FIRMWARE RESOLVE FAILURE duration={time.perf_counter()-started:.3f}s "
                f"type={type(exc).__name__} message={exc}"
            )
            raise
        _emit(
            f"FIRMWARE RESOLVE END duration={time.perf_counter()-started:.3f}s "
            f"run_id={bundle.run_id} run_number={bundle.run_number} artifact_id={bundle.artifact_id} "
            f"artifact_name={bundle.artifact_name!r} root={bundle.root}"
        )
        _emit(f"FIRMWARE FILE factory={bundle.factory} size={bundle.factory.stat().st_size if bundle.factory.exists() else -1}")
        _emit(f"FIRMWARE FILE metadata={bundle.metadata} size={bundle.metadata.stat().st_size if bundle.metadata.exists() else -1}")
        _emit(f"FIRMWARE FILE ota={bundle.ota} size={bundle.ota.stat().st_size if bundle.ota.exists() else -1}")
        _emit(f"FIRMWARE FILE littlefs={bundle.littlefs} size={bundle.littlefs.stat().st_size if bundle.littlefs.exists() else -1}")
        return bundle

    def detailed_download(self, artifact_id: int, destination: Path) -> None:
        _emit(f"ARTIFACT DOWNLOAD START id={artifact_id} destination={destination}")
        started = time.perf_counter()
        try:
            result = original_download(self, artifact_id, destination)
        except Exception as exc:
            _emit(
                f"ARTIFACT DOWNLOAD FAILURE id={artifact_id} duration={time.perf_counter()-started:.3f}s "
                f"type={type(exc).__name__} message={exc}"
            )
            raise
        size = destination.stat().st_size if destination.exists() else -1
        _emit(f"ARTIFACT DOWNLOAD END id={artifact_id} duration={time.perf_counter()-started:.3f}s size={size}")
        return result

    client_cls.__init__ = detailed_init
    client_cls._get_json = detailed_get_json
    client_cls.resolve_latest = detailed_resolve_latest
    client_cls._download_zip = detailed_download

    _emit("=" * 72)
    _emit("JARNSEN-MESH-FLASHER detailed diagnostics enabled")
    _emit(f"log_path={_LOG_PATH}")
    _emit(f"app_frozen={getattr(sys, 'frozen', False)} executable={sys.executable}")
    _emit(f"python={sys.version.replace(chr(10), ' ')}")
    _emit(f"platform={sys.platform} os_name={os.name} cwd={Path.cwd()}")
    _emit(f"helper_command={_format_command(services.helper_command())}")
    _emit("Sensitive values (tokens/passwords/PSKs/private keys) are redacted.")
    _emit("=" * 72)

    return _LOG_PATH
