from __future__ import annotations

import os
import queue
import re
import subprocess
import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

_INSTALLED = False
_EXPECTED_JARNSEN_ROLE_BY_PORT: dict[str, str] = {}
_FAST_IDENTITY_BY_PORT: dict[str, Any] = {}

_ROLE_KEY_BY_FUNCTION = {
    "tak": "tak",
    "tak_tracker": "tak_tracker",
    "tak_repeater": "tak_repeater",
    "drone_repeater": "drone_repeater",
}


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _key(port: str) -> str:
    return str(port or "").strip().upper()


def _norm_role(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().casefold()).strip("_")


def _record(services: Any, port: str) -> Any | None:
    manager = getattr(services, "flash_transactions", None)
    if manager is None:
        return None
    try:
        return manager.active(port)
    except Exception:
        return None


def _functional_role(services: Any) -> tuple[Any | None, str]:
    try:
        import functional_profiles

        selected = functional_profiles.active_profile(services)
        identifier = str(getattr(selected, "identifier", "") or "").strip().lower()
        return selected, _ROLE_KEY_BY_FUNCTION.get(identifier, "")
    except Exception:
        return None, ""


def _raw_command(
    port: str,
    command: str,
    *,
    expected: str,
    timeout: float,
    attempts: int = 2,
    services: Any | None = None,
) -> str:
    import radio_profile_node_sync as node_sync

    last: BaseException | None = None
    for attempt in range(1, max(1, int(attempts)) + 1):
        try:
            line = node_sync._raw_command(
                port,
                command,
                expected=expected,
                timeout=max(2.0, float(timeout)),
            )
            _emit(
                f"PROVISION V2 RAW OK port={port} command={command.split()[0]!r} "
                f"attempt={attempt}/{attempts} response={line[:500]!r}"
            )
            return line
        except Exception as exc:
            last = exc
            _emit(
                f"PROVISION V2 RAW RETRY port={port} command={command.split()[0]!r} "
                f"attempt={attempt}/{attempts} type={type(exc).__name__} message={str(exc)[:350]!r}"
            )
            if attempt < attempts:
                if services is not None:
                    try:
                        services.wait_for_serial(port, timeout=12)
                    except Exception:
                        pass
                time.sleep(0.45)
    if last is not None:
        raise last
    raise TimeoutError(f"Keine Antwort auf {command!r} von {port}")


def _parse_tool_identity(line: str) -> Any | None:
    if "===JARNSEN_INFO===" not in str(line or ""):
        return None

    def field(name: str) -> str:
        match = re.search(rf"\b{name}=([^\s]+)", line, re.IGNORECASE)
        return match.group(1).strip() if match else ""

    product = field("product") or "JARNSEN-MESH"
    version = field("version").lstrip("vV")
    build_text = field("build")
    hardware_match = re.search(
        r"\bhardware=(.+?)(?=\s+sha=|\s+[a-z_]+=|$)", line, re.IGNORECASE
    )
    hardware = hardware_match.group(1).strip() if hardware_match else ""
    sha = field("sha")
    try:
        build = int(build_text) if build_text else None
    except Exception:
        build = None
    return SimpleNamespace(
        product=product,
        edition="JARNSEN-MESH",
        version=version,
        build=build,
        hardware=hardware,
        sha=sha,
        is_jarnsen=True,
    )


def _cached_build_hint(services: Any, port: str) -> int:
    record = _record(services, port)
    try:
        expected = int(getattr(record, "expected_firmware_build", 0) or 0)
    except Exception:
        expected = 0
    if expected:
        return expected

    cached = getattr(services, "cached_jarnsen_identity", None)
    if callable(cached):
        try:
            identity = cached(port)
            return int(getattr(identity, "build", 0) or 0)
        except Exception:
            pass
    return 0


def _probe_role_api(services: Any, port: str, role_key: str) -> tuple[bool, Any | None]:
    build_hint = _cached_build_hint(services, port)
    if 0 < build_hint < 168:
        _emit(
            f"PROVISION V2 ROLE API port={port} build={build_hint} role={role_key} "
            "api=legacy reason=pre-role-api-build"
        )
        return False, None

    try:
        line = _raw_command(
            port,
            "JARNSEN_TOOL_INFO",
            expected="===JARNSEN_INFO===",
            timeout=4.0,
            attempts=2,
            services=services,
        )
    except Exception as exc:
        if build_hint >= 168 or role_key == "drone_repeater":
            raise services.FlasherError(
                "Die installierte Unified-Core-Firmware konnte den persistenten "
                "JARNSEN-Rollendienst (role_api=1) nicht bestätigen."
            ) from exc
        _emit(
            f"PROVISION V2 ROLE API port={port} build={build_hint or 'unknown'} "
            f"role={role_key} api=legacy reason=no-tool-info"
        )
        return False, None

    identity = _parse_tool_identity(line)
    if identity is not None:
        _FAST_IDENTITY_BY_PORT[_key(port)] = identity
    if "role_api=1" not in line:
        if build_hint >= 168 or role_key == "drone_repeater":
            raise services.FlasherError(
                "Die aktuelle Firmware meldet role_api=1 nicht. "
                "Für diese Funktionsrolle ist eine aktuelle Unified-Core-Firmware erforderlich."
            )
        return False, identity
    return True, identity


def _parse_role_info(line: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for name in (
        "role",
        "known",
        "persisted",
        "allowed",
        "gps_ready",
        "external_gps_required",
        "role_api",
    ):
        match = re.search(rf"\b{name}=([^\s]+)", str(line or ""), re.IGNORECASE)
        if match:
            result[name] = match.group(1).strip()
    return result


def _verify_role_line(services: Any, role_key: str, line: str, *, phase: str) -> None:
    data = _parse_role_info(line)
    actual = _norm_role(data.get("role", ""))
    wanted = _norm_role(role_key)
    if (
        actual != wanted
        or data.get("known") != "1"
        or data.get("persisted") != "1"
        or data.get("allowed") != "1"
        or data.get("role_api") != "1"
    ):
        raise services.FlasherError(
            f"JARNSEN-Rollenprüfung ({phase}) fehlgeschlagen: erwartet {role_key}, "
            f"Antwort {line.strip() or 'leer'}."
        )


def _sync_firmware_role(services: Any, port: str) -> None:
    """Persist every functional role through role_api=1 on Build 168+."""
    selected, role_key = _functional_role(services)
    if not role_key:
        return

    record = _record(services, port)
    kind = str(getattr(record, "kind", "") or "") if record is not None else ""
    if kind not in {"profile_only", "full"}:
        return

    # Defense in depth for Drone Repeater. The firmware repeats the same board
    # gate, but the Flasher must reject the combination before ROLE_SET too.
    if role_key == "drone_repeater":
        board_key = str(getattr(record, "board_key", "") or "").strip().lower()
        if not board_key:
            raise services.FlasherError(
                "DRONE REPEATER wird nicht geschrieben, weil das Zielboard nicht "
                "eindeutig bestätigt werden konnte."
            )
        import functional_profiles

        functional_profiles.require_compatible_board(selected, board_key, services)
        if board_key == "heltec_v4":
            _emit(f"PROVISION V2 DRONE V4 WARNING port={port} external-gnss-required=1")

    api_available, _identity = _probe_role_api(services, port, role_key)
    if not api_available:
        _emit(
            f"PROVISION V2 ROLE PATH port={port} kind={kind} role={role_key} api=legacy-device-role"
        )
        return

    line = _raw_command(
        port,
        "JARNSEN_TOOL_ROLE_INFO",
        expected="===JARNSEN_ROLE===",
        timeout=4.0,
        attempts=2,
        services=services,
    )
    data = _parse_role_info(line)
    current = _norm_role(data.get("role", ""))
    wanted = _norm_role(role_key)
    already_persisted = (
        current == wanted
        and data.get("known") == "1"
        and data.get("persisted") == "1"
        and data.get("allowed") == "1"
        and data.get("role_api") == "1"
    )

    _EXPECTED_JARNSEN_ROLE_BY_PORT[_key(port)] = role_key
    if already_persisted:
        _emit(
            f"PROVISION V2 ROLE PATH port={port} kind={kind} role={role_key} "
            "api=1 write=skip reason=already-persisted"
        )
        return

    result = _raw_command(
        port,
        f"JARNSEN_TOOL_ROLE_SET {role_key}",
        expected="===JARNSEN_ROLE_OK===",
        timeout=5.0,
        attempts=2,
        services=services,
    )
    if (
        _norm_role(_parse_role_info(result).get("role", "")) != wanted
        or "verified=1" not in result
    ):
        raise services.FlasherError(
            f"JARNSEN ROLE_SET hat {role_key} nicht eindeutig bestätigt: {result}"
        )

    # The firmware contract requires an explicit read-back after every write.
    verify = _raw_command(
        port,
        "JARNSEN_TOOL_ROLE_INFO",
        expected="===JARNSEN_ROLE===",
        timeout=4.0,
        attempts=2,
        services=services,
    )
    _verify_role_line(services, role_key, verify, phase="direkt nach ROLE_SET")

    import profile_runtime_stability_v2 as stability

    stability._ROLE_SERVICE_REBOOT_PENDING.add(_key(port))
    _emit(
        f"PROVISION V2 ROLE PATH port={port} kind={kind} role={role_key} "
        "api=1 write=ok readback=ok reboot=deferred"
    )


def _fast_read_identity(services: Any, port: str) -> Any | None:
    key = _key(port)
    identity = _FAST_IDENTITY_BY_PORT.get(key)
    if identity is not None and bool(getattr(identity, "is_jarnsen", False)):
        _emit(f"PROVISION V2 IDENTITY CACHE port={port} source=role-api-preflight")
        return identity

    cached = getattr(services, "cached_jarnsen_identity", None)
    if callable(cached):
        try:
            identity = cached(port)
            if identity is not None and bool(getattr(identity, "is_jarnsen", False)):
                _emit(
                    f"PROVISION V2 IDENTITY CACHE port={port} source=trusted-ui-cache"
                )
                return identity
        except Exception:
            pass

    try:
        line = _raw_command(
            port,
            "JARNSEN_TOOL_INFO",
            expected="===JARNSEN_INFO===",
            timeout=4.0,
            attempts=3,
            services=services,
        )
        identity = _parse_tool_identity(line)
        if identity is not None:
            _FAST_IDENTITY_BY_PORT[key] = identity
            return identity
    except Exception as exc:
        _emit(
            f"PROVISION V2 IDENTITY FAST FAIL port={port} type={type(exc).__name__} "
            f"message={str(exc)[:350]!r}"
        )
    return None


def _adaptive_settle_auto_reboot(
    services: Any,
    port: str,
    reason: str,
    *,
    wait_seconds: int = 30,
    stage: str = "Automatischer Neustart",
    explicit_reboot: bool = False,
) -> None:
    """Finish early only after a real USB disconnect and stable return."""
    import profile_runtime_stability_v2 as stability

    started = time.monotonic()
    observed_disconnect = False
    stable_since: float | None = None
    next_ui = started
    full_wait = max(1.0, float(wait_seconds))

    def present() -> bool:
        try:
            ports = getattr(services, "list_ports", None)
            if ports is not None:
                return any(
                    str(getattr(item, "device", "")).strip().upper() == _key(port)
                    for item in ports.comports()
                )
        except Exception:
            pass
        checker = getattr(services, "live_serial_port", None)
        if callable(checker):
            try:
                return bool(checker(port))
            except Exception:
                pass
        return True

    _emit(
        f"PROVISION V2 REBOOT WAIT port={port} reason={reason!r} max={wait_seconds}s "
        f"adaptive-disconnect=1 explicit={int(explicit_reboot)}"
    )
    while time.monotonic() - started < full_wait:
        now = time.monotonic()
        is_present = present()
        if not is_present:
            observed_disconnect = True
            stable_since = None
        elif observed_disconnect:
            if stable_since is None:
                stable_since = now
            if now - started >= 6.0 and now - stable_since >= 3.0:
                break

        if now >= next_ui:
            elapsed = now - started
            remaining = max(0, int(full_wait - elapsed))
            stability._profile_callback(
                services,
                min(0.98, 0.78 + 0.16 * min(1.0, elapsed / full_wait)),
                stage,
                f"Gerät übernimmt Änderungen · noch max. {remaining}s",
            )
            next_ui = now + 1.0
        time.sleep(0.25)

    try:
        services.wait_for_serial(port, timeout=90)
    except Exception as exc:
        stability._AUTO_REBOOT_PENDING.pop(_key(port), None)
        raise services.FlasherError(
            f"{port} ist nach dem automatischen Neustart nicht wieder erreichbar."
        ) from exc

    # Bridges that never disappear keep the conservative original 30 s wait.
    # Native-USB boards already proved the reboot by disappearing and returning
    # stably, so an additional fixed 3 s tail would only waste time.
    if not observed_disconnect:
        stable_started = time.monotonic()
        while time.monotonic() - stable_started < 3.0:
            if not present():
                stable_started = time.monotonic()
            time.sleep(0.25)

    stability._AUTO_REBOOT_PENDING.pop(_key(port), None)
    _emit(
        f"PROVISION V2 REBOOT READY port={port} reason={reason!r} "
        f"elapsed={time.monotonic()-started:.2f}s disconnect={int(observed_disconnect)}"
    )


def _install_fast_backup(services: Any) -> None:
    """Try 921600 for the existing safety backup, retaining every fallback."""
    base_esptool = services.esptool

    def esptool(port: str, *args: str, **kwargs: Any):
        values = [str(value) for value in args]
        read_flash = "read-flash" in values or "read_flash" in values
        if read_flash and "--baud" in values:
            index = values.index("--baud")
            if index + 1 < len(values) and values[index + 1] == "460800":
                fast = list(values)
                fast[index + 1] = "921600"
                _emit(
                    f"PROVISION V2 BACKUP FAST port={port} requested=460800 actual=921600 "
                    "fallback=460800"
                )
                try:
                    return base_esptool(port, *fast, **kwargs)
                except Exception as exc:
                    try:
                        import backup_stability

                        retryable = backup_stability._retryable(exc)
                    except Exception:
                        retryable = False
                    if not retryable:
                        raise
                    _emit(
                        f"PROVISION V2 BACKUP FAST FALLBACK port={port} "
                        f"type={type(exc).__name__} next=460800"
                    )
                    return base_esptool(port, *args, **kwargs)
        return base_esptool(port, *args, **kwargs)

    services.esptool = esptool
    services._jarnsen_backup_921600_first = True


def _install_profile_stream(services: Any) -> None:
    import profile_restore as pr

    def stream_configure(
        runtime_services: Any,
        port: str,
        profile_path: Path,
        profile_data: dict[str, Any],
        *,
        timeout: int,
        stage: str,
        allow_disconnect_after_commit: bool,
    ) -> subprocess.CompletedProcess[str]:
        planned_paths = pr._planned_leaf_paths(profile_data)
        planned_set = {str(path).casefold() for path in planned_paths}
        planned_total = max(1, len(planned_set))
        owner = str(profile_data.get("owner") or "").strip()
        owner_short = str(profile_data.get("owner_short") or "").strip()

        cmd = runtime_services.helper_command() + ["meshtastic", "--port", port]
        # Meshtastic processes these identity switches before opening the YAML
        # settings transaction. They stay in the SAME helper process, so this
        # adds no second connection and no second reboot.
        if owner:
            cmd.extend(["--set-owner", owner])
        if owner_short:
            cmd.extend(["--set-owner-short", owner_short])
        cmd.extend(["--configure", str(profile_path), "--wait-to-disconnect", "1"])

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        pr._emit(
            f"PROFILE STREAM V2 START stage={stage!r} port={port} planned={planned_total} "
            f"timeout={timeout}s owner-prewrite={int(bool(owner or owner_short))} same-process=1"
        )
        pr._ui_log(
            runtime_services,
            f"{stage.upper()} START · {planned_total} geplante Werte · Port={port}",
        )
        pr._notify_profile(
            runtime_services, 0.0, stage, f"0/{planned_total} · Verbindung aufbauen"
        )

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
            startupinfo=runtime_services._startupinfo(),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        output_queue: queue.Queue[str | None] = queue.Queue()

        def reader() -> None:
            try:
                if proc.stdout is not None:
                    for raw in proc.stdout:
                        output_queue.put(raw.rstrip("\r\n"))
            finally:
                output_queue.put(None)

        threading.Thread(
            target=reader, name=f"profile-output-{stage}", daemon=True
        ).start()
        started = time.monotonic()
        deadline = started + timeout
        last_heartbeat = started
        last_detail = "Verbindung aufbauen"
        seen_settings: set[str] = set()
        lines: list[str] = []
        reader_done = False
        write_seen_at: float | None = None
        commit_seen_at: float | None = None
        accepted_after_commit = False

        while True:
            now = time.monotonic()
            try:
                item = output_queue.get(timeout=0.15)
            except queue.Empty:
                item = "__NO_LINE__"

            if item is None:
                reader_done = True
            elif item != "__NO_LINE__":
                line = str(item)
                if line:
                    lines.append(line)
                    kind, setting_key, display = pr._describe_config_line(line)
                    if kind == "setting" and setting_key and display:
                        seen_settings.add(setting_key)
                        # Meshtastic acknowledges Long+Short name in one line.
                        # Count both planned values instead of reporting 15/16.
                        if setting_key == "owner" and "owner_short" in planned_set:
                            seen_settings.add("owner_short")
                        done = len(seen_settings)
                        fraction = min(0.88, 0.88 * (done / max(planned_total, done)))
                        last_detail = f"{done}/{planned_total} · {display}"
                        pr._notify_profile(
                            runtime_services, fraction, stage, last_detail
                        )
                        pr._ui_log(
                            runtime_services,
                            f"{stage} · {done}/{planned_total} · {display}",
                        )
                        pr._emit(
                            f"PROFILE SETTING V2 stage={stage!r} index={done}/{planned_total} key={setting_key!r}"
                        )
                    elif kind == "connect" and display:
                        last_detail = display
                        pr._notify_profile(runtime_services, 0.03, stage, display)
                        pr._ui_log(runtime_services, f"{stage} · {display}")
                    elif kind == "write" and display:
                        write_seen_at = time.monotonic()
                        last_detail = display
                        pr._notify_profile(runtime_services, 0.93, stage, display)
                        pr._ui_log(runtime_services, f"{stage} · {display}")
                        pr._emit(f"PROFILE WRITE SENT stage={stage!r} port={port}")
                    elif kind == "transaction" and display:
                        pr._notify_profile(runtime_services, 0.95, stage, display)
                        pr._ui_log(runtime_services, f"{stage} · {display}")
                    elif kind == "commit" and display:
                        commit_seen_at = time.monotonic()
                        last_detail = display
                        pr._notify_profile(runtime_services, 0.98, stage, display)
                        pr._ui_log(runtime_services, f"{stage} · {display}")
                        pr._emit(f"PROFILE COMMIT SEEN stage={stage!r} port={port}")
                    elif kind == "other" and display:
                        pr._emit(
                            f"PROFILE TOOL OUTPUT stage={stage!r}> {display[:1000]}"
                        )

            now = time.monotonic()
            if now - last_heartbeat >= 2.0:
                last_heartbeat = now
                elapsed = int(now - started)
                done = len(seen_settings)
                fraction = (
                    0.98
                    if commit_seen_at is not None
                    else (
                        0.93
                        if write_seen_at is not None
                        else min(0.88, 0.88 * (done / max(planned_total, done)))
                    )
                )
                pr._notify_profile(
                    runtime_services, fraction, stage, f"{last_detail} · {elapsed}s"
                )
                pr._ui_log(
                    runtime_services, f"{stage} HEARTBEAT · {elapsed}s · {last_detail}"
                )

            if (
                proc.poll() is None
                and commit_seen_at is not None
                and now - commit_seen_at >= 15.0
            ):
                try:
                    proc.kill()
                except Exception:
                    pass
                accepted_after_commit = True
                pr._ui_log(
                    runtime_services,
                    f"{stage} · Commit bestätigt · CLI nach 15s beendet, Ablauf wird fortgesetzt",
                )
                pr._emit(
                    f"PROFILE STREAM COMMIT-GRACE stage={stage!r} port={port} action=kill-and-continue"
                )
            elif (
                proc.poll() is None
                and allow_disconnect_after_commit
                and write_seen_at is not None
                and now - write_seen_at >= 30.0
            ):
                try:
                    proc.kill()
                except Exception:
                    pass
                accepted_after_commit = True
                pr._ui_log(
                    runtime_services,
                    f"{stage} · Schreibvorgang gesendet · USB-Reaktion abgewartet · weiter",
                )
                pr._emit(
                    f"PROFILE STREAM WRITE-GRACE stage={stage!r} port={port} action=kill-and-continue"
                )

            if now >= deadline and proc.poll() is None:
                if write_seen_at is not None and allow_disconnect_after_commit:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    accepted_after_commit = True
                    pr._emit(
                        f"PROFILE STREAM TIMEOUT-AFTER-WRITE stage={stage!r} port={port} accepted=1"
                    )
                else:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    raise subprocess.TimeoutExpired(
                        cmd, timeout, output="\n".join(lines)
                    )

            if proc.poll() is not None and (reader_done or accepted_after_commit):
                break

        try:
            returncode = int(proc.wait(timeout=3))
        except Exception:
            returncode = 0 if accepted_after_commit else -1
        elapsed = time.monotonic() - started
        output = "\n".join(lines)
        post_commit_disconnect = bool(
            returncode != 0
            and allow_disconnect_after_commit
            and (commit_seen_at is not None or write_seen_at is not None)
            and any(
                marker in output.casefold()
                for marker in (
                    "disconnected",
                    "clearcommerror",
                    "permissionerror",
                    "device could not be opened",
                    "could not open port",
                    "file not found",
                )
            )
        )
        if accepted_after_commit or post_commit_disconnect:
            returncode = 0
        if returncode != 0:
            raise runtime_services.FlasherError(
                output.strip() or f"{stage} fehlgeschlagen (Exit {returncode})"
            )

        pr._notify_profile(runtime_services, 1.0, stage, f"fertig · {elapsed:.1f}s")
        pr._ui_log(
            runtime_services,
            f"{stage.upper()} ENDE · {len(seen_settings)} Werte beobachtet · Dauer={elapsed:.1f}s",
        )
        pr._emit(
            f"PROFILE STREAM V2 END stage={stage!r} port={port} exit={returncode} duration={elapsed:.2f}s "
            f"seen={len(seen_settings)}/{planned_total} owner-prewrite={int(bool(owner or owner_short))} "
            f"accepted_after_commit={int(accepted_after_commit)} post_commit_disconnect={int(post_commit_disconnect)}"
        )
        return subprocess.CompletedProcess(cmd, returncode, output, "")

    pr._stream_configure = stream_configure


def _install_drone_contract(services: Any) -> None:
    import functional_profiles as fp

    allowed_boards = {"tracker", "heltec_v4"}
    base_compat = fp.compatibility_for_board

    def compatibility(
        profile: Any, board_key: str | None, runtime_services: Any
    ) -> tuple[bool, str]:
        item = fp.functional_profile(profile)
        board = str(board_key or "").strip().lower()
        if item.identifier != "drone_repeater":
            return base_compat(item, board_key, runtime_services)
        if not board:
            return True, "Board wird beim Schreiben geprüft."
        if board not in runtime_services.BOARD_PROFILES:
            return False, f"Unbekanntes Zielboard: {board_key!r}."
        label = str(runtime_services.BOARD_PROFILES[board].get("label") or board)
        if board not in allowed_boards:
            return (
                False,
                f"DRONE REPEATER ist auf {label} gesperrt. Zulässig sind nur Heltec Tracker V1.1 und Heltec V4.",
            )
        if board == "heltec_v4":
            return (
                True,
                "Heltec V4: DRONE REPEATER ist zulässig; GPS-/Positionsfunktionen benötigen ein nutzbares externes GNSS.",
            )
        return (
            True,
            "Heltec Tracker V1.1: DRONE REPEATER ist mit internem GNSS zulässig.",
        )

    def firmware_compatibility(
        profile: Any, board_key: str | None, runtime_services: Any
    ) -> tuple[bool, str]:
        item = fp.functional_profile(profile)
        if item.identifier == "drone_repeater":
            return compatibility(item, board_key, runtime_services)
        return fp._review_v2_base_firmware_compat(item, board_key, runtime_services)

    if not hasattr(fp, "_review_v2_base_firmware_compat"):
        fp._review_v2_base_firmware_compat = fp.firmware_compatibility_for_board

    def require(profile: Any, board_key: str | None, runtime_services: Any) -> str:
        allowed, message = compatibility(profile, board_key, runtime_services)
        if not allowed:
            raise runtime_services.FlasherError(message)
        return message

    fp.compatibility_for_board = compatibility
    fp.firmware_compatibility_for_board = firmware_compatibility
    fp.require_compatible_board = require

    # Update the help/description object used by the UI without changing the
    # profile's fixed Meshtastic values.
    updated = []
    for item in fp.FUNCTIONAL_PROFILES:
        if item.identifier == "drone_repeater":
            item = replace(
                item,
                description="Drone-Repeater für Heltec Tracker V1.1 und Heltec V4; V4 benötigt externes GNSS für Position.",
                firmware_rules=(
                    "Persistente JARNSEN-Rolle wird über role_api=1 gesetzt und zurückgelesen.",
                    "Heltec V4 benötigt für GPS-/Positionsfunktionen ein nutzbares externes GNSS.",
                    "GNSS/Position, kein Schlafbetrieb, Wi-Fi aus und Service-Bluetooth bleiben Teil des Drone-Repeater-Profils.",
                ),
            )
        updated.append(item)
    fp.FUNCTIONAL_PROFILES = tuple(updated)
    fp._BY_ID = {item.identifier: item for item in fp.FUNCTIONAL_PROFILES}
    fp._BY_LABEL = {item.label: item for item in fp.FUNCTIONAL_PROFILES}
    _emit(
        "PROVISION V2 DRONE CONTRACT tracker=allow heltec_v4=allow v3/wio/tbeam/supreme=block legacy-dedicated=0"
    )


def install(services: Any) -> None:
    global _INSTALLED
    if _INSTALLED or getattr(services, "_jarnsen_review_team_provisioning_v2", False):
        return
    _INSTALLED = True

    import profile_runtime_stability_v2 as stability
    import transaction_flow

    _install_drone_contract(services)
    _install_profile_stream(services)
    _install_fast_backup(services)

    # Existing profile-only closure resolves this global at call time, so this
    # fixes persisted=0 and adds mandatory read-back without another wrapper.
    stability._sync_firmware_role = _sync_firmware_role
    stability._settle_auto_reboot = _adaptive_settle_auto_reboot

    # Full/First-Flash was the missing path. Run role persistence immediately
    # before the complete profile transaction; ROLE_SET itself does not reboot.
    base_restore_profile = services.restore_profile

    def restore_profile(port: str, profile=None):
        record = _record(services, port)
        if str(getattr(record, "kind", "") or "") == "full":
            _sync_firmware_role(services, port)
        return base_restore_profile(port, profile)

    services.restore_profile = restore_profile

    # Avoid three nested raw-identity/--info attempts during final verification.
    # A role-api preflight identity is firmware-stable across the profile reboot.
    transaction_flow._read_identity = _fast_read_identity
    base_verify_final = transaction_flow._verify_final_state

    def verify_final_state(runtime_services: Any, record: Any, info: str) -> None:
        base_verify_final(runtime_services, record, info)
        role_key = _EXPECTED_JARNSEN_ROLE_BY_PORT.get(_key(record.port), "")
        if not role_key:
            return
        line = _raw_command(
            record.port,
            "JARNSEN_TOOL_ROLE_INFO",
            expected="===JARNSEN_ROLE===",
            timeout=4.0,
            attempts=2,
            services=runtime_services,
        )
        _verify_role_line(runtime_services, role_key, line, phase="nach Neustart")
        _EXPECTED_JARNSEN_ROLE_BY_PORT.pop(_key(record.port), None)
        _emit(
            f"PROVISION V2 FINAL ROLE OK port={record.port} role={role_key} persisted=1 readback=1"
        )

    transaction_flow._verify_final_state = verify_final_state

    services._jarnsen_review_team_provisioning_v2 = True
    services._jarnsen_full_flash_role_api = True
    services._jarnsen_role_api_readback = True
    services._jarnsen_profile_names_same_process = True
    services._jarnsen_profile_count_owner_pair = True
    services._jarnsen_adaptive_reboot_wait = True
    services._jarnsen_fast_final_identity = True
    _emit(
        "REVIEW TEAM PROVISIONING V2 installed full-role-api=1 profile-role-api=1 "
        "role-set-readback=1 owner-prewrite-same-process=1 owner-pair-count=1 "
        "backup-921600-first=1 adaptive-reboot=1 fast-final-identity=1"
    )
