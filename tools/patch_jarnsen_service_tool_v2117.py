"""v2.1.17: resilient profile apply, PyInstaller-safe restart, and visible stored BT PIN."""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "2.1.17"


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


def patch(source: str) -> str:
    source = re.sub(r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{APP_VERSION}"', source, count=1)
    source = source.replace('APP_VERSION != "2.1.16"', 'APP_VERSION != "2.1.17"')
    source = source.replace("App-Version ist nicht v2.1.16", "App-Version ist nicht v2.1.17")

    restart = r'''    def restart_app(self) -> None:
        if not messagebox.askyesno(
            "App neu starten",
            "Jarnsen Node Service Tool jetzt neu starten? Laufende Downloads werden beendet.",
        ):
            return
        self.stop_event.set()
        self.live_stop.set()
        with contextlib.suppress(Exception):
            if self.serial_monitor_active():
                self.stop_serial_monitor()
        self.update_idletasks()
        executable = str(pathlib.Path(sys.executable).resolve())
        tool_log("APP_RESTART_REQUEST", executable=executable, frozen=bool(getattr(sys, "frozen", False)))
        try:
            if getattr(sys, "frozen", False) and os.name == "nt":
                restart_env = os.environ.copy()
                restart_env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
                creationflags = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)) | int(
                    getattr(subprocess, "DETACHED_PROCESS", 0)
                )
                subprocess.Popen(
                    [executable, *sys.argv[1:]],
                    close_fds=True,
                    env=restart_env,
                    creationflags=creationflags,
                )
                tool_log(
                    "APP_RESTART_SCHEDULED_V2117",
                    mode="pyinstaller_reset_environment",
                    executable=executable,
                )
                self.destroy()
                return

            subprocess.Popen([sys.executable, os.path.abspath(sys.argv[0]), *sys.argv[1:]], close_fds=True)
            tool_log("APP_RESTART_SCHEDULED_V2117", mode="subprocess", executable=sys.executable)
            self.destroy()
        except Exception as exc:
            tool_log_exception("restart_app_v2117", exc)
            messagebox.showerror("Neustart fehlgeschlagen", str(exc))
'''
    source = replace_method(source, "restart_app", restart)

    apply_start, apply_end = method_span(source, "_config_profile_apply_worker")
    method = source[apply_start:apply_end]

    stage_anchor = '''            def stage(label: str) -> None:\n                self.events.put(("status", f"Grundprofil {slot + 1}: {label}"))\n                tool_log(\n                    "CONFIG_PROFILE_WRITE_STAGE_V2116",\n                    slot=slot + 1,\n                    transport=connection[0],\n                    stage=label,\n                )\n'''
    safe_writer = stage_anchor + '''\n            def write_config_safe(name: str, kind: str) -> bool:\n                try:\n                    node.writeConfig(name)\n                    return True\n                except SystemExit as exc:\n                    skipped.append(\n                        f"{kind} {name}: vom eingebauten Meshtastic-Python-Client nicht schreibbar; übersprungen"\n                    )\n                    tool_log(\n                        "CONFIG_PROFILE_UNSUPPORTED_WRITE_V2117",\n                        slot=slot + 1,\n                        transport=connection[0],\n                        kind=kind,\n                        name=name,\n                        exit_code=getattr(exc, "code", "--"),\n                    )\n                    return False\n'''
    if method.count(stage_anchor) != 1:
        raise SystemExit("v2.1.17 stage anchor missing or ambiguous")
    method = method.replace(stage_anchor, safe_writer, 1)

    config_write_old = '''                    stage(f"Config {name} schreiben")\n                    node.writeConfig(name)\n                    expected_config[name] = section.SerializeToString()\n                    time.sleep(0.65)\n'''
    config_write_new = '''                    stage(f"Config {name} schreiben")\n                    if write_config_safe(name, "Config"):\n                        expected_config[name] = section.SerializeToString()\n                    time.sleep(0.65)\n'''
    if method.count(config_write_old) != 1:
        raise SystemExit("v2.1.17 config write anchor missing or ambiguous")
    method = method.replace(config_write_old, config_write_new, 1)

    module_write_old = '''                    stage(f"Modul {name} schreiben")\n                    node.writeConfig(name)\n                    expected_modules[name] = section.SerializeToString()\n                    time.sleep(0.65)\n'''
    module_write_new = '''                    stage(f"Modul {name} schreiben")\n                    if write_config_safe(name, "Modul"):\n                        expected_modules[name] = section.SerializeToString()\n                    time.sleep(0.65)\n'''
    if method.count(module_write_old) != 1:
        raise SystemExit("v2.1.17 module write anchor missing or ambiguous")
    method = method.replace(module_write_old, module_write_new, 1)
    source = source[:apply_start] + method + source[apply_end:]

    pin_old = '''            if not enabled:\n                text = "Bluetooth ist auf der Node deaktiviert"\n            elif mode_name == "FIXED_PIN" and fixed_pin:\n                text = f"{fixed_pin:06d}"\n'''
    pin_new = '''            if not enabled:\n                if fixed_pin:\n                    text = f"Bluetooth aus · gespeicherter PIN {fixed_pin:06d} · Modus {mode_name}"\n                else:\n                    text = f"Bluetooth aus · kein gespeicherter PIN · Modus {mode_name}"\n            elif mode_name == "FIXED_PIN" and fixed_pin:\n                text = f"{fixed_pin:06d}"\n'''
    if source.count(pin_old) != 1:
        raise SystemExit("v2.1.17 BT PIN display anchor missing or ambiguous")
    source = source.replace(pin_old, pin_new, 1)

    required = (
        'APP_VERSION = "2.1.17"',
        'restart_env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"',
        "APP_RESTART_SCHEDULED_V2117",
        "CONFIG_PROFILE_UNSUPPORTED_WRITE_V2117",
        'write_config_safe(name, "Modul")',
        'write_config_safe(name, "Config")',
        "gespeicherter PIN",
    )
    missing = [marker for marker in required if marker not in source]
    if missing:
        raise SystemExit("v2.1.17 validation failed: " + ", ".join(missing))
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v2117.py <source.py>")
    path = Path(sys.argv[1])
    path.write_text(patch(path.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"Patched {path} to v{APP_VERSION}: resilient profile apply + safe restart + visible stored BT PIN")


if __name__ == "__main__":
    main()
