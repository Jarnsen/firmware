from pathlib import Path
import shutil

artifact = Path("artifact")
artifact.mkdir(parents=True, exist_ok=True)

for source in [
    Path("tools/tracker_log_download.py"),
    Path("tools/tracker_log_download.bat"),
    Path("tools/README-TRACKER-LOG.txt"),
]:
    if not source.exists():
        raise SystemExit(f"Tracker artifact extra missing: {source}")
    shutil.copy2(source, artifact / source.name)
    print(f"Tracker artifact extra: {source.name}")
