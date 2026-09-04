from __future__ import annotations

import os
import subprocess
import sys
import traceback
from pathlib import Path


HERE = Path(__file__).resolve().parent
APP_DIR = HERE.parent
REPO_ROOT = APP_DIR.parents[1]
CI_LOGS = REPO_ROOT / "ci-logs"
CI_LOGS.mkdir(parents=True, exist_ok=True)
LOG_FILE = CI_LOGS / "flasher-source-ui-smoke.txt"

if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


def log(message: str) -> None:
    print(message, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")


def _close_stale_flasher_windows() -> None:
    """Make the later frozen screenshot test deterministic on the self-hosted PC.

    Versioned flasher builds can have different process names, so killing only
    ``JarnsenMeshFlasher`` is not sufficient.  During GitHub Actions we close every
    process whose main-window title identifies it as a JARNSEN MESH Flasher.  This
    prevents a previously opened build from being mistaken for the EXE launched by
    the visual regression test.
    """
    if os.name != "nt" or os.environ.get("GITHUB_ACTIONS", "").lower() != "true":
        return

    command = (
        "$targets = Get-Process -ErrorAction SilentlyContinue | "
        "Where-Object { $_.MainWindowTitle -like '*JARNSEN MESH Flasher*' }; "
        "if ($targets) { "
        "  $targets | ForEach-Object { Write-Output ('closing pid=' + $_.Id + ' title=' + $_.MainWindowTitle) }; "
        "  $targets | Stop-Process -Force -ErrorAction SilentlyContinue "
        "}"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
        detail = (result.stdout or "").strip()
        if detail:
            for line in detail.splitlines():
                log(f"CI GUI CLEANUP · {line}")
        if result.returncode != 0:
            log(
                "CI GUI CLEANUP · warning · powershell-exit="
                f"{result.returncode} stderr={(result.stderr or '').strip()}"
            )
    except Exception as exc:
        log(f"CI GUI CLEANUP · warning · {type(exc).__name__}: {exc}")


def main() -> int:
    app = None
    try:
        _close_stale_flasher_windows()

        import services
        from app import FlasherApp
        from native_dashboard import _build_dashboard

        log("SOURCE UI SMOKE · start")
        app = FlasherApp()
        app.update_idletasks()

        # In production the native dashboard is installed at mainloop entry. For the
        # source smoke test we deliberately build it only after FlasherApp.__init__ has
        # returned, which exercises the exact race that broke Build 116 without starting
        # the serial/device timers.
        if not getattr(app, "_jarnsen_native_dashboard_ready", False):
            _build_dashboard(app, services)
        app.update_idletasks()

        required = (
            "body",
            "device_combo",
            "status_label",
            "usb_log_button",
            "progress",
            "flash_button",
            "log_box",
            "native_device_count_var",
            "native_board_count_var",
            "native_ready_var",
        )
        missing = [name for name in required if not hasattr(app, name)]
        if missing:
            raise AssertionError(f"Native dashboard attributes missing: {missing}")

        if not getattr(app, "_jarnsen_native_dashboard_ready", False):
            raise AssertionError("Native dashboard did not reach ready state")
        if not app.body.winfo_exists():
            raise AssertionError("Native dashboard body no longer exists")
        if len(app.body.winfo_children()) < 8:
            raise AssertionError(
                f"Expected at least 8 dashboard cards, got {len(app.body.winfo_children())}"
            )
        if not callable(app.flash_button.cget("command")):
            raise AssertionError("Automatic flash button has no callable command")
        if not callable(app.usb_log_button.cget("command")):
            raise AssertionError("USB log button has no callable command")

        root_children = len(app.winfo_children())
        if root_children < 2 or root_children > 4:
            raise AssertionError(
                f"Unexpected root widget tree after native rebuild: {root_children} children"
            )

        log(
            "SOURCE UI SMOKE · PASS · native-dashboard=ready "
            f"cards={len(app.body.winfo_children())} root-children={root_children}"
        )
        return 0
    except Exception as exc:
        log(f"SOURCE UI SMOKE · FAIL · {type(exc).__name__}: {exc}")
        log(traceback.format_exc())
        return 2
    finally:
        if app is not None:
            try:
                app.destroy()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
