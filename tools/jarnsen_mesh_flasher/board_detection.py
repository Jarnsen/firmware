from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Detection:
    board_key: str | None
    score: int
    reason: str


STRUCTURED_FIELDS = (
    "pioEnv",
    "pio_env",
    "environment",
    "build_environment",
    "hwModel",
    "hw_model",
    "hardwareModel",
    "hardware_model",
    "hardware",
    "board",
    "boardName",
    "board_name",
    "variant",
    "buildHardware",
    "build_hardware",
    "jarnsenHardware",
    "jarnsen_hardware",
)

# Intentionally avoid generic aliases such as just "WIRELESS TRACKER" or
# "TRACKER".  Those caused Seeed Wio Tracker L1 to be classified as a Heltec
# Tracker when Meshtastic printed generic tracker wording elsewhere in --info.
ALIASES: dict[str, tuple[str, ...]] = {
    "tracker": (
        "HELTEC_WIRELESS_TRACKER",
        "HELTEC WIRELESS TRACKER",
        "HELTEC-WIRELESS-TRACKER",
        "HELTEC WIRELESS TRACKER V1.1",
        "HELTEC TRACKER V1.1",
        "TRACKER V1.1",
        "heltec-wireless-tracker",
    ),
    "repeater": (
        "HELTEC_V3",
        "HELTEC V3",
        "HELTEC-V3",
        "HELTEC WIFI LORA 32 V3",
        "HELTEC LORA32 V3",
        "V3 REPEATER",
        "heltec-v3",
    ),
    "wio": (
        "WIO_TRACKER_L1",
        "WIO TRACKER L1",
        "SEEED WIO TRACKER L1",
        "SEEED_WIO_TRACKER_L1",
        "SEEED-WIO-TRACKER-L1",
        "seeed_wio_tracker_L1",
    ),
}

# Exact hardware strings compiled into JARNSEN-MESH Unified Core builds.
BUILD_HARDWARE: dict[str, tuple[str, ...]] = {
    "tracker": ("TRACKER V1.1", "HELTEC TRACKER V1.1"),
    "repeater": ("HELTEC V3",),
    "wio": ("WIO TRACKER L1", "SEEED WIO TRACKER L1"),
}


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _normalize(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", (value or "").upper()).strip("_")


def _available_boards(board_profiles: dict[str, Any] | None) -> set[str]:
    available = set((board_profiles or {}).keys())
    # The Wio profile is installed at runtime.  Keeping aliases here allows
    # exact Wio hardware fields to be recognized even during startup ordering.
    return available or {"tracker", "repeater", "wio"}


def _alias_match(value: str, board_profiles: dict[str, Any] | None = None) -> str | None:
    normalized = _normalize(value)
    if not normalized:
        return None
    available = _available_boards(board_profiles)

    # First compare the actual PlatformIO environments from the runtime board
    # profiles.  This is the strongest cross-version identifier Meshtastic
    # exposes in metadata.
    for board_key, profile in (board_profiles or {}).items():
        pio_env = _normalize(str(profile.get("pio_env") or ""))
        if pio_env and pio_env == normalized:
            return board_key

    for board_key, aliases in ALIASES.items():
        if board_key not in available and board_profiles:
            continue
        for alias in aliases:
            if _normalize(alias) == normalized:
                return board_key
    return None


def _extract_structured(source: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for field in STRUCTURED_FIELDS:
        patterns = (
            rf'''(?i)["']?{re.escape(field)}["']?\s*[:=]\s*["']?([^\r\n,"']+)''',
            rf'''(?i)\b{re.escape(field)}\b\s+([A-Za-z0-9_.\- ]+)''',
        )
        for pattern in patterns:
            match = re.search(pattern, source)
            if match:
                value = match.group(1).strip()
                if value:
                    found.append((field, value))
                break
    return found


def _contains_phrase(source: str, phrase: str) -> bool:
    # Normalize separators while still requiring the whole hardware phrase.
    normalized_source = f"_{_normalize(source)}_"
    normalized_phrase = _normalize(phrase)
    return bool(normalized_phrase and f"_{normalized_phrase}_" in normalized_source)


def detect(text: str, board_profiles: dict[str, Any] | None = None) -> Detection:
    source = text or ""
    if not source.strip():
        return Detection(None, 0, "empty serial info")

    profiles = board_profiles or {}
    available = _available_boards(profiles)

    # 1) Structured hardware/PIO fields win immediately.  This fixes the Wio
    # false-positive even if generic tracker wording occurs elsewhere in info.
    structured = _extract_structured(source)
    for field, raw in structured:
        board_key = _alias_match(raw, profiles)
        if board_key:
            return Detection(board_key, 1000, f"structured {field}={raw}")

    # 2) Exact JARNSEN-MESH build-hardware phrases are stronger than any legacy
    # free-text match.  Refuse to guess if two exact hardware identities occur.
    exact_hits: list[tuple[str, str]] = []
    for board_key, phrases in BUILD_HARDWARE.items():
        if board_key not in available and profiles:
            continue
        for phrase in phrases:
            if _contains_phrase(source, phrase):
                exact_hits.append((board_key, phrase))
                break
    exact_boards = {key for key, _phrase in exact_hits}
    if len(exact_boards) == 1:
        board_key, phrase = exact_hits[0]
        return Detection(board_key, 900, f"exact hardware phrase={phrase}")
    if len(exact_boards) > 1:
        return Detection(None, 0, f"conflicting exact hardware phrases={exact_hits}")

    # 3) Dynamic scoring for older/original Meshtastic output.  All currently
    # installed boards participate in one competition; Wio is never a fallback
    # after Heltec.
    scores: dict[str, int] = {key: 0 for key in available}
    reasons: dict[str, list[str]] = {key: [] for key in available}

    for board_key, profile in profiles.items():
        if board_key not in scores:
            continue
        pio_env = str(profile.get("pio_env") or "")
        if pio_env and _contains_phrase(source, pio_env):
            scores[board_key] += 180
            reasons[board_key].append(f"pio:{pio_env}")

        # Profile match tokens are useful only when they identify a complete
        # board string.  Short/generic tracker words no longer count.
        for token in profile.get("match", ()):
            token = str(token or "").strip()
            if len(_normalize(token)) < 8:
                continue
            if _contains_phrase(source, token):
                scores[board_key] += 75
                reasons[board_key].append(f"profile:{token}")

    for board_key, aliases in ALIASES.items():
        if board_key not in scores:
            continue
        for alias in aliases:
            normalized = _normalize(alias)
            if len(normalized) < 8:
                continue
            if _contains_phrase(source, alias):
                # Explicit vendor-prefixed aliases beat generic legacy ones.
                vendor = any(name in normalized for name in ("HELTEC", "SEEED", "WIO"))
                scores[board_key] += 90 if vendor else 45
                reasons[board_key].append(f"alias:{alias}")

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if not ranked:
        return Detection(None, 0, "no board profiles installed")
    winner, best = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0

    if best < 75:
        return Detection(None, best, f"no strong board evidence scores={scores}")
    if second and best - second < 40:
        return Detection(None, best, f"ambiguous board evidence scores={scores}")

    reason = ", ".join(reasons[winner][:8]) or f"scores={scores}"
    return Detection(winner, best, reason)


def install(services: Any) -> None:
    def detect_board_from_text(text: str) -> str | None:
        result = detect(text, services.BOARD_PROFILES)
        _emit(
            "BOARD DETECTION "
            f"board={result.board_key!r} score={result.score} reason={result.reason!r} "
            f"chars={len(text or '')}"
        )
        return result.board_key

    services.detect_board_from_text = detect_board_from_text
    _emit("BOARD DETECTION installed: exact hardware/PIO first + dynamic 3-board scoring")
