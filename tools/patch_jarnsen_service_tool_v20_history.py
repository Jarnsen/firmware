"""v2.0 history-schema migration for extended diagnostic metrics."""
from __future__ import annotations

import sys
from pathlib import Path


def function_span(text: str, name: str) -> tuple[int, int]:
    start = text.find(f"def {name}(")
    if start < 0:
        raise SystemExit(f"function {name} not found")
    next_def = text.find("\ndef ", start + 1)
    next_class = text.find("\nclass ", start + 1)
    ends = [value for value in (next_def, next_class) if value >= 0]
    return start, min(ends) if ends else len(text)


def patch(source: str) -> str:
    replacement = r'''def update_history(payload: bytes) -> str:
    """Append one legacy CSV history row while safely migrating added v2 columns."""
    current = log_metrics(payload)
    history_path = output_directory() / "Jarnsen_Node_History.csv"
    current_fields = list(current)
    previous = None
    rows: list[dict[str, str]] = []
    old_fields: list[str] = []

    if history_path.exists():
        try:
            with history_path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle, delimiter=";")
                old_fields = [field for field in (reader.fieldnames or []) if field]
                for raw in reader:
                    # DictReader uses key None for surplus columns from an older
                    # malformed append. Ignore that synthetic key but preserve all
                    # named legacy data.
                    rows.append({str(key): str(value or "") for key, value in raw.items() if key})
            same_node = [
                row
                for row in rows
                if current.get("node_id") and row.get("node_id") == current.get("node_id")
            ]
            previous = same_node[-1] if same_node else None
        except (OSError, csv.Error):
            rows = []
            old_fields = []
            previous = None

    fields = list(dict.fromkeys(old_fields + current_fields))
    if not fields:
        fields = current_fields

    # If v2 introduced columns, rewrite the CSV once with the union header. Raw
    # diagnostic text files and SQLite remain the source of truth; this only keeps
    # the convenience CSV structurally valid across app upgrades.
    rewrite = history_path.exists() and old_fields != fields
    mode = "w" if rewrite or not history_path.exists() else "a"
    with history_path.open(mode, encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter=";", extrasaction="ignore")
        if mode == "w":
            writer.writeheader()
            if rewrite:
                writer.writerows(rows)
        writer.writerow(current)

    if not previous:
        return "Historie: erster Messpunkt dieser Node gespeichert"

    changes = []
    for key, label in (
        ("firmware", "Firmware"),
        ("build", "Build"),
        ("battery_mv", "Akku mV"),
        ("battery_pct", "Akku %"),
        ("capacity", "Kapazität"),
        ("confidence", "Vertrauen"),
        ("capacity_cycles", "Lernzyklen"),
        ("tx", "TX"),
        ("motion", "Motion"),
        ("positions", "Positionen"),
        ("live_positions", "V3 Live-TX"),
        ("position_state", "V3 Bewegungszustand"),
        ("reported_accuracy", "GPS gemeldet"),
        ("estimated_accuracy", "GPS geschätzt"),
        ("fixed_difference", "Abstand Fixposition"),
    ):
        old, new = previous.get(key, ""), str(current.get(key, "") or "")
        if old and new and old != new:
            changes.append(f"{label}: {old} -> {new}")
    return "Vergleich zum letzten Log:\n" + (
        "\n".join(changes) if changes else "keine Änderung der erfassten Werte"
    )
'''
    start, end = function_span(source, "update_history")
    source = source[:start] + replacement.rstrip() + "\n\n" + source[end:].lstrip("\n")
    for marker in (
        'old_fields != fields',
        'extrasaction="ignore"',
        '("capacity_cycles", "Lernzyklen")',
        '("live_positions", "V3 Live-TX")',
        '("position_state", "V3 Bewegungszustand")',
    ):
        if marker not in source:
            raise SystemExit(f"missing v2.0 history marker: {marker}")
    return source


def main() -> None:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "tools/JARNSEN_NODE_SERVICE_TOOL.py")
    target.write_text(patch(target.read_text(encoding="utf-8")), encoding="utf-8")
    print("Service tool v2.0 history: legacy CSV schema migration enabled")


if __name__ == "__main__":
    main()
