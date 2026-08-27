"""v2.1.2: restart a frozen PyInstaller onefile app as an independent process."""
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


def replace_method(text: str, name: str, replacement: str) -> str:
    start, end = method_span(text, name)
    return text[:start] + replacement.rstrip() + "\n" + text[end:]


def patch(source: str) -> str:
    source = re.sub(r'APP_VERSION = "[^"]+"', f'APP_VERSION = "{APP_VERSION}"', source, count=1)
    source = source.replace('APP_VERSION != "2.1.1"', 'APP_VERSION != "2.1.2"')
    source = source.replace("App-Version ist nicht v2.1.1", "App-Version ist nicht v2.1.2")

    restart = r'''    def restart_app(self) -> None:
        if not messagebox.askyesno(
            "App neu starten",
            "Jarnsen Node Service Tool jetzt neu starten? Laufende Downloads werden beendet.",
        ):
            return
        self.stop_event.set()
        self.live_stop.set()
        self.update_idletasks()
        try:
            if getattr(sys, "frozen", False):
                executable = pathlib.Path(sys.executable).resolve()
                argv = [str(executable), *sys.argv[1:]]
                env = os.environ.copy()
                # PyInstaller onefile must treat the replacement as a brand-new
                # top-level instance; inheriting the bootloader parent state can
                # otherwise trigger "failed to obtain executable path for parent process".
                env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
                creationflags = 0
                if os.name == "nt":
                    creationflags = (
                        getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                        | getattr(subprocess, "DETACHED_PROCESS", 0)
                    )
                tool_log("APP_RESTART", executable=executable, frozen=True)
                subprocess.Popen(
                    argv,
                    executable=str(executable),
                    cwd=str(executable.parent),
                    env=env,
                    close_fds=True,
                    creationflags=creationflags,
                )
            else:
                script = pathlib.Path(sys.argv[0]).resolve()
                tool_log("APP_RESTART", executable=sys.executable, script=script, frozen=False)
                subprocess.Popen(
                    [sys.executable, str(script), *sys.argv[1:]],
                    cwd=str(script.parent),
                    close_fds=True,
                )
            tool_log("APP_SHUTDOWN", reason="restart")
            self.after(150, self.destroy)
        except Exception as exc:
            tool_log_exception("restart_app", exc)
            messagebox.showerror("Neustart fehlgeschlagen", str(exc))
'''
    source = replace_method(source, "restart_app", restart)

    required = (
        'APP_VERSION = "2.1.2"',
        'env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"',
        'tool_log("APP_RESTART"',
        "subprocess.Popen(",
        "self.after(150, self.destroy)",
    )
    for marker in required:
        if marker not in source:
            raise SystemExit(f"missing v2.1.2 restart marker: {marker}")
    return source


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "tools/JARNSEN_NODE_SERVICE_TOOL.py")
    target.write_text(patch(target.read_text(encoding="utf-8")), encoding="utf-8")
    print("Service tool v2.1.2: frozen onefile restart fixed")


if __name__ == "__main__":
    main()
