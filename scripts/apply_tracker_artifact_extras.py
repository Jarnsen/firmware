from pathlib import Path
import shutil

artifact = Path("artifact")
artifact.mkdir(parents=True, exist_ok=True)

for source in [
    Path("tools/diagnostic_log_download.py"),
    Path("tools/diagnostic_log_download.bat"),
    Path("tools/README-DIAGNOSTIC-LOG.txt"),
    Path("tools/README-INA226-R100-TRACKER-V11.txt"),
]:
    if not source.exists():
        raise SystemExit(f"Tracker artifact extra missing: {source}")
    shutil.copy2(source, artifact / source.name)
    print(f"Tracker artifact extra: {source.name}")
