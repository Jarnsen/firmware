"""Keep Service/Recovery interactive and audit the complete Framework7 wiring.

The Service panel used document-level click delegation while Framework7 owns the
global event pipeline. The panel is now patched for stable polling and then gets
direct local control handlers. This build step also performs a whole-tool software
contract audit: navigation views, JavaScript syntax, API routes and service/series
action wiring must all be present before an EXE can be produced.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one anchor, found {count}")
    return text.replace(old, new, 1)


def apply_stable_polling(path: pathlib.Path) -> None:
    text = path.read_text(encoding="utf-8")
    if "serviceUiInteractionUntil" in text:
        print("Framework7 Service UI stability v3.15 already installed")
        return

    text = replace_once(
        text,
        "  let poll = null;\n  let busy = false;\n",
        "  let poll = null;\n  let busy = false;\n  let lastRenderSignature = '';\n  let serviceUiInteractionUntil = 0;\n  let deferredRenderTimer = null;\n\n  function noteServiceInteraction() {\n    serviceUiInteractionUntil = Date.now() + 1400;\n  }\n\n  function renderSignature(nextStatus, nextState) {\n    const usb = (nextStatus?.usb || []).map(item => [item.device, item.identity, item.mapped_node_id]);\n    const serial = nextStatus?.serial || {};\n    const update = nextStatus?.app_update || {};\n    return JSON.stringify({\n      usb,\n      serial: [serial.active, serial.status, serial.bytes, serial.log_path, serial.tail],\n      update: [update.available, update.remote_version, update.url_ready],\n      critical: nextStatus?.critical || {},\n      security: nextStatus?.security_profiles || [],\n      nodes: (nextState?.nodes || []).map(node => [node.node_id, node.long_name, node.usb_reachable]),\n    });\n  }\n\n  function scheduleDeferredRender() {\n    if (deferredRenderTimer) return;\n    const delay = Math.max(120, serviceUiInteractionUntil - Date.now() + 40);\n    deferredRenderTimer = setTimeout(() => {\n      deferredRenderTimer = null;\n      if (!overlay || Date.now() < serviceUiInteractionUntil) { scheduleDeferredRender(); return; }\n      const signature = renderSignature(status, appState);\n      if (signature !== lastRenderSignature) {\n        render();\n        lastRenderSignature = signature;\n      }\n    }, delay);\n  }\n",
        "service UI interaction state",
    )

    text = replace_once(
        text,
        "  async function refresh() {\n    if (!overlay || busy || document.hidden) return;\n    busy = true;\n    try {\n      [status, appState] = await Promise.all([request('/api/service-status'), request('/api/state')]);\n      render();\n    } catch (error) {\n      toast(error.message || String(error), true);\n    } finally { busy = false; }\n  }\n",
        "  async function refresh() {\n    if (!overlay || busy || document.hidden) return;\n    busy = true;\n    try {\n      const [nextStatus, nextState] = await Promise.all([request('/api/service-status'), request('/api/state')]);\n      status = nextStatus;\n      appState = nextState;\n      const signature = renderSignature(status, appState);\n      if (signature !== lastRenderSignature) {\n        if (Date.now() < serviceUiInteractionUntil) {\n          scheduleDeferredRender();\n        } else {\n          render();\n          lastRenderSignature = signature;\n        }\n      }\n    } catch (error) {\n      toast(error.message || String(error), true);\n    } finally { busy = false; }\n  }\n",
        "non-destructive service refresh",
    )

    text = replace_once(
        text,
        "  function close() {\n    if (!overlay) return;\n    overlay.remove();\n    overlay = null;\n    if (poll) clearInterval(poll);\n    poll = null;\n  }\n",
        "  function close() {\n    if (!overlay) return;\n    overlay.remove();\n    overlay = null;\n    if (poll) clearInterval(poll);\n    poll = null;\n    if (deferredRenderTimer) clearTimeout(deferredRenderTimer);\n    deferredRenderTimer = null;\n    lastRenderSignature = '';\n  }\n",
        "service close cleanup",
    )

    text = replace_once(
        text,
        "    document.body.appendChild(overlay);\n    refresh();\n    poll = setInterval(refresh, 1500);\n",
        "    document.body.appendChild(overlay);\n    overlay.addEventListener('pointerdown', noteServiceInteraction, true);\n    overlay.addEventListener('mousedown', noteServiceInteraction, true);\n    overlay.addEventListener('touchstart', noteServiceInteraction, { capture: true, passive: true });\n    overlay.addEventListener('keydown', noteServiceInteraction, true);\n    overlay.addEventListener('input', noteServiceInteraction, true);\n    overlay.addEventListener('change', noteServiceInteraction, true);\n    refresh();\n    poll = setInterval(refresh, 2500);\n",
        "service interaction listeners and poll cadence",
    )
    path.write_text(text, encoding="utf-8")
    print("Framework7 Service UI stability v3.15 installed")


def apply_direct_service_events(root: pathlib.Path, parity: pathlib.Path) -> None:
    patcher = root / "patch_framework7_service_direct_events_v316.py"
    done = subprocess.run(
        [sys.executable, str(patcher), str(parity)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if done.stdout:
        print(done.stdout.strip())
    if done.returncode != 0:
        detail = (done.stderr or done.stdout or "unknown direct-event patch error").strip()
        raise RuntimeError(f"Framework7 Service direct events v3.16 failed: {detail}")


def functional_contract_audit(root: pathlib.Path) -> None:
    web = root / "service_tool_web"
    index = (web / "index.html").read_text(encoding="utf-8")
    js_names = (
        "app-v31.js",
        "map-settings-v32.js",
        "radio-auth-v33.js",
        "legacy-compat-v34.js",
        "parity-v35.js",
        "parity-enhance-v36.js",
        "series-v37.js",
        "version-v38.js",
        "service-cleanup-v39.js",
    )
    js_sources: dict[str, str] = {}
    for name in js_names:
        path = web / name
        if not path.is_file():
            raise RuntimeError(f"Functional audit: missing JavaScript asset {name}")
        source = path.read_text(encoding="utf-8")
        js_sources[name] = source
        checked = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True, timeout=30, check=False)
        if checked.returncode != 0:
            raise RuntimeError(f"Functional audit: {name} syntax error: {(checked.stderr or checked.stdout).strip()}")
        if name not in index:
            raise RuntimeError(f"Functional audit: index.html does not load {name}")

    expected_views = {"overview", "map", "live", "logs", "firmware", "series", "service", "details", "diagnostics", "settings"}
    actual_views = set(re.findall(r'data-view="([^"]+)"', index))
    if actual_views != expected_views:
        raise RuntimeError(f"Functional audit: navigation mismatch expected={sorted(expected_views)} actual={sorted(actual_views)}")
    combined_js = "\n".join(js_sources.values())
    for view in sorted(expected_views):
        if view not in combined_js:
            raise RuntimeError(f"Functional audit: no JavaScript wiring found for view {view}")

    parity = js_sources["parity-v35.js"]
    for marker in (
        "bindServiceControls",
        "data.localBound",
        "serviceUiInteractionUntil",
        "poll = setInterval(refresh, 2500)",
        "/api/service-status",
        "/api/service/action",
    ):
        if marker not in parity:
            raise RuntimeError(f"Functional audit: Service/Recovery marker missing: {marker}")

    python_names = (
        "JARNSEN_FRAMEWORK7_SERVICE_TOOL.py",
        "JARNSEN_FRAMEWORK7_FEATURES.py",
        "JARNSEN_FRAMEWORK7_RADIO_AUTH.py",
        "JARNSEN_FRAMEWORK7_LEGACY_COMPAT.py",
        "JARNSEN_FRAMEWORK7_PARITY.py",
        "JARNSEN_FRAMEWORK7_PARITY_FIXES.py",
        "JARNSEN_FRAMEWORK7_SERIES.py",
        "JARNSEN_FRAMEWORK7_HEADLESS_BOOT.py",
    )
    backend_parts = []
    for name in python_names:
        path = root / name
        if not path.is_file():
            raise RuntimeError(f"Functional audit: missing backend module {name}")
        backend_parts.append(path.read_text(encoding="utf-8"))
    backend = "\n".join(backend_parts)

    # Every API URL literally used by the browser must exist in backend routing.
    api_paths = sorted(set(re.findall(r"/api/[A-Za-z0-9_./-]+", combined_js)))
    missing_api = [path for path in api_paths if path not in backend]
    if missing_api:
        raise RuntimeError(f"Functional audit: frontend API paths missing in backend: {missing_api}")

    service_actions = sorted(set(re.findall(r'data-parity-action="([^"]+)"', parity)))
    missing_service = [action for action in service_actions if action not in backend]
    if missing_service:
        raise RuntimeError(f"Functional audit: Service actions missing in backend: {missing_service}")

    series = js_sources["series-v37.js"]
    for marker in ("seriesStart", "seriesCancel", "seriesTemplateSave", "seriesTemplateDelete", "/api/series/action"):
        if marker not in series:
            raise RuntimeError(f"Functional audit: series workflow marker missing: {marker}")

    # Guard against reintroducing the two failures observed on physical hardware.
    legacy = (root / "JARNSEN_FRAMEWORK7_LEGACY_COMPAT.py").read_text(encoding="utf-8")
    for marker in ("framework7-usb-discovery", "API request threads NEVER enumerate COM ports"):
        if marker not in legacy:
            raise RuntimeError(f"Functional audit: non-blocking USB guard missing: {marker}")

    print(
        "Framework7 full functional contract audit OK: "
        f"{len(expected_views)} views, {len(api_paths)} API paths, "
        f"{len(service_actions)} Service actions, {len(js_names)} JS modules"
    )


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_framework7_service_ui_stability_v315.py <parity-v35.js>", file=sys.stderr)
        return 2

    parity = pathlib.Path(sys.argv[1])
    root = parity.parent.parent
    apply_stable_polling(parity)
    apply_direct_service_events(root, parity)
    functional_contract_audit(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
