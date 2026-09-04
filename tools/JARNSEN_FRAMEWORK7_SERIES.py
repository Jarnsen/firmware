"""Framework7 v3.7 safe serial-series provisioning.

Keeps the proven v2.1.x reset/flash/profile worker and adds a guarded repeated
"same setup, new names" workflow, firmware-source selection, templates and
postcondition verification for the headless Framework7 service.
"""
from __future__ import annotations

import base64
import contextlib
import datetime as dt
import hashlib
import io
import json
import pathlib
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from typing import Any

STORE_NAME = "Jarnsen_Series_Provision.json"
MAX_UPLOAD = 10 * 1024 * 1024
MAX_FIRMWARE = 0x330000
DEVICES = {
    "TRACKER": {"device": "HELTEC_TRACKER_V1.1", "label": "Heltec Tracker V1.1", "hints": ("tracker", "v11", "v1.1"), "bad": ("v3",)},
    "V3": {"device": "HELTEC_V3_REPEATER", "label": "Heltec V3", "hints": ("v3", "heltec-v3"), "bad": ("tracker",)},
}


def _now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _worker_alive(tool: Any) -> bool:
    worker = getattr(tool, "worker", None)
    checker = getattr(worker, "is_alive", None)
    if not callable(checker):
        return False
    with contextlib.suppress(Exception):
        return bool(checker())
    return False


def _store_path() -> pathlib.Path:
    import JARNSEN_NODE_SERVICE_TOOL as legacy
    path = pathlib.Path(legacy.output_directory()) / STORE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _empty_store() -> dict[str, Any]:
    return {"schema": 1, "templates": [], "history": [], "last_settings": {}}


def _load_store() -> dict[str, Any]:
    try:
        raw = json.loads(_store_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_store()
    if not isinstance(raw, dict):
        return _empty_store()
    return {
        "schema": 1,
        "templates": list(raw.get("templates") or [])[:40] if isinstance(raw.get("templates"), list) else [],
        "history": list(raw.get("history") or [])[-200:] if isinstance(raw.get("history"), list) else [],
        "last_settings": dict(raw.get("last_settings") or {}) if isinstance(raw.get("last_settings"), dict) else {},
    }


def _save_store(data: dict[str, Any]) -> None:
    clean = {
        "schema": 1,
        "templates": list(data.get("templates") or [])[:40],
        "history": list(data.get("history") or [])[-200:],
        "last_settings": dict(data.get("last_settings") or {}),
    }
    target = _store_path()
    temp = target.with_suffix(".tmp")
    temp.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(target)


def _settings(raw: dict[str, Any]) -> dict[str, Any]:
    source = str(raw.get("firmware_source") or "latest").lower()
    source = source if source in {"latest", "github", "local"} else "latest"
    hardware = str(raw.get("hardware") or "AUTO").upper()
    hardware = hardware if hardware in {"AUTO", "TRACKER", "V3"} else "AUTO"
    pin = str(raw.get("pin") or "240180").strip()
    if not re.fullmatch(r"\d{6}", pin):
        raise RuntimeError("Bluetooth-PIN muss genau 6 Ziffern haben")
    try:
        slot = max(0, int(raw.get("profile_slot") or 0))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Ungültiger Grundprofil-Slot") from exc
    return {
        "profile_slot": slot,
        "hardware": hardware,
        "pin": pin,
        "apply_psk": bool(raw.get("apply_psk", False)),
        "firmware_source": source,
        "github_tag": str(raw.get("github_tag") or "").strip()[:160],
        "github_manifest": pathlib.Path(str(raw.get("github_manifest") or "")).name[:240],
        "port": str(raw.get("port") or "").strip()[:80],
    }


def _profile(tool: Any, slot: int) -> dict[str, Any]:
    profiles = tool.config_profile_store.get("profiles", [])
    profile = profiles[slot] if isinstance(profiles, list) and 0 <= slot < len(profiles) else None
    if not isinstance(profile, dict):
        raise RuntimeError(f"Grundprofil {slot + 1} ist leer")
    return profile


def _http_json(url: str, timeout: float = 20.0) -> dict[str, Any] | list[Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "Jarnsen-Node-Service-Tool"})
    with contextlib.closing(urllib.request.urlopen(request, timeout=timeout)) as response:  # nosec B310
        value = json.load(response)
    if not isinstance(value, (dict, list)):
        raise RuntimeError("GitHub antwortet mit unerwarteten Daten")
    return value


def _http_bytes(url: str, limit: int, timeout: float) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "Jarnsen-Node-Service-Tool"})
    with contextlib.closing(urllib.request.urlopen(request, timeout=timeout)) as response:  # nosec B310
        data = response.read(limit + 1)
    if len(data) > limit:
        raise RuntimeError("Firmwaredatei ist unerwartet groß")
    return data


def _validate_image(data: bytes, size: int = 0, digest: str = "") -> str:
    if not data or len(data) > MAX_FIRMWARE or data[0] != 0xE9:
        raise RuntimeError("Firmware ist kein gültiges ESP32-S3-Updateabbild")
    actual = hashlib.sha256(data).hexdigest()
    if size and len(data) != size:
        raise RuntimeError("Firmwaregröße stimmt nicht mit dem Manifest überein")
    if digest and actual.lower() != digest.lower():
        raise RuntimeError("SHA-256-Prüfung der Firmware fehlgeschlagen")
    return actual


def _filename_guard(filename: str, code: str) -> None:
    meta = DEVICES[code]
    name = pathlib.Path(filename).name.lower()
    if any(hint in name for hint in meta["bad"]):
        raise RuntimeError(f"Dateiname {filename} passt nicht zu {meta['label']}")
    if not any(hint in name for hint in meta["hints"]):
        raise RuntimeError(f"Lokale Einzel-Firmware muss {meta['label']} im Dateinamen erkennen lassen; alternativ ZIP mit .ota.json verwenden")


def _zip_member(names: list[str], wanted: str) -> str:
    if wanted in names:
        return wanted
    base = pathlib.Path(wanted).name
    matches = [name for name in names if pathlib.Path(name).name == base]
    return matches[0] if len(matches) == 1 else ""


def _local_bundle(raw: bytes, filename: str, code: str) -> tuple[bytes, dict[str, Any], str]:
    meta = DEVICES[code]
    if filename.lower().endswith(".zip"):
        try:
            with zipfile.ZipFile(io.BytesIO(raw), "r") as archive:
                names = [name for name in archive.namelist() if not name.endswith("/")]
                matches: list[tuple[str, dict[str, Any]]] = []
                for name in names:
                    if not name.lower().endswith(".ota.json"):
                        continue
                    with contextlib.suppress(Exception):
                        manifest = json.loads(archive.read(name).decode("utf-8"))
                        if isinstance(manifest, dict) and str(manifest.get("device") or "") == meta["device"]:
                            matches.append((name, manifest))
                if len(matches) > 1:
                    canonical = [m for m in matches if "light-sleep" in m[0].lower() or "vehicle-motion-wake" in m[0].lower()]
                    if len(canonical) != 1:
                        raise RuntimeError(f"ZIP enthält mehrere passende {meta['label']} OTA-Manifeste")
                    matches = canonical
                if matches:
                    manifest_name, manifest = matches[0]
                    asset = str(manifest.get("firmware_asset") or "")
                    member = _zip_member(names, asset)
                    if not member:
                        raise RuntimeError(f"ZIP-Manifest {manifest_name} verweist auf fehlende Firmware {asset}")
                    firmware = archive.read(member)
                    sha = _validate_image(firmware, int(manifest.get("firmware_size") or 0), str(manifest.get("firmware_sha256") or ""))
                    result = dict(manifest)
                    result.update(source="local-zip", local_sha256=sha)
                    return firmware, result, pathlib.Path(member).name
                bins = []
                for name in names:
                    if not name.lower().endswith(".update.bin"):
                        continue
                    try:
                        _filename_guard(name, code)
                        bins.append(name)
                    except RuntimeError:
                        pass
                if len(bins) != 1:
                    raise RuntimeError(f"ZIP enthält kein eindeutiges {meta['label']} OTA-Manifest/Updateabbild")
                firmware = archive.read(bins[0])
                sha = _validate_image(firmware)
                return firmware, {"schema": 1, "device": meta["device"], "source": "local-zip", "source_sha": "", "firmware_asset": pathlib.Path(bins[0]).name, "firmware_size": len(firmware), "firmware_sha256": sha, "local_sha256": sha}, pathlib.Path(bins[0]).name
        except zipfile.BadZipFile as exc:
            raise RuntimeError("Lokale ZIP-Datei ist beschädigt") from exc
    if not filename.lower().endswith(".bin"):
        raise RuntimeError("Lokale Firmware muss .bin/.update.bin oder ZIP sein")
    _filename_guard(filename, code)
    sha = _validate_image(raw)
    return raw, {"schema": 1, "device": meta["device"], "source": "local-bin", "source_sha": "", "firmware_asset": pathlib.Path(filename).name, "firmware_size": len(raw), "firmware_sha256": sha, "local_sha256": sha}, pathlib.Path(filename).name


def _github_options() -> list[dict[str, Any]]:
    releases = _http_json("https://api.github.com/repos/Jarnsen/firmware/releases?per_page=40")
    if not isinstance(releases, list):
        return []
    rows = []
    for release in releases:
        if not isinstance(release, dict) or release.get("draft"):
            continue
        tag = str(release.get("tag_name") or "")
        title = str(release.get("name") or tag)
        published = str(release.get("published_at") or release.get("updated_at") or "")
        for asset in release.get("assets", []):
            if not isinstance(asset, dict):
                continue
            name = str(asset.get("name") or "")
            lower = name.lower()
            if not lower.endswith(".ota.json"):
                continue
            code = "TRACKER" if "tracker" in lower else ("V3" if "v3" in lower else "")
            if code:
                rows.append({"tag": tag, "release": title, "published_at": published, "manifest": name, "hardware": code, "label": f"{DEVICES[code]['label']} · {name} · {tag}"})
    return rows[:80]


def _github_bundle(tag: str, manifest_name: str, code: str) -> tuple[bytes, dict[str, Any], str]:
    tag = tag.strip()
    manifest_name = pathlib.Path(manifest_name).name
    if not tag or not manifest_name.endswith(".ota.json"):
        raise RuntimeError("GitHub-Release oder OTA-Manifest fehlt")
    release = _http_json(f"https://api.github.com/repos/Jarnsen/firmware/releases/tags/{urllib.parse.quote(tag, safe='')}")
    if not isinstance(release, dict):
        raise RuntimeError("GitHub-Release ist ungültig")
    assets = {str(a.get("name") or ""): str(a.get("browser_download_url") or "") for a in release.get("assets", []) if isinstance(a, dict)}
    manifest_url = assets.get(manifest_name, "")
    if not manifest_url:
        raise RuntimeError(f"Manifest {manifest_name} fehlt im Release {tag}")
    try:
        manifest = json.loads(_http_bytes(manifest_url, 128 * 1024, 30.0).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("GitHub-OTA-Manifest ist ungültig") from exc
    if not isinstance(manifest, dict):
        raise RuntimeError("GitHub-OTA-Manifest ist ungültig")
    if str(manifest.get("device") or "") != DEVICES[code]["device"]:
        raise RuntimeError(f"GitHub-Firmware passt nicht zu {DEVICES[code]['label']}")
    asset = str(manifest.get("firmware_asset") or "")
    url = assets.get(asset, "")
    if not url:
        raise RuntimeError(f"Firmware {asset} fehlt im Release {tag}")
    firmware = _http_bytes(url, MAX_FIRMWARE, 90.0)
    sha = _validate_image(firmware, int(manifest.get("firmware_size") or 0), str(manifest.get("firmware_sha256") or ""))
    result = dict(manifest)
    result.update(source="github-release", release_tag=tag, manifest_asset=manifest_name, local_sha256=sha)
    return firmware, result, asset


def _decode_local(payload: dict[str, Any]) -> tuple[bytes, str]:
    item = payload.get("local_file")
    if not isinstance(item, dict):
        raise RuntimeError("Keine lokale Firmwaredatei ausgewählt")
    name = pathlib.Path(str(item.get("name") or "")).name
    encoded = str(item.get("data_b64") or "")
    if not name or not encoded:
        raise RuntimeError("Lokale Firmwaredatei ist leer")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise RuntimeError("Lokale Firmware konnte nicht gelesen werden") from exc
    if not raw or len(raw) > MAX_UPLOAD:
        raise RuntimeError("Lokale Firmwaredatei ist leer oder größer als 10 MiB")
    supplied = str(item.get("sha256") or "").lower()
    actual = hashlib.sha256(raw).hexdigest()
    if supplied and supplied != actual:
        raise RuntimeError("SHA-256 der übertragenen lokalen Datei stimmt nicht")
    return raw, name


def _preflight(tool: Any, port: str, expected: str) -> str:
    import JARNSEN_NODE_SERVICE_TOOL as legacy
    interface = None
    detected = ""
    try:
        tool._select_serial_port_in_ui(port)
        interface, _node = tool._open_config_profile_interface(("USB", port, port))
        metadata = getattr(interface, "metadata", None)
        with contextlib.suppress(Exception):
            detected = str(legacy.OTABT_HARDWARE_CODES.get(int(getattr(metadata, "hw_model", 0) or 0), ""))
        if not detected:
            with contextlib.suppress(Exception):
                info = interface.getMyNodeInfo() or {}
                user = info.get("user") if isinstance(info, dict) else None
                text = str((user or {}).get("hwModel") or (user or {}).get("hw_model") or "") if isinstance(user, dict) else ""
                converter = getattr(tool, "_device_code_from_hw_text", None)
                if callable(converter):
                    detected = str(converter(text) or "")
    finally:
        if interface is not None:
            with contextlib.suppress(Exception):
                interface.close()
    detected = detected.upper()
    if detected not in DEVICES:
        raise RuntimeError("Hardware konnte nicht sicher direkt von der USB-Node erkannt werden; Werkreset wurde nicht gestartet")
    if expected in DEVICES and expected != detected:
        raise RuntimeError(f"Hardwareprüfung abgebrochen: erkannt {DEVICES[detected]['label']}, ausgewählt {DEVICES[expected]['label']}")
    return detected


def _public_job(job: Any) -> dict[str, Any] | None:
    if not isinstance(job, dict):
        return None
    return {key: value for key, value in job.items() if not str(key).startswith("_")}


def _append_history(job: dict[str, Any]) -> None:
    store = _load_store()
    store["history"].append({
        "time": _now(), "job_id": job.get("id", ""), "status": job.get("state", ""), "node_id": job.get("node_id", ""),
        "long_name": job.get("long_name", ""), "short_name": job.get("short_name", ""), "hardware": job.get("device_label", ""),
        "profile_name": job.get("profile_name", ""), "firmware_source": job.get("firmware_source", ""), "firmware_label": job.get("firmware_label", ""),
        "source_sha": job.get("source_sha", ""), "message": job.get("message", ""),
    })
    _save_store(store)


def _verify_completion(tool: Any, job: dict[str, Any]) -> tuple[bool, str, str]:
    if job.get("_provision_error"):
        return False, str(job["_provision_error"]), ""
    snapshot = job.get("_completion_snapshot")
    if not isinstance(snapshot, dict):
        return False, "Provisioning endete ohne bestätigten Abschlussdatensatz", ""
    node_id = str(snapshot.get("node_id") or "")
    problems = []
    if not node_id:
        problems.append("Node-ID")
    if str(snapshot.get("long_name") or "") != str(job.get("long_name") or ""):
        problems.append("Long Name")
    if str(snapshot.get("short_name") or "") != str(job.get("short_name") or "")[:4]:
        problems.append("Short Name")
    expected_hw = DEVICES[str(job.get("device_code") or "")]["device"]
    actual_hw = str(snapshot.get("hardware") or "")
    if actual_hw and actual_hw != expected_hw:
        problems.append("Hardware")
    management = tool.repository.management_for_node(node_id) if node_id else None
    if not isinstance(management, dict):
        problems.append("Tool-Datenbank")
    else:
        if int(management.get("profile_slot") or 0) != int(job.get("profile_slot") or 0) + 1:
            problems.append("Grundprofil")
        if not bool(management.get("ota_ready")):
            problems.append("otaBTupdate")
        expected_build = str(job.get("source_sha") or "").lower()
        actual_build = str(management.get("firmware_build") or "").lower()
        if expected_build and actual_build and not (expected_build.startswith(actual_build) or actual_build.startswith(expected_build)):
            problems.append("Firmware-Build")
    if problems:
        return False, "Rückprüfung fehlgeschlagen: " + ", ".join(problems), node_id
    return True, "Node vollständig eingerichtet und zurückgelesen", node_id


class _ProvisionEvents:
    """Pass-through queue restoring the old Tk provisioning hand-offs headlessly."""
    def __init__(self, tool: Any, inner: Any) -> None:
        self.tool, self.inner = tool, inner

    def put(self, item: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            kind, value = item
            job = self.tool.__dict__.get("_framework7_series_job")
            if isinstance(job, dict):
                if kind == "status":
                    job["stage"] = str(value or "")
                elif kind == "progress_detail" and isinstance(value, (tuple, list)) and len(value) >= 3:
                    job["progress"] = max(0, min(100, int(value[0] or 0)))
                    job["stage"] = str(value[1] or job.get("stage") or "")
                    with contextlib.suppress(Exception):
                        self.tool.set_transfer_progress(value[0], str(value[1]), bool(value[2]))
                elif kind == "provision_ready_for_profile" and isinstance(value, dict):
                    job["progress"] = max(76, int(job.get("progress") or 0))
                    self.tool._handoff_provision_to_profile(dict(value))
                elif kind == "config_profile_apply_result" and isinstance(value, (tuple, list)) and len(value) >= 2:
                    verified = bool(value[1])
                    if not verified:
                        job["_provision_error"] = str(value[0] or "Profil-Rückprüfung fehlgeschlagen")
                    self.tool._schedule_profile_registration(verified)
                elif kind == "provision_complete" and isinstance(value, (tuple, list)) and len(value) >= 1:
                    job["_completion_snapshot"] = dict(value[0]) if isinstance(value[0], dict) else {}
                    job["_completion_provision"] = dict(value[1]) if len(value) > 1 and isinstance(value[1], dict) else {}
                    self.tool._provision_active = False
                    self.tool._provision_context = None
                    job["progress"] = 100
                elif kind in {"provision_error", "config_profile_error"} and bool(getattr(self.tool, "_provision_active", False)):
                    job["_provision_error"] = str(value or kind)
                    self.tool._provision_active = False
                    self.tool._provision_context = None
                    with contextlib.suppress(Exception):
                        self.tool._profile_apply_management_context = None
        except Exception as exc:
            job = self.tool.__dict__.get("_framework7_series_job")
            if isinstance(job, dict):
                job["_provision_error"] = f"Headless Provisioning-Handoff fehlgeschlagen: {exc}"
                self.tool._provision_active = False
        return self.inner.put(item, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


def _install_event_proxy(tool: Any) -> None:
    current = getattr(tool, "events", None)
    if isinstance(current, _ProvisionEvents):
        return
    if current is None or not hasattr(current, "put") or not hasattr(current, "get_nowait"):
        raise RuntimeError("Service-Eventqueue ist nicht verfügbar")
    tool.events = _ProvisionEvents(tool, current)


def _install_bundle_wrapper(tool: Any) -> None:
    if bool(tool.__dict__.get("_framework7_series_bundle_wrapped", False)):
        return
    original = getattr(tool, "_download_serial_bundle", None)
    if not callable(original):
        raise RuntimeError("Serieller Firmware-Bundle-Loader fehlt im Servicekern")

    def wrapped(code: str):
        override = tool.__dict__.get("_framework7_series_bundle_override")
        if not isinstance(override, dict):
            return original(code)
        try:
            code = str(code or "").upper()
            expected = str(override.get("device_code") or "").upper()
            if code != expected:
                raise RuntimeError(f"Firmware-Sicherheitsprüfung: erkannt {code}, erwartet {expected}")
            latest_firmware, loader, latest_manifest = original(code)
            source = str(override.get("source") or "latest")
            if source == "latest":
                firmware, manifest, label = latest_firmware, dict(latest_manifest), "Aktuellste geprüfte Jarnsen-Firmware"
            elif source == "github":
                firmware, manifest, asset = _github_bundle(str(override.get("github_tag") or ""), str(override.get("github_manifest") or ""), code)
                label = f"GitHub {override.get('github_tag')} · {asset}"
            elif source == "local":
                firmware, manifest, asset = _local_bundle(bytes(override.get("local_bytes") or b""), str(override.get("local_name") or "firmware.bin"), code)
                label = f"Lokal · {asset} · SHA256 {str(manifest.get('local_sha256') or '')[:12]}"
            else:
                raise RuntimeError(f"Unbekannte Firmwarequelle: {source}")
            job = tool.__dict__.get("_framework7_series_job")
            if isinstance(job, dict):
                job["source_sha"] = str(manifest.get("source_sha") or "").lower()
                job["firmware_label"] = label
            return firmware, loader, manifest
        finally:
            tool._framework7_series_bundle_override = None

    tool._download_serial_bundle = wrapped
    tool._framework7_series_bundle_wrapped = True


def _guard(tool: Any, job_id: str) -> None:
    deadline = time.monotonic() + 20 * 60
    seen = False
    while time.monotonic() < deadline:
        job = tool.__dict__.get("_framework7_series_job")
        if not isinstance(job, dict) or str(job.get("id") or "") != job_id:
            return
        active = bool(getattr(tool, "_provision_active", False))
        alive = _worker_alive(tool)
        seen = seen or active or alive
        if seen and not active and not alive:
            ok, message, node_id = _verify_completion(tool, job)
            job["state"] = "success" if ok else "failed"
            job["message"] = message
            job["node_id"] = node_id
            job["finished_at"] = _now()
            job["progress"] = 100 if ok else int(job.get("progress") or 0)
            tool._framework7_series_bundle_override = None
            _append_history(job)
            return
        time.sleep(0.35)
    job = tool.__dict__.get("_framework7_series_job")
    if isinstance(job, dict) and str(job.get("id") or "") == job_id:
        job.update(state="failed", message="Zeitüberschreitung bei Serienbereitstellung", finished_at=_now())
        tool._framework7_series_bundle_override = None
        _append_history(job)


def install_series(LegacyBridge: type, ApiHandler: type) -> None:
    """Install the serial-series API and capability reporting once."""
    if bool(getattr(LegacyBridge, "_framework7_series_v37_installed", False)):
        return
    original_status = LegacyBridge.service_status
    original_get = ApiHandler.do_GET
    original_post = ApiHandler.do_POST

    def series_status(self: Any) -> dict[str, Any]:
        def collect() -> dict[str, Any]:
            store = _load_store()
            return {
                "ok": True,
                "usb": self._usb_targets() if hasattr(self, "_usb_targets") else [],
                "job": _public_job(self.tool.__dict__.get("_framework7_series_job")),
                "templates": store["templates"],
                "history": store["history"][-60:],
                "last_settings": store["last_settings"],
                "busy": _worker_alive(self.tool) or bool(getattr(self.tool, "_provision_active", False)),
                "capabilities": {"repeat_names_only": True, "usb_preflight": True, "latest_github": True, "github_release_select": True, "local_bundle": True, "full_reset": True, "ota_loader": True, "profile_readback": True, "postcondition_verify": True, "saved_templates": True, "series_history": True},
            }
        return self.call_ui(collect, timeout=15.0)

    def series_github(self: Any) -> dict[str, Any]:
        try:
            return {"ok": True, "options": _github_options()}
        except (OSError, urllib.error.URLError, ValueError, RuntimeError) as exc:
            raise RuntimeError(f"GitHub-Firmwareliste konnte nicht geladen werden: {exc}") from exc

    def series_action(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
        command = str(payload.get("command") or "").strip()
        if command == "save_template":
            name = str(payload.get("name") or "").strip()
            if not name:
                raise RuntimeError("Vorlagenname fehlt")
            saved = _settings(dict(payload.get("settings") or {}))
            if saved["firmware_source"] == "local":
                saved["local_file_required"] = True
            store = _load_store()
            ident = str(payload.get("id") or "").strip() or uuid.uuid4().hex[:12]
            entry = {"id": ident, "name": name[:80], "saved_at": _now(), "settings": saved}
            store["templates"] = [x for x in store["templates"] if str(x.get("id") or "") != ident] + [entry]
            _save_store(store)
            return {"ok": True, "message": f"Vorlage „{entry['name']}“ gespeichert", "template": entry}
        if command == "delete_template":
            ident = str(payload.get("id") or "").strip()
            store = _load_store()
            before = len(store["templates"])
            store["templates"] = [x for x in store["templates"] if str(x.get("id") or "") != ident]
            _save_store(store)
            return {"ok": True, "message": "Vorlage gelöscht", "deleted": before - len(store["templates"])}
        if command == "clear_history":
            store = _load_store(); store["history"] = []; _save_store(store)
            return {"ok": True, "message": "Serienverlauf geleert"}
        if command == "cancel":
            self.tool.stop_event.set()
            return {"ok": True, "message": "Abbruch angefordert"}
        if command != "start":
            raise RuntimeError(f"Unbekannte Serienaktion: {command}")

        settings = _settings(payload)
        long_name = str(payload.get("long_name") or "").strip()
        short_name = str(payload.get("short_name") or "").strip()
        if not long_name:
            raise RuntimeError("Long Name fehlt")
        if not short_name or len(short_name) > 4:
            raise RuntimeError("Short Name muss 1 bis 4 Zeichen lang sein")
        local_bytes, local_name = (b"", "")
        if settings["firmware_source"] == "local":
            local_bytes, local_name = _decode_local(payload)

        def execute() -> dict[str, Any]:
            if _worker_alive(self.tool) or bool(getattr(self.tool, "_provision_active", False)):
                raise RuntimeError("Ein anderer Log-/Firmware-/Provisioning-Vorgang läuft noch")
            profile = _profile(self.tool, settings["profile_slot"])
            targets = self._usb_targets() if hasattr(self, "_usb_targets") else []
            requested = settings["port"]
            if requested:
                if not any(str(x.get("device") or "") == requested for x in targets):
                    raise RuntimeError(f"USB/COM-Port {requested} ist nicht mehr verfügbar")
                port = requested
            elif len(targets) == 1:
                port = str(targets[0].get("device") or "")
            elif len(targets) > 1:
                raise RuntimeError("Mehrere USB-Nodes erkannt – bitte den Ziel-Port auswählen")
            else:
                raise RuntimeError("Keine kompatible USB-Node erkannt")
            detected = _preflight(self.tool, port, settings["hardware"])
            _install_event_proxy(self.tool)
            _install_bundle_wrapper(self.tool)
            self.tool._select_serial_port_in_ui(port)
            self.tool.config_profile_transport_var.set("USB")
            self.tool.config_target_long_var.set(long_name)
            self.tool.config_target_short_var.set(short_name)
            self.tool.config_bt_pin_var.set(settings["pin"])
            self.tool.config_apply_bt_pin_var.set(True)
            self.tool.config_apply_psk_var.set(bool(settings["apply_psk"]))
            profile_name = str(profile.get("name") or f"Profil {settings['profile_slot'] + 1}")
            job_id = uuid.uuid4().hex[:14]
            job = {
                "id": job_id, "state": "running", "started_at": _now(), "finished_at": "", "progress": 1,
                "stage": f"{DEVICES[detected]['label']} erkannt · sichere Neueinrichtung startet", "message": "", "port": port,
                "profile_slot": settings["profile_slot"], "profile_name": profile_name, "long_name": long_name, "short_name": short_name[:4],
                "device_code": detected, "device_label": DEVICES[detected]["label"], "firmware_source": settings["firmware_source"],
                "firmware_label": "Aktuellste geprüfte Jarnsen-Firmware" if settings["firmware_source"] == "latest" else ("GitHub-Auswahl" if settings["firmware_source"] == "github" else f"Lokal · {local_name}"),
                "source_sha": "", "node_id": "",
            }
            self.tool._framework7_series_job = job
            self.tool._framework7_series_bundle_override = {"source": settings["firmware_source"], "device_code": detected, "github_tag": settings["github_tag"], "github_manifest": settings["github_manifest"], "local_bytes": local_bytes, "local_name": local_name}
            store = _load_store(); store["last_settings"] = {**settings, "port": port}; _save_store(store)
            self.tool._provision_active = True
            self.tool._provision_context = None
            self.tool.stop_event.clear()
            self.tool.worker = threading.Thread(target=self.tool._config_profile_provision_worker, args=(settings["profile_slot"], profile, port), daemon=True, name=f"framework7-series-{job_id}")
            self.tool.worker.start()
            threading.Thread(target=_guard, args=(self.tool, job_id), daemon=True, name=f"framework7-series-guard-{job_id}").start()
            return {"ok": True, "message": f"{long_name} wird auf {port} sicher eingerichtet", "job": _public_job(job)}
        return self.call_ui(execute, timeout=60.0)

    def service_status(self: Any) -> dict[str, Any]:
        data = original_status(self)
        critical = data.setdefault("critical", {})
        critical["series_provisioning"] = all(hasattr(self.tool, name) for name in ("_config_profile_provision_worker", "_download_serial_bundle", "_open_config_profile_interface", "_schedule_profile_registration"))
        data["series"] = {"sources": ["latest", "github", "local"], "repeat_names_only": True, "postcondition_verify": True}
        data["ok"] = all(bool(v) for v in critical.values())
        return data

    LegacyBridge.series_status = series_status
    LegacyBridge.series_github = series_github
    LegacyBridge.series_action = series_action
    LegacyBridge.service_status = service_status
    LegacyBridge._framework7_series_v37_installed = True

    def do_GET(self: Any) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        if path in {"/api/series/status", "/api/series/github"}:
            if not self._authorized():
                self._send(403, {"ok": False, "error": "forbidden"}); return
            try:
                self._send(200, self.bridge.series_status() if path.endswith("status") else self.bridge.series_github())
            except Exception as exc:  # noqa: BLE001
                self._send(500, {"ok": False, "error": str(exc), "type": type(exc).__name__})
            return
        original_get(self)

    def do_POST(self: Any) -> None:  # noqa: N802
        if urllib.parse.urlparse(self.path).path == "/api/series/action":
            if not self._authorized():
                self._send(403, {"ok": False, "error": "forbidden"}); return
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                if length > 16 * 1024 * 1024:
                    raise RuntimeError("Serienanforderung ist zu groß")
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                self._send(200, self.bridge.series_action(payload))
            except Exception as exc:  # noqa: BLE001
                self._send(500, {"ok": False, "error": str(exc), "type": type(exc).__name__})
            return
        original_post(self)

    ApiHandler.do_GET = do_GET
    ApiHandler.do_POST = do_POST
