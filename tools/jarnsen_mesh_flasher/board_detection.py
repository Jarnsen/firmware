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
    "hwModel",
    "hw_model",
    "hardwareModel",
    "hardware_model",
    "board",
    "boardName",
    "board_name",
    "variant",
    "pio_env",
)

ALIASES: dict[str, tuple[str, ...]] = {
    "tracker": (
        "HELTEC_WIRELESS_TRACKER",
        "HELTEC WIRELESS TRACKER",
        "HELTEC-WIRELESS-TRACKER",
        "WIRELESS_TRACKER",
        "WIRELESS TRACKER V1.1",
        "TRACKER V1.1",
        "HELTEC TRACKER V1.1",
        "heltec-wireless-tracker",
    ),
    "repeater": (
        "HELTEC_V3",
        "HELTEC V3",
        "HELTEC-V3",
        "HELTEC WIFI LORA 32 V3",
        "WIFI LORA 32 V3",
        "V3 REPEATER",
        "heltec-v3",
    ),
}


def _emit(message: str) -> None:
    try:
        import diagnostics

        diagnostics._emit(message)
    except Exception:
        pass


def _normalize(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", (value or "").upper()).strip("_")


def _alias_match(value: str) -> str | None:
    normalized = _normalize(value)
    if not normalized:
        return None
    for board_key, aliases in ALIASES.items():
        for alias in aliases:
            if _normalize(alias) == normalized:
                return board_key
    return None


def detect(text: str, board_profiles: dict[str, Any] | None = None) -> Detection:
    source = text or ""
    if not source.strip():
        return Detection(None, 0, "empty serial info")

    # 1. Structured hardware/model fields are strongest. Meshtastic --info has
    # used several spellings across versions, so support JSON and key:value text.
    for field in STRUCTURED_FIELDS:
        patterns = (
            rf'(?i)["\']?{re.escape(field)}["\']?\s*[:=]\s*["\']([^"\'\r\n,}}]+)',
            rf'(?i)\b{re.escape(field)}\b\s+([A-Za-z0-9_.\- ]+)',
        )
        for pattern in patterns:
            match = re.search(pattern, source)
            if not match:
                continue
            raw = match.group(1).strip()
            board_key = _alias_match(raw)
            if board_key:
                return Detection(board_key, 100, f"structured {field}={raw}")

    upper = source.upper()
    scores = {"tracker": 0, "repeater": 0}
    reasons: dict[str, list[str]] = {"tracker": [], "repeater": []}

    # 2. Exact aliases and PIO environment strings.
    for board_key, aliases in ALIASES.items():
        for alias in aliases:
            if alias.upper() in upper:
                weight = 45 if alias.lower().startswith("heltec-") else 30
                scores[board_key] += weight
                reasons[board_key].append(alias)

    # 3. Also consume aliases from services.BOARD_PROFILES so future additions
    # automatically become visible to the detector.
    for board_key, profile in (board_profiles or {}).items():
        if board_key not in scores:
            continue
        pio_env = str(profile.get("pio_env") or "")
        if pio_env and pio_env.upper() in upper:
            scores[board_key] += 50
            reasons[board_key].append(f"pio:{pio_env}")
        for token in profile.get("match", ()):
            token = str(token or "")
            if token and token.upper() in upper:
                scores[board_key] += 20
                reasons[board_key].append(token)

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    winner, best = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0

    # Do not guess from weak/generic strings. We need a clear margin so series
    # flashing cannot select a profile/firmware for the wrong board.
    if best < 25:
        return Detection(None, best, f"no strong board evidence scores={scores}")
    if second and best - second < 20:
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
    _emit("BOARD DETECTION installed: structured fields + confidence scoring")
