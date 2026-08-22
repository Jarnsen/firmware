from pathlib import Path

STATUS = Path("src/vehicle/TrackerStatusModule.cpp")
status = STATUS.read_text()

start_marker = "void showTrackerMenu(TrackerMenu menu, int initialSelection)\n"
end_marker = "void trackerServiceOpenMenu()\n"
start = status.find(start_marker)
if start < 0:
    raise SystemExit("Tracker menu structure guard: showTrackerMenu start not found")
end = status.find(end_marker, start)
if end < 0:
    raise SystemExit("Tracker menu structure guard: trackerServiceOpenMenu boundary not found")

segment = status[start:end]
delta = segment.count("{") - segment.count("}")
if delta == 1:
    # The generated switch is complete but the outer showTrackerMenu function
    # lost its final brace while composing the menu patches. Repair only this
    # known boundary; never append a brace at EOF or mask another syntax issue.
    status = status[:end] + "}\n\n" + status[end:]
    print("Tracker menu structure guard: repaired one missing showTrackerMenu closing brace")
elif delta == 0:
    print("Tracker menu structure guard: balanced")
else:
    raise SystemExit(f"Tracker menu structure guard: unexpected brace delta {delta}")

# Re-check the exact function region after any repair.
end = status.find(end_marker, start)
segment = status[start:end]
final_delta = segment.count("{") - segment.count("}")
if final_delta != 0:
    raise SystemExit(f"Tracker menu structure guard: repair failed, delta {final_delta}")

STATUS.write_text(status)
