"""v2.1.12: robust Meshtastic profile capture and reliable onefile restart."""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "2.1.12"


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
    source = source.replace('APP_VERSION != "2.1.11"', 'APP_VERSION != "2.1.12"')
    source = source.replace("App-Version ist nicht v2.1.11", "App-Version ist nicht v2.1.12")

    local_old = '''            for field in node.localConfig.DESCRIPTOR.fields:\n                section = getattr(node.localConfig, field.name)\n                clone = type(section)()\n                clone.CopyFrom(section)\n'''
    local_new = '''            for field in node.localConfig.DESCRIPTOR.fields:\n                # LocalConfig can contain protobuf message sections as well as\n                # scalar wrapper/meta fields. Only message sections are valid\n                # writeConfig() targets and support CopyFrom/SerializeToString.\n                if field.message_type is None:\n                    tool_log(\n                        "CONFIG_PROFILE_SCALAR_SKIP_V2112",\n                        container="localConfig",\n                        field=field.name,\n                        value=getattr(node.localConfig, field.name, None),\n                    )\n                    continue\n                section = getattr(node.localConfig, field.name)\n                clone = type(section)()\n                clone.CopyFrom(section)\n'''
    if source.count(local_old) != 1:
        raise SystemExit("v2.1.12 localConfig capture anchor missing or ambiguous")
    source = source.replace(local_old, local_new, 1)

    module_old = '''            for field in node.moduleConfig.DESCRIPTOR.fields:\n                section = getattr(node.moduleConfig, field.name)\n                clone = type(section)()\n                clone.CopyFrom(section)\n                module_sections[field.name] = self._protobuf_payload(clone)\n'''
    module_new = '''            for field in node.moduleConfig.DESCRIPTOR.fields:\n                # ModuleConfig may also expose scalar/meta fields. They are not\n                # independently writable Meshtastic config sections.\n                if field.message_type is None:\n                    tool_log(\n                        "CONFIG_PROFILE_SCALAR_SKIP_V2112",\n                        container="moduleConfig",\n                        field=field.name,\n                        value=getattr(node.moduleConfig, field.name, None),\n                    )\n                    continue\n                section = getattr(node.moduleConfig, field.name)\n                clone = type(section)()\n                clone.CopyFrom(section)\n                module_sections[field.name] = self._protobuf_payload(clone)\n'''
    if source.count(module_old) != 1:
        raise SystemExit("v2.1.12 moduleConfig capture anchor missing or ambiguous")
    source = source.replace(module_old, module_new, 1)

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
                # Do not replace a running PyInstaller onefile child directly.
                # A short-lived .cmd file survives the extracted child, waits
                # one second, starts the original EXE and then removes itself.
                restart_argv = [executable, *sys.argv[1:]]
                command_line = subprocess.list2cmdline(restart_argv)
                temp_dir = pathlib.Path(os.environ.get("TEMP") or os.environ.get("TMP") or pathlib.Path(executable).parent)
                script_path = temp_dir / f"jarnsen-node-service-restart-{os.getpid()}.cmd"
                script_text = "\r\n".join((
                    "@echo off",
                    "timeout /t 1 /nobreak >nul",
                    f"start \"\" {command_line}",
                    "del \"%~f0\"",
                    "",
                ))
                script_path.write_text(script_text, encoding="utf-8")
                creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) | int(
                    getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                )
                subprocess.Popen(
                    ["cmd.exe", "/d", "/c", str(script_path)],
                    close_fds=True,
                    creationflags=creationflags,
                )
                tool_log(
                    "APP_RESTART_SCHEDULED_V2112",
                    mode="temp_cmd",
                    executable=executable,
                    script=script_path,
                )
                self.destroy()
                return

            argv = [sys.executable, os.path.abspath(sys.argv[0]), *sys.argv[1:]]
            subprocess.Popen(argv, close_fds=True)
            tool_log("APP_RESTART_SCHEDULED_V2112", mode="subprocess", executable=sys.executable)
            self.destroy()
        except Exception as exc:
            tool_log_exception("restart_app_v2112", exc)
            messagebox.showerror("Neustart fehlgeschlagen", str(exc))
'''
    source = replace_method(source, "restart_app", restart)

    required = (
        'APP_VERSION = "2.1.12"',
        "CONFIG_PROFILE_SCALAR_SKIP_V2112",
        "field.message_type is None",
        "APP_RESTART_SCHEDULED_V2112",
        "jarnsen-node-service-restart-",
        'start \\\"\\\"',
        "def _config_profile_capture_worker(",
        "Authorized 915 A",
        "Authorized 915 B",
    )
    missing = [marker for marker in required if marker not in source]
    if missing:
        raise SystemExit("v2.1.12 validation failed: " + ", ".join(missing))

    capture_start, capture_end = method_span(source, "_config_profile_capture_worker")
    capture_method = source[capture_start:capture_end]
    if "authorized_freq_a_var" in capture_method or "authorized_freq_b_var" in capture_method:
        raise SystemExit("Authorized-915 frequency fields must not gate profile capture")
    return source


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_jarnsen_service_tool_v2112.py <source.py>")
    path = Path(sys.argv[1])
    source = path.read_text(encoding="utf-8")
    path.write_text(patch(source), encoding="utf-8")
    print(f"Patched {path} to v{APP_VERSION}: robust config capture + reliable restart")


if __name__ == "__main__":
    main()
