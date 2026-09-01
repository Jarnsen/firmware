"""Keep the Framework7 Service overlay interactive while status is polled.

The parity panel used to replace its complete DOM every 1.5 seconds. A USB
hot-plug changes service status exactly while the user is interacting, which can
replace the button/select under the pointer between pointerdown and click. Keep
polling, but render only when data actually changes and never replace controls
while the user is actively interacting with the overlay.
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
        print("usage: patch_framework7_service_ui_stability_v315.py <parity-v35.js>", file=sys.stderr)
        return 2

    path = pathlib.Path(sys.argv[1])
    text = path.read_text(encoding="utf-8")
    if "serviceUiInteractionUntil" in text:
        print("Framework7 Service UI stability v3.15 already installed")
        return 0

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
    print("Framework7 Service UI stability v3.15 installed: controls survive polling and USB hot-plug")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
