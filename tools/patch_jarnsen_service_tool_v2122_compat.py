"""Compatibility shim for the v2.1.22 Service Tool patch."""
from __future__ import annotations

import sys
from pathlib import Path

import patch_jarnsen_service_tool_v2122 as core


def normalize_v2118_worker(source: str) -> str:
    worker_start = '''        interface = None
        expected_config: dict[str, bytes] = {}
'''
    if "fixed_bt_pin = 240180" not in source:
        if worker_start not in source:
            raise SystemExit("v2.1.22 compat worker start anchor missing")
        source = source.replace(
            worker_start,
            '''        fixed_bt_pin = 240180
        interface = None
        expected_config: dict[str, bytes] = {}
''',
            1,
        )

    deferred_old = '''                    desired.ParseFromString(self._decode_protobuf_payload(deferred_bluetooth))
                    configure_fixed_bt_pin(desired)
                    section.CopyFrom(desired)
'''
    deferred_new = '''                    desired.ParseFromString(self._decode_protobuf_payload(deferred_bluetooth))
                    section.CopyFrom(desired)
'''
    if deferred_old in source:
        source = source.replace(deferred_old, deferred_new, 1)
    return source


def finalize_ui(source: str) -> str:
    source = source.replace(
        'ttk.Entry(pin_controls, textvariable=self.config_bt_pin_var, width=9).pack(',
        'ttk.Entry(pin_controls, textvariable=self.config_bt_pin_var, width=9, state="readonly").pack(',
        1,
    )
    source = source.replace(
        'text="BT-PIN beim Übertragen setzen"',
        'text="Jarnsen-PIN 240180 wird immer gesetzt"',
        1,
    )
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v2122_compat.py <source.py>")
    path = Path(sys.argv[1])
    source = normalize_v2118_worker(path.read_text(encoding="utf-8"))
    source = core.patch(source)
    source = finalize_ui(source)
    path.write_text(source, encoding="utf-8")
    print("Patched Service Tool to v2.1.22 through v2.1.18 compatibility shim")


if __name__ == "__main__":
    main()
