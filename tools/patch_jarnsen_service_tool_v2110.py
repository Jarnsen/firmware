"""v2.1.10: make Meshtastic config BLE safe in PyInstaller --windowed builds."""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "2.1.10"


def method_span(text: str, name: str) -> tuple[int, int]:
    start = text.find(f"    def {name}(")
    if start < 0:
        raise SystemExit(f"method {name} not found")
    next_method = text.find("\n    def ", start + 1)
    next_decorator = text.find("\n    @", start + 1)
    candidates = [value for value in (next_method, next_decorator) if value >= 0]
    return start, min(candidates) if candidates else len(text)


def replace_method(text: str, name: str, replacement: str) -> str:
    start, end = method_span(text, name)
    return text[:start] + replacement.rstrip() + "\n" + text[end:]


def insert_before_method(text: str, name: str, code: str) -> str:
    start, _ = method_span(text, name)
    return text[:start] + code.rstrip() + "\n\n" + text[start:]


def patch(source: str) -> str:
    source = re.sub(r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{APP_VERSION}"', source, count=1)
    source = source.replace('APP_VERSION != "2.1.9"', 'APP_VERSION != "2.1.10"')
    source = source.replace("App-Version ist nicht v2.1.9", "App-Version ist nicht v2.1.10")

    if "    def _ensure_meshtastic_gui_streams(self" not in source:
        helper = r'''    def _ensure_meshtastic_gui_streams(self) -> None:
        """Provide stdout/stderr for meshtastic-python inside a windowed EXE.

        PyInstaller --windowed deliberately sets sys.stdout/sys.stderr to None.
        meshtastic-python's BLEClient.async_await() unconditionally calls
        sys.stdout.flush(), so configuration reads would otherwise fail before
        the BLE transaction can complete.  A persistent os.devnull stream keeps
        the library happy without opening a console window or polluting logs.
        """
        stdout_ok = sys.stdout is not None and callable(getattr(sys.stdout, "flush", None))
        stderr_ok = sys.stderr is not None and callable(getattr(sys.stderr, "flush", None))
        if stdout_ok and stderr_ok:
            return
        sink = getattr(self, "_meshtastic_console_sink", None)
        if sink is None or getattr(sink, "closed", False):
            sink = open(os.devnull, "w", encoding="utf-8", buffering=1)
            self._meshtastic_console_sink = sink
        if not stdout_ok:
            sys.stdout = sink
        if not stderr_ok:
            sys.stderr = sink
        tool_log(
            "MESHTASTIC_GUI_STREAM_V2110",
            stdout_repaired=not stdout_ok,
            stderr_repaired=not stderr_ok,
        )
'''
        source = insert_before_method(source, "_open_config_profile_interface", helper)

    replacement = r'''    def _open_config_profile_interface(self, connection: tuple[str, str, str]):
        self._ensure_meshtastic_gui_streams()
        transport, target, _label = connection
        if transport == "Bluetooth":
            if MeshtasticBLEInterface is None:
                raise RuntimeError("Meshtastic-BLE-Unterstützung fehlt.")
            interface = MeshtasticBLEInterface(target, noNodes=True, timeout=90)
        else:
            if MeshtasticSerialInterface is None:
                raise RuntimeError("Meshtastic-USB-Unterstützung fehlt.")
            interface = MeshtasticSerialInterface(devPath=target, noNodes=True, timeout=90)
        node = interface.localNode
        if node is None or not node.waitForConfig("channels"):
            interface.close()
            raise RuntimeError("Meshtastic-Konfiguration wurde nicht vollständig von der Node empfangen.")
        return interface, node
'''
    source = replace_method(source, "_open_config_profile_interface", replacement)

    required = (
        'APP_VERSION = "2.1.10"',
        "def _ensure_meshtastic_gui_streams(self)",
        "MESHTASTIC_GUI_STREAM_V2110",
        "self._ensure_meshtastic_gui_streams()",
        'open(os.devnull, "w", encoding="utf-8", buffering=1)',
    )
    missing = [marker for marker in required if marker not in source]
    if missing:
        raise SystemExit("v2.1.10 validation failed: " + ", ".join(missing))
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v2110.py <source.py>")
    path = Path(sys.argv[1])
    source = path.read_text(encoding="utf-8")
    path.write_text(patch(source), encoding="utf-8")
    print(f"Patched {path} to v{APP_VERSION}: Meshtastic windowed stdout/stderr compatibility")


if __name__ == "__main__":
    main()
