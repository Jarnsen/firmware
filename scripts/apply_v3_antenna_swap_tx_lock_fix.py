from pathlib import Path

core = Path("scripts/apply_v3_antenna_swap_tx_lock_core.py")
if not core.exists():
    raise SystemExit("V3 antenna swap TX lock core script missing")
exec(compile(core.read_text(), str(core), "exec"), {"__name__": "__main__"})
