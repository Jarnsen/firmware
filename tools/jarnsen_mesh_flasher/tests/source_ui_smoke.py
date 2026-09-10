from __future__ import annotations

import copy
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


def _radio_profile_smoke(services) -> None:
    required_hooks = (
        "load_radio_profile_settings",
        "save_radio_profile_settings",
        "validate_radio_profile_settings",
        "radio_profile_summary",
        "apply_radio_profile_overlay",
        "verify_written_profile",
    )
    missing_hooks = [name for name in required_hooks if not callable(getattr(services, name, None))]
    if missing_hooks:
        raise AssertionError(f"Radio-profile service hooks missing: {missing_hooks}")

    defaults = services.validate_radio_profile_settings({"selected": "standard"})
    if defaults["standard_hops"] != 7:
        raise AssertionError(f"Standard hop default must stay 7: {defaults}")
    if defaults["jarnsen_1_hops"] != 20 or defaults["jarnsen_2_hops"] != 20:
        raise AssertionError(f"Jarnsen 1/2 hop defaults must be 20: {defaults}")

    base = {
        "config": {
            "device": {"role": "TRACKER"},
            "lora": {
                "region": "US",
                "hop_limit": 5,
                "tx_power": 22,
                "override_frequency": 868.5,
                "override_duty_cycle": False,
            },
        }
    }
    original = copy.deepcopy(base)

    j1_settings = {
        "selected": "jarnsen1",
        "jarnsen_1_mhz": "915.625",
        "jarnsen_2_mhz": "917.375",
        "jarnsen_1_hops": 5,
        "jarnsen_1_modem_preset": "MEDIUM_FAST",
    }
    j1 = services.apply_radio_profile_overlay(base, j1_settings)
    j1_lora = j1["config"]["lora"]
    if j1_lora["override_frequency"] != 915.625:
        raise AssertionError(f"Jarnsen 1 exact frequency failed: {j1_lora}")
    if j1_lora["hop_limit"] != 5:
        raise AssertionError(f"Jarnsen 1 independent hop setting failed: {j1_lora}")
    if j1_lora["override_duty_cycle"] is not True:
        raise AssertionError(f"Jarnsen duty-cycle override missing: {j1_lora}")
    if j1_lora["tx_power"] != 0:
        raise AssertionError(f"Jarnsen TX max/auto setting missing: {j1_lora}")
    if j1_lora.get("use_preset") is not True or j1_lora.get("modem_preset") != "MEDIUM_FAST":
        raise AssertionError(f"Jarnsen 1 independent modem preset failed: {j1_lora}")
    if j1["config"]["device"]["role"] != "TRACKER":
        raise AssertionError("Radio profile must never change the device role")
    if base != original:
        raise AssertionError("Radio overlay mutated the stored/master profile")

    high_hops = copy.deepcopy(base)
    high_hops["config"]["lora"]["hop_limit"] = 99
    j2 = services.apply_radio_profile_overlay(
        high_hops,
        {
            "selected": "jarnsen2",
            "jarnsen_1_mhz": "915.625",
            "jarnsen_2_mhz": "917.375",
            "jarnsen_2_hops": 99,
            "jarnsen_2_modem_preset": "SHORT_SLOW",
        },
    )
    j2_lora = j2["config"]["lora"]
    if j2_lora["override_frequency"] != 917.375:
        raise AssertionError(f"Jarnsen 2 exact frequency failed: {j2_lora}")
    if j2_lora["hop_limit"] != 20:
        raise AssertionError(f"Jarnsen hop ceiling must be 20, not fixed/above 20: {j2}")
    if j2_lora.get("use_preset") is not True or j2_lora.get("modem_preset") != "SHORT_SLOW":
        raise AssertionError(f"Jarnsen 2 independent modem preset failed: {j2_lora}")

    standard = services.apply_radio_profile_overlay(high_hops, {"selected": "standard"})
    standard_lora = standard["config"]["lora"]
    if standard_lora["hop_limit"] != 7:
        raise AssertionError(f"Standard hop ceiling must be 7: {standard_lora}")
    if standard_lora["override_frequency"] != 0.0:
        raise AssertionError(f"Standard must clear the Jarnsen frequency override: {standard_lora}")
    if standard_lora["override_duty_cycle"] is not False:
        raise AssertionError(f"Standard must use normal duty-cycle handling: {standard_lora}")
    if standard_lora["tx_power"] != 22:
        raise AssertionError(f"Standard must preserve master-profile TX power: {standard_lora}")

    log("SOURCE UI SMOKE · radio-profiles=PASS · standard<=7 jarnsen<=20 exact-freq=1 independent-hops=1 independent-modem=1 duty-free=1 tx=max-auto role-touch=0")


def main() -> int:
    app = None
    try:
        _close_stale_flasher_windows()

        from ui_icons import smoke_test as icon_smoke_test
        icon_smoke_test()
        log("SOURCE UI SMOKE · icon-set=PASS")

        # Importing app imports _build_version, which installs the exact runtime
        # layers that the packaged EXE receives. This therefore catches the case
        # where a board implementation exists in the repository but is never
        # wired into the actual application.
        from app import FlasherApp
        import services

        required_boards = {
            "tracker",
            "repeater",
            "wio",
            "heltec_v4",
            "tbeam",
            "tbeam_supreme",
        }
        missing_boards = sorted(required_boards.difference(services.BOARD_PROFILES))
        if missing_boards:
            raise AssertionError(f"Unified runtime board profiles missing: {missing_boards}")
        for hook in (
            "run_flash_preflight",
            "create_diagnostic_package",
            "flash_baud_candidates",
            "is_retryable_flash_error",
        ):
            if not callable(getattr(services, hook, None)):
                raise AssertionError(f"Advanced flasher service hook missing: {hook}")
        if not getattr(services.flash_bundle, "_jarnsen_resilient_flash", False):
            raise AssertionError("Final flash_bundle binding has no baud fallback")
        if not callable(getattr(services.GitHubFirmwareClient, "_download_zip", None)):
            raise AssertionError("Resumable firmware downloader is not installed")

        stock_cases = (
            ("hwModel: T_BEAM\nfirmwareVersion: 2.7.11", "tbeam"),
            ("hardwareModel: T-BEAM\nOwner: Stock Meshtastic", "tbeam"),
            ("pioEnv: tbeam\nfirmwareVersion: 2.7.11", "tbeam"),
            ("hwModel: T_BEAM_SUPREME\nfirmwareVersion: 2.7.11", "tbeam_supreme"),
            ("pioEnv: tbeam-s3-core\nfirmwareVersion: 2.7.11", "tbeam_supreme"),
        )
        for info_text, expected in stock_cases:
            detected = services.detect_board_from_text(info_text)
            if detected != expected:
                raise AssertionError(
                    f"Stock Meshtastic board detection failed: expected={expected!r} "
                    f"detected={detected!r} info={info_text!r}"
                )
        log("SOURCE UI SMOKE · stock-tbeam-detection=PASS · tbeam + supreme")

        _radio_profile_smoke(services)

        log("SOURCE UI SMOKE · start · expected-build-path=direct-reference-v4-only")
        app = FlasherApp()
        app.update_idletasks()

        if not getattr(app, "_jarnsen_manual_board_fallback", False):
            raise AssertionError("Manual unified-board fallback was not installed on FlasherApp")
        manual_values = tuple(getattr(app, "_jarnsen_manual_board_values", ()))
        for board_key in ("tbeam", "tbeam_supreme"):
            label = str(services.BOARD_PROFILES[board_key]["label"])
            if label not in manual_values:
                raise AssertionError(f"Manual board menu missing {board_key}: {manual_values}")
            app.board_var.set(label)
            if app._selected_board_key() != board_key:
                raise AssertionError(
                    f"Manual board resolution failed for {label}: {app._selected_board_key()!r}"
                )
        app.board_var.set("Automatisch")
        log("SOURCE UI SMOKE · manual-tbeam-fallback=PASS · menu + resolver")

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
            "radio_profile_var",
            "radio_hop_var",
            "radio_modem_var",
            "radio_frequency_var",
            "radio_tx_var",
            "radio_duty_var",
            "radio_profile_status_var",
            "radio_profile_allocation_var",
            "radio_profile_menu",
            "radio_modem_menu",
            "radio_hop_menu",
            "radio_profile_panel",
            "flash_mode_switch",
            "support_zip_button",
        )
        missing = [name for name in required if not hasattr(app, name)]
        if missing:
            raise AssertionError(f"Reference dashboard attributes missing: {missing}")
        if not getattr(app, "_jarnsen_radio_profile_ui_ready", False):
            raise AssertionError("Radio-profile controls were not attached to 2. GRUNDEINSTELLUNGEN")
        if str(app.radio_profile_var.get()) not in ("Standard", "Jarnsen 1", "Jarnsen 2"):
            raise AssertionError(f"Unexpected radio-profile selection: {app.radio_profile_var.get()!r}")
        if str(app.radio_frequency_var.get()) not in ("Profil/FW", "915.625 MHz", "917.375 MHz"):
            raise AssertionError(f"Unexpected fixed radio-frequency display: {app.radio_frequency_var.get()!r}")
        if str(app.radio_tx_var.get()) not in ("Profil/FW", "Max/Auto"):
            raise AssertionError(f"Unexpected TX display: {app.radio_tx_var.get()!r}")
        if str(app.radio_duty_var.get()) not in ("Profil/FW", "Frei"):
            raise AssertionError(f"Unexpected duty display: {app.radio_duty_var.get()!r}")
        if not str(app.radio_hop_var.get()).isdigit():
            raise AssertionError(f"Unexpected hop selection: {app.radio_hop_var.get()!r}")
        log(
            "SOURCE UI SMOKE · radio-profile-ui=PASS · dynamic-editor=1 fixed-frequency-display=1 "
            "profile-dropdown=1 modem-dropdown=1 hop-dropdown=1"
        )

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
        if str(app.operation_mode.get()) != "Firmware-Update":
            raise AssertionError(f"Safe default flash mode missing: {app.operation_mode.get()!r}")
        expected_modes = {"Firmware-Update", "Reparatur", "Werkseinstellung", "Serie"}
        actual_modes = set(app.flash_mode_switch.cget("values"))
        if actual_modes != expected_modes:
            raise AssertionError(f"Flash mode choices mismatch: {actual_modes}")
        if not callable(app.support_zip_button.cget("command")):
            raise AssertionError("Diagnostic ZIP button has no callable command")

        root_children = len(app.winfo_children())
        if root_children != 3:
            raise AssertionError(f"Expected header/body/footer only, got {root_children} root children")

        log(
            "SOURCE UI SMOKE · PASS · build-path=direct-reference-v4 legacy-build=0 icons=pil "
            f"cards={len(cards)} managers=place fullscreen=1 custom-chrome=1 radio-profiles=1 "
            f"flash-modes=3 support-zip=1 root-children={root_children}"
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
