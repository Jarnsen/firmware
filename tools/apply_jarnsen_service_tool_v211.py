"""Apply the v2.1.1 stability patch after normalizing the generated entrypoint.

Earlier patch generations can leave harmless whitespace or appended text around the
module entrypoint. The v2.1.1 patch intentionally replaces that entrypoint so its
startup logger runs before Tk is created.
"""
from __future__ import annotations

import sys
from pathlib import Path

from patch_jarnsen_service_tool_v211_stability import patch


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "tools/JARNSEN_NODE_SERVICE_TOOL.py")
    source = target.read_text(encoding="utf-8")
    entry = source.rfind('if __name__ == "__main__":')
    if entry < 0:
        raise SystemExit("generated Service Tool entrypoint not found")
    # The only supported pre-v2.1.1 entrypoint is self-test or GUI. Normalize it
    # before the stability patch installs startup logging and Tcl/Tk resolution.
    source = source[:entry].rstrip() + '''\n\nif __name__ == "__main__":\n    if "--self-test" in sys.argv:\n        raise SystemExit(packaged_self_test())\n    ServiceTool().mainloop()\n'''
    target.write_text(patch(source), encoding="utf-8")
    print("Service tool v2.1.1 applied after entrypoint normalization")


if __name__ == "__main__":
    main()
