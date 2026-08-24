from pathlib import Path
import runpy
import runpy

core = Path("scripts/apply_v3_antenna_swap_tx_lock_core.py")
if not core.exists():
    raise SystemExit("V3 antenna swap TX lock core script missing")
runpy.run_path(str(core), run_name="__main__")

runpy.run_path("scripts/apply_v3_ina226_backend.py", run_name="__main__")
runpy.run_path("scripts/apply_v3_ina226_vbus_guard.py", run_name="__main__")
runpy.run_path("scripts/apply_v3_ina226_ci_compat.py", run_name="__main__")
runpy.run_path("scripts/apply_v3_diag_metadata.py", run_name="__main__")
runpy.run_path("scripts/apply_v3_service_export_ui_fix.py", run_name="__main__")
runpy.run_path("scripts/apply_v3_runtime_log_fixes.py", run_name="__main__")
