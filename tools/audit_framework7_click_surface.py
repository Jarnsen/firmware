"""Audit every visible Framework7 button/control family for a reachable handler.

This is intentionally stricter than syntax checks. It scans index.html and all
first-party UI JavaScript after build-time patching, collects visible button IDs
and data-* action families, and verifies that each has an explicit handler path.
It also verifies the capture-phase router used on Windows/WebView2 and the direct
handlers used by additive modules such as Service/Recovery and Series.
"""
from __future__ import annotations

import pathlib
import re
import sys

JS_NAMES = (
    "app-v31.js",
    "map-settings-v32.js",
    "radio-auth-v33.js",
    "legacy-compat-v34.js",
    "parity-v35.js",
    "parity-enhance-v36.js",
    "series-v37.js",
    "version-v38.js",
    "service-cleanup-v39.js",
    "usb-status-v320.js",
    "overview-v321.js",
    "full-redesign-v322.js",
    "page-bridges-v322.js",
    "usb-attach-v322.js",
)

# Framework7-native close links are intentionally handled by Framework7 itself.
NATIVE_CLASSES = {"sheet-close", "popup-close"}


def tags(source: str) -> list[str]:
    return re.findall(r"<button\b[^>]*>|<a\b[^>]*>", source, flags=re.I)


def attr(tag: str, name: str) -> str:
    m = re.search(rf'\b{name}=["\']([^"\']+)["\']', tag, flags=re.I)
    return m.group(1) if m else ""


def has_native_class(tag: str) -> bool:
    classes = set(attr(tag, "class").split())
    return bool(classes & NATIVE_CLASSES)


def main() -> int:
    root = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else pathlib.Path("tools/service_tool_web")
    index_path = root / "index.html"
    if not index_path.is_file():
        raise RuntimeError(f"click audit: missing {index_path}")

    sources: dict[str, str] = {"index.html": index_path.read_text(encoding="utf-8")}
    for name in JS_NAMES:
        path = root / name
        if not path.is_file():
            raise RuntimeError(f"click audit: missing {path}")
        sources[name] = path.read_text(encoding="utf-8")

    combined = "\n".join(sources.values())
    app = sources["app-v31.js"]
    parity = sources["parity-v35.js"]
    series = sources["series-v37.js"]
    enhance = sources["parity-enhance-v36.js"]

    # The primary Windows input path must exist and must be capture-phase.
    for marker in (
        "function jarnsenCaptureUiClick(event)",
        "document.addEventListener('click', jarnsenCaptureUiClick, true)",
        "target.closest('#activityButton')",
        "target.closest('[data-live-action]')",
        "target.closest('[data-live-control]')",
        "target.closest('[data-view]')",
        "target.closest('[data-action]')",
    ):
        if marker not in app:
            raise RuntimeError(f"click audit: full capture router marker missing: {marker}")

    # Service/Recovery must not depend only on document bubbling.
    for marker in (
        "function bindServiceControls()",
        "closeButton.addEventListener('click'",
        "button.addEventListener('click'",
        "bindServiceControls();",
    ):
        if marker not in parity:
            raise RuntimeError(f"click audit: Service direct-handler marker missing: {marker}")

    visible_ids: set[str] = set()
    data_families: set[str] = set()
    unresolved: list[str] = []

    for filename, source in sources.items():
        for tag in tags(source):
            if has_native_class(tag):
                continue
            element_id = attr(tag, "id")
            if element_id:
                visible_ids.add(element_id)
            for family in re.findall(r'\b(data-[a-zA-Z0-9_-]+)=', tag):
                data_families.add(family)

    # Every explicit button id must be referenced outside its creation at least once.
    for element_id in sorted(visible_ids):
        occurrences = combined.count(element_id)
        if occurrences < 2:
            unresolved.append(f"id #{element_id}: only creation/reference occurrence={occurrences}")
            continue
        selector_markers = (
            f"getElementById('{element_id}')",
            f'getElementById("{element_id}")',
            f"querySelector('#{element_id}')",
            f'querySelector("#{element_id}")',
            f"closest('#{element_id}')",
            f'closest("#{element_id}")',
        )
        if not any(marker in combined for marker in selector_markers):
            # IDs used by Framework7 native widgets may be wired through object creation,
            # but first-party buttons must have an explicit selector path.
            unresolved.append(f"id #{element_id}: no explicit selector/handler path")

    # Every data-* family used on a button/link must have a selector or dataset path.
    for family in sorted(data_families):
        key = family[5:].replace("-", "_")
        camel = re.sub(r"-([a-z])", lambda m: m.group(1).upper(), family[5:])
        markers = (
            f"[{family}]",
            f"dataset.{camel}",
            f"dataset['{camel}']",
            f'dataset["{camel}"]',
        )
        if not any(marker in combined for marker in markers):
            unresolved.append(f"{family}: no selector/dataset handler path")

    # Additive Series module: all of its primary buttons must be explicitly bound.
    for element_id in (
        "seriesReload",
        "seriesTemplateSave",
        "seriesTemplateDelete",
        "seriesGithubLoad",
        "seriesLocalFile",
        "seriesStart",
        "seriesCancel",
    ):
        if element_id in series:
            if series.count(element_id) < 2:
                unresolved.append(f"Series #{element_id}: rendered but not referenced by handler")

    # Serial/zoom enhancement controls are direct-bound after decoration.
    for element_id in ("serialPauseButton", "serialExportButton", "globalUiZoom"):
        if element_id not in enhance or enhance.count(element_id) < 2:
            unresolved.append(f"Parity enhance #{element_id}: missing direct binding")

    if unresolved:
        detail = "\n - ".join(unresolved)
        raise RuntimeError(f"Framework7 complete click-surface audit FAILED:\n - {detail}")

    print(
        "Framework7 complete click-surface audit OK: "
        f"{len(visible_ids)} explicit control IDs, {len(data_families)} data-action families, "
        f"{len(JS_NAMES)} UI modules"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
