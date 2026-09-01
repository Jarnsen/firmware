"""Keep the Framework7 frontend alive if WebView2 exits without a user close.

USB hot-plug is handled by the backend process, but on affected Windows systems
WebView2 can return from its native event loop while the backend remains healthy.
Treat that as a renderer/window failure, not as an application shutdown. A real
user close is tracked through the window closing event and still exits normally.
"""
from __future__ import annotations

import pathlib
import sys


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_framework7_webview_resilience_v315.py <runtime-fixes.py>", file=sys.stderr)
        return 2
    path = pathlib.Path(sys.argv[1])
    text = path.read_text(encoding="utf-8")
    if "Framework7 WebView resilience v3.15" in text:
        print("Framework7 WebView resilience v3.15 already installed")
        return 0

    old = '''            _append_startup_log("creating WebView window")\n            webview.create_window(\n                "Jarnsen Node Service Tool",\n                url=url,\n                width=1600,\n                height=980,\n                min_size=(1120, 720),\n                background_color="#F5F7FB",\n                confirm_close=False,\n            )\n            _append_startup_log("WebView event loop entering")\n            webview.start(debug=debug)\n            _append_startup_log(f"WebView event loop returned; backend_poll={backend.poll() if backend is not None else None}")\n\n            with contextlib.suppress(Exception):\n'''
    new = '''            # Framework7 WebView resilience v3.15\n            # Affected Windows/WebView2 installations can return from the native\n            # loop during USB hot-plug even though our backend is still healthy.\n            # Distinguish an explicit close from that renderer/window failure.\n            user_close = {"requested": False}\n            reopen_count = 0\n            while True:\n                _append_startup_log(f"creating WebView window attempt={reopen_count + 1}")\n                window = webview.create_window(\n                    "Jarnsen Node Service Tool",\n                    url=url,\n                    width=1600,\n                    height=980,\n                    min_size=(1120, 720),\n                    background_color="#F5F7FB",\n                    confirm_close=False,\n                )\n\n                def _mark_user_close(*_args: Any, **_kwargs: Any) -> None:\n                    user_close["requested"] = True\n                    _append_startup_log("WebView explicit closing event received")\n\n                with contextlib.suppress(Exception):\n                    window.events.closing += _mark_user_close\n                _append_startup_log(f"WebView event loop entering attempt={reopen_count + 1}")\n                webview.start(debug=debug)\n                backend_code = backend.poll() if backend is not None else None\n                _append_startup_log(\n                    f"WebView event loop returned attempt={reopen_count + 1}; "\n                    f"backend_poll={backend_code} user_close={user_close['requested']}"\n                )\n                if user_close["requested"] or backend_code is not None:\n                    break\n                reopen_count += 1\n                if reopen_count >= 5:\n                    raise RuntimeError(\n                        "WebView2 wurde wiederholt unerwartet beendet, obwohl das Backend weiterlief"\n                    )\n                _append_startup_log(\n                    f"WebView unexpected exit with healthy backend; reopening in 0.75s count={reopen_count}"\n                )\n                time.sleep(0.75)\n\n            with contextlib.suppress(Exception):\n'''
    text = replace_once(text, old, new, "WebView resilient loop")
    path.write_text(text, encoding="utf-8")
    compile(text, str(path), "exec")
    print("Framework7 WebView resilience v3.15 installed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
