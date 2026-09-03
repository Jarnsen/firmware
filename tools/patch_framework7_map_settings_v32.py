"""Route Framework7 map/settings pages and validate additive service modules.

The large app-v31.js remains the proven shell. This build-time patch only renames
its legacy map/settings renderers and adds tiny delegating wrappers. If the new
module is ever missing the old renderer is still available as a fallback.

Because this script is already a mandatory Framework7 build step, it also performs
static validation for the additive v3.7 serial-series workflow. This keeps the
large PowerShell build stable while ensuring the new Python/JS/CSS modules cannot
silently disappear or ship with invalid JavaScript syntax.

It also hardens the Framework7 headless USB startup path. The packaged application
must be able to start with a Tracker/V3 already attached, and all startup/tool logs
must land below Downloads/Meshtastic-Logs/Tool-Logs.
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


def patch_usb_startup(root: pathlib.Path) -> None:
    runtime_path = root / "JARNSEN_FRAMEWORK7_RUNTIME_FIXES_V312.py"
    headless_path = root / "JARNSEN_FRAMEWORK7_HEADLESS_CORE.py"
    parity_path = root / "JARNSEN_FRAMEWORK7_PARITY_FIXES.py"
    for required in (runtime_path, headless_path, parity_path):
        if not required.is_file():
            raise RuntimeError(f"Framework7 USB startup source missing: {required}")

    runtime = runtime_path.read_text(encoding="utf-8")
    diagnostic_path = 'Downloads" / "Meshtastic-Logs" / "Tool-Logs" / f"Jarnsen-Service-Tool_{stamp}.log"'
    fixed_path = 'Downloads" / "Meshtastic-Logs" / "Tool-Logs" / "Jarnsen-Service-Tool-startup.log"'
    if diagnostic_path not in runtime and fixed_path not in runtime:
        old = '''    candidates: list[Path] = []\n    local = str(os.environ.get("LOCALAPPDATA") or "").strip()\n    if local:\n        candidates.append(Path(local) / "Jarnsen" / "NodeServiceTool" / "Jarnsen-Service-Tool-startup.log")\n    candidates.append(Path.home() / "Jarnsen-Service-Tool-startup.log")\n    candidates.append(Path.cwd() / "Jarnsen-Service-Tool-startup.log")\n'''
        new = '''    candidates: list[Path] = [\n        Path.home() / "Downloads" / "Meshtastic-Logs" / "Tool-Logs" / "Jarnsen-Service-Tool-startup.log",\n    ]\n    local = str(os.environ.get("LOCALAPPDATA") or "").strip()\n    if local:\n        candidates.append(Path(local) / "Jarnsen" / "NodeServiceTool" / "Jarnsen-Service-Tool-startup.log")\n    candidates.append(Path.home() / "Jarnsen-Service-Tool-startup.log")\n    candidates.append(Path.cwd() / "Jarnsen-Service-Tool-startup.log")\n'''
        runtime = replace_once(runtime, old, new, "startup log directory")
        runtime_path.write_text(runtime, encoding="utf-8")

    headless = headless_path.read_text(encoding="utf-8")
    if "def set_result(self, text: Any)" not in headless and "def set_result(self, text: str)" not in headless:
        anchor = '''    def set_status(self, text: str, level: str = "normal") -> None:\n        self.status_text_var.set(str(text or ""))\n        self.status_level = str(level or "normal")\n\n'''
        replacement = anchor + '''    def set_result(self, text: Any) -> None:\n        self.last_result = str(text or "")\n        result = self.__dict__.get("result_text")\n        if result is not None:\n            with contextlib.suppress(Exception):\n                result.delete("1.0", "end")\n                result.insert("end", self.last_result)\n\n'''
        headless = replace_once(headless, anchor, replacement, "headless set_result")

    marker = '''            self.status_text_var = HeadlessValue("Bereit")\n            self.status_var = self.status_text_var\n'''
    if "self.auto_usb_log_var = HeadlessValue(True)" not in headless:
        replacement = marker + '''            self.auto_usb_log_var = HeadlessValue(True)\n            self._auto_usb_seen: set[str] = set()\n            self._auto_usb_last_poll = 0.0\n            self.start_button = HeadlessLabel("Start")\n            self.cancel_button = HeadlessLabel("Abbrechen")\n            self.result_text = HeadlessText()\n            self.last_result = ""\n'''
        headless = replace_once(headless, marker, replacement, "headless USB controls")
    headless_path.write_text(headless, encoding="utf-8")

    parity = parity_path.read_text(encoding="utf-8")
    old_output = '            output = pathlib.Path(legacy.output_directory())\n            output.mkdir(parents=True, exist_ok=True)\n'
    new_output = '            output = pathlib.Path(legacy.output_directory()) / "Tool-Logs"\n            output.mkdir(parents=True, exist_ok=True)\n'
    if 'pathlib.Path(legacy.output_directory()) / "Tool-Logs"' not in parity:
        count = parity.count(old_output)
        if count != 2:
            raise RuntimeError(f"tool log directory: expected two output anchors, found {count}")
        parity = parity.replace(old_output, new_output)
        parity_path.write_text(parity, encoding="utf-8")

    runtime_check = runtime_path.read_text(encoding="utf-8")
    headless_check = headless_path.read_text(encoding="utf-8")
    parity_check = parity_path.read_text(encoding="utf-8")
    if 'Meshtastic-Logs" / "Tool-Logs"' not in runtime_check:
        raise RuntimeError("Framework7 USB startup hardening marker missing: startup log path")
    for marker_text, source, label in (
        ("self.auto_usb_log_var = HeadlessValue(True)", headless_check, "USB auto-log state"),
        ("self.start_button = HeadlessLabel", headless_check, "USB start control"),
        ('pathlib.Path(legacy.output_directory()) / "Tool-Logs"', parity_check, "service log path"),
    ):
        if marker_text not in source:
            raise RuntimeError(f"Framework7 USB startup hardening marker missing: {label}")
    if "def set_result(self, text: Any)" not in headless_check and "def set_result(self, text: str)" not in headless_check:
        raise RuntimeError("Framework7 USB startup hardening marker missing: headless result sink")
    print("Framework7 USB-attached startup + Tool-Logs hardening installed")


def patch_bridge_mapping_access(root: pathlib.Path) -> None:
    """Remove the remaining mapping-style .get crash from the base bridge."""
    path = root / "JARNSEN_FRAMEWORK7_SERVICE_TOOL.py"
    text = path.read_text(encoding="utf-8")
    safe_marker = 'sync_get = getattr(sync_store, "get", None)'
    if safe_marker in text:
        print("Framework7 callable mapping guard already installed")
        return
    text = replace_once(
        text,
        '        sync_state = str(getattr(self.tool, "node_sync_state_v2132", {}).get(node_id) or "")\n',
        '        sync_store = getattr(self.tool, "node_sync_state_v2132", {})\n'
        '        sync_get = getattr(sync_store, "get", None)\n'
        '        sync_state = str(sync_get(node_id) or "") if callable(sync_get) else ""\n',
        "node sync mapping-safe get",
    )
    path.write_text(text, encoding="utf-8")
    compile(text, str(path), "exec")
    print("Framework7 callable mapping access hardened")


def patch_usb_transport_ui(path: pathlib.Path) -> None:
    """Make Overview/Details use the effective USB-first transport, not BLE alone."""
    text = path.read_text(encoding="utf-8")
    if "function nodeConnection(node)" in text:
        print("Framework7 USB-first transport UI already installed")
        return

    helper = """  function nodeConnection(node) {
    if (node?.usb_reachable) {
      const port = node.usb?.device ? ` · ${node.usb.device}` : '';
      return { online: true, transport: 'USB', chip: `USB${port}`, fact: node.usb?.device || 'USB verbunden' };
    }
    if (node?.ble_reachable) return { online: true, transport: 'BLE', chip: 'BLE erreichbar', fact: 'BLE erreichbar' };
    return { online: false, transport: 'Offline', chip: 'Offline', fact: 'Nicht verbunden' };
  }

"""
    text = replace_once(text, "  function filteredNodes() {\n", helper + "  function filteredNodes() {\n", "transport helper")
    text = replace_once(text, "      if (state.filter === 'ble' && !node.ble_reachable) return false;\n", "      if (state.filter === 'ble' && !nodeConnection(node).online) return false;\n", "connected filter")
    text = replace_once(text, "  function nodeCard(node) {\n    const selected = state.selectedSet.has(node.node_id);\n", "  function nodeCard(node) {\n    const connection = nodeConnection(node);\n    const selected = state.selectedSet.has(node.node_id);\n", "node card transport")
    text = replace_once(text, "      chip(node.ble_reachable ? 'In Reichweite' : 'Offline', node.ble_reachable ? 'green' : ''),\n", "      chip(connection.chip, connection.online ? 'green' : ''),\n", "node card connection chip")
    text = replace_once(text, '          <div><div class="fact-label">BLE</div><div class="fact-value">${node.ble_reachable ? \'Erreichbar\' : \'Nicht sichtbar\'}</div></div>\n', '          <div><div class="fact-label">Verbindung</div><div class="fact-value">${esc(connection.fact)}</div></div>\n', "node card connection fact")
    text = replace_once(text, '        <div class="sync-line"><span class="status-dot ${node.ble_reachable ? \'ok\' : node.log_due ? \'warn\' : \'\'}"></span>${esc(node.sync_state || (node.log_due ? \'Log wartet auf Synchronisierung\' : \'Synchronisiert\'))}</div>\n', '        <div class="sync-line"><span class="status-dot ${connection.online ? \'ok\' : node.log_due ? \'warn\' : \'\'}"></span>${esc(node.sync_state || (node.log_due ? \'Log wartet auf Synchronisierung\' : \'Synchronisiert\'))}</div>\n', "node card connection dot")
    text = replace_once(text, "  function renderOverview() {\n    const s = state.data?.summary || { nodes: 0, ble: 0, logs_due: 0, updates: 0, warnings: 0 };\n    const nodes = filteredNodes();\n    pageHost.innerHTML = `\n", "  function renderOverview() {\n    const s = state.data?.summary || { nodes: 0, ble: 0, logs_due: 0, updates: 0, warnings: 0 };\n    const nodes = filteredNodes();\n    const connectedCount = (state.data?.nodes || []).filter(node => nodeConnection(node).online).length;\n    pageHost.innerHTML = `\n", "overview connected count")
    text = replace_once(text, '        <div class="kpi-card"><div class="kpi-icon green">⌁</div><div><div class="kpi-label">BLE in Reichweite</div><div class="kpi-value">${s.ble}</div><div class="kpi-meta">Aktuell sichtbar</div></div></div>\n', '        <div class="kpi-card"><div class="kpi-icon green">⌁</div><div><div class="kpi-label">Verbunden</div><div class="kpi-value">${connectedCount}</div><div class="kpi-meta">USB bevorzugt · BLE Fallback</div></div></div>\n', "overview connection KPI")
    text = replace_once(text, "${[['all','Alle'],['ble','In Reichweite'],['due','Logs fällig'],['updates','Updates'],['warnings','Warnungen']].map", "${[['all','Alle'],['ble','Verbunden'],['due','Logs fällig'],['updates','Updates'],['warnings','Warnungen']].map", "overview connected filter label")
    text = replace_once(text, "Filter oder Suche ändern – oder BLE erneut prüfen.", "Filter oder Suche ändern – oder Verbindung erneut prüfen.", "overview empty connection copy")
    text = replace_once(text, '    inspector.innerHTML = `\n      <div class="inspector-head">', '    const connection = nodeConnection(node);\n    inspector.innerHTML = `\n      <div class="inspector-head">', "inspector transport")
    text = replace_once(text, '      <div class="chip-row">${chip(node.device_label, \'blue\')}${chip(node.ble_reachable ? \'In Reichweite\' : \'Offline\', node.ble_reachable ? \'green\' : \'\')}${chip(node.log_due ? \'Log fällig\' : \'Log aktuell\', node.log_due ? \'orange\' : \'green\')}</div>\n', '      <div class="chip-row">${chip(node.device_label, \'blue\')}${chip(connection.chip, connection.online ? \'green\' : \'\')}${chip(node.log_due ? \'Log fällig\' : \'Log aktuell\', node.log_due ? \'orange\' : \'green\')}</div>\n', "inspector connection chip")
    text = replace_once(text, '      <div class="inspector-section-title">BLE & Log-Automatik</div><div class="auto-panel"><div class="auto-row"><span>BLE</span><strong>${node.ble_reachable ? \'Erkannt\' : \'Nicht in Reichweite\'}</strong></div>', '      <div class="inspector-section-title">Verbindung & Log-Automatik</div><div class="auto-panel"><div class="auto-row"><span>Transport</span><strong>${esc(connection.fact)}</strong></div>', "inspector connection panel")
    text = replace_once(text, "  function renderDetails() {\n    const node = getNode(state.selected);\n    if (!node) return emptyPage('Node-Details', 'Wähle zuerst eine Node aus der Übersicht aus.');\n    const metrics = node.metrics || {};\n", "  function renderDetails() {\n    const node = getNode(state.selected);\n    if (!node) return emptyPage('Node-Details', 'Wähle zuerst eine Node aus der Übersicht aus.');\n    const metrics = node.metrics || {};\n    const connection = nodeConnection(node);\n", "details transport")
    text = replace_once(text, '<div class="chip-row">${chip(node.ble_reachable ? \'In Reichweite\' : \'Offline\', node.ble_reachable ? \'green\' : \'\')}${chip(node.log_due ? \'Log fällig\' : \'Log aktuell\', node.log_due ? \'orange\' : \'green\')}${node.update ? chip(\'Update verfügbar\', \'purple\') : \'\'}</div>', '<div class="chip-row">${chip(connection.chip, connection.online ? \'green\' : \'\')}${chip(node.log_due ? \'Log fällig\' : \'Log aktuell\', node.log_due ? \'orange\' : \'green\')}${node.update ? chip(\'Update verfügbar\', \'purple\') : \'\'}</div>', "details connection chip")
    text = replace_once(text, "      document.getElementById('visibleBleCount').textContent = data.summary?.ble ?? 0;\n      const value = document.getElementById('connectionValue');\n", "      const connected = (data.nodes || []).filter(node => nodeConnection(node).online).length;\n      document.getElementById('visibleBleCount').textContent = connected;\n      const value = document.getElementById('connectionValue');\n      const uniqueUsb = data.connections?.unique_usb;\n", "header connected count")
    text = replace_once(text, "      value.textContent = data.busy ? data.status : 'BLE-Automatik aktiv';\n", "      value.textContent = data.busy ? data.status : uniqueUsb ? `USB ${uniqueUsb.device} aktiv` : connected ? 'Verbindung bereit' : 'Keine Node verbunden';\n", "header connection value")
    text = replace_once(text, "      document.getElementById('connectionMeta').textContent = data.busy ? 'Vorgang läuft …' : 'USB → BLE · PIN 240180';\n", "      document.getElementById('connectionMeta').textContent = data.busy ? 'Vorgang läuft …' : uniqueUsb ? 'USB aktiv · BLE Fallback' : 'USB → BLE · PIN 240180';\n", "header connection meta")
    text = replace_once(text, "BLE-Scans, Pairing, Logdownloads, Profile und OTA erscheinen hier.", "USB/BLE-Erkennung, Pairing, Logdownloads, Profile und OTA erscheinen hier.", "activity transport copy")
    path.write_text(text, encoding="utf-8")
    print("Framework7 USB-first transport UI installed")


def patch_serial_service_input(root: pathlib.Path) -> None:
    """Preserve serial command draft and CR/LF choice across Service rerenders."""
    path = root / "service_tool_web" / "parity-v35.js"
    text = path.read_text(encoding="utf-8")
    if "previousSerialCommand" in text:
        print("Framework7 serial command preservation already installed")
        return
    text = replace_once(
        text,
        "    const previousProfile = selected('paritySecurityProfile');\n",
        "    const previousProfile = selected('paritySecurityProfile');\n"
        "    const previousSerialCommand = overlay.querySelector('#paritySerialCommand')?.value || '';\n"
        "    const previousSerialNewline = overlay.querySelector('#paritySerialNewline')?.checked ?? true;\n",
        "serial command draft capture",
    )
    text = replace_once(
        text,
        "    const baud = overlay.querySelector('#parityBaud'); if (baud) baud.value = previousBaud;\n"
        "    const profile = overlay.querySelector('#paritySecurityProfile');\n",
        "    const baud = overlay.querySelector('#parityBaud'); if (baud) baud.value = previousBaud;\n"
        "    const serialCommand = overlay.querySelector('#paritySerialCommand'); if (serialCommand) serialCommand.value = previousSerialCommand;\n"
        "    const serialNewline = overlay.querySelector('#paritySerialNewline'); if (serialNewline) serialNewline.checked = previousSerialNewline;\n"
        "    const profile = overlay.querySelector('#paritySecurityProfile');\n",
        "serial command draft restore",
    )
    path.write_text(text, encoding="utf-8")
    print("Framework7 serial command preservation installed")


def validate_additional_web_modules(root: pathlib.Path) -> None:
    """Cover the late-loaded BLE popup that the older functional audit omitted."""
    web = root / "service_tool_web"
    index = (web / "index.html").read_text(encoding="utf-8")
    for name in ("ble-popup-v319.js",):
        path = web / name
        if not path.is_file():
            raise RuntimeError(f"Framework7 additional UI asset missing: {name}")
        if name not in index:
            raise RuntimeError(f"Framework7 index.html does not load {name}")
        checked = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True, timeout=30, check=False)
        if checked.returncode != 0:
            detail = (checked.stderr or checked.stdout or "unknown JavaScript syntax error").strip()
            raise RuntimeError(f"{name} syntax validation failed: {detail}")
    print("Framework7 late-loaded UI module validation OK")


def run_patcher(patcher: pathlib.Path, target: pathlib.Path, label: str, markers: tuple[str, ...]) -> None:
    completed = subprocess.run([sys.executable, str(patcher), str(target)], capture_output=True, text=True, timeout=30, check=False)
    if completed.stdout:
        print(completed.stdout.strip())
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or f"unknown {label} patch error").strip()
        raise RuntimeError(f"{label} failed: {detail}")
    source = target.read_text(encoding="utf-8")
    for marker in markers:
        if marker not in source:
            raise RuntimeError(f"{label} marker missing: {marker}")


def apply_nonblocking_usb_cache(root: pathlib.Path) -> None:
    target = root / "JARNSEN_FRAMEWORK7_LEGACY_COMPAT.py"
    run_patcher(root / "patch_framework7_usb_cache_v314.py", target, "Framework7 USB cache v3.14", ("_framework7_usb_refresh_worker", "framework7-usb-discovery"))
    source = target.read_text(encoding="utf-8")
    invariant_markers = ("API request threads NEVER enumerate COM ports", "Never enumerate COM ports on an API request thread")
    if not any(marker in source for marker in invariant_markers):
        raise RuntimeError("Framework7 USB cache v3.14 marker missing: nonblocking API/COM invariant")


def apply_webview_resilience(root: pathlib.Path) -> None:
    run_patcher(root / "patch_framework7_webview_resilience_v315.py", root / "JARNSEN_FRAMEWORK7_RUNTIME_FIXES_V312.py", "Framework7 WebView resilience v3.15", ("Framework7 WebView resilience v3.15", "WebView explicit closing event received", "WebView unexpected exit with healthy backend"))


def apply_service_ui_stability(root: pathlib.Path) -> None:
    run_patcher(root / "patch_framework7_service_ui_stability_v315.py", root / "service_tool_web" / "parity-v35.js", "Framework7 Service UI stability v3.15", ("serviceUiInteractionUntil", "renderSignature", "poll = setInterval(refresh, 2500)", "previousSerialCommand"))


def validate_series(root: pathlib.Path) -> None:
    series_py = root / "JARNSEN_FRAMEWORK7_SERIES.py"
    series_js = root / "service_tool_web" / "series-v37.js"
    series_css = root / "service_tool_web" / "series-v37.css"
    index = root / "service_tool_web" / "index.html"
    for path in (series_py, series_js, series_css, index):
        if not path.is_file():
            raise RuntimeError(f"Framework7 series asset missing: {path}")
    py_source = series_py.read_text(encoding="utf-8")
    compile(py_source, str(series_py), "exec")
    for marker in ("def install_series(", 'critical["series_provisioning"]', '"/api/series/status"', '"/api/series/action"', '"/api/series/github"', "_framework7_series_bundle_override", "postcondition_verify"):
        if marker not in py_source:
            raise RuntimeError(f"Framework7 series backend marker missing: {marker}")
    js_source = series_js.read_text(encoding="utf-8")
    for marker in ("/api/series/status", "/api/series/action", "/api/series/github", "seriesFirmwareSource", "seriesTemplateSave", "seriesTemplateDelete", "seriesStart", "seriesCancel", "seriesLocalFile", "SHA-256", "Soll/Ist", "Neue Nodes / Serienbereitstellung"):
        if marker not in js_source:
            raise RuntimeError(f"Framework7 series UI marker missing: {marker}")
    css_source = series_css.read_text(encoding="utf-8")
    for marker in (".series-page", ".series-grid", ".series-job-card", ".series-result"):
        if marker not in css_source:
            raise RuntimeError(f"Framework7 series CSS marker missing: {marker}")
    html = index.read_text(encoding="utf-8")
    for marker in ('data-view="series"', 'href="series-v37.css"', 'src="series-v37.js"'):
        if marker not in html:
            raise RuntimeError(f"Framework7 series index wiring missing: {marker}")
    checked = subprocess.run(["node", "--check", str(series_js)], capture_output=True, text=True, timeout=30, check=False)
    if checked.returncode != 0:
        detail = (checked.stderr or checked.stdout or "unknown JavaScript syntax error").strip()
        raise RuntimeError(f"series-v37.js syntax validation failed: {detail}")
    print("Framework7 series v3.7 validation OK")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: patch_framework7_map_settings_v32.py <app-v31.js>", file=sys.stderr)
        return 2
    path = pathlib.Path(sys.argv[1])
    text = path.read_text(encoding="utf-8")
    if "JarnsenMapSettings.renderMap" not in text:
        text = replace_once(text, "  async function renderMap() {", "  async function renderMapLegacy() {", "map renderer")
        text = replace_once(text, "  function renderSettings() {", "  function renderSettingsLegacy() {", "settings renderer")
        anchor = "  function emptyPage(title, text) {"
        wrapper = """  async function renderMap() {
    if (window.JarnsenMapSettings && typeof window.JarnsenMapSettings.renderMap === 'function') {
      return window.JarnsenMapSettings.renderMap({ app, state, request, pageHost, esc, chip, getNode, VERSION, toast, apiAction, renderPage });
    }
    return renderMapLegacy();
  }

  function renderSettings() {
    if (window.JarnsenMapSettings && typeof window.JarnsenMapSettings.renderSettings === 'function') {
      return window.JarnsenMapSettings.renderSettings({ app, state, request, pageHost, esc, chip, getNode, VERSION, toast, apiAction, renderPage });
    }
    return renderSettingsLegacy();
  }

"""
        text = replace_once(text, anchor, wrapper + anchor, "wrapper insertion")
        path.write_text(text, encoding="utf-8")
        print("Framework7 enhanced map/settings routing installed")
    else:
        print("Framework7 map/settings v3.2 delegation already present")
    root = path.parent.parent
    patch_bridge_mapping_access(root)
    patch_usb_transport_ui(path)
    patch_usb_startup(root)
    apply_nonblocking_usb_cache(root)
    apply_webview_resilience(root)
    patch_serial_service_input(root)
    apply_service_ui_stability(root)
    validate_additional_web_modules(root)
    validate_series(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
