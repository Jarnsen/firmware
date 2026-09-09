"""Prevent Framework7 window close from killing an active service worker."""
from __future__ import annotations

import pathlib
import sys


def replace_exact(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_runtime(path: pathlib.Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "def _block_close_while_busy" in text:
        return

    old = '''            webview.create_window(\n                "Jarnsen Node Service Tool",\n                url=url,\n                width=1600,\n                height=980,\n                min_size=(1120, 720),\n                background_color="#F5F7FB",\n                confirm_close=False,\n            )\n            webview.start(debug=debug)\n'''
    new = '''            window = webview.create_window(\n                "Jarnsen Node Service Tool",\n                url=url,\n                width=1600,\n                height=980,\n                min_size=(1120, 720),\n                background_color="#F5F7FB",\n                confirm_close=True,\n            )\n\n            def _block_close_while_busy() -> bool | None:\n                """Cancel a close request while a device worker/provision is active."""\n                busy = False\n                detail = ""\n                headers = {"X-Jarnsen-Token": token, "Cache-Control": "no-cache"}\n                try:\n                    state_request = urllib.request.Request(base_url + "/api/state", headers=headers)\n                    with urllib.request.urlopen(state_request, timeout=1.5) as response:\n                        state_payload = json.load(response)\n                    if isinstance(state_payload, dict):\n                        busy = bool(state_payload.get("busy"))\n                        detail = str(state_payload.get("status") or "")\n\n                    series_request = urllib.request.Request(base_url + "/api/series/status", headers=headers)\n                    with urllib.request.urlopen(series_request, timeout=1.5) as response:\n                        series_payload = json.load(response)\n                    if isinstance(series_payload, dict):\n                        job = series_payload.get("job")\n                        series_busy = bool(series_payload.get("busy")) or (\n                            isinstance(job, dict) and str(job.get("state") or "") == "running"\n                        )\n                        busy = busy or series_busy\n                        if series_busy and isinstance(job, dict):\n                            detail = str(job.get("stage") or job.get("message") or detail)\n                except Exception as exc:  # Backend loss must never trap the desktop window.\n                    _append_startup_log(f"close guard backend probe skipped: {type(exc).__name__}: {exc}")\n                    return None\n\n                if not busy:\n                    return None\n\n                _append_startup_log(f"window close blocked: active worker detail={detail or '-'}")\n                if os.name == "nt":\n                    with contextlib.suppress(Exception):\n                        import ctypes\n                        ctypes.windll.user32.MessageBoxW(\n                            0,\n                            "Ein Geräte-Vorgang läuft noch und darf nicht durch Schließen des Tools unterbrochen werden.\\n\\n"\n                            + (f"Status: {detail}\\n\\n" if detail else "")\n                            + "Bitte den Vorgang abschließen oder über die vorgesehene Abbrechen-Funktion beenden.",\n                            "Jarnsen Service Tool – Vorgang läuft",\n                            0x30,\n                        )\n                return False\n\n            window.events.closing += _block_close_while_busy\n            webview.start(debug=debug)\n'''
    if old not in text:
        raise RuntimeError("safe-close WebView anchor missing")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_validator(path: pathlib.Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "safe close guard" in text:
        return
    helper = '''\n\ndef test_safe_close_guard() -> None:\n    source = (ROOT / "JARNSEN_FRAMEWORK7_RUNTIME_FIXES_V312.py").read_text(encoding="utf-8")\n    for marker in (\n        "confirm_close=True",\n        "def _block_close_while_busy",\n        "window.events.closing += _block_close_while_busy",\n        'base_url + "/api/state"',\n        'base_url + "/api/series/status"',\n        "return False",\n    ):\n        if marker not in source:\n            raise AssertionError(f"safe close guard missing: {marker}")\n    print("OK safe close guard")\n'''
    main_anchor = "\ndef main() -> None:\n"
    if text.count(main_anchor) != 1:
        raise RuntimeError("safe-close validator main anchor missing")
    text = text.replace(main_anchor, helper + main_anchor, 1)
    old = "    test_build_smoke_contract()\n"
    new = "    test_safe_close_guard()\n    test_build_smoke_contract()\n"
    if text.count(old) != 1:
        raise RuntimeError("safe-close validator call anchor missing")
    text = text.replace(old, new, 1)
    text += "\n# safe close guard\n"
    path.write_text(text, encoding="utf-8")


def main() -> None:
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "tools")
    patch_runtime(root / "JARNSEN_FRAMEWORK7_RUNTIME_FIXES_V312.py")
    patch_validator(root / "ci" / "validate_framework7_hardening_contracts.py")
    print("Applied Framework7 active-worker safe-close guard")


if __name__ == "__main__":
    main()
