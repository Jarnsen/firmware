"""Framework7 Series v3.8 safety hardening.

Installed after the v3.7 Series bridge. Every destructive Series run validates
hardware and the complete firmware + otaBTupdate bundle before reset. Firmware
sources remain read-only; this module never builds or mutates firmware.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import pathlib
import re
import threading
import urllib.parse
from typing import Any

import JARNSEN_FRAMEWORK7_SERIES as series

HARDENING_VERSION = "3.8"
MAX_REQUEST = 16 * 1024 * 1024
OTA_LOADER_URL = (
    "https://github.com/meshtastic/esp32-unified-ota/releases/download/"
    "v1.0.1/mt-esp32s3-ota.bin"
)
OTA_LOADER_SHA256 = "3e62c5451afda604bac372444f058fc689dd588a87772ad4be90c228e04c1995"
OTA_LOADER_OFFSET = "0x340000"
OTA_LOADER_MAX = 2 * 1024 * 1024
_STORE_LOCK = threading.RLock()

_ORIGINAL_LOCAL_BUNDLE = series._local_bundle
_ORIGINAL_GITHUB_BUNDLE = series._github_bundle
_ORIGINAL_PREFLIGHT = series._preflight
_ORIGINAL_APPEND_HISTORY = series._append_history


def _strict_update_name(filename: str) -> None:
    name = pathlib.Path(str(filename or "")).name.lower()
    if not name.endswith(".update.bin"):
        raise RuntimeError(
            "Für den seriellen App-Slot ist ausschließlich eine .update.bin erlaubt; "
            "Factory-/Webflasher-/generische .bin-Abbilder werden nicht verwendet"
        )
    if any(token in name for token in ("factory", "webflasher", "merged")):
        raise RuntimeError("Factory-/Webflasher-Abbilder sind im Updatepfad gesperrt")


def _validate_manifest_contract(
    manifest: dict[str, Any], code: str, asset: str = "", *, require_schema: bool = True
) -> None:
    if not isinstance(manifest, dict):
        raise RuntimeError("Firmware-Manifest ist ungültig")
    if require_schema and int(manifest.get("schema") or 0) != 1:
        raise RuntimeError("Firmware-Manifest hat nicht Schema 1")
    if str(manifest.get("device") or "") != str(series.DEVICES[code]["device"]):
        raise RuntimeError("Firmware-Manifest passt nicht zur erkannten Hardware")
    firmware_asset = str(asset or manifest.get("firmware_asset") or "")
    _strict_update_name(firmware_asset)
    digest = str(manifest.get("firmware_sha256") or "").lower()
    size = int(manifest.get("firmware_size") or 0)
    if size <= 0 or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise RuntimeError("Firmware-Manifest enthält keine vollständige Größe/SHA-256")


def _strict_local_bundle(
    raw: bytes, filename: str, code: str
) -> tuple[bytes, dict[str, Any], str]:
    if not str(filename).lower().endswith(".zip"):
        _strict_update_name(filename)
    firmware, manifest, asset = _ORIGINAL_LOCAL_BUNDLE(raw, filename, code)
    _strict_update_name(asset)
    _validate_manifest_contract(manifest, code, asset, require_schema=False)
    return firmware, manifest, asset


def _strict_github_bundle(
    tag: str, manifest_name: str, code: str
) -> tuple[bytes, dict[str, Any], str]:
    firmware, manifest, asset = _ORIGINAL_GITHUB_BUNDLE(tag, manifest_name, code)
    _validate_manifest_contract(manifest, code, asset)
    return firmware, manifest, asset


def _verified_loader() -> bytes:
    data = series._http_bytes(OTA_LOADER_URL, OTA_LOADER_MAX, 60.0)
    digest = hashlib.sha256(data).hexdigest()
    if digest != OTA_LOADER_SHA256:
        raise RuntimeError(
            f"otaBTupdate SHA-256 stimmt nicht ({digest} statt {OTA_LOADER_SHA256})"
        )
    if not data or data[0] != 0xE9:
        raise RuntimeError("otaBTupdate ist kein gültiges ESP32-S3-Abbild")
    return data


def _profile_code(tool: Any, slot: int) -> str:
    profile = series._profile(tool, slot)
    converter = getattr(tool, "_device_code_from_hw_text", None)
    if not callable(converter):
        return ""
    return str(converter(str(profile.get("source_hw") or "")) or "").upper()


def _detect_usb_hardware(tool: Any, port: str) -> str:
    import JARNSEN_NODE_SERVICE_TOOL as legacy

    interface = None
    detected = ""
    try:
        tool._select_serial_port_in_ui(port)
        interface, _node = tool._open_config_profile_interface(("USB", port, port))
        metadata = getattr(interface, "metadata", None)
        with contextlib.suppress(Exception):
            detected = str(
                legacy.OTABT_HARDWARE_CODES.get(
                    int(getattr(metadata, "hw_model", 0) or 0), ""
                )
            )
        if not detected:
            with contextlib.suppress(Exception):
                info = interface.getMyNodeInfo() or {}
                user = info.get("user") if isinstance(info, dict) else None
                text = (
                    str((user or {}).get("hwModel") or (user or {}).get("hw_model") or "")
                    if isinstance(user, dict)
                    else ""
                )
                converter = getattr(tool, "_device_code_from_hw_text", None)
                if callable(converter):
                    detected = str(converter(text) or "")
    finally:
        if interface is not None:
            with contextlib.suppress(Exception):
                interface.close()
    return detected.upper()


def _resolve_bundle(tool: Any, code: str, context: dict[str, Any]) -> tuple[tuple[bytes, bytes, dict[str, Any]], str]:
    source = str(context.get("source") or "latest")
    if source == "latest":
        original = tool.__dict__.get("_framework7_series_original_bundle_loader")
        if not callable(original):
            original = getattr(tool, "_download_serial_bundle", None)
        if not callable(original):
            raise RuntimeError("Serieller Firmware-Bundle-Loader fehlt im Servicekern")
        firmware, loader, manifest = original(code)
        manifest = dict(manifest)
        _validate_manifest_contract(manifest, code)
        if hashlib.sha256(bytes(loader)).hexdigest() != OTA_LOADER_SHA256:
            raise RuntimeError("Legacy otaBTupdate entspricht nicht dem geprüften Loader")
        return (bytes(firmware), bytes(loader), manifest), "Aktuellste geprüfte Jarnsen-Firmware"

    if source == "github":
        firmware, manifest, asset = _strict_github_bundle(
            str(context.get("github_tag") or ""),
            str(context.get("github_manifest") or ""),
            code,
        )
        return (firmware, _verified_loader(), manifest), f"GitHub {context.get('github_tag')} · {asset}"

    if source == "local":
        firmware, manifest, asset = _strict_local_bundle(
            bytes(context.get("local_bytes") or b""),
            str(context.get("local_name") or ""),
            code,
        )
        label = f"Lokal · {asset} · SHA256 {str(manifest.get('local_sha256') or manifest.get('firmware_sha256') or '')[:12]}"
        return (firmware, _verified_loader(), manifest), label

    raise RuntimeError(f"Unbekannte Firmwarequelle: {source}")


def _preflight_and_prefetch(tool: Any, port: str, expected: str) -> str:
    context = tool.__dict__.get("_framework7_series_request_context")
    if not isinstance(context, dict):
        return _ORIGINAL_PREFLIGHT(tool, port, expected)

    physical = ""
    detection_error: Exception | None = None
    try:
        physical = _detect_usb_hardware(tool, port)
    except Exception as exc:
        detection_error = exc

    expected = str(expected or "AUTO").upper()
    slot = int(context.get("profile_slot") or 0)
    profile_code = _profile_code(tool, slot)

    if physical in series.DEVICES:
        code = physical
        if expected in series.DEVICES and expected != code:
            raise RuntimeError(
                f"Hardwareprüfung abgebrochen: erkannt {series.DEVICES[code]['label']}, "
                f"ausgewählt {series.DEVICES[expected]['label']}"
            )
        if profile_code in series.DEVICES and profile_code != code:
            raise RuntimeError(
                f"Grundprofil passt nicht zur Node: Profil={series.DEVICES[profile_code]['label']}, "
                f"Node={series.DEVICES[code]['label']}"
            )
    else:
        if profile_code not in series.DEVICES:
            detail = f" ({detection_error})" if detection_error else ""
            raise RuntimeError(
                "Hardware konnte nicht direkt von der USB-Node erkannt werden und das Grundprofil "
                "enthält keinen eindeutigen Tracker/V3-Hardwaretyp" + detail
            )
        if expected in series.DEVICES and expected != profile_code:
            raise RuntimeError(
                "Hardwareauswahl widerspricht dem Grundprofil; Werkreset wurde nicht gestartet"
            )
        code = profile_code
        context["virgin_profile_fallback"] = True

    bundle, label = _resolve_bundle(tool, code, context)
    firmware, loader, manifest = bundle
    series._validate_image(
        firmware,
        int(manifest.get("firmware_size") or 0),
        str(manifest.get("firmware_sha256") or ""),
    )
    if hashlib.sha256(loader).hexdigest() != OTA_LOADER_SHA256:
        raise RuntimeError("otaBTupdate konnte vor dem Werkreset nicht verifiziert werden")
    offset = str(manifest.get("ota_partition_offset") or OTA_LOADER_OFFSET).lower()
    if offset != OTA_LOADER_OFFSET.lower():
        raise RuntimeError("OTA-Loader-Offset im Manifest ist nicht 0x340000")

    tool._framework7_series_prefetched_bundle = {
        "device_code": code,
        "source": str(context.get("source") or "latest"),
        "bundle": (firmware, loader, manifest),
        "label": label,
    }
    return code


def _install_prefetch_bundle_wrapper(tool: Any) -> None:
    if bool(tool.__dict__.get("_framework7_series_bundle_wrapped_v38", False)):
        return
    original = getattr(tool, "_download_serial_bundle", None)
    if not callable(original):
        raise RuntimeError("Serieller Firmware-Bundle-Loader fehlt im Servicekern")
    tool._framework7_series_original_bundle_loader = original

    def wrapped(code: str):
        override = tool.__dict__.get("_framework7_series_bundle_override")
        if not isinstance(override, dict):
            return original(code)
        prefetched = tool.__dict__.get("_framework7_series_prefetched_bundle")
        try:
            code = str(code or "").upper()
            expected = str(override.get("device_code") or "").upper()
            if code != expected:
                raise RuntimeError(f"Firmware-Sicherheitsprüfung: erkannt {code}, erwartet {expected}")
            if not isinstance(prefetched, dict):
                raise RuntimeError(
                    "Firmwarebundle wurde nicht vor dem Werkreset validiert; Flash wird abgebrochen"
                )
            if str(prefetched.get("device_code") or "").upper() != code:
                raise RuntimeError("Vorgeprüftes Firmwarebundle gehört zu anderer Hardware")
            if str(prefetched.get("source") or "") != str(override.get("source") or "latest"):
                raise RuntimeError("Vorgeprüfte Firmwarequelle stimmt nicht mit Auftrag überein")
            bundle = prefetched.get("bundle")
            if not isinstance(bundle, tuple) or len(bundle) != 3:
                raise RuntimeError("Vorgeprüftes Firmwarebundle ist unvollständig")
            firmware, loader, manifest = bundle
            job = tool.__dict__.get("_framework7_series_job")
            if isinstance(job, dict):
                job["source_sha"] = str(manifest.get("source_sha") or "").lower()
                job["firmware_label"] = str(prefetched.get("label") or "Geprüfte Firmware")
            return bytes(firmware), bytes(loader), dict(manifest)
        finally:
            tool._framework7_series_bundle_override = None
            tool._framework7_series_prefetched_bundle = None

    tool._download_serial_bundle = wrapped
    tool._framework7_series_bundle_wrapped = True
    tool._framework7_series_bundle_wrapped_v38 = True


def _locked_append_history(job: dict[str, Any]) -> None:
    with _STORE_LOCK:
        _ORIGINAL_APPEND_HISTORY(job)


def install_series_hardening(LegacyBridge: type, ApiHandler: type) -> None:
    """Install v3.8 safety contracts after ``install_series``."""
    if bool(getattr(LegacyBridge, "_framework7_series_v38_installed", False)):
        return
    if not bool(getattr(LegacyBridge, "_framework7_series_v37_installed", False)):
        raise RuntimeError("Series v3.7 muss vor dem Hardening installiert sein")

    series._local_bundle = _strict_local_bundle
    series._github_bundle = _strict_github_bundle
    series._preflight = _preflight_and_prefetch
    series._install_bundle_wrapper = _install_prefetch_bundle_wrapper
    series._append_history = _locked_append_history

    previous_action = LegacyBridge.series_action

    def series_action(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise RuntimeError("Serienanforderung muss ein JSON-Objekt sein")
        command = str(payload.get("command") or "").strip()
        if command in {"save_template", "delete_template", "clear_history"}:
            with _STORE_LOCK:
                return previous_action(self, payload)
        if command != "start":
            return previous_action(self, payload)

        settings = series._settings(payload)
        context: dict[str, Any] = {
            "source": settings["firmware_source"],
            "profile_slot": settings["profile_slot"],
            "hardware": settings["hardware"],
            "github_tag": settings["github_tag"],
            "github_manifest": settings["github_manifest"],
        }
        if settings["firmware_source"] == "local":
            local_bytes, local_name = series._decode_local(payload)
            context.update(local_bytes=local_bytes, local_name=local_name)

        self.tool._framework7_series_request_context = context
        self.tool._framework7_series_prefetched_bundle = None
        try:
            result = previous_action(self, payload)
            if not isinstance(result, dict) or not result.get("ok", False):
                self.tool._framework7_series_prefetched_bundle = None
            return result
        except Exception:
            self.tool._framework7_series_prefetched_bundle = None
            self.tool._framework7_series_bundle_override = None
            raise
        finally:
            self.tool._framework7_series_request_context = None

    LegacyBridge.series_action = series_action

    previous_status = LegacyBridge.service_status

    def service_status(self: Any) -> dict[str, Any]:
        data = previous_status(self)
        critical = data.setdefault("critical", {})
        critical["series_pre_destructive_bundle"] = True
        critical["series_update_image_only"] = True
        info = data.setdefault("series", {})
        info.update(
            hardening=HARDENING_VERSION,
            pre_destructive_bundle=True,
            update_image_only=True,
            fixed_ota_loader_sha256=OTA_LOADER_SHA256,
            ota_partition_offset=OTA_LOADER_OFFSET,
            virgin_profile_fallback=True,
        )
        data["ok"] = all(bool(value) for value in critical.values())
        return data

    LegacyBridge.service_status = service_status

    previous_post = ApiHandler.do_POST

    def do_POST(self: Any) -> None:  # noqa: N802
        if urllib.parse.urlparse(self.path).path != "/api/series/action":
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
            if length <= 0 or length > MAX_REQUEST:
                self._send(
                    413 if length > MAX_REQUEST else 400,
                    {"ok": False, "error": "Serienanforderung ist leer oder zu groß"},
                )
                return
            raw = self.rfile.read(length)
            if len(raw) != length:
                self._send(400, {"ok": False, "error": "Serienanforderung ist unvollständig"})
                return
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict):
                self._send(400, {"ok": False, "error": "Serienanforderung muss ein JSON-Objekt sein"})
                return
            self._send(200, self.bridge.series_action(payload))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            self._send(400, {"ok": False, "error": f"Ungültige Serienanforderung: {exc}"})
        except RuntimeError as exc:
            self._send(409, {"ok": False, "error": str(exc), "type": type(exc).__name__})
        except Exception as exc:  # noqa: BLE001
            self._send(500, {"ok": False, "error": str(exc), "type": type(exc).__name__})

    ApiHandler.do_POST = do_POST
    LegacyBridge._framework7_series_v38_installed = True
