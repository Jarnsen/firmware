"""Frequency-bound Jarnsen radio authorization for the Framework7 Service Tool.

The tool stores the two assigned frequencies once and carries the authorization
metadata into every profile.  Standard profiles remain limited to max. 7 hops
and normal duty-cycle behavior.  Profiles using exactly Frequency A/B may use
max. 20 hops and get override_duty_cycle enabled.

Transmit-power authorization is intentionally stored as frequency-bound metadata
instead of toggling Meshtastic's global owner.is_licensed flag, because that flag
would unlock regulatory power limits on every frequency.  Compatible Jarnsen
firmware can consume the metadata and only lift its power limit when the active
RF frequency exactly matches A or B.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import math
import urllib.parse
from typing import Any

STORE_KEY = "jarnsen_radio_authorization"
STANDARD_MAX_HOPS = 7
AUTHORIZED_MAX_HOPS = 20


def _mhz_to_hz(value: object) -> int:
    text = str(value or "").strip().replace(",", ".")
    if not text:
        return 0
    try:
        mhz = float(text)
    except ValueError as exc:
        raise RuntimeError("Frequenz muss als MHz-Wert eingegeben werden") from exc
    if not math.isfinite(mhz) or mhz <= 0:
        return 0
    if mhz < 100.0 or mhz > 2500.0:
        raise RuntimeError("Frequenz muss zwischen 100 und 2500 MHz liegen")
    return int(round(mhz * 1_000_000.0))


def _hz_to_mhz(hz: int) -> float:
    return round(int(hz or 0) / 1_000_000.0, 6) if hz else 0.0


def _default_auth() -> dict[str, Any]:
    return {
        "schema": 1,
        "frequency_a_hz": 0,
        "frequency_b_hz": 0,
        "frequency_a_mhz": 0.0,
        "frequency_b_mhz": 0.0,
        "standard_max_hops": STANDARD_MAX_HOPS,
        "authorized_max_hops": AUTHORIZED_MAX_HOPS,
        "unlock_tx_power": True,
        "unlock_duty_cycle": True,
        "frequency_bound": True,
        "updated_at": "",
    }


def _load_auth(tool: Any) -> dict[str, Any]:
    raw = tool.config_profile_store.get(STORE_KEY, {})
    auth = _default_auth()
    if isinstance(raw, dict):
        with contextlib.suppress(Exception):
            auth["frequency_a_hz"] = max(0, int(raw.get("frequency_a_hz") or 0))
        with contextlib.suppress(Exception):
            auth["frequency_b_hz"] = max(0, int(raw.get("frequency_b_hz") or 0))
        auth["updated_at"] = str(raw.get("updated_at") or "")
    auth["frequency_a_mhz"] = _hz_to_mhz(auth["frequency_a_hz"])
    auth["frequency_b_mhz"] = _hz_to_mhz(auth["frequency_b_hz"])
    return auth


def _mode_for_frequency(auth: dict[str, Any], frequency_hz: int) -> str:
    if frequency_hz and frequency_hz == int(auth.get("frequency_a_hz") or 0):
        return "jarnsen_1"
    if frequency_hz and frequency_hz == int(auth.get("frequency_b_hz") or 0):
        return "jarnsen_2"
    return "standard"


def _lora_frequency_hz(data: dict[str, Any]) -> int:
    value = data.get("override_frequency")
    try:
        mhz = float(value or 0)
    except (TypeError, ValueError):
        return 0
    if not math.isfinite(mhz) or mhz <= 0:
        return 0
    return int(round(mhz * 1_000_000.0))


def _apply_rules_to_lora(data: dict[str, Any], auth: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    updated = dict(data)
    frequency_hz = _lora_frequency_hz(updated)
    mode = _mode_for_frequency(auth, frequency_hz)
    authorized = mode != "standard"
    max_hops = AUTHORIZED_MAX_HOPS if authorized else STANDARD_MAX_HOPS

    try:
        hops = int(updated.get("hop_limit") or 0)
    except (TypeError, ValueError):
        hops = 0
    if hops < 0:
        hops = 0
    if hops > max_hops:
        hops = max_hops
    updated["hop_limit"] = hops

    # Duty-cycle override is safe to bind directly to the exact A/B frequency.
    updated["override_duty_cycle"] = bool(authorized and auth.get("unlock_duty_cycle", True))

    policy = {
        "mode": mode,
        "authorized": authorized,
        "frequency_hz": frequency_hz,
        "frequency_mhz": _hz_to_mhz(frequency_hz),
        "max_hops": max_hops,
        "duty_cycle_unlocked": bool(updated["override_duty_cycle"]),
        # Do not map this to owner.is_licensed: that would remove limits globally.
        "tx_power_unlock_requested": bool(authorized and auth.get("unlock_tx_power", True)),
        "tx_power_requires_frequency_aware_firmware": True,
    }
    return updated, policy


def _profile_metadata(auth: dict[str, Any], policy: dict[str, Any] | None = None) -> dict[str, Any]:
    result = {
        "schema": 1,
        "frequency_a_hz": int(auth.get("frequency_a_hz") or 0),
        "frequency_b_hz": int(auth.get("frequency_b_hz") or 0),
        "standard_max_hops": STANDARD_MAX_HOPS,
        "authorized_max_hops": AUTHORIZED_MAX_HOPS,
        "unlock_tx_power": True,
        "unlock_duty_cycle": True,
        "frequency_bound": True,
    }
    if policy:
        result.update(policy)
    return result


def _sync_profiles(tool: Any, auth: dict[str, Any]) -> None:
    """Carry the global authorization into every existing profile."""
    try:
        from google.protobuf import json_format
    except Exception:
        json_format = None

    profiles = tool.config_profile_store.get("profiles", [])
    if not isinstance(profiles, list):
        return

    changed = False
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        policy: dict[str, Any] | None = None
        if json_format is not None:
            with contextlib.suppress(Exception):
                current = tool._profile_message(profile, "config", "lora")
                data = json_format.MessageToDict(current, preserving_proto_field_name=True)
                updated_data, policy = _apply_rules_to_lora(data, auth)
                if updated_data != data:
                    updated = type(current)()
                    json_format.ParseDict(updated_data, updated, ignore_unknown_fields=False)
                    tool._save_profile_message(profile, "config", "lora", updated)
                    changed = True
        metadata = _profile_metadata(auth, policy)
        if profile.get(STORE_KEY) != metadata:
            profile[STORE_KEY] = metadata
            changed = True

    if changed:
        tool._save_config_profile_store()


def install_radio_authorization(LegacyBridge: type, ApiHandler: type) -> None:
    """Install the global A/B frequency API and profile enforcement layer."""

    def radio_authorization(self: Any) -> dict[str, Any]:
        def collect() -> dict[str, Any]:
            auth = _load_auth(self.tool)
            profiles = self.tool.config_profile_store.get("profiles", [])
            auth["profiles_seen"] = sum(1 for p in profiles if isinstance(p, dict)) if isinstance(profiles, list) else 0
            return auth

        return self.call_ui(collect, timeout=15.0)

    def save_radio_authorization(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
        frequency_a_hz = _mhz_to_hz(payload.get("frequency_a_mhz"))
        frequency_b_hz = _mhz_to_hz(payload.get("frequency_b_mhz"))
        if frequency_a_hz and frequency_b_hz and frequency_a_hz == frequency_b_hz:
            raise RuntimeError("Frequenz A und Frequenz B müssen unterschiedlich sein")

        def save() -> dict[str, Any]:
            auth = _default_auth()
            auth.update(
                {
                    "frequency_a_hz": frequency_a_hz,
                    "frequency_b_hz": frequency_b_hz,
                    "frequency_a_mhz": _hz_to_mhz(frequency_a_hz),
                    "frequency_b_mhz": _hz_to_mhz(frequency_b_hz),
                    "updated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                }
            )
            self.tool.config_profile_store[STORE_KEY] = {
                key: auth[key]
                for key in (
                    "schema",
                    "frequency_a_hz",
                    "frequency_b_hz",
                    "standard_max_hops",
                    "authorized_max_hops",
                    "unlock_tx_power",
                    "unlock_duty_cycle",
                    "frequency_bound",
                    "updated_at",
                )
            }
            _sync_profiles(self.tool, auth)
            self.tool._save_config_profile_store()
            return auth

        return self.call_ui(save, timeout=30.0)

    LegacyBridge.radio_authorization = radio_authorization
    LegacyBridge.save_radio_authorization = save_radio_authorization

    original_save_section = getattr(LegacyBridge, "save_profile_section", None)
    if original_save_section is not None:
        def save_profile_section_with_radio_policy(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
            adjusted = dict(payload)
            if str(adjusted.get("kind") or "") == "config" and str(adjusted.get("name") or "") == "lora":
                raw = adjusted.get("data")
                if isinstance(raw, dict):
                    auth = self.radio_authorization()
                    updated, _policy = _apply_rules_to_lora(raw, auth)
                    adjusted["data"] = updated
            result = original_save_section(self, adjusted)
            if str(adjusted.get("kind") or "") == "config" and str(adjusted.get("name") or "") == "lora":
                def sync() -> None:
                    _sync_profiles(self.tool, _load_auth(self.tool))
                self.call_ui(sync, timeout=20.0)
            return result

        LegacyBridge.save_profile_section = save_profile_section_with_radio_policy

    original_profile_action = getattr(LegacyBridge, "profile_action", None)
    if original_profile_action is not None:
        def profile_action_with_radio_policy(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
            command = str(payload.get("command") or "")
            if command in {"apply", "provision"}:
                self.call_ui(lambda: _sync_profiles(self.tool, _load_auth(self.tool)), timeout=25.0)
            return original_profile_action(self, payload)

        LegacyBridge.profile_action = profile_action_with_radio_policy

    original_get = ApiHandler.do_GET
    original_post = ApiHandler.do_POST

    def do_GET(self: Any) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/radio-authorization":
            if not self._authorized():
                self._send(403, {"ok": False, "error": "forbidden"})
                return
            try:
                self._send(200, self.bridge.radio_authorization())
            except Exception as exc:  # noqa: BLE001
                self._send(500, {"ok": False, "error": str(exc), "type": type(exc).__name__})
            return
        original_get(self)

    def do_POST(self: Any) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/radio-authorization":
            if not self._authorized():
                self._send(403, {"ok": False, "error": "forbidden"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
                import json
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                self._send(200, self.bridge.save_radio_authorization(payload))
            except Exception as exc:  # noqa: BLE001
                self._send(500, {"ok": False, "error": str(exc), "type": type(exc).__name__})
            return
        original_post(self)

    ApiHandler.do_GET = do_GET
    ApiHandler.do_POST = do_POST
