"""v2.1.23: post-reset robustness, profile-name prefill and protobuf compatibility."""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "2.1.23"


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"v2.1.23 {label} anchor missing or ambiguous ({count})")
    return source.replace(old, new, 1)


def patch(source: str) -> str:
    if "PATCH_V2123_POST_RESET" in source:
        return source

    source = re.sub(r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{APP_VERSION}"', source, count=1)
    source = source.replace('APP_VERSION != "2.1.22"', 'APP_VERSION != "2.1.23"')
    source = source.replace("App-Version ist nicht v2.1.22", "App-Version ist nicht v2.1.23")

    # protobuf/upb no longer exposes FieldDescriptor.label in the packaged runtime.
    source = replace_once(
        source,
        '''                if field.label == FieldDescriptor.LABEL_REPEATED:\n                    advanced[0] = True\n                    continue\n''',
        '''                if bool(getattr(field, "is_repeated", False)):\n                    advanced[0] = True\n                    continue\n''',
        "protobuf repeated-field",
    )

    # Reading a reusable base profile also reads the current owner names.  They stay
    # metadata (not copied into the profile payload), but prefill the target fields.
    source = replace_once(
        source,
        '''            interface, node = self._open_config_profile_interface(connection)\n            source_hw, source_firmware = self._config_profile_metadata(interface)\n            config_sections: dict[str, str] = {}\n''',
        '''            interface, node = self._open_config_profile_interface(connection)\n            source_hw, source_firmware = self._config_profile_metadata(interface)\n            source_long_name = str(interface.getLongName() or "").strip()\n            source_short_name = str(interface.getShortName() or "").strip()\n            config_sections: dict[str, str] = {}\n''',
        "profile capture owner names",
    )
    source = replace_once(
        source,
        '''                "source_hw": source_hw,\n                "source_firmware": source_firmware,\n                "psk_included": include_psk,\n''',
        '''                "source_hw": source_hw,\n                "source_firmware": source_firmware,\n                "source_long_name": source_long_name,\n                "source_short_name": source_short_name,\n                "psk_included": include_psk,\n''',
        "profile owner metadata",
    )
    source = replace_once(
        source,
        '''                    profiles[int(slot)] = dict(profile)\n                    self._save_config_profile_store()\n                    self._refresh_config_profile_ui()\n                    self.status_level = "success"\n''',
        '''                    profiles[int(slot)] = dict(profile)\n                    self._save_config_profile_store()\n                    self._refresh_config_profile_ui()\n                    source_long_name = str(profile.get("source_long_name") or "").strip()\n                    source_short_name = str(profile.get("source_short_name") or "").strip()\n                    if source_long_name and hasattr(self, "config_target_long_var"):\n                        self.config_target_long_var.set(source_long_name)\n                    if source_short_name and hasattr(self, "config_target_short_var"):\n                        self.config_target_short_var.set(source_short_name[:4])\n                    tool_log(\n                        "CONFIG_PROFILE_TARGET_NAMES_V2123",\n                        slot=int(slot) + 1,\n                        long_name=source_long_name or "--",\n                        short_name=source_short_name or "--",\n                    )\n                    self.status_level = "success"\n''',
        "profile capture name prefill event",
    )
    source = source.replace(
        '"Node-ID, Long/Short Name, Device-Keys und feste Position wurden nicht übernommen.",',
        '"Node-ID, Device-Keys und feste Position wurden nicht übernommen. Long/Short Name wurden als Zielname vorausgefüllt.",',
        1,
    )

    # The custom firmware may enforce Bluetooth enabled/disabled according to its
    # runtime/service policy.  Verify the transferable pairing policy itself (mode
    # and fixed PIN) without reporting the firmware-owned enabled bit as a mismatch.
    source = replace_once(
        source,
        '''                            for field_name in ("enabled", "mode", "fixed_pin"):\n''',
        '''                            for field_name in ("mode", "fixed_pin"):\n''',
        "bluetooth policy verification",
    )

    # After a reset/flash the node can need roughly a minute before the diagnostic
    # export marker appears.  45 s was shorter than a proven manual transfer.
    source = replace_once(
        source,
        '''            deadline = time.monotonic() + (45 if auto_mode else 300)\n''',
        '''            deadline = time.monotonic() + (100 if auto_mode else 300)\n''',
        "auto USB log timeout",
    )
    source = source.replace(
        'self.after(900, lambda selected_port=str(connection[1]): self._start_auto_usb_download(selected_port))',
        'self.after(3000, lambda selected_port=str(connection[1]): self._start_auto_usb_download(selected_port))',
        1,
    )

    source = replace_once(
        source,
        'return "Jarnsen Policy: Firmware kennt POLICY v1 noch nicht; nach Firmwareupdate erneut anwenden"',
        'return "Jarnsen RF-Policy-Schnittstelle (POLICY v1) nicht erkannt; nach Firmwareupdate erneut anwenden"',
        "policy warning wording",
    )

    source += "\n# PATCH_V2123_POST_RESET\n"

    required = (
        'APP_VERSION = "2.1.23"',
        'getattr(field, "is_repeated", False)',
        'CONFIG_PROFILE_TARGET_NAMES_V2123',
        '"source_long_name": source_long_name',
        'for field_name in ("mode", "fixed_pin")',
        '(100 if auto_mode else 300)',
        'self.after(3000, lambda selected_port=',
        'Jarnsen RF-Policy-Schnittstelle (POLICY v1) nicht erkannt',
        'PATCH_V2123_POST_RESET',
    )
    missing = [marker for marker in required if marker not in source]
    if missing:
        raise SystemExit("v2.1.23 validation failed: " + ", ".join(missing))
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v2123.py <source.py>")
    path = Path(sys.argv[1])
    source = path.read_text(encoding="utf-8")
    path.write_text(patch(source), encoding="utf-8")
    print(f"Patched {path} to v{APP_VERSION}: post-reset USB log + profile names + protobuf compatibility")


if __name__ == "__main__":
    main()
