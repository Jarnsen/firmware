"""v2.1.2: safe onefile restart, fast firmware-crash detection, clearer BLE guidance."""
from __future__ import annotations

import re
import sys
from pathlib import Path

APP_VERSION = "2.1.2"


def method_span(text: str, name: str) -> tuple[int, int]:
    start = text.find(f"    def {name}(")
    if start < 0:
        raise SystemExit(f"method {name} not found")
    match = re.search(r"\n    (?=@|def )", text[start + 1 :])
    end = start + 1 + match.start() if match else len(text)
    return start, end


def replace_method(text: str, name: str, updater) -> str:
    start, end = method_span(text, name)
    return text[:start] + updater(text[start:end]) + text[end:]


def patch(source: str) -> str:
    source = re.sub(r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{APP_VERSION}"', source, count=1)
    source = source.replace('APP_VERSION != "2.1.1"', 'APP_VERSION != "2.1.2"')
    source = source.replace("App-Version ist nicht v2.1.1", "App-Version ist nicht v2.1.2")

    def replace_restart(_method: str) -> str:
        return r'''    def restart_app(self) -> None:
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
                # Do not os.execv() a PyInstaller --onefile child process. The
                # bootloader validates its parent process and can fail with
                # "failed to obtain executable path for parent process" when
                # the old extracted child replaces itself directly. A short-
                # lived cmd.exe becomes the new executable's stable parent and
                # starts it only after this GUI has had time to exit.
                restart_argv = [executable, *sys.argv[1:]]
                command_line = subprocess.list2cmdline(restart_argv)
                delayed = f'timeout /t 1 /nobreak >nul & start "" {command_line}'
                creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) | int(
                    getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                )
                subprocess.Popen(
                    ["cmd.exe", "/d", "/s", "/c", delayed],
                    close_fds=True,
                    creationflags=creationflags,
                )
                tool_log("APP_RESTART_SCHEDULED", mode="delayed_cmd", executable=executable)
                self.destroy()
                return

            argv = [sys.executable, os.path.abspath(sys.argv[0]), *sys.argv[1:]]
            subprocess.Popen(argv, close_fds=True)
            tool_log("APP_RESTART_SCHEDULED", mode="subprocess", executable=sys.executable)
            self.destroy()
        except Exception as exc:
            tool_log_exception("restart_app", exc)
            messagebox.showerror("Neustart fehlgeschlagen", str(exc))
'''

    source = replace_method(source, "restart_app", replace_restart)

    def harden_serial_download(method: str) -> str:
        if 'NODE_FIRMWARE_CRASH' in method:
            return method
        anchor = '''                if chunk:\n                    serial_bytes_received += len(chunk)\n                    scan.extend(chunk)\n'''
        if method.count(anchor) != 1:
            raise SystemExit("serial crash-detection anchor not found")
        crash_block = anchor + r'''                    if started:
                        crash_probe = bytes(captured[-8192:]) + bytes(scan[-8192:])
                        crash_signature = None
                        if b"Guru Meditation Error:" in crash_probe:
                            crash_signature = "Guru Meditation"
                        elif b"Stack canary watchpoint triggered" in crash_probe:
                            crash_signature = "Stack canary"
                        elif b"ESP-ROM:esp32s3" in crash_probe and b"Rebooting" in crash_probe:
                            crash_signature = "ESP32-S3 reboot"
                        if crash_signature:
                            crash_payload = bytes(captured) + bytes(scan)
                            crash_file = output_directory() / (
                                f"Jarnsen_Node_Log_CRASH_{now_local():%Y-%m-%d_%H%M%S}.txt"
                            )
                            crash_file.write_bytes(crash_payload)
                            reason_match = re.search(
                                rb"Debug exception reason:\s*([^\r\n]+)", crash_probe
                            )
                            reason = (
                                reason_match.group(1).decode("utf-8", "replace").strip()
                                if reason_match
                                else crash_signature
                            )
                            tool_log(
                                "NODE_FIRMWARE_CRASH",
                                port=port,
                                reason=reason,
                                bytes=serial_bytes_received,
                                crash_file=crash_file,
                            )
                            raise RuntimeError(
                                "Firmware-Crash am Node während des Logdownloads erkannt. "
                                f"{reason}. Der Node hat vor dem Endmarker neu gestartet. "
                                f"Crash-Datei: {crash_file}"
                            )
'''
        return method.replace(anchor, crash_block, 1)

    source = replace_method(source, "_download_worker", harden_serial_download)

    def improve_ble_scan(method: str) -> str:
        method = method.replace('tool_log("BLE_SCAN_START", timeout_s=8.0)', 'tool_log("BLE_SCAN_START", timeout_s=12.0)', 1)
        method = method.replace('BleakScanner.discover(timeout=8.0, return_adv=True)', 'BleakScanner.discover(timeout=12.0, return_adv=True)', 1)
        if 'BLE_SCAN_EMPTY' not in method:
            anchor = '''        except Exception as exc:\n'''
            if method.count(anchor) != 1:
                raise SystemExit("BLE empty-result anchor not found")
            addition = r'''            if not found:
                tool_log(
                    "BLE_SCAN_EMPTY",
                    total=len(devices),
                    advice="V3 Servicefenster per GPIO0 öffnen und Suche erneut starten",
                )
                self.events.put((
                    "status_warning",
                    "Keine BLE-Nodes gefunden · beim V3 einmal das Servicefenster per GPIO0 öffnen und Suche erneut starten",
                ))
'''
            method = method.replace(anchor, addition + anchor, 1)
        return method

    source = replace_method(source, "_ble_scan_worker", improve_ble_scan)

    required = (
        'APP_VERSION = "2.1.2"',
        'def restart_app(self)',
        'APP_RESTART_SCHEDULED',
        'timeout /t 1 /nobreak',
        'NODE_FIRMWARE_CRASH',
        'Guru Meditation Error:',
        'Stack canary watchpoint triggered',
        'Jarnsen_Node_Log_CRASH_',
        'BLE_SCAN_EMPTY',
        'timeout_s=12.0',
        'BleakScanner.discover(timeout=12.0, return_adv=True)',
    )
    for marker in required:
        if marker not in source:
            raise SystemExit(f"missing v2.1.2 marker: {marker}")

    restart_start, restart_end = method_span(source, "restart_app")
    restart_method = source[restart_start:restart_end]
    if "os.execv(" in restart_method:
        raise SystemExit("unsafe os.execv restart still present")
    return source


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "tools/JARNSEN_NODE_SERVICE_TOOL.py")
    target.write_text(patch(target.read_text(encoding="utf-8")), encoding="utf-8")
    print("Service tool v2.1.2: safe restart + V3 crash detection + BLE guidance")


if __name__ == "__main__":
    main()
