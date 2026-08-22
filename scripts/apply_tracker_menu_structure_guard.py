from pathlib import Path

STATUS = Path("src/vehicle/TrackerStatusModule.cpp")
status = STATUS.read_text()

start_marker = "void showTrackerMenu(TrackerMenu menu, int initialSelection)\n"
end_marker = "bool trackerServiceMenuActive()\n"
start = status.find(start_marker)
if start < 0:
    raise SystemExit("Tracker menu structure guard: showTrackerMenu start not found")
end = status.find(end_marker, start)
if end < 0:
    raise SystemExit("Tracker menu structure guard: trackerServiceMenuActive boundary not found")

# First validate/repair only the generated showTrackerMenu function. The clean
# settings replacement has historically lost this one closing brace.
segment = status[start:end]
delta = segment.count("{") - segment.count("}")
if delta == 1:
    status = status[:end] + "}\n\n" + status[end:]
    print("Tracker menu structure guard: repaired one missing showTrackerMenu closing brace")
elif delta == 0:
    print("Tracker menu structure guard: showTrackerMenu balanced")
else:
    raise SystemExit(f"Tracker menu structure guard: unexpected showTrackerMenu brace delta {delta}")

end = status.find(end_marker, start)
segment = status[start:end]
if segment.count("{") - segment.count("}") != 0:
    raise SystemExit("Tracker menu structure guard: showTrackerMenu repair failed")

# Some composed replacements preserve both the replacement '#else' and the
# original boundary '#else', yielding '#else#else'. Normalize only this exact
# invalid token before checking the outer HELTEC_TRACKER_V1_1/HAS_SCREEN guard.
if "#else#else" in status:
    count = status.count("#else#else")
    status = status.replace("#else#else", "#else")
    print(f"Tracker menu structure guard: normalized duplicated #else x{count}")

if "#else#else" in status:
    raise SystemExit("Tracker menu structure guard: duplicated #else remains")

# The generated service/menu helpers intentionally remain in the anonymous
# namespace opened near the top of TrackerStatusModule.cpp. Large menu span
# replacements can consume the original namespace terminator, so require it
# immediately before the final outer #else. The final #else is the build stub
# branch for boards without this Tracker display implementation.
outer_else = status.rfind("\n#else\n")
if outer_else < 0:
    raise SystemExit("Tracker menu structure guard: outer #else not found")

required_boundary = "} // namespace\n\n#else\n"
window_start = max(0, outer_else - 80)
if required_boundary not in status[window_start:outer_else + len("\n#else\n")]:
    status = status[:outer_else] + "\n} // namespace\n" + status[outer_else:]
    print("Tracker menu structure guard: restored anonymous namespace close")

if "} // namespace\n\n#else\n" not in status[-500:]:
    raise SystemExit("Tracker menu structure guard: final namespace/#else boundary invalid")

# The source must finish with one outer fallback and one #endif, never a glued
# preprocessor directive. This catches the exact compiler failure before the
# expensive PlatformIO build starts.
if status.rstrip().count("#endif") == 0 or not status.rstrip().endswith("#endif"):
    raise SystemExit("Tracker menu structure guard: final #endif missing")

STATUS.write_text(status)
