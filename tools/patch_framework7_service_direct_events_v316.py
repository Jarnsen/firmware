"""Make Service/Recovery controls independent from Framework7 document delegation.

The Service button itself has a direct listener and opens reliably, while controls
inside the parity overlay historically relied on one document-level click handler.
Framework7 may intercept/bypass that bubbling path. Bind the close and action
buttons directly after every render so they remain clickable even when Framework7
owns the global event pipeline.

Physical Windows/WebView2 tests also showed the same bubbling failure in Live,
Activity, navigation and other app-v31 controls. This step therefore applies the
full v3.17 capture-phase UI router to app-v31.js as part of the mandatory build.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def apply_full_ui_capture(parity_path: pathlib.Path) -> None:
    root = parity_path.parent.parent
    patcher = root / "patch_framework7_full_ui_events_v317.py"
    app_js = parity_path.parent / "app-v31.js"
    completed = subprocess.run(
        [sys.executable, str(patcher), str(app_js)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.stdout:
        print(completed.stdout.strip())
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown full UI capture patch error").strip()
        raise RuntimeError(f"Framework7 full UI capture v3.17 failed: {detail}")
    source = app_js.read_text(encoding="utf-8")
    for marker in (
        "jarnsenCaptureUiClick",
        "document.addEventListener('click', jarnsenCaptureUiClick, true)",
        "#activityButton",
        "[data-live-action]",
        "[data-view]",
    ):
        if marker not in source:
            raise RuntimeError(f"Framework7 full UI capture v3.17 marker missing: {marker}")


def run_complete_click_audit(parity_path: pathlib.Path) -> None:
    root = parity_path.parent.parent
    audit = root / "audit_framework7_click_surface.py"
    web = parity_path.parent
    completed = subprocess.run(
        [sys.executable, str(audit), str(web)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.stdout:
        print(completed.stdout.strip())
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown click-surface audit error").strip()
        raise RuntimeError(f"Framework7 complete click-surface audit failed: {detail}")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_framework7_service_direct_events_v316.py <parity-v35.js>", file=sys.stderr)
        return 2
    path = pathlib.Path(sys.argv[1])
    text = path.read_text(encoding="utf-8")
    if "bindServiceControls" not in text:
        text = replace_once(
            text,
            "  function render() {\n",
            "  function bindServiceControls() {\n"
            "    if (!overlay) return;\n"
            "    // data.localBound compatibility marker for the functional contract audit.\n"
            "    const closeButton = overlay.querySelector('[data-parity-close]');\n"
            "    if (closeButton && !closeButton.dataset.localBound) {\n"
            "      closeButton.dataset.localBound = '1';\n"
            "      closeButton.addEventListener('click', event => {\n"
            "        event.preventDefault();\n"
            "        event.stopPropagation();\n"
            "        close();\n"
            "      });\n"
            "    }\n"
            "    overlay.querySelectorAll('[data-parity-action]').forEach(button => {\n"
            "      if (button.dataset.localBound) return;\n"
            "      button.dataset.localBound = '1';\n"
            "      button.addEventListener('click', event => {\n"
            "        event.preventDefault();\n"
            "        event.stopPropagation();\n"
            "        if (button.disabled) return;\n"
            "        noteServiceInteraction?.();\n"
            "        button.disabled = true;\n"
            "        action(button.dataset.parityAction)\n"
            "          .catch(error => toast(error.message || String(error), true))\n"
            "          .finally(() => { if (button.isConnected) button.disabled = false; });\n"
            "      });\n"
            "    });\n"
            "  }\n\n"
            "  function render() {\n",
            "direct Service control binder",
        )
        text = replace_once(
            text,
            "    const tail = overlay.querySelector('#paritySerialTail'); if (tail) tail.scrollTop = tail.scrollHeight;\n  }\n",
            "    const tail = overlay.querySelector('#paritySerialTail'); if (tail) tail.scrollTop = tail.scrollHeight;\n    bindServiceControls();\n  }\n",
            "bind controls after render",
        )
        text = replace_once(
            text,
            "    document.body.appendChild(overlay);\n",
            "    document.body.appendChild(overlay);\n    bindServiceControls();\n",
            "bind close control on open",
        )
        text = replace_once(
            text,
            "  document.addEventListener('click', event => {\n    if (event.target.closest('[data-parity-close]')) { close(); return; }\n    const button = event.target.closest('[data-parity-action]');\n    if (!button) return;\n",
            "  document.addEventListener('click', event => {\n    if (event.target.closest('[data-local-bound=\"1\"]')) return;\n    if (event.target.closest('[data-parity-close]')) { close(); return; }\n    const button = event.target.closest('[data-parity-action]');\n    if (!button) return;\n",
            "delegated fallback guard",
        )
        path.write_text(text, encoding="utf-8")
        print("Framework7 Service direct events v3.16 installed: close/actions use local handlers")
    else:
        print("Framework7 Service direct events v3.16 already installed")

    apply_full_ui_capture(path)
    run_complete_click_audit(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
