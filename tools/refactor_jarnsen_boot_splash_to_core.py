#!/usr/bin/env python3
"""Route the Meshtastic cold-boot frame through the shared JARNSEN-MESH Core splash.

This is an integration seam for the Unified Core branch. It keeps upstream
Screen.cpp easy to rebase while ensuring every CI-built JARNSEN-MESH target
uses the same boot layout, version source and per-board hardware label.
"""

from pathlib import Path

SCREEN = Path("src/graphics/Screen.cpp")
INCLUDE_ANCHOR = '#include "JarnsenLiveDisplay.h"\n'
CORE_INCLUDE = '#include "jarnsen/core/display/JarnsenBootSplash.h"\n'
OLD_BOOT = '''            const char *region = myRegion ? myRegion->name : nullptr;\n            graphics::UIRenderer::drawBootIconScreen(region, display, state, x, y);'''
NEW_BOOT = '''            jarnsen::drawBootSplash(display, x, y);'''


def main() -> None:
    text = SCREEN.read_text(encoding="utf-8")

    if CORE_INCLUDE not in text:
        if INCLUDE_ANCHOR not in text:
            raise SystemExit("JARNSEN boot refactor: Screen.cpp include anchor not found")
        text = text.replace(INCLUDE_ANCHOR, INCLUDE_ANCHOR + CORE_INCLUDE, 1)

    if NEW_BOOT not in text:
        if OLD_BOOT not in text:
            raise SystemExit("JARNSEN boot refactor: upstream boot-render call not found")
        text = text.replace(OLD_BOOT, NEW_BOOT, 1)

    SCREEN.write_text(text, encoding="utf-8")
    print("Routed cold boot through JARNSEN-MESH Core splash")


if __name__ == "__main__":
    main()
