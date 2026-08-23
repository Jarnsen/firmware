from pathlib import Path
import shutil

artifact = Path("artifact")
artifact.mkdir(parents=True, exist_ok=True)

# One clearly named downloader per device artifact. Keep generic/legacy tools in
# the repository for backwards compatibility, but do not package them here.
for old_name in [
    "diagnostic_log_download.py",
    "diagnostic_log_download.bat",
    "README-DIAGNOSTIC-LOG.txt",
    "V3_DIAG_LOG_DOWNLOADER.py",
]:
    old = artifact / old_name
    if old.exists():
        old.unlink()

for source in [
    Path("tools/TRACKER_V11_DIAG_LOG_DOWNLOADER.py"),
    Path("tools/README-INA226-R100-TRACKER-V11.txt"),
]:
    if not source.exists():
        raise SystemExit(f"Tracker artifact extra missing: {source}")
    shutil.copy2(source, artifact / source.name)
    print(f"Tracker artifact extra: {source.name}")
