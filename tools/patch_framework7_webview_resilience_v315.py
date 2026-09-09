"""Keep Framework7 alive on unexpected WebView2 exit without weakening safe-close.

USB hot-plug is handled by the backend process, but on affected Windows systems
WebView2 can return from its native event loop while the backend remains healthy.
Treat that as a renderer/window failure, not as an application shutdown.  When
the active-worker safe-close guard is installed, preserve it and only mark a
close as user-requested after that guard has allowed the close.
"""
from __future__ import annotations

import pathlib
import sys


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_safe_close_runtime(text: str) -> str:
    """Combine v3.15 renderer recovery with the already-installed v3.12 guard."""
    start_marker = '            _append_startup_log("creating WebView window")\n'
    end_marker = (
        '            _append_startup_log(f"WebView event loop returned; '
        'backend_poll={backend.poll() if backend is not None else None}")\n'
    )
    if text.count(start_marker) != 1 or text.count(end_marker) != 1:
        raise RuntimeError(
            "WebView safe-close/resilience anchor missing or ambiguous: "
            f"start={text.count(start_marker)} end={text.count(end_marker)}"
        )
    start = text.index(start_marker)
    end = text.index(end_marker, start) + len(end_marker)
    block = text[start:end]

    guard_marker = "            def _block_close_while_busy() -> bool | None:\n"
    handler_marker = "            window.events.closing += _block_close_while_busy\n"
    if guard_marker not in block or handler_marker not in block:
        raise RuntimeError("active-worker close guard is incomplete before WebView resilience patch")
    guard_start = block.index(guard_marker)
    guard_end = block.index(handler_marker)
    guard_source = block[guard_start:guard_end]

    replacement = '''            # Framework7 WebView resilience v3.15 + safe-close v3.12
            # Unexpected renderer exits are reopened. An explicit close is only
            # accepted after _block_close_while_busy() permits it.
            user_close = {"requested": False}
            reopen_count = 0
''' + guard_source + '''            while True:
                _append_startup_log(f"creating WebView window attempt={reopen_count + 1}")
                window = webview.create_window(
                    "Jarnsen Node Service Tool",
                    url=url,
                    width=1600,
                    height=980,
                    min_size=(1120, 720),
                    background_color="#F5F7FB",
                    confirm_close=True,
                )

                def _guarded_user_close(*_args: Any, **_kwargs: Any) -> bool | None:
                    decision = _block_close_while_busy()
                    if decision is False:
                        return False
                    user_close["requested"] = True
                    _append_startup_log("WebView explicit closing event received")
                    return decision

                window.events.closing += _guarded_user_close
                _append_startup_log(f"WebView event loop entering attempt={reopen_count + 1}")
                webview.start(debug=debug)
                backend_code = backend.poll() if backend is not None else None
                _append_startup_log(
                    f"WebView event loop returned attempt={reopen_count + 1}; "
                    f"backend_poll={backend_code} user_close={user_close['requested']}"
                )
                if user_close["requested"] or backend_code is not None:
                    break
                reopen_count += 1
                if reopen_count >= 5:
                    raise RuntimeError(
                        "WebView2 wurde wiederholt unerwartet beendet, obwohl das Backend weiterlief"
                    )
                _append_startup_log(
                    f"WebView unexpected exit with healthy backend; reopening in 0.75s count={reopen_count}"
                )
                time.sleep(0.75)
'''
    return text[:start] + replacement + text[end:]


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_framework7_webview_resilience_v315.py <runtime-fixes.py>", file=sys.stderr)
        return 2
    path = pathlib.Path(sys.argv[1])
    text = path.read_text(encoding="utf-8")
    if "Framework7 WebView resilience v3.15" in text:
        print("Framework7 WebView resilience v3.15 already installed")
        return 0

    if "def _block_close_while_busy" in text:
        text = patch_safe_close_runtime(text)
    else:
        old = '''            _append_startup_log("creating WebView window")\n            webview.create_window(\n                "Jarnsen Node Service Tool",\n                url=url,\n                width=1600,\n                height=980,\n                min_size=(1120, 720),\n                background_color="#F5F7FB",\n                confirm_close=False,\n            )\n            _append_startup_log("WebView event loop entering")\n            webview.start(debug=debug)\n            _append_startup_log(f"WebView event loop returned; backend_poll={backend.poll() if backend is not None else None}")\n\n            with contextlib.suppress(Exception):\n'''
        new = '''            # Framework7 WebView resilience v3.15\n            user_close = {"requested": False}\n            reopen_count = 0\n            while True:\n                _append_startup_log(f"creating WebView window attempt={reopen_count + 1}")\n                window = webview.create_window(\n                    "Jarnsen Node Service Tool",\n                    url=url,\n                    width=1600,\n                    height=980,\n                    min_size=(1120, 720),\n                    background_color="#F5F7FB",\n                    confirm_close=False,\n                )\n\n                def _mark_user_close(*_args: Any, **_kwargs: Any) -> None:\n                    user_close["requested"] = True\n                    _append_startup_log("WebView explicit closing event received")\n\n                with contextlib.suppress(Exception):\n                    window.events.closing += _mark_user_close\n                _append_startup_log(f"WebView event loop entering attempt={reopen_count + 1}")\n                webview.start(debug=debug)\n                backend_code = backend.poll() if backend is not None else None\n                _append_startup_log(\n                    f"WebView event loop returned attempt={reopen_count + 1}; "\n                    f"backend_poll={backend_code} user_close={user_close['requested']}"\n                )\n                if user_close["requested"] or backend_code is not None:\n                    break\n                reopen_count += 1\n                if reopen_count >= 5:\n                    raise RuntimeError(\n                        "WebView2 wurde wiederholt unerwartet beendet, obwohl das Backend weiterlief"\n                    )\n                _append_startup_log(\n                    f"WebView unexpected exit with healthy backend; reopening in 0.75s count={reopen_count}"\n                )\n                time.sleep(0.75)\n\n            with contextlib.suppress(Exception):\n'''
        text = replace_once(text, old, new, "WebView resilient loop")

    for marker in (
        "Framework7 WebView resilience v3.15",
        "WebView explicit closing event received",
        "WebView unexpected exit with healthy backend",
    ):
        if marker not in text:
            raise RuntimeError(f"WebView resilience marker missing after patch: {marker}")
    if "def _block_close_while_busy" in text:
        for marker in ("confirm_close=True", "_guarded_user_close", "decision = _block_close_while_busy()", "return False"):
            if marker not in text:
                raise RuntimeError(f"safe-close contract lost during resilience patch: {marker}")

    path.write_text(text, encoding="utf-8")
    compile(text, str(path), "exec")
    print("Framework7 WebView resilience v3.15 installed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
