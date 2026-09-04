"""Performance/focus layer for the Framework7 desktop shell.

The first Framework7 preview was visually cleaner than Tk, but it still rebuilt the
main DOM every three seconds and polled the live display every 450 ms.  This layer
keeps the same behavior while reducing background work and avoiding full rerenders
when the visible state has not changed.
"""
from __future__ import annotations

import json
import time
import urllib.parse
from typing import Any


def install_performance_focus(base: Any) -> None:
    """Install low-overhead state caching and serve an optimized frontend runtime."""

    # A very short cache prevents duplicate /api/state work from UI refreshes that
    # arrive close together. Actions invalidate the cache immediately.
    original_state = base.LegacyBridge.state
    original_action = base.LegacyBridge.action

    def cached_state(self: Any) -> dict[str, Any]:
        now = time.monotonic()
        cached = getattr(self, "_framework7_state_cache", None)
        if cached and now - cached[0] < 1.25:
            return cached[1]
        value = original_state(self)
        self._framework7_state_cache = (now, value)
        return value

    def invalidating_action(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
        self._framework7_state_cache = None
        try:
            return original_action(self, payload)
        finally:
            self._framework7_state_cache = None

    base.LegacyBridge.state = cached_state
    base.LegacyBridge.action = invalidating_action

    previous_do_get = base.ApiHandler.do_GET

    old_fetch_state = """  async function fetchState() {
    try {
      const data = await request('/api/state');
      state.data = data;
      document.getElementById('visibleBleCount').textContent = data.summary?.ble ?? 0;
      const value = document.getElementById('connectionValue');
      value.textContent = data.busy ? data.status : 'BLE-Automatik aktiv';
      value.style.color = '';
      document.getElementById('connectionMeta').textContent = data.busy ? 'Vorgang läuft …' : 'USB → BLE · PIN 240180';
      if (state.selected && !getNode(state.selected)) state.selected = null;
      if (state.view === 'overview' || state.view === 'details' || state.view === 'firmware' || state.view === 'diagnostics' || state.view === 'settings') renderPage();
      else renderInspector();
      renderActivity();
    } catch (error) {
      const value = document.getElementById('connectionValue');
      value.textContent = 'Backend nicht erreichbar';
      value.style.color = 'var(--app-red)';
    }
  }
"""

    new_fetch_state = """  let _stateFetchInFlight = false;
  let _lastStateRenderKey = '';

  async function fetchState() {
    if (_stateFetchInFlight) return;
    _stateFetchInFlight = true;
    try {
      const data = await request('/api/state');
      state.data = data;
      document.getElementById('visibleBleCount').textContent = data.summary?.ble ?? 0;
      const value = document.getElementById('connectionValue');
      value.textContent = data.busy ? data.status : 'BLE-Automatik aktiv';
      value.style.color = '';
      document.getElementById('connectionMeta').textContent = data.busy ? 'Vorgang läuft …' : 'USB → BLE · PIN 240180';
      if (state.selected && !getNode(state.selected)) state.selected = null;

      const nodeKey = (data.nodes || []).map(node => [
        node.node_id, node.battery, node.ble_reachable, node.log_due, node.update,
        node.attention, node.captured_at, node.firmware, node.sync_state, node.warning_count,
        node.node_id === state.selected ? node.metrics : null,
      ]);
      const renderKey = JSON.stringify([
        state.view, state.selected, state.filter, state.search,
        data.busy, data.status, data.summary, nodeKey,
      ]);
      const changed = renderKey !== _lastStateRenderKey;

      if (changed) {
        if (state.view === 'overview' || state.view === 'details' || state.view === 'firmware' || state.view === 'diagnostics' || state.view === 'settings') renderPage();
        else renderInspector();
        _lastStateRenderKey = renderKey;
      }
      renderActivity();
    } catch (error) {
      const value = document.getElementById('connectionValue');
      value.textContent = 'Backend nicht erreichbar';
      value.style.color = 'var(--app-red)';
    } finally {
      _stateFetchInFlight = false;
    }
  }
"""

    def optimized_js() -> bytes:
        source_path = base._resource_path("service_tool_web/app-v31.js")
        source = source_path.read_text(encoding="utf-8")
        if old_fetch_state not in source:
            raise RuntimeError("Framework7 performance patch: fetchState anchor missing")
        source = source.replace(old_fetch_state, new_fetch_state, 1)
        source = source.replace(
            "state.liveTimer = setInterval(refreshLiveState, 450);",
            "state.liveTimer = setInterval(() => { if (!document.hidden) refreshLiveState(); }, 650);",
            1,
        )
        source = source.replace(
            "state.poll = setInterval(fetchState, 3000);",
            "state.poll = setInterval(() => { if (!document.hidden) fetchState(); }, 7000);\n  window.addEventListener('focus', () => fetchState());\n  document.addEventListener('visibilitychange', () => { if (!document.hidden) fetchState(); });",
            1,
        )
        return source.encode("utf-8")

    def do_GET(self: Any) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/ui/app-v31.js":
            return previous_do_get(self)
        try:
            data = optimized_js()
        except Exception as exc:  # noqa: BLE001
            body = json.dumps({"error": str(exc)}).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/javascript; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    base.ApiHandler.do_GET = do_GET
    base._framework7_optimized_js = optimized_js
