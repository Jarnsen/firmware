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
            log(f"CI GUI CLEANUP · warning · powershell-exit={result.returncode} stderr={(result.stderr or '').strip()}")
    except Exception as exc:
        log(f"CI GUI CLEANUP · warning · {type(exc).__name__}: {exc}")


def main() -> int:
    app = None
    try:
        _close_stale_flasher_windows()

        from ui_icons import smoke_test as icon_smoke_test
        icon_smoke_test()
        log("SOURCE UI SMOKE · icon-set=PASS")

        from app import FlasherApp

        log("SOURCE UI SMOKE · start · expected-build-path=direct-reference-v4-only")
        app = FlasherApp()
        app.update_idletasks()

        if not getattr(app, "_jarnsen_native_build_override", False):
            raise AssertionError("Direct reference _build_ui override was not installed")
        if not getattr(app, "_jarnsen_native_dashboard_ready", False):
            raise AssertionError("Reference dashboard was not built directly during FlasherApp.__init__")
        if not getattr(app, "_jarnsen_reference_dashboard_v2", False):
            raise AssertionError("Reference dashboard base flag missing; legacy/native v1 path may be active")
        if not getattr(app, "_jarnsen_reference_dashboard_v3", False):
            raise AssertionError("Reference dashboard v3 asymmetric geometry flag missing")
        if not getattr(app, "_jarnsen_reference_dashboard_v4", False):
            raise AssertionError("Reference dashboard v4 fullscreen chrome flag missing")
        if getattr(app, "_jarnsen_design_revision", "") != "reference-v4-fullscreen-asymmetric-place-pil-icons":
            raise AssertionError(f"Unexpected design revision: {getattr(app, '_jarnsen_design_revision', None)!r}")
        if getattr(app, "_jarnsen_reference_geometry", "") != "approved-1325x750-proportional":
            raise AssertionError(f"Unexpected reference geometry: {getattr(app, '_jarnsen_reference_geometry', None)!r}")
        if getattr(app, "_jarnsen_reference_window", "") != "1920x1080-125-fullscreen-custom-chrome":
            raise AssertionError(f"Unexpected reference window: {getattr(app, '_jarnsen_reference_window', None)!r}")
        if not bool(getattr(app, "_jarnsen_reference_fullscreen", False)):
            raise AssertionError("Reference fullscreen state was not enabled")

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
            raise AssertionError(f"Reference dashboard attributes missing: {missing}")

        if not app.body.winfo_exists():
            raise AssertionError("Reference dashboard body no longer exists")
        cards = list(app.body.winfo_children())
        if len(cards) != 8:
            raise AssertionError(f"Expected exactly 8 dashboard cards, got {len(cards)}")
        if any(card.winfo_manager() != "place" for card in cards):
            managers = [card.winfo_manager() for card in cards]
            raise AssertionError(f"Reference cards must use final proportional place geometry, got {managers}")
        if not callable(app.flash_button.cget("command")):
            raise AssertionError("Automatic flash button has no callable command")
        if not callable(app.usb_log_button.cget("command")):
            raise AssertionError("USB log button has no callable command")

        root_children = len(app.winfo_children())
        if root_children != 3:
            raise AssertionError(f"Expected header/body/footer only, got {root_children} root children")

        log(
            "SOURCE UI SMOKE · PASS · build-path=direct-reference-v4 legacy-build=0 icons=pil "
            f"cards={len(cards)} managers=place fullscreen=1 custom-chrome=1 root-children={root_children}"
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
