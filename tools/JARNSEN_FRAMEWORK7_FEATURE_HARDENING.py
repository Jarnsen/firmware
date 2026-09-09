"""Safety/robustness contracts for Framework7 profile and BLE feature bridges."""
from __future__ import annotations

import contextlib
import json
import re
import urllib.error
import urllib.parse
from typing import Any, Callable

import JARNSEN_FRAMEWORK7_SERIES as series
import JARNSEN_FRAMEWORK7_SERIES_HARDENING as series_hard

MAX_FEATURE_REQUEST = 4 * 1024 * 1024


def _profile_usb_port(bridge: Any, node_id: str) -> str:
    node_id = str(node_id or "").strip()
    if not node_id:
        raise RuntimeError(
            "Für Werkreset + Neuaufsetzen muss eine bekannte Ziel-Node gewählt sein; "
            "Virgin-Nodes bitte über 'Serie / Nodes einrichten' initialisieren"
        )
    management: dict[str, Any] = {}
    if hasattr(bridge.tool.repository, "management_for_node"):
        with contextlib.suppress(Exception):
            value = bridge.tool.repository.management_for_node(node_id)
            if value:
                management = dict(value)
    expected_identity = str(management.get("usb_identity") or "").lower()
    last_port = str(management.get("last_port") or "")
    candidates: list[dict[str, Any]] = []
    with contextlib.suppress(Exception):
        candidates = list(bridge.tool._auto_usb_log_candidates())
    for item in candidates:
        with contextlib.suppress(Exception):
            key = str(bridge.tool._serial_identity_key(item) or "").lower()
            if expected_identity and key == expected_identity:
                return str(item.get("device") or "")
    if last_port:
        for item in candidates:
            if str(item.get("device") or "") == last_port:
                return last_port
    if len(candidates) == 1:
        # A known node with a lost/stale mapping may still have exactly one physical
        # USB candidate.  The hardware preflight below must confirm its board type
        # before this candidate can be used destructively.
        return str(candidates[0].get("device") or "")
    if len(candidates) > 1:
        raise RuntimeError(
            "Mehrere USB-Nodes erkannt und die Ziel-Node ist nicht eindeutig zugeordnet"
        )
    raise RuntimeError("Die Ziel-Node ist aktuell nicht über USB/COM erreichbar")


def _prepare_profile_provision_bundle(bridge: Any, payload: dict[str, Any]) -> tuple[str, str]:
    slot = int(payload.get("slot", -1))
    profile = series._profile(bridge.tool, slot)
    code = series_hard._profile_code(bridge.tool, slot)
    if code not in series.DEVICES:
        raise RuntimeError(
            "Das Grundprofil enthält keinen eindeutigen Tracker/V3-Hardwaretyp; "
            "Werkreset wurde nicht gestartet"
        )
    node_id = str(payload.get("node_id") or "").strip()
    port = _profile_usb_port(bridge, node_id)

    def detect() -> str:
        return series_hard._detect_usb_hardware(bridge.tool, port)

    detected = str(bridge.call_ui(detect, timeout=45.0) or "").upper()
    if detected in series.DEVICES and detected != code:
        raise RuntimeError(
            f"Profil-Provisioning abgebrochen: Node={series.DEVICES[detected]['label']}, "
            f"Grundprofil={series.DEVICES[code]['label']}"
        )
    if detected not in series.DEVICES:
        # This path is intentionally more conservative than the Series page: a
        # known managed node should be directly identifiable.  Virgin boards belong
        # to the dedicated Series bootstrap where the fallback is explicit.
        raise RuntimeError(
            "Hardware der bekannten Ziel-Node konnte vor dem Werkreset nicht sicher gelesen werden; "
            "nichts wurde zurückgesetzt"
        )

    loader = getattr(bridge.tool, "_download_serial_bundle", None)
    if not callable(loader):
        raise RuntimeError("Serieller Firmware-Bundle-Loader fehlt")
    try:
        firmware, ota_loader, manifest = loader(code)
    except Exception as exc:
        raise RuntimeError(
            f"Firmwarequelle für {series.DEVICES[code]['label']} ist vor dem Werkreset nicht verfügbar: {exc}"
        ) from exc
    manifest = dict(manifest)
    series_hard._validate_manifest_contract(manifest, code)
    series._validate_image(
        bytes(firmware),
        int(manifest.get("firmware_size") or 0),
        str(manifest.get("firmware_sha256") or ""),
    )
    if series_hard.hashlib.sha256(bytes(ota_loader)).hexdigest() != series_hard.OTA_LOADER_SHA256:
        raise RuntimeError("otaBTupdate konnte vor dem Werkreset nicht verifiziert werden")
    offset = str(
        manifest.get("ota_partition_offset") or series_hard.OTA_LOADER_OFFSET
    ).lower()
    if offset != series_hard.OTA_LOADER_OFFSET.lower():
        raise RuntimeError("OTA-Loader-Offset im Manifest ist nicht 0x340000")

    # Reuse the Series one-shot wrapper so the already verified bundle is consumed
    # by the legacy worker after reset instead of being downloaded again.
    series_hard._install_prefetch_bundle_wrapper(bridge.tool)
    source = "profile-provision-preflight"
    bridge.tool._framework7_series_bundle_override = {
        "source": source,
        "device_code": code,
    }
    bridge.tool._framework7_series_prefetched_bundle = {
        "device_code": code,
        "source": source,
        "bundle": (bytes(firmware), bytes(ota_loader), manifest),
        "label": "Vorgeprüfte Firmwarequelle der Profilseite",
    }
    return code, port


def _clear_profile_bundle(tool: Any) -> None:
    tool._framework7_series_bundle_override = None
    tool._framework7_series_prefetched_bundle = None


def _node_device_code(tool: Any, node_id: str) -> str:
    wanted = str(node_id or "").strip().lower()
    try:
        rows = tool.repository.list_nodes(True)
    except TypeError:
        rows = tool.repository.list_nodes()
    for row in rows:
        data = dict(row)
        if str(data.get("node_id") or "").strip().lower() != wanted:
            continue
        device = str(data.get("device") or "")
        if device == series.DEVICES["TRACKER"]["device"]:
            return "TRACKER"
        if device == series.DEVICES["V3"]["device"]:
            return "V3"
    with contextlib.suppress(Exception):
        latest = tool.repository.latest_log(node_id)
        metrics = dict((latest or {}).get("metrics") or {})
        device = str((latest or {}).get("device") or metrics.get("device") or "")
        if device == series.DEVICES["TRACKER"]["device"]:
            return "TRACKER"
        if device == series.DEVICES["V3"]["device"]:
            return "V3"
    raise RuntimeError(f"Hardwaretyp der Node {node_id} ist in der Tool-Datenbank unbekannt")


def _validate_ble_bundle(code: str, bundle: Any) -> tuple[bytes, dict[str, Any]]:
    if not isinstance(bundle, tuple) or len(bundle) != 2:
        raise RuntimeError("Bluetooth-OTA-Bundle ist unvollständig")
    firmware, manifest = bundle
    manifest = dict(manifest)
    series_hard._validate_manifest_contract(manifest, code)
    series._validate_image(
        bytes(firmware),
        int(manifest.get("firmware_size") or 0),
        str(manifest.get("firmware_sha256") or ""),
    )
    return bytes(firmware), manifest


def _prefetch_ble_bundles(tool: Any, node_ids: list[str]) -> tuple[dict[str, tuple[bytes, dict[str, Any]]], Callable[[], None]]:
    codes = {_node_device_code(tool, node_id) for node_id in node_ids}
    loader = getattr(tool, "_download_otabt_bundle", None)
    if not callable(loader):
        raise RuntimeError("Bluetooth-OTA-Downloader fehlt im Servicekern")
    bundles: dict[str, tuple[bytes, dict[str, Any]]] = {}
    for code in sorted(codes):
        try:
            bundles[code] = _validate_ble_bundle(code, loader(code))
        except (OSError, ValueError, RuntimeError, urllib.error.URLError) as exc:
            raise RuntimeError(
                f"Bluetooth-OTA für {series.DEVICES[code]['label']} wurde nicht gestartet: "
                f"geprüfte Updatequelle ist nicht vollständig verfügbar ({exc})"
            ) from exc

    original = loader
    remaining = dict(bundles)
    token = object()
    tool._framework7_ble_bundle_cache_token = token

    def restore() -> None:
        if tool.__dict__.get("_framework7_ble_bundle_cache_token") is token:
            tool._framework7_ble_bundle_cache_token = None
        if getattr(tool, "_download_otabt_bundle", None) is cached:
            tool._download_otabt_bundle = original

    def cached(code: str):
        code = str(code or "").upper()
        if (
            tool.__dict__.get("_framework7_ble_bundle_cache_token") is token
            and code in remaining
        ):
            bundle = remaining.pop(code)
            if not remaining:
                restore()
            return bundle
        return original(code)

    tool._download_otabt_bundle = cached
    return bundles, restore


def install_feature_hardening(LegacyBridge: type, ApiHandler: type) -> None:
    if bool(getattr(LegacyBridge, "_framework7_feature_hardening_installed", False)):
        return
    for name in ("profile_action", "service_action", "action"):
        if not hasattr(LegacyBridge, name):
            raise RuntimeError(f"Framework7 Feature-Hardening benötigt LegacyBridge.{name}")

    previous_profile_action = LegacyBridge.profile_action

    def profile_action(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise RuntimeError("Profilaktion muss ein JSON-Objekt sein")
        if str(payload.get("command") or "").strip() != "provision":
            return previous_profile_action(self, payload)
        preferred = str(payload.get("transport") or "Automatisch").strip().lower()
        if preferred not in {"automatisch", "auto", "usb"}:
            raise RuntimeError("Werkreset + Neuaufsetzen ist nur über USB erlaubt")
        code, port = _prepare_profile_provision_bundle(self, payload)
        guarded = dict(payload)
        guarded["transport"] = "USB"
        try:
            result = previous_profile_action(self, guarded)
            if isinstance(result, dict):
                result["hardware_verified"] = code
                result["preflight_bundle"] = True
                result["preflight_port"] = port
            return result
        except Exception:
            _clear_profile_bundle(self.tool)
            raise

    LegacyBridge.profile_action = profile_action

    previous_service_action = LegacyBridge.service_action

    def service_action(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise RuntimeError("Service-Aktion muss ein JSON-Objekt sein")
        if str(payload.get("command") or "").strip() != "ble_recovery":
            return previous_service_action(self, payload)
        node_id = str(payload.get("node_id") or "").strip()
        if not node_id:
            raise RuntimeError("Bitte eine Node für Bluetooth-Recovery auswählen")
        _bundles, restore = _prefetch_ble_bundles(self.tool, [node_id])

        def execute() -> dict[str, Any]:
            if getattr(self.tool, "worker", None) is not None and self.tool.worker.is_alive():
                raise RuntimeError("Ein anderer Vorgang läuft bereits")
            entries, missing = self.tool._ble_entries_for_nodes_v2133([node_id])
            if missing or len(entries) != 1:
                raise RuntimeError("Die Node ist aktuell nicht eindeutig über BLE erreichbar")
            self._select_nodes([node_id])
            selected = list(self.tool._selected_node_ids_v2133())
            if len(selected) != 1 or str(selected[0]).strip().lower() != node_id.lower():
                raise RuntimeError("Bluetooth-Recovery konnte die Ziel-Node nicht eindeutig auswählen")
            self.tool.batch_ota_v2133()  # v2.1.33 signature intentionally has no args
            return {
                "message": "Bluetooth-Recovery/OTA gestartet",
                "node_id": node_id,
                "firmware_preflight": True,
            }

        try:
            return self.call_ui(execute, timeout=40.0)
        except Exception:
            restore()
            raise

    LegacyBridge.service_action = service_action

    previous_action = LegacyBridge.action

    def action(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise RuntimeError("Aktion muss ein JSON-Objekt sein")
        if str(payload.get("command") or "").strip() != "ota":
            return previous_action(self, payload)
        node_ids = [
            str(item).strip()
            for item in payload.get("node_ids") or []
            if str(item).strip()
        ]
        node_id = str(payload.get("node_id") or "").strip()
        if node_id and node_id not in node_ids:
            node_ids.append(node_id)
        if not node_ids:
            raise RuntimeError("Bitte mindestens eine Node für Bluetooth-OTA auswählen")
        _bundles, restore = _prefetch_ble_bundles(self.tool, node_ids)
        try:
            result = previous_action(self, payload)
            if isinstance(result, dict):
                result["firmware_preflight"] = True
            return result
        except Exception:
            restore()
            raise

    LegacyBridge.action = action

    previous_status = LegacyBridge.service_status

    def service_status(self: Any) -> dict[str, Any]:
        data = previous_status(self)
        critical = data.setdefault("critical", {})
        critical["profile_provision_hardware_guard"] = True
        critical["profile_provision_preflight_bundle"] = True
        critical["ble_ota_source_preflight"] = True
        critical["ble_recovery_signature"] = True
        data["ok"] = all(bool(value) for value in critical.values())
        return data

    LegacyBridge.service_status = service_status

    previous_post = ApiHandler.do_POST

    def do_POST(self: Any) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        if path not in {"/api/profile/action", "/api/profile/section", "/api/live/action"}:
            return previous_post(self)
        if not self._authorized():
            self._send(403, {"ok": False, "error": "forbidden"})
            return
        try:
            raw_length = str(self.headers.get("Content-Length", "") or "").strip()
            if not re.fullmatch(r"\d+", raw_length):
                self._send(400, {"ok": False, "error": "Ungültige Content-Length"})
                return
            length = int(raw_length)
            if length <= 0 or length > MAX_FEATURE_REQUEST:
                self._send(
                    413 if length > MAX_FEATURE_REQUEST else 400,
                    {"ok": False, "error": "Feature-Anforderung ist leer oder zu groß"},
                )
                return
            raw = self.rfile.read(length)
            if len(raw) != length:
                self._send(400, {"ok": False, "error": "Feature-Anforderung ist unvollständig"})
                return
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                self._send(400, {"ok": False, "error": "Feature-Anforderung muss ein JSON-Objekt sein"})
                return
            if path == "/api/profile/action":
                self._send(200, self.bridge.profile_action(payload))
            elif path == "/api/profile/section":
                self._send(200, self.bridge.save_profile_section(payload))
            else:
                self._send(200, self.bridge.live_action(payload))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            self._send(400, {"ok": False, "error": f"Ungültige Feature-Anforderung: {exc}"})
        except RuntimeError as exc:
            self._send(409, {"ok": False, "error": str(exc), "type": type(exc).__name__})
        except Exception as exc:  # noqa: BLE001
            self._send(500, {"ok": False, "error": str(exc), "type": type(exc).__name__})

    ApiHandler.do_POST = do_POST
    LegacyBridge._framework7_feature_hardening_installed = True
