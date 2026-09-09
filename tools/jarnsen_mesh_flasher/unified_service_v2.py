from __future__ import annotations

import re
import struct
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from tkinter import messagebox
from typing import Any


_LOCK_GUARD = threading.Lock()
_PORT_LOCKS: dict[str, threading.RLock] = {}
_IDENTITY_CACHE: dict[str, tuple[float, Any]] = {}
_IDENTITY_CACHE_TTL = 4.0


def _emit(message: str) -> None:
    try:
        import diagnostics
        diagnostics._emit(message)
    except Exception:
        pass


def _port_key(port: str) -> str:
    return str(port or "").strip().upper()


def _lock_for(port: str) -> threading.RLock:
    key = _port_key(port)
    with _LOCK_GUARD:
        return _PORT_LOCKS.setdefault(key, threading.RLock())


@contextmanager
def _serial_guard(port: str):
    lock = _lock_for(port)
    lock.acquire()
    try:
        yield
    finally:
        lock.release()


def _parse_partition_table(factory: bytes) -> list[dict[str, int | str]]:
    table_offset = 0x8000
    if len(factory) < table_offset + 32 or factory[table_offset:table_offset + 2] != b"\xaa\x50":
        raise ValueError("ESP32-Partitionstabelle bei 0x8000 fehlt oder ist ungültig")
    parts: list[dict[str, int | str]] = []
    raw_table = factory[table_offset:table_offset + 0x1000]
    for pos in range(0, len(raw_table), 32):
        raw = raw_table[pos:pos + 32]
        if len(raw) < 32:
            break
        magic = struct.unpack_from("<H", raw, 0)[0]
        if magic == 0xFFFF:
            break
        if magic == 0xEBEB:
            continue
        if magic != 0x50AA:
            break
        p_type = raw[2]
        subtype = raw[3]
        offset, size = struct.unpack_from("<II", raw, 4)
        label = raw[12:28].split(b"\x00", 1)[0].decode("ascii", errors="replace")
        parts.append({"type": p_type, "subtype": subtype, "offset": offset, "size": size, "label": label})
    if not parts:
        raise ValueError("ESP32-Partitionstabelle enthält keine Partitionen")
    return parts


def _esp32_update_targets(bundle: Any) -> list[tuple[str, int, int]]:
    update_path = Path(bundle.update)
    factory_path = Path(bundle.factory)
    update = update_path.read_bytes()
    factory = factory_path.read_bytes()
    if not update or update[0] != 0xE9:
        raise ValueError(f"Ungültiges ESP32-Update-Image: {update_path.name}")
    parts = _parse_partition_table(factory)
    app_parts = [p for p in parts if int(p["type"]) == 0x00 and int(p["size"]) >= len(update)]
    exact = [
        p for p in app_parts
        if len(factory) >= int(p["offset"]) + len(update)
        and factory[int(p["offset"]):int(p["offset"]) + len(update)] == update
    ]
    ota = [p for p in app_parts if int(p["subtype"]) in (0x10, 0x11)]
    selected = ota if ota else exact[:1]
    if not selected:
        summary = ", ".join(
            f"{p['label'] or '?'}@0x{int(p['offset']):x}/0x{int(p['size']):x}/sub=0x{int(p['subtype']):02x}"
            for p in app_parts
        ) or "keine"
        raise ValueError(f"Kein passendes App-Ziel im Factory-Image gefunden: {summary}")
    targets = [(str(p["label"] or "app"), int(p["offset"]), int(p["size"])) for p in selected]
    _emit(
        "UNIFIED UPDATE TARGETS "
        f"board={getattr(bundle, 'board_key', '')!r} update={update_path.name!r} "
        f"targets={[(label, hex(offset), hex(size)) for label, offset, size in targets]!r} hardcoded=0"
    )
    return targets


def _patch_artifact_resolver(services: Any) -> None:
    client_type = services.GitHubFirmwareClient
    if getattr(client_type, "_jarnsen_v2_artifact_resolver", False):
        return

    def resolve_bundle_files(self: Any, *, board_key: str, run_id: int, run_number: int,
                             artifact_id: int, artifact_name: str, cache_root: Path, version: str):
        profile = services.BOARD_PROFILES[board_key]
        artifact_kind = str(profile.get("artifact_kind") or "esp32").lower()
        env_name = str(profile.get("pio_env") or "")
        all_files = [p for p in cache_root.rglob("*") if p.is_file() and p.name != ".complete"]

        def pick(label: str, *, exact: tuple[str, ...] = (), suffix: tuple[str, ...] = (), required: bool = True) -> Path | None:
            exact_lower = {name.lower() for name in exact}
            suffix_lower = tuple(value.lower() for value in suffix)
            matches = [p for p in all_files if p.name.lower() in exact_lower or (suffix_lower and p.name.lower().endswith(suffix_lower))]
            unique: list[Path] = []
            seen: set[Path] = set()
            for path in matches:
                resolved = path.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    unique.append(path)
            if not unique and not required:
                return None
            if len(unique) != 1:
                available = ", ".join(sorted(p.name for p in all_files)) or "<leer>"
                raise services.FlasherError(
                    f"Artifact {artifact_name}: {label} nicht eindeutig gefunden ({len(unique)} Treffer).\nVerfügbare Dateien: {available}"
                )
            return unique[0]

        checksums = pick("SHA256SUMS", exact=("SHA256SUMS.txt",), suffix=("-sha256sums.txt",))
        expected = services._read_checksum_manifest(checksums)

        def verify(path: Path) -> None:
            wanted = expected.get(path.name)
            if not wanted:
                raise services.FlasherError(f"{checksums.name} enthält {path.name} nicht.")
            actual = services._sha256(path)
            if actual != wanted:
                raise services.FlasherError(f"SHA256-Prüfung fehlgeschlagen: {path.name}\nErwartet: {wanted}\nIst: {actual}")

        if artifact_kind == "uf2":
            uf2 = pick("UF2-Firmware", exact=("firmware.uf2", f"firmware-{env_name}.uf2"), suffix=("-firmware.uf2", ".uf2"))
            verify(uf2)
            bundle = services.FirmwareBundle(
                board_key=board_key, run_id=run_id, run_number=run_number, artifact_id=artifact_id,
                artifact_name=artifact_name, root=cache_root, factory=uf2, update=uf2, webflasher=uf2,
                checksums=checksums, version=version,
            )
            bundle.flash_strategy = "uf2"
            return bundle

        factory = pick("Factory-Image", exact=(f"firmware-{env_name}.factory.bin",), suffix=("-factory.bin", ".factory.bin"))
        update = pick("Update-Image", exact=(f"firmware-{env_name}.bin",), suffix=("-update.bin",))
        web = pick("Webflasher-Image", exact=(f"firmware-{env_name}.webflasher.bin",), suffix=("-webflasher.bin", ".webflasher.bin"), required=False)
        verify(factory)
        verify(update)
        if web is not None:
            verify(web)
        bundle = services.FirmwareBundle(
            board_key=board_key, run_id=run_id, run_number=run_number, artifact_id=artifact_id,
            artifact_name=artifact_name, root=cache_root, factory=factory, update=update,
            webflasher=web or update, checksums=checksums, version=version,
        )
        try:
            bundle.flash_targets = _esp32_update_targets(bundle)
            bundle.flash_strategy = "partition_update"
        except Exception as exc:
            raise services.FlasherError(f"Flashlayout konnte nicht sicher bestimmt werden: {exc}") from exc
        _emit(f"UNIFIED ARTIFACT V2 board={board_key!r} kind=esp32 webflasher={bool(web)} targets={[(label, hex(offset)) for label, offset, _ in bundle.flash_targets]!r}")
        return bundle

    client_type._resolve_bundle_files = resolve_bundle_files
    client_type._jarnsen_v2_artifact_resolver = True


def _patch_serial_arbitration(services: Any) -> None:
    if getattr(services, "_jarnsen_serial_arbitration_v2", False):
        return
    services._jarnsen_serial_arbitration_v2 = True
    base_meshtastic = services.meshtastic

    def meshtastic(port: str, *args: str, **kwargs: Any):
        with _serial_guard(port):
            return base_meshtastic(port, *args, **kwargs)

    services.meshtastic = meshtastic
    services.jarnsen_serial_guard = _serial_guard

    try:
        import firmware_status_ui
        base_identity = services.query_jarnsen_identity

        def query_identity(port: str, *args: Any, **kwargs: Any):
            key = _port_key(port)
            cached = _IDENTITY_CACHE.get(key)
            now = time.monotonic()
            if cached and now - cached[0] <= _IDENTITY_CACHE_TTL:
                return cached[1]
            with _serial_guard(port):
                identity = base_identity(port, *args, **kwargs)
            if identity is not None and bool(getattr(identity, "is_jarnsen", False)):
                _IDENTITY_CACHE[key] = (time.monotonic(), identity)
            return identity

        services.query_jarnsen_identity = query_identity
        firmware_status_ui.query_jarnsen_identity = query_identity
    except Exception as exc:
        _emit(f"SERIAL ARBITRATION identity patch skipped {type(exc).__name__}:{exc}")

    try:
        import radio_profile_legacy_fallback as legacy
        import radio_profile_node_sync as node_sync
        base_raw = legacy._stable_raw_command

        def raw_command(port: str, command: str, **kwargs: Any) -> str:
            with _serial_guard(port):
                return base_raw(port, command, **kwargs)

        legacy._stable_raw_command = raw_command
        node_sync._raw_command = raw_command

        class NoPermanentUnsupported(set):
            def add(self, element: object) -> None:
                _emit(f"RADIO NODE SYNC transient-unsupported ignored port={element!r}")
            def __contains__(self, element: object) -> bool:
                return False

        legacy._UNSUPPORTED_PORTS = NoPermanentUnsupported()
    except Exception as exc:
        _emit(f"SERIAL ARBITRATION radio patch skipped {type(exc).__name__}:{exc}")

    base_scan = services.scan_devices

    def scan_devices(*args: Any, **kwargs: Any):
        devices = base_scan(*args, **kwargs)
        for device in devices:
            if getattr(device, "board_key", None):
                continue
            try:
                identity = services.query_jarnsen_identity(device.port)
                hardware = str(getattr(identity, "hardware", "") or "") if identity is not None else ""
                if hardware:
                    detected = services.detect_board_from_text(f"hardware: {hardware}\nJARNSEN-MESH")
                    if detected:
                        device.board_key = detected
                        device.model_text = str(getattr(device, "model_text", "") or "") + f"\n===JARNSEN_LOCAL_IDENTITY=== hardware={hardware}"
                        _emit(f"BOARD DETECTION service-fallback port={device.port} board={detected!r} hardware={hardware!r}")
            except Exception as exc:
                _emit(f"BOARD DETECTION service-fallback skipped port={getattr(device, 'port', '')} {type(exc).__name__}:{exc}")
        return devices

    services.scan_devices = scan_devices
    _emit("SERIAL ARBITRATION V2 installed per-port-lock=1 identity-cache=4s unknown-board-service-fallback=1 permanent-negative-cache=0")


def _write_update_slots(services: Any, port: str, common: list[str], image: Path, targets: list, log: Any) -> None:
    from flash_runtime import _stream_esptool

    if not targets:
        raise ValueError("Keine App-Partitionen für das Update vorhanden")
    write_args = [value for _label, offset, _size in targets for value in (hex(offset), str(image))]
    _stream_esptool(
        services, port, [*common, *write_args], timeout=600 * len(targets),
        stage="App-Slots schreiben", phase_start=0.08, phase_end=0.88,
        log=log, progress_parts=len(targets),
    )


def _patch_native_actions(services: Any) -> None:
    import native_actions
    import reference_dashboard
    from usb_log_download import download_tracker_usb_log
    from flash_runtime import _stream_esptool

    def start_usb_log(app: Any, runtime_services: Any) -> None:
        if getattr(app, "busy", False):
            return
        device = app._selected_device()
        if device is None:
            messagebox.showwarning("Kein Gerät", "Bitte zuerst ein USB-Gerät auswählen.", parent=app)
            return
        board_key = app._selected_board_key()
        if board_key not in runtime_services.BOARD_PROFILES:
            messagebox.showwarning("Board unbekannt", "Bitte das Board zuerst eindeutig erkennen oder manuell auswählen.", parent=app)
            return
        app._set_busy(True)

        def worker() -> None:
            try:
                label = runtime_services.BOARD_PROFILES[board_key]["label"]
                app._append_log(f"USB-LOG START · Port={device.port} · Board={label} · Protokoll=JARNSEN_TOOL_FULL")
                app._set_progress(0.02, "USB-Log · Raw-Modus vorbereiten")
                try:
                    runtime_services.reboot_node(device.port)
                except Exception as exc:
                    app._append_log(f"USB-LOG · Reboot meldet {type(exc).__name__}: {exc}")
                app._set_progress(0.08, "USB-Log · Auf USB-Neuanmeldung warten")
                runtime_services.wait_for_serial(device.port, timeout=90)
                time.sleep(1.0)
                output_dir = Path(runtime_services.PATHS.logs) / "NODE-LOGS"

                def progress(value: float, detail: str) -> None:
                    app._set_progress(0.10 + 0.88 * max(0.0, min(1.0, value)), detail)

                with _serial_guard(device.port):
                    target = download_tracker_usb_log(device.port, output_dir, progress=progress, log=app._append_log)
                app._set_progress(1.0, f"USB-Log gespeichert · {target.name}")
                app.after(0, messagebox.showinfo, "Node-Log gespeichert", f"{label}\n\n{target}")
            except Exception as exc:
                app._append_log(f"USB-LOG FEHLER · {type(exc).__name__}: {exc}")
                app._show_error(exc)
            finally:
                app._set_busy(False)

        threading.Thread(target=worker, name="jarnsen-usb-log-all-boards", daemon=True).start()

    def start_firmware_only(app: Any, runtime_services: Any) -> None:
        if getattr(app, "busy", False):
            return
        device = app._selected_device()
        if device is None:
            messagebox.showwarning("Kein Gerät", "Bitte zuerst ein USB-Gerät auswählen.", parent=app)
            return
        board_key = app._selected_board_key()
        if board_key not in runtime_services.BOARD_PROFILES:
            messagebox.showwarning("Board unbekannt", "Bitte das Board zuerst eindeutig erkennen oder manuell auswählen.", parent=app)
            return
        app._set_busy(True)

        def worker() -> None:
            previous = getattr(runtime_services, "_jarnsen_flash_progress_callback", None)
            try:
                label = runtime_services.BOARD_PROFILES[board_key]["label"]
                app._set_progress(0.03, "Firmware-Update · Firmware auflösen")
                bundle = getattr(app, "bundle", None)
                if not (bundle is not None and getattr(bundle, "board_key", None) == board_key):
                    bundle = runtime_services.GitHubFirmwareClient().resolve_latest(board_key)
                    app.bundle = bundle
                    app.after(0, app.firmware_var.set, bundle.display_name)

                decision: list[bool] = []
                ready = threading.Event()

                def ask() -> None:
                    try:
                        decision.append(messagebox.askyesno(
                            "Nur Firmware updaten",
                            f"Port: {device.port}\nBoard: {label}\nFirmware: {bundle.display_name}\n\n"
                            "Firmware wird boardgerecht aktualisiert. Profil, Namen, NVS und Diagnose-Logs bleiben erhalten.\n\nFirmware jetzt aktualisieren?",
                            parent=app,
                        ))
                    finally:
                        ready.set()

                app.after(0, ask)
                ready.wait()
                if not decision or not decision[0]:
                    app._set_progress(0.0, "Firmware-Update abgebrochen")
                    return

                def flash_progress(fraction: float, stage: str, detail: str) -> None:
                    suffix = f" · {detail}" if detail else ""
                    app._set_progress(fraction, f"Firmware-Update · {stage}{suffix}")

                runtime_services._jarnsen_flash_progress_callback = flash_progress
                if board_key == "wio":
                    runtime_services.flash_bundle(device.port, bundle, log=app._append_log)
                else:
                    update_image = Path(bundle.update)
                    targets = list(getattr(bundle, "flash_targets", []) or _esp32_update_targets(bundle))
                    baud = str(getattr(runtime_services, "_jarnsen_flash_baud", "921600"))
                    if baud not in {"115200", "230400", "460800", "921600"}:
                        baud = "921600"
                    common = ["--baud", baud, "write-flash", "--flash-mode", "dio", "--flash-freq", "80m", "--flash-size", "keep"]
                    _write_update_slots(runtime_services, device.port, common, update_image, targets, app._append_log)
                    _stream_esptool(
                        runtime_services, device.port, ["run"], timeout=30, stage="Node starten",
                        phase_start=0.88, phase_end=0.91, log=app._append_log, check=False,
                    )

                app._set_progress(0.93, "Firmware-Update · Auf USB warten")
                runtime_services.wait_for_serial(device.port, timeout=90)
                app._set_progress(0.97, "Firmware-Update · Board prüfen")
                runtime_services.verify_node(device.port, expected_board=board_key)
                app._set_progress(1.0, "Firmware-Update fertig")
                app.after(0, messagebox.showinfo, "Firmware aktualisiert",
                          f"{bundle.display_name}\n\nProfil, Namen, NVS und Diagnose-Logs wurden nicht verändert.")
            except Exception as exc:
                app._append_log(f"FIRMWARE-ONLY FEHLER · {type(exc).__name__}: {exc}")
                app._show_error(exc)
            finally:
                runtime_services._jarnsen_flash_progress_callback = previous
                app._set_busy(False)

        threading.Thread(target=worker, name="jarnsen-firmware-only-all-boards", daemon=True).start()

    native_actions.start_usb_log = start_usb_log
    native_actions.start_firmware_only = start_firmware_only
    reference_dashboard.start_usb_log = start_usb_log
    reference_dashboard.start_firmware_only = start_firmware_only
    _emit("NATIVE ACTIONS V2 all-board-log=1 all-board-update=1 tracker-protocol=shared dynamic-partition-targets=1")


def _patch_local_firmware_copy() -> None:
    try:
        import local_firmware
        base_copy = local_firmware._copy_neighbours
        if getattr(local_firmware, "_jarnsen_copy_json_v2", False):
            return

        def copy_neighbours(source: Path, target: Path) -> None:
            base_copy(source, target)
            build = re.search(r"(?i)Build[-_ ]?(\d+)", source.name)
            build_no = build.group(1) if build else ""
            for item in source.parent.iterdir():
                if not item.is_file() or item.suffix.lower() != ".json":
                    continue
                if build_no and re.search(rf"(?i)Build[-_ ]?{re.escape(build_no)}\b", item.name):
                    destination = target / item.name
                    if not destination.exists():
                        import shutil
                        shutil.copy2(item, destination)

        local_firmware._copy_neighbours = copy_neighbours
        local_firmware._jarnsen_copy_json_v2 = True
    except Exception as exc:
        _emit(f"LOCAL FIRMWARE JSON PATCH skipped {type(exc).__name__}:{exc}")


def install(services: Any) -> None:
    if getattr(services, "_jarnsen_unified_service_v2", False):
        return
    services._jarnsen_unified_service_v2 = True
    _patch_artifact_resolver(services)
    _patch_serial_arbitration(services)
    _patch_native_actions(services)
    _patch_local_firmware_copy()
    services.esp32_update_targets = _esp32_update_targets
    _emit(
        "UNIFIED SERVICE V2 installed all-boards=6 log-download=1 firmware-update=1 "
        "radio-slots-no-permanent-negative-cache=1 board-service-fallback=1 firmware-identity-cache=1"
    )
