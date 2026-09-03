from __future__ import annotations

import copy
import os
import queue
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any


def _emit(message: str) -> None:
    try:
        import diagnostics
        diagnostics._emit(message)
    except Exception:
        pass


def _ui_log(services: Any, message: str) -> None:
    callback = getattr(services, "_jarnsen_ui_log_callback", None)
    if callable(callback):
        try:
            callback(str(message))
        except Exception:
            pass


def _notify_profile(services: Any, fraction: float, stage: str, detail: str = "") -> None:
    callback = getattr(services, "_jarnsen_profile_progress_callback", None)
    if callable(callback):
        try:
            callback(max(0.0, min(1.0, float(fraction))), str(stage), str(detail))
        except Exception as exc:
            _emit(f"PROFILE UI CALLBACK ERROR type={type(exc).__name__} message={exc}")


def _decode(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _pop_case_insensitive(mapping: dict[str, Any], wanted: str) -> Any:
    wanted_norm = wanted.replace("_", "").replace("-", "").lower()
    for key in list(mapping):
        norm = str(key).replace("_", "").replace("-", "").lower()
        if norm == wanted_norm:
            return mapping.pop(key)
    return None


def _remove_device_identity(mapping: dict[str, Any]) -> list[str]:
    removed: list[str] = []
    for root_name in ("config", None):
        root = mapping.get(root_name) if root_name else mapping
        if not isinstance(root, dict):
            continue
        security = root.get("security")
        if not isinstance(security, dict):
            continue
        for key in list(security):
            norm = str(key).replace("_", "").replace("-", "").lower()
            if norm in {"privatekey", "publickey"}:
                security.pop(key, None)
                removed.append(f"{root_name + '.' if root_name else ''}security.{key}")
    return removed


def _remove_owner_fields(mapping: dict[str, Any]) -> None:
    for key in list(mapping):
        norm = str(key).replace("_", "").replace("-", "").lower()
        if norm in {"owner", "ownershort", "longname", "shortname"}:
            mapping.pop(key, None)


def split_profile_data(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """Split ordinary settings from role/power activation."""
    safe = copy.deepcopy(data)
    final: dict[str, Any] = {}
    removed_identity = _remove_device_identity(safe)
    _remove_owner_fields(safe)

    def split_root(root_key: str | None) -> None:
        safe_root = safe.get(root_key) if root_key else safe
        if not isinstance(safe_root, dict):
            return
        final_root: dict[str, Any] = {}

        device = safe_root.get("device")
        if isinstance(device, dict):
            role = _pop_case_insensitive(device, "role")
            if role is not None:
                final_root.setdefault("device", {})["role"] = role
            if not device:
                safe_root.pop("device", None)

        power = safe_root.get("power")
        if isinstance(power, dict):
            for key in list(power):
                norm = str(key).replace("_", "").replace("-", "").lower()
                if norm == "ispowersaving":
                    final_root.setdefault("power", {})[key] = power.pop(key)
            if not power:
                safe_root.pop("power", None)

        if final_root:
            if root_key:
                final[root_key] = final_root
            else:
                final.update(final_root)

    split_root("config")
    split_root(None)

    if isinstance(safe.get("config"), dict) and not safe["config"]:
        safe.pop("config", None)
    return safe, final, removed_identity


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    import yaml
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _final_expectations(final: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    roots: list[dict[str, Any]] = []
    config = final.get("config")
    if isinstance(config, dict):
        roots.append(config)
    roots.append(final)
    for root in roots:
        device = root.get("device")
        if isinstance(device, dict) and "role" in device and "role" not in result:
            result["role"] = device.get("role")
        power = root.get("power")
        if isinstance(power, dict) and "power_saving" not in result:
            for key, value in power.items():
                norm = str(key).replace("_", "").replace("-", "").lower()
                if norm == "ispowersaving":
                    result["power_saving"] = value
                    break
    return result


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().lower()
    if text in {"true", "1", "yes", "on"}:
        return True
    if text in {"false", "0", "no", "off"}:
        return False
    return None


def _local_role(info: str) -> str:
    metadata = re.search(r'(?im)^Metadata:\s*\{[^\n]*?"role"\s*:\s*"([^"]+)"', info or "")
    if metadata:
        return metadata.group(1).strip()
    prefs = re.search(r'(?is)Preferences:\s*\{.*?"device"\s*:\s*\{.*?"role"\s*:\s*"([^"]+)"', info or "")
    return prefs.group(1).strip() if prefs else ""


def _local_power_saving(info: str) -> bool | None:
    match = re.search(r'"isPowerSaving"\s*:\s*(true|false)', info or "", re.IGNORECASE)
    if not match:
        match = re.search(r'"is_power_saving"\s*:\s*(true|false)', info or "", re.IGNORECASE)
    if not match:
        return None
    return match.group(1).lower() == "true"


def _sensitive_path(path: str) -> bool:
    norm = path.lower().replace("-", "_")
    tokens = ("password", "private", "public_key", "private_key", "psk", "admin", "token", "secret", "fixed_pin", "channel.url")
    return any(token in norm for token in tokens)


def _safe_value(path: str, value: str) -> str:
    return "<geschützt>" if _sensitive_path(path) else value.strip()


def _planned_leaf_paths(value: Any, prefix: tuple[str, ...] = ()) -> list[str]:
    """Approximate the individual values meshtastic --configure will report."""
    result: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            name = str(key)
            # Meshtastic prints config/module_config children without those wrapper names.
            next_prefix = prefix if not prefix and name in {"config", "module_config"} else (*prefix, name)
            result.extend(_planned_leaf_paths(child, next_prefix))
        return result
    if isinstance(value, list):
        # Channel arrays are emitted by the CLI as one channel URL operation.
        if prefix and any(part.lower().startswith("channel") for part in prefix):
            return ["channel.url"]
        for index, child in enumerate(value):
            result.extend(_planned_leaf_paths(child, (*prefix, str(index))))
        return result
    if prefix:
        result.append(".".join(prefix))
    return result


def _describe_config_line(line: str) -> tuple[str | None, str | None, str | None]:
    """Return (kind, key, safe display text)."""
    stripped = line.strip()
    match = re.search(r"\bSet\s+([^\s]+)\s+to\s+(.*)$", stripped)
    if match:
        key = match.group(1).strip()
        value = _safe_value(key, match.group(2))
        return "setting", key.lower(), f"{key} = {value}"

    match = re.search(r"\bSetting\s+channel\s+url\s+to\s+(.+)$", stripped, re.IGNORECASE)
    if match:
        return "setting", "channel.url", "channel.url = <geschützt>"

    match = re.search(r"\bSetting\s+canned\s+message\s+messages\s+to\s+(.+)$", stripped, re.IGNORECASE)
    if match:
        return "setting", "canned_message.messages", f"canned_message.messages = {match.group(1).strip()}"

    if "Writing modified configuration to device" in stripped:
        return "write", None, "Änderungen an Node übertragen"
    if "beginSettingsTransaction" in stripped or "open a transaction to edit settings" in stripped:
        return "transaction", None, "Konfigurations-Transaktion geöffnet"
    if "commitSettingsTransaction" in stripped or "commit open transaction" in stripped:
        return "commit", None, "Konfigurations-Transaktion bestätigen"
    if "Connected to radio" in stripped:
        return "connect", None, "Mit Node verbunden"
    if stripped:
        return "other", None, stripped
    return None, None, None


def _stream_configure(
    services: Any,
    port: str,
    profile_path: Path,
    profile_data: dict[str, Any],
    *,
    timeout: int,
    stage: str,
    allow_disconnect_after_commit: bool,
) -> subprocess.CompletedProcess[str]:
    planned_paths = _planned_leaf_paths(profile_data)
    planned_total = max(1, len(set(planned_paths)))
    cmd = services.helper_command() + ["meshtastic", "--port", port, "--configure", str(profile_path)]
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    _emit(
        f"PROFILE STREAM START stage={stage!r} port={port} planned={planned_total} timeout={timeout}s "
        f"allow_disconnect_after_commit={int(allow_disconnect_after_commit)}"
    )
    _ui_log(services, f"{stage.upper()} START · {planned_total} geplante Werte · Port={port}")
    _notify_profile(services, 0.0, stage, f"0/{planned_total} · Verbindung aufbauen")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        env=env,
        startupinfo=services._startupinfo(),
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

    threading.Thread(target=reader, name=f"profile-output-{stage}", daemon=True).start()

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
                kind, key, display = _describe_config_line(line)
                if kind == "setting" and key and display:
                    seen_settings.add(key)
                    done = len(seen_settings)
                    fraction = min(0.88, 0.88 * (done / max(planned_total, done)))
                    last_detail = f"{done}/{planned_total} · {display}"
                    _notify_profile(services, fraction, stage, last_detail)
                    _ui_log(services, f"{stage} · {done}/{planned_total} · {display}")
                    _emit(f"PROFILE SETTING stage={stage!r} index={done}/{planned_total} key={key!r}")
                elif kind == "connect" and display:
                    last_detail = display
                    _notify_profile(services, 0.03, stage, display)
                    _ui_log(services, f"{stage} · {display}")
                elif kind == "write" and display:
                    write_seen_at = time.monotonic()
                    last_detail = display
                    _notify_profile(services, 0.93, stage, display)
                    _ui_log(services, f"{stage} · {display}")
                    _emit(f"PROFILE WRITE SENT stage={stage!r} port={port}")
                elif kind == "transaction" and display:
                    _notify_profile(services, 0.95, stage, display)
                    _ui_log(services, f"{stage} · {display}")
                elif kind == "commit" and display:
                    commit_seen_at = time.monotonic()
                    last_detail = display
                    _notify_profile(services, 0.98, stage, display)
                    _ui_log(services, f"{stage} · {display}")
                    _emit(f"PROFILE COMMIT SEEN stage={stage!r} port={port}")
                elif kind == "other" and display:
                    # Keep verbose diagnostics but avoid echoing arbitrary raw values into the UI.
                    _emit(f"PROFILE TOOL OUTPUT stage={stage!r}> {display[:1000]}")

        now = time.monotonic()
        if now - last_heartbeat >= 2.0:
            last_heartbeat = now
            elapsed = int(now - started)
            done = len(seen_settings)
            if commit_seen_at is not None:
                fraction = 0.98
            elif write_seen_at is not None:
                fraction = 0.93
            else:
                fraction = min(0.88, 0.88 * (done / max(planned_total, done)))
            _notify_profile(services, fraction, stage, f"{last_detail} · {elapsed}s")
            _ui_log(services, f"{stage} HEARTBEAT · {elapsed}s · {last_detail}")

        # Some Meshtastic versions successfully commit and then never close their CLI
        # because USB changes underneath them. Do not sit at 79% for five minutes.
        if proc.poll() is None and commit_seen_at is not None and now - commit_seen_at >= 15.0:
            try:
                proc.kill()
            except Exception:
                pass
            accepted_after_commit = True
            _ui_log(services, f"{stage} · Commit bestätigt · CLI nach 15s beendet, Ablauf wird fortgesetzt")
            _emit(f"PROFILE STREAM COMMIT-GRACE stage={stage!r} port={port} action=kill-and-continue")
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
            _ui_log(services, f"{stage} · Schreibvorgang gesendet · USB-Reaktion abgewartet · weiter")
            _emit(f"PROFILE STREAM WRITE-GRACE stage={stage!r} port={port} action=kill-and-continue")

        if now >= deadline and proc.poll() is None:
            if write_seen_at is not None and allow_disconnect_after_commit:
                try:
                    proc.kill()
                except Exception:
                    pass
                accepted_after_commit = True
                _emit(f"PROFILE STREAM TIMEOUT-AFTER-WRITE stage={stage!r} port={port} accepted=1")
            else:
                try:
                    proc.kill()
                except Exception:
                    pass
                raise subprocess.TimeoutExpired(cmd, timeout, output="\n".join(lines))

        if proc.poll() is not None and (reader_done or accepted_after_commit):
            break

    try:
        returncode = int(proc.wait(timeout=3))
    except Exception:
        returncode = 0 if accepted_after_commit else -1
    elapsed = time.monotonic() - started
    output = "\n".join(lines)

    if accepted_after_commit:
        returncode = 0
    if returncode != 0:
        raise services.FlasherError(output.strip() or f"{stage} fehlgeschlagen (Exit {returncode})")

    _notify_profile(services, 1.0, stage, f"fertig · {elapsed:.1f}s")
    _ui_log(services, f"{stage.upper()} ENDE · {len(seen_settings)} Werte beobachtet · Dauer={elapsed:.1f}s")
    _emit(
        f"PROFILE STREAM END stage={stage!r} port={port} exit={returncode} duration={elapsed:.2f}s "
        f"seen={len(seen_settings)}/{planned_total} accepted_after_commit={int(accepted_after_commit)}"
    )
    return subprocess.CompletedProcess(cmd, returncode, output, "")


def install(services: Any) -> None:
    base_reboot_node = services.reboot_node
    base_verify_node = services.verify_node
    pending_final: dict[str, Path] = {}
    pending_final_data: dict[str, dict[str, Any]] = {}
    expected_final: dict[str, dict[str, Any]] = {}
    work_dir = services.PATHS.root / "restore-work"
    work_dir.mkdir(parents=True, exist_ok=True)

    def restore_profile(port: str, profile: Path | None = None) -> None:
        source = Path(profile or services.PATHS.active_profile)
        if not source.exists():
            raise services.FlasherError("Kein aktives Grundeinstellungs-Profil vorhanden.")
        try:
            import yaml
            raw = yaml.safe_load(source.read_text(encoding="utf-8", errors="replace")) or {}
        except Exception as exc:
            raise services.FlasherError(f"Profil konnte nicht als YAML gelesen werden: {exc}") from exc
        if not isinstance(raw, dict):
            raise services.FlasherError("Profil hat kein gültiges YAML-Objekt als Wurzel.")

        safe, final, removed_identity = split_profile_data(raw)
        stamp = str(int(time.time() * 1000))
        safe_path = work_dir / f"{port}-{stamp}-safe.yaml"
        final_path = work_dir / f"{port}-{stamp}-final.yaml"
        _write_yaml(safe_path, safe)
        if final:
            _write_yaml(final_path, final)

        _emit(
            f"PROFILE RESTORE SPLIT port={port} source={source.name!r} safe={safe_path.name!r} "
            f"final_present={bool(final)} identity_fields_removed={removed_identity!r}"
        )
        try:
            if safe:
                _stream_configure(
                    services,
                    port,
                    safe_path,
                    safe,
                    timeout=300,
                    stage="Grundeinstellungen",
                    allow_disconnect_after_commit=True,
                )
            else:
                _notify_profile(services, 1.0, "Grundeinstellungen", "keine Werte")
                _emit(f"PROFILE RESTORE SAFE SKIP port={port} reason=empty")
        except subprocess.TimeoutExpired as exc:
            out = "\n".join(filter(None, (_decode(exc.stdout), _decode(exc.stderr))))
            _emit(f"PROFILE RESTORE SAFE TIMEOUT port={port} output_chars={len(out)}")
            raise services.FlasherError(
                "Grundeinstellungen konnten nicht vollständig übertragen werden: "
                "der USB-Konfigurationsschritt hat das Zeitlimit erreicht."
            ) from exc
        finally:
            try:
                safe_path.unlink(missing_ok=True)
            except Exception:
                pass

        key = port.upper()
        old = pending_final.pop(key, None)
        pending_final_data.pop(key, None)
        if old:
            try:
                old.unlink(missing_ok=True)
            except Exception:
                pass
        expected_final.pop(key, None)
        if final:
            pending_final[key] = final_path
            pending_final_data[key] = final
            expected_final[key] = _final_expectations(final)
            _emit(
                f"PROFILE RESTORE FINAL DEFERRED port={port} file={final_path.name!r} "
                f"expect={expected_final[key]!r}"
            )
        else:
            try:
                final_path.unlink(missing_ok=True)
            except Exception:
                pass

    def reboot_node(port: str) -> None:
        key = port.upper()
        final_path = pending_final.pop(key, None)
        final_data = pending_final_data.pop(key, {})
        if final_path is None:
            return base_reboot_node(port)

        timed_out = False
        try:
            _stream_configure(
                services,
                port,
                final_path,
                final_data,
                timeout=45,
                stage="Rolle/Power aktivieren",
                allow_disconnect_after_commit=True,
            )
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            out = "\n".join(filter(None, (_decode(exc.stdout), _decode(exc.stderr))))
            _emit(f"PROFILE RESTORE FINAL EXPECTED DISCONNECT port={port} output_chars={len(out)}")
        finally:
            try:
                final_path.unlink(missing_ok=True)
            except Exception:
                pass

        if not timed_out:
            base_reboot_node(port)

    def verify_node(port: str, expected_board: str | None = None) -> str:
        info = base_verify_node(port, expected_board=expected_board)
        key = port.upper()
        expected = expected_final.get(key)
        if not expected:
            return info

        wanted_role = expected.get("role")
        if isinstance(wanted_role, str) and wanted_role.strip():
            actual_role = _local_role(info)
            if actual_role.upper() != wanted_role.strip().upper():
                raise services.FlasherError(
                    f"Endprüfung: Rolle nicht übernommen. Erwartet {wanted_role}, gelesen {actual_role or 'unbekannt'}."
                )

        if "power_saving" in expected:
            wanted_power = _as_bool(expected.get("power_saving"))
            actual_power = _local_power_saving(info)
            if wanted_power is not None and actual_power is not wanted_power:
                raise services.FlasherError(
                    "Endprüfung: Power-Saving nicht korrekt übernommen. "
                    f"Erwartet {wanted_power}, gelesen {actual_power}."
                )

        _emit(
            f"PROFILE RESTORE FINAL VERIFY OK port={port} expected={expected!r} "
            f"role={_local_role(info)!r} power_saving={_local_power_saving(info)!r}"
        )
        expected_final.pop(key, None)
        return info

    services.restore_profile = restore_profile
    services.reboot_node = reboot_node
    services.verify_node = verify_node

    _emit(
        "PROFILE RESTORE installed staged=1 live-setting-progress=1 heartbeat=2s commit-grace=15s "
        "safe-first=1 role-power-last=1 device-identity-clone=0 final-role-power-verify=1"
    )
