from pathlib import Path

STATUS = Path("src/vehicle/TrackerStatusModule.cpp")
status = STATUS.read_text()

start_marker = "void showTrackerMenu(TrackerMenu menu, int initialSelection)\n"
public_marker = "bool trackerServiceMenuActive()\n"
start = status.find(start_marker)
if start < 0:
    raise SystemExit("Tracker menu structure guard: showTrackerMenu start not found")
public = status.find(public_marker, start)
if public < 0:
    raise SystemExit("Tracker menu structure guard: trackerServiceMenuActive boundary not found")

# Validate/repair only the generated showTrackerMenu function. The clean
# settings replacement has historically lost this one closing brace.
segment = status[start:public]
delta = segment.count("{") - segment.count("}")
if delta == 1:
    status = status[:public] + "}\n\n" + status[public:]
    print("Tracker menu structure guard: repaired one missing showTrackerMenu closing brace")
elif delta == 0:
    print("Tracker menu structure guard: showTrackerMenu balanced")
else:
    raise SystemExit(f"Tracker menu structure guard: unexpected showTrackerMenu brace delta {delta}")

public = status.find(public_marker, start)
segment = status[start:public]
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

# showTrackerMenu and its helpers are implementation details and stay in the
# anonymous namespace. Everything from trackerServiceMenuActive() onward is the
# public API declared in TrackerStatusModule.h and is called from other
# translation units. Therefore the anonymous namespace MUST end immediately
# before trackerServiceMenuActive(). Keeping these definitions inside the
# anonymous namespace compiles but fails at link time with undefined references.
public = status.find(public_marker, start)
outer_else = status.rfind("\n#else\n")
if outer_else < 0 or outer_else <= public:
    raise SystemExit("Tracker menu structure guard: outer #else not found after public API")

# Move any late outer namespace terminator to the actual public API boundary.
# Limit this normalization to the exact generated comment so nested function
# braces and unrelated namespaces cannot be touched.
late = status[public:outer_else]
late_count = late.count("} // namespace\n")
if late_count > 1:
    raise SystemExit(f"Tracker menu structure guard: unexpected late namespace closes {late_count}")
if late_count:
    late = late.replace("} // namespace\n", "", 1)
    status = status[:public] + late + status[outer_else:]
    print("Tracker menu structure guard: moved late anonymous namespace close")

public = status.find(public_marker, start)
required_boundary = "} // namespace\n\n" + public_marker
if status[max(0, public - 40):public + len(public_marker)] != required_boundary:
    # Avoid duplicating an already adjacent terminator with slightly different
    # surrounding whitespace.
    before = status[max(0, public - 40):public]
    if "} // namespace" in before:
        raise SystemExit("Tracker menu structure guard: ambiguous namespace boundary before public API")
    status = status[:public] + "} // namespace\n\n" + status[public:]
    print("Tracker menu structure guard: closed anonymous namespace before public Tracker API")

# Recompute after the insertion and require all cross-TU entry points to be on
# the public side of the boundary.
public = status.find(public_marker, start)
namespace_close = status.rfind("} // namespace\n", start, public)
if namespace_close < 0 or namespace_close + len("} // namespace\n\n") != public:
    raise SystemExit("Tracker menu structure guard: public API namespace boundary invalid")

for signature in (
    "bool trackerServiceMenuActive()\n",
    "void trackerServiceMenuPump()\n",
    "void trackerServiceMenuForceClose()\n",
    "void trackerServiceMenuSelect()\n",
    "bool trackerServicePageVisible()\n",
    "void trackerServiceMenuOpen()\n",
    "void trackerServiceMenuShortPress()\n",
    "void trackerStatusRequestFocus()\n",
    "void trackerStatusSetMotionActive(bool active)\n",
):
    pos = status.find(signature)
    if pos < public:
        raise SystemExit(f"Tracker menu structure guard: public definition missing/outside public region: {signature.strip()}")

outer_else = status.rfind("\n#else\n")
if "} // namespace\n" in status[public:outer_else]:
    raise SystemExit("Tracker menu structure guard: anonymous namespace closes again inside public API region")

# The source must finish with one outer fallback and one #endif, never a glued
# preprocessor directive. This catches structure failures before PlatformIO.
if status.rstrip().count("#endif") == 0 or not status.rstrip().endswith("#endif"):
    raise SystemExit("Tracker menu structure guard: final #endif missing")

STATUS.write_text(status)
