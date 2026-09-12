from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from profile_utils import summary_from_info_text, summary_from_profile_file

_FULL_SEQUENCE = (
    "backup",
    "firmware",
    "profile",
    "names",
    "reboot",
    "final_verify",
    "profile_verify",
)
_PROFILE_SEQUENCE = ("profile", "names", "reboot", "final_verify", "profile_verify")


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _key(port: str) -> str:
    return str(port or "").strip().upper()


def _norm(value: Any) -> str:
    return str(value or "").strip().casefold()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


def _safe_filename(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    return text.strip("-_.") or "device"


@dataclass
class TransactionRecord:
    transaction_id: str
    kind: str
    port: str
    board_key: str = ""
    started_at: str = ""
    updated_at: str = ""
    status: str = "running"
    current_stage: str = ""
    completed: list[str] = field(default_factory=list)
    failed_stage: str = ""
    error: str = ""
    expected_profile: str = ""
    expected_profile_sha256: str = ""
    expected_role: str = ""
    expected_long_name: str = ""
    expected_short_name: str = ""
    expected_firmware_version: str = ""
    expected_firmware_build: int | None = None
    expected_artifact: str = ""
    backup_path: str = ""
    final_board: str = ""
    final_role: str = ""
    final_long_name: str = ""
    final_short_name: str = ""
    final_firmware_version: str = ""
    final_firmware_build: int | None = None

    @property
    def sequence(self) -> tuple[str, ...]:
        return _FULL_SEQUENCE if self.kind == "full" else _PROFILE_SEQUENCE

    def next_stage(self) -> str:
        for stage in self.sequence:
            if stage not in self.completed:
                return stage
        return ""


class TransactionManager:
    def __init__(self, services: Any) -> None:
        self.services = services
        self.root = Path(services.PATHS.root) / "transactions"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._active: dict[str, TransactionRecord] = {}
        self._paths: dict[str, Path] = {}

    def _new(self, port: str, kind: str, board_key: str = "") -> TransactionRecord:
        now = datetime.now()
        txid = f"{now.strftime('%Y%m%d-%H%M%S')}-{_safe_filename(port)}-{kind}"
        record = TransactionRecord(
            transaction_id=txid,
            kind=kind,
            port=str(port),
            board_key=str(board_key or ""),
            started_at=now.isoformat(timespec="seconds"),
            updated_at=now.isoformat(timespec="seconds"),
        )
        key = _key(port)
        with self._lock:
            self._active[key] = record
            self._paths[key] = self.root / f"{txid}.json"
        self._save(record)
        _emit(
            f"TRANSACTION START id={txid} kind={kind} port={port} board={board_key!r}"
        )
        return record

    def ensure(self, port: str, kind: str, board_key: str = "") -> TransactionRecord:
        key = _key(port)
        with self._lock:
            record = self._active.get(key)
        if record is None or record.status not in {"running", "failed"}:
            return self._new(port, kind, board_key)
        if board_key and not record.board_key:
            record.board_key = str(board_key)
            self._save(record)
        return record

    def active(self, port: str) -> TransactionRecord | None:
        with self._lock:
            return self._active.get(_key(port))

    def _save(self, record: TransactionRecord) -> None:
        record.updated_at = datetime.now().isoformat(timespec="seconds")
        key = _key(record.port)
        with self._lock:
            path = self._paths.get(key)
            if path is None:
                path = self.root / f"{record.transaction_id}.json"
                self._paths[key] = path
            payload = json.dumps(asdict(record), ensure_ascii=False, indent=2)
            path.write_text(payload + "\n", encoding="utf-8")

    def stage_start(self, record: TransactionRecord, stage: str) -> None:
        record.current_stage = stage
        record.status = "running"
        record.failed_stage = ""
        record.error = ""
        self._save(record)
        _emit(
            f"TRANSACTION STAGE START id={record.transaction_id} stage={stage} "
            f"resume_from={record.next_stage()!r}"
        )

    def stage_ok(self, record: TransactionRecord, stage: str) -> None:
        if stage not in record.completed:
            record.completed.append(stage)
        record.current_stage = ""
        record.failed_stage = ""
        record.error = ""
        record.status = "running"
        self._save(record)
        _emit(
            f"TRANSACTION STAGE OK id={record.transaction_id} stage={stage} "
            f"completed={record.completed!r} next={record.next_stage()!r}"
        )

    def stage_fail(
        self, record: TransactionRecord, stage: str, exc: BaseException
    ) -> None:
        record.current_stage = ""
        record.failed_stage = stage
        record.error = f"{type(exc).__name__}: {exc}"
        record.status = "failed"
        self._save(record)
        _emit(
            f"TRANSACTION STAGE FAIL id={record.transaction_id} stage={stage} "
            f"resume_from={record.next_stage()!r} error={record.error[:700]!r}"
        )

    def release(self, record: TransactionRecord, reason: str) -> None:
        key = _key(record.port)
        released = False
        with self._lock:
            if self._active.get(key) is record:
                self._active.pop(key, None)
                released = True
            self._paths.pop(key, None)
        _emit(
            f"TRANSACTION RELEASE id={record.transaction_id} port={record.port} "
            f"status={record.status!r} reason={reason!r} released={int(released)}"
        )

    def complete(self, record: TransactionRecord) -> None:
        record.status = "success"
        record.current_stage = ""
        record.failed_stage = ""
        record.error = ""
        self._save(record)
        _emit(
            f"TRANSACTION COMPLETE id={record.transaction_id} kind={record.kind} "
            f"completed={record.completed!r}"
        )
        self.release(record, "success")

    def resume_plan(self, port: str | None = None) -> dict[str, Any] | None:
        record = self.active(port) if port else None
        if record is None:
            wanted_port = _key(port) if port else ""
            candidates = sorted(
                self.root.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
            )
            for path in candidates:
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if data.get("status") != "failed":
                        continue
                    if wanted_port and _key(data.get("port", "")) != wanted_port:
                        continue
                    sequence = (
                        _FULL_SEQUENCE
                        if data.get("kind") == "full"
                        else _PROFILE_SEQUENCE
                    )
                    completed = list(data.get("completed") or [])
                    next_stage = next(
                        (stage for stage in sequence if stage not in completed), ""
                    )
                    return {
                        "transaction_id": data.get("transaction_id", ""),
                        "port": data.get("port", ""),
                        "board_key": data.get("board_key", ""),
                        "kind": data.get("kind", ""),
                        "completed": completed,
                        "failed_stage": data.get("failed_stage", ""),
                        "error": data.get("error", ""),
                        "resume_from": next_stage,
                    }
                except Exception:
                    continue
            return None

        return {
            "transaction_id": record.transaction_id,
            "port": record.port,
            "board_key": record.board_key,
            "kind": record.kind,
            "completed": list(record.completed),
            "failed_stage": record.failed_stage,
            "error": record.error,
            "resume_from": record.next_stage(),
        }


def _selected_role_for_restore(services: Any, port: str, profile: Path) -> str:
    try:
        import write_choice_guard

        selected = str(
            write_choice_guard._ROLE_OVERRIDE_BY_PORT.get(_key(port), "") or ""
        ).strip()
        if selected:
            return selected
    except Exception:
        pass
    try:
        return str(summary_from_profile_file(profile).role or "").strip()
    except Exception:
        return ""


def _read_identity(services: Any, port: str) -> Any:
    query = getattr(services, "query_jarnsen_identity", None)
    if not callable(query):
        return None
    last = None
    for attempt in range(1, 4):
        try:
            identity = query(port, timeout=3.2)
            if identity is not None:
                last = identity
                if bool(getattr(identity, "is_jarnsen", False)):
                    return identity
        except Exception as exc:
            _emit(
                f"TRANSACTION IDENTITY RETRY port={port} attempt={attempt}/3 "
                f"error={type(exc).__name__}:{str(exc)[:300]}"
            )
        if attempt < 3:
            time.sleep(0.6)
    return last


def _verify_final_state(services: Any, record: TransactionRecord, info: str) -> None:
    summary = summary_from_info_text(info)
    detected = services.detect_board_from_text(info)

    identity = None
    if record.expected_firmware_version or not detected:
        identity = _read_identity(services, record.port)
        if not detected and identity is not None:
            hardware = str(getattr(identity, "hardware", "") or "")
            if hardware:
                detected = services.detect_board_from_text(
                    f"hardware: {hardware}\nJARNSEN-MESH"
                )

    if record.board_key:
        if not detected:
            raise services.FlasherError(
                f"Endprüfung: Board {services.BOARD_PROFILES[record.board_key]['label']} "
                "konnte nach dem Neustart nicht eindeutig bestätigt werden."
            )
        if detected != record.board_key:
            raise services.FlasherError(
                "Endprüfung: falsches Board. "
                f"Erwartet {services.BOARD_PROFILES[record.board_key]['label']}, "
                f"gelesen {services.BOARD_PROFILES.get(detected, {}).get('label', detected)}."
            )

    if record.expected_role:
        actual_role = str(summary.role or "").strip()
        if _norm(actual_role) != _norm(record.expected_role):
            raise services.FlasherError(
                f"Endprüfung: Rolle erwartet {record.expected_role}, "
                f"gelesen {actual_role or 'unbekannt'}."
            )
        record.final_role = actual_role

    if record.expected_long_name or record.expected_short_name:
        actual_long = str(summary.long_name or "").strip()
        actual_short = str(summary.short_name or "").strip()
        if (
            actual_long != record.expected_long_name
            or actual_short != record.expected_short_name
        ):
            raise services.FlasherError(
                "Endprüfung: Gerätenamen stimmen nach Neustart nicht. "
                f"Erwartet {record.expected_long_name!r}/{record.expected_short_name!r}, "
                f"gelesen {actual_long!r}/{actual_short!r}."
            )
        record.final_long_name = actual_long
        record.final_short_name = actual_short

    if record.expected_firmware_version:
        if identity is None:
            identity = _read_identity(services, record.port)
        if identity is None or not bool(getattr(identity, "is_jarnsen", False)):
            raise services.FlasherError(
                "Endprüfung: JARNSEN-Firmwareidentität konnte nach dem Flash nicht bestätigt werden."
            )
        actual_version = str(getattr(identity, "version", "") or "").strip()
        actual_build_raw = getattr(identity, "build", None)
        try:
            actual_build = (
                int(actual_build_raw) if actual_build_raw is not None else None
            )
        except Exception:
            actual_build = None
        if actual_version and _norm(actual_version) != _norm(
            record.expected_firmware_version
        ):
            raise services.FlasherError(
                f"Endprüfung: Firmwareversion erwartet {record.expected_firmware_version}, "
                f"gelesen {actual_version}."
            )
        if (
            record.expected_firmware_build is not None
            and actual_build is not None
            and actual_build != record.expected_firmware_build
        ):
            raise services.FlasherError(
                f"Endprüfung: Firmware-Build erwartet {record.expected_firmware_build}, "
                f"gelesen {actual_build}."
            )
        record.final_firmware_version = actual_version
        record.final_firmware_build = actual_build

    record.final_board = detected or ""


def _profile_for_final_verify(
    services: Any,
    record: TransactionRecord,
    profile: Path | None,
) -> tuple[Path, Path | None]:
    source = (
        Path(profile)
        if profile is not None
        else Path(record.expected_profile or services.PATHS.active_profile)
    )
    expected_role = str(record.expected_role or "").strip()
    if not expected_role:
        return source, None

    try:
        profile_role = str(summary_from_profile_file(source).role or "").strip()
    except Exception:
        profile_role = ""
    if _norm(profile_role) == _norm(expected_role):
        return source, None

    try:
        data = (
            yaml.safe_load(source.read_text(encoding="utf-8", errors="replace")) or {}
        )
    except Exception as exc:
        raise services.FlasherError(
            f"Endprüfung: ausgewählte Rolle konnte nicht in den Profilvertrag übernommen werden: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise services.FlasherError("Endprüfung: Profil ist kein gültiges YAML-Objekt.")

    root = data.get("config")
    if not isinstance(root, dict):
        root = data
    device = root.get("device")
    if not isinstance(device, dict):
        device = {}
        root["device"] = device
    device["role"] = expected_role

    work = Path(services.PATHS.root) / "profile-verify"
    work.mkdir(parents=True, exist_ok=True)
    target = work / f"{_safe_filename(record.port)}-{time.time_ns()}-verify.yaml"
    target.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    _emit(
        f"TRANSACTION PROFILE VERIFY OVERRIDE id={record.transaction_id} "
        f"profile_role={profile_role!r} expected_role={expected_role!r} temp={target.name!r}"
    )
    return target, target


def install(services: Any) -> None:
    """Persist and verify one all-board transaction around full/profile-only writes."""
    if getattr(services, "_jarnsen_transaction_flow_v1", False):
        return

    manager = TransactionManager(services)
    services.flash_transactions = manager
    services.flash_transaction_resume_plan = manager.resume_plan
    services.flash_transaction_release = manager.release

    base_backup_flash = services.backup_flash
    base_flash_bundle = services.flash_bundle
    base_restore_profile = services.restore_profile
    base_set_names = services.set_names
    base_reboot_node = services.reboot_node
    base_verify_node = services.verify_node
    base_verify_written_profile = services.verify_written_profile

    def backup_flash(port: str, board_key: str):
        record = manager.ensure(port, "full", board_key)
        manager.stage_start(record, "backup")
        try:
            result = base_backup_flash(port, board_key)
            record.backup_path = str(result)
            manager.stage_ok(record, "backup")
            return result
        except Exception as exc:
            manager.stage_fail(record, "backup", exc)
            raise

    def flash_bundle(port: str, bundle: Any, log=None):
        record = manager.ensure(
            port, "full", str(getattr(bundle, "board_key", "") or "")
        )
        record.expected_firmware_version = str(
            getattr(bundle, "version", "") or ""
        ).strip()
        try:
            record.expected_firmware_build = (
                int(getattr(bundle, "run_number", 0) or 0) or None
            )
        except Exception:
            record.expected_firmware_build = None
        record.expected_artifact = str(getattr(bundle, "artifact_name", "") or "")
        manager.stage_start(record, "firmware")
        try:
            result = base_flash_bundle(port, bundle, log=log)
            manager.stage_ok(record, "firmware")
            return result
        except Exception as exc:
            manager.stage_fail(record, "firmware", exc)
            raise

    def restore_profile(port: str, profile=None):
        record = manager.active(port)
        if record is None:
            record = manager.ensure(port, "profile_only")
        profile_path = (
            Path(profile)
            if profile is not None
            else Path(services.PATHS.active_profile)
        )
        record.expected_profile = str(profile_path)
        if profile_path.exists():
            try:
                record.expected_profile_sha256 = _sha256(profile_path)
            except Exception:
                record.expected_profile_sha256 = ""
        record.expected_role = _selected_role_for_restore(services, port, profile_path)
        manager.stage_start(record, "profile")
        try:
            result = base_restore_profile(port, profile)
            manager.stage_ok(record, "profile")
            return result
        except Exception as exc:
            manager.stage_fail(record, "profile", exc)
            raise

    def set_names(port: str, long_name: str, short_name: str):
        record = manager.active(port)
        if record is None:
            record = manager.ensure(port, "profile_only")
        record.expected_long_name = str(long_name or "").strip()
        record.expected_short_name = str(short_name or "").strip()
        manager.stage_start(record, "names")
        try:
            result = base_set_names(port, long_name, short_name)
            manager.stage_ok(record, "names")
            return result
        except Exception as exc:
            manager.stage_fail(record, "names", exc)
            raise

    def reboot_node(port: str):
        record = manager.active(port)
        if record is None:
            return base_reboot_node(port)
        manager.stage_start(record, "reboot")
        try:
            result = base_reboot_node(port)
            manager.stage_ok(record, "reboot")
            return result
        except Exception as exc:
            manager.stage_fail(record, "reboot", exc)
            raise

    def verify_node(port: str, expected_board: str | None = None) -> str:
        record = manager.active(port)
        try:
            info = base_verify_node(port, expected_board=expected_board)
        except Exception as exc:
            if record is not None:
                manager.stage_fail(record, "final_verify", exc)
            raise

        if record is None:
            return info

        if expected_board:
            record.board_key = str(expected_board)
        manager.stage_start(record, "final_verify")
        try:
            _verify_final_state(services, record, info)
            manager.stage_ok(record, "final_verify")
            _emit(
                f"TRANSACTION NODE VERIFY OK id={record.transaction_id} board={record.final_board!r} "
                f"role={record.final_role!r} names={record.final_long_name!r}/{record.final_short_name!r} "
                f"firmware={record.final_firmware_version!r} build={record.final_firmware_build!r} "
                "next='profile_verify'"
            )
        except Exception as exc:
            manager.stage_fail(record, "final_verify", exc)
            raise
        return info

    def verify_written_profile(port: str, profile=None, board_key: str | None = None):
        record = manager.active(port)
        if record is None:
            return base_verify_written_profile(port, profile, board_key=board_key)

        manager.stage_start(record, "profile_verify")
        temp_path: Path | None = None
        try:
            verify_path, temp_path = _profile_for_final_verify(
                services,
                record,
                Path(profile) if profile is not None else None,
            )
            result = base_verify_written_profile(
                port,
                verify_path,
                board_key=board_key or record.board_key or None,
            )
            manager.stage_ok(record, "profile_verify")
            manager.complete(record)
            _emit(
                f"TRANSACTION VERIFY OK id={record.transaction_id} board={record.final_board!r} "
                f"role={record.final_role!r} names={record.final_long_name!r}/{record.final_short_name!r} "
                f"firmware={record.final_firmware_version!r} build={record.final_firmware_build!r} "
                "profile-differences=0 live-slot-released=1"
            )
            return result
        except Exception as exc:
            manager.stage_fail(record, "profile_verify", exc)
            raise
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except Exception:
                    pass

    services.backup_flash = backup_flash
    services.flash_bundle = flash_bundle
    services.restore_profile = restore_profile
    services.set_names = set_names
    services.reboot_node = reboot_node
    services.verify_node = verify_node
    services.verify_written_profile = verify_written_profile
    services._jarnsen_transaction_flow_v1 = True
    services._jarnsen_transaction_resume_state = True
    services._jarnsen_transaction_final_verify = True
    services._jarnsen_transaction_profile_verify = True
    services._jarnsen_transaction_release_after_success = True
    _emit(
        "TRANSACTION FLOW installed all-boards=1 persistent-state=1 resume-plan=1 "
        "post-reboot-board-role-name-firmware-verify=1 profile-contract-final-gate=1 "
        "selected-role-profile-verify=1 release-after-success=1 resume-port-isolation=1"
    )
