from pathlib import Path
import runpy

core = Path("scripts/apply_v3_antenna_swap_tx_lock_core.py")
if not core.exists():
    raise SystemExit("V3 antenna swap TX lock core script missing")
exec(compile(core.read_text(), str(core), "exec"), {"__name__": "__main__"})

runpy.run_path("scripts/apply_v3_ina226_backend.py", run_name="__main__")
runpy.run_path("scripts/apply_v3_diag_metadata.py", run_name="__main__")
