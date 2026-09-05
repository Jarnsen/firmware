#!/usr/bin/env python3
"""Static contract checks for JARNSEN-MESH tracker changes.

These checks are intentionally small and explicit. They do not replace the
firmware compiler or real-hardware tests; they guard invariants that have
already regressed during refactors so CI can fail fast with a useful message.
"""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


class PreflightFailure(RuntimeError):
    pass


def read(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        raise PreflightFailure(f"required file missing: {rel}")
    return path.read_text(encoding="utf-8")


def require(text: str, needle: str, message: str) -> None:
    if needle not in text:
        raise PreflightFailure(message)


def forbid(text: str, needle: str, message: str) -> None:
    if needle in text:
        raise PreflightFailure(message)


def between(text: str, start: str, end: str, label: str) -> str:
    start_pos = text.find(start)
    if start_pos < 0:
        raise PreflightFailure(f"cannot find start of {label}: {start}")
    end_pos = text.find(end, start_pos + len(start))
    if end_pos < 0:
        raise PreflightFailure(f"cannot find end of {label}: {end}")
    return text[start_pos:end_pos]


def main() -> int:
    common = read("src/vehicle/TrackerCommonPolicy.cpp")
    enhancements = read("src/vehicle/TrackerEnhancements.cpp")
    status = read("src/vehicle/TrackerStatusModule.cpp")
    display_model = read("src/jarnsen/core/display/JarnsenDisplayModel.h")

    # Role ownership: Tracker runtime must use the normalized Unified Core role,
    # never silently fall back to direct legacy role reads.
    for rel, text in (
        ("TrackerCommonPolicy.cpp", common),
        ("TrackerEnhancements.cpp", enhancements),
        ("TrackerStatusModule.cpp", status),
    ):
        forbid(
            text,
            "config.device.role",
            f"{rel}: direct config.device.role read reintroduced; use normalized Core role",
        )

    # Display timeout contract: screen_on_secs owns the visible time. Historical
    # fixed 20s/10s overrides must not return.
    require(
        common,
        "config.display.screen_on_secs",
        "TrackerCommonPolicy.cpp: display timeout no longer reads config.display.screen_on_secs",
    )
    require(
        common,
        "seconds == 0 ? TRACKER_COMMON_DEFAULT_DISPLAY_SECS : seconds",
        "TrackerCommonPolicy.cpp: screen_on_secs default semantics changed unexpectedly",
    )
    require(
        common,
        "resetDisplayWindow(releaseNow);",
        "TrackerCommonPolicy.cpp: display timer is no longer reset from button release",
    )
    forbid(
        common,
        "TRACKER_COMMON_DISPLAY_MS",
        "TrackerCommonPolicy.cpp: fixed TRACKER_COMMON_DISPLAY_MS timeout reintroduced",
    )
    forbid(
        common,
        "TRACKER_COMMON_LOW_BATTERY_DISPLAY_MS",
        "TrackerCommonPolicy.cpp: low-battery display timeout override reintroduced",
    )

    # Normal short-press page order is a product contract. SERVICE remains a
    # compatibility page only and must not enter the 5-page operator cycle.
    expected_transitions = (
        "case DisplayPage::MGRS:\n        return DisplayPage::NODE_STATUS;",
        "case DisplayPage::NODE_STATUS:\n        return DisplayPage::RADIO;",
        "case DisplayPage::RADIO:\n        return DisplayPage::NETWORK;",
        "case DisplayPage::NETWORK:\n        return DisplayPage::SYSTEM;",
    )
    for transition in expected_transitions:
        require(display_model, transition, f"JarnsenDisplayModel.h: missing page transition: {transition!r}")
    require(
        display_model,
        "constexpr uint8_t displayPageCount()\n{\n    return 5U;\n}",
        "JarnsenDisplayModel.h: operator display page count is no longer 5",
    )

    # Page 2 layout contract and overflow protection.
    node_page = between(status, "void drawOwnNodePage(", "void drawServicePage(", "drawOwnNodePage")
    require(node_page, 'display->drawString(x + 2, y + 1, "2/5");', "Tracker page 2: missing 2/5 label at top-left")
    require(node_page, "drawBattery(display, x, y);", "Tracker page 2: missing shared battery indicator")
    require(node_page, "display->getStringWidth(name)", "Tracker page 2: long name is not fitted by rendered pixel width")
    require(node_page, "const int w = display->getWidth();", "Tracker page 2: runtime display width is not used")
    require(node_page, "const int h = display->getHeight();", "Tracker page 2: runtime display height is not used")

    # Display geometry shown to the operator must come from the active driver,
    # not from a hard-coded 160x80 assumption.
    forbid(status, '"Display: 160x80"', "TrackerStatusModule.cpp: hard-coded display geometry reintroduced")
    require(
        status,
        'std::snprintf(buffer, size, "Display: %dx%d", screen ? screen->getWidth() : 0, screen ? screen->getHeight() : 0);',
        "Tracker SYSTEM INFO: runtime display geometry readout missing",
    )

    # Radio profiles are not roles and must stay the only PROFILE menu choices.
    require(
        status,
        'static const char *items[] = {"Standard", "Jarnsen 1", "Jarnsen 2", "ZURUECK"};',
        "Tracker PROFILE menu changed; Standard/Jarnsen 1/Jarnsen 2 must remain radio profiles",
    )
    select_profile = between(
        status,
        "    case MenuView::PROFILE:\n",
        "    case MenuView::TRACKER:\n",
        "PROFILE selection block",
    )
    forbid(select_profile, "Role", "Tracker PROFILE selection block must not expose role changes")
    forbid(select_profile, "role", "Tracker PROFILE selection block must not expose role changes")

    print("JARNSEN preflight contracts: PASS")
    print("- normalized Tracker role ownership")
    print("- configured display timeout and release reset")
    print("- 5-page MGRS/NODE/FUNK/NETZ/SYSTEM cycle")
    print("- page 2 runtime geometry and pixel-width fitting")
    print("- dynamic SYSTEM INFO display geometry")
    print("- radio profiles remain separate from device roles")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PreflightFailure as exc:
        print(f"JARNSEN preflight contracts: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
