(() => {
  'use strict';

  const params = new URLSearchParams(location.search);
  const API = params.get('api') || 'http://127.0.0.1:0';
  const TOKEN = params.get('token') || '';
  const VERSION = params.get('version') || '3.1.1b';
  const pageHost = document.getElementById('pageHost');
  const mainColumn = document.querySelector('.main-column');
  const searchInput = document.getElementById('globalSearch');
  if (!pageHost || !mainColumn) return;

  let snapshot = null;
  let busy = false;
  let lastSignature = '';
  const selectedIds = new Set();

  const esc = value => String(value ?? '')
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;').replaceAll("'", '&#039;');

  const num = value => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  };

  function mode() {
    return document.body.dataset.redesignPage || 'dashboard';
  }

  async function request(path) {
    const response = await fetch(`${API}${path}`, {
      headers: { 'X-Jarnsen-Token': TOKEN },
      cache: 'no-store',
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
    return body;
  }

  function usbTargets() {
    return Array.isArray(snapshot?.connections?.usb) ? snapshot.connections.usb : [];
  }

  function usbTargetFor(node) {
    const id = String(node?.node_id || '').toLowerCase();
    return usbTargets().find(target => String(target?.mapped_node_id || '').toLowerCase() === id) || null;
  }

  function transport(node) {
    const usb = usbTargetFor(node);
    if (usb) return { label: 'USB', detail: usb.device || 'seriell', tone: 'usb' };
    if (node?.ble_reachable) return { label: 'BLE', detail: 'verbunden', tone: 'ble' };
    return { label: 'Offline', detail: 'nicht erreichbar', tone: 'offline' };
  }

  function voltage(node) {
    const candidates = [
      node?.voltage,
      node?.battery_voltage,
      node?.metrics?.voltage,
      node?.metrics?.battery_voltage,
      node?.metrics?.battery_voltage_mv ? Number(node.metrics.battery_voltage_mv) / 1000 : null,
    ];
    const value = candidates.map(num).find(item => item !== null);
    return value === undefined ? null : value;
  }

  function position(node) {
    const p = node?.position || node?.metrics?.position || {};
    const lat = [node?.latitude, node?.lat, p.latitude, p.lat, node?.metrics?.latitude].map(num).find(v => v !== null);
    const lon = [node?.longitude, node?.lon, p.longitude, p.lon, node?.metrics?.longitude].map(num).find(v => v !== null);
    if (lat === undefined || lon === undefined) return '—';
    return `${lat.toFixed(4)} / ${lon.toFixed(4)}`;
  }

  function formatTime(value) {
    if (!value) return '—';
    const date = new Date(String(value).replace(' ', 'T'));
    if (Number.isNaN(date.getTime())) return String(value).slice(0, 16);
    const diff = Math.max(0, Date.now() - date.getTime());
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'gerade eben';
    if (mins < 60) return `vor ${mins} min`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `vor ${hours} h`;
    return new Intl.DateTimeFormat('de-DE', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }).format(date);
  }

  function status(node) {
    if (node?.attention) return { label: 'Hinweis', tone: 'warning' };
    if (node?.update) return { label: 'Update', tone: 'update' };
    if (node?.ble_reachable || usbTargetFor(node)) return { label: 'Online', tone: 'online' };
    return { label: 'Offline', tone: 'offline' };
  }

  function filteredNodes() {
    const q = String(searchInput?.value || '').trim().toLowerCase();
    const nodes = Array.isArray(snapshot?.nodes) ? snapshot.nodes : [];
    if (!q) return nodes;
    return nodes.filter(node => [node.long_name, node.short_name, node.node_id, node.device_label, node.firmware]
      .some(value => String(value || '').toLowerCase().includes(q)));
  }

  function selectedFromInspector() {
    const text = String(document.querySelector('.inspector-sub')?.textContent || '');
    return text.match(/![0-9a-f]{8,}/i)?.[0] || '';
  }

  function syncSelectedFromCanonical() {
    const canonical = [...pageHost.querySelectorAll('.node-card.selected[data-node]')]
      .map(card => card.getAttribute('data-node')).filter(Boolean);
    if (!canonical.length && pageHost.querySelector('.node-grid')) selectedIds.clear();
    canonical.forEach(id => selectedIds.add(id));
  }

  function summary() {
    const nodes = Array.isArray(snapshot?.nodes) ? snapshot.nodes : [];
    const usb = nodes.filter(node => Boolean(usbTargetFor(node))).length;
    const ble = nodes.filter(node => node.ble_reachable && !usbTargetFor(node)).length;
    const online = nodes.filter(node => node.ble_reachable || usbTargetFor(node)).length;
    const sleeping = nodes.filter(node => /sleep/i.test(String(node.sync_state || node.status || ''))).length;
    const logs = nodes.filter(node => node.log_due).length;
    const issues = nodes.filter(node => node.attention || node.update).length;
    return { total: nodes.length, usb, ble, online, sleeping, logs, issues };
  }

  function connectionPill(node) {
    const item = transport(node);
    return `<span class="v323-pill ${item.tone}"><i></i>${esc(item.label)}<small>${esc(item.detail)}</small></span>`;
  }

  function statusPill(node) {
    const item = status(node);
    return `<span class="v323-status ${item.tone}"><i></i>${esc(item.label)}</span>`;
  }

  function battery(node) {
    const percent = num(node?.battery);
    const volts = voltage(node);
    return `<div class="v323-battery"><strong>${percent === null ? '—' : `${Math.round(percent)} %`}</strong><small>${volts === null ? '' : `${volts.toFixed(2)} V`}</small></div>`;
  }

  function nodeRow(node) {
    const selected = selectedIds.has(node.node_id);
    const current = selectedFromInspector().toLowerCase() === String(node.node_id || '').toLowerCase();
    return `
      <div class="v323-node-row${current ? ' current' : ''}" data-v323-node="${esc(node.node_id)}">
        <div class="v323-check-cell"><button class="v323-check${selected ? ' selected' : ''}" data-action="select" data-node="${esc(node.node_id)}" aria-label="${selected ? 'Auswahl entfernen' : 'Node auswählen'}">${selected ? '✓' : ''}</button></div>
        <button class="v323-node-identity" data-action="inspect" data-node="${esc(node.node_id)}">
          <strong>${esc(node.long_name || node.node_id)}</strong>
          <span>${esc(node.node_id)} · ${esc(node.device_label || node.short_name || 'Node')}</span>
        </button>
        <div>${connectionPill(node)}</div>
        <div>${battery(node)}</div>
        <div class="v323-firmware"><strong>${esc(node.firmware || '—')}</strong><small>${esc(node.build || node.firmware_build || '')}</small></div>
        <div>${statusPill(node)}</div>
        <div class="v323-position"><strong>${esc(position(node))}</strong><small>${esc(formatTime(node.position_at || node.last_position_at || node.captured_at))}</small></div>
        <div class="v323-row-actions">
          <button class="primary" data-action="inspect" data-node="${esc(node.node_id)}">Öffnen</button>
          <button data-action="log" data-node="${esc(node.node_id)}" title="Log laden">▤</button>
          <button data-action="live-view" data-node="${esc(node.node_id)}" title="Live-Ansicht">▣</button>
          <button data-action="ota" data-node="${esc(node.node_id)}" title="OTA">⬡</button>
        </div>
      </div>`;
  }

  function nodeTable(nodes) {
    return `
      <section class="v323-table-shell">
        <div class="v323-node-table v323-table-head">
          <div></div><div>Node / Name</div><div>Verbindung</div><div>Akku</div><div>Firmware</div><div>Status</div><div>Letzte Position</div><div>Aktionen</div>
        </div>
        <div class="v323-table-body">
          ${nodes.length ? nodes.map(nodeRow).join('') : '<div class="v323-empty">Keine Nodes für die aktuelle Suche gefunden.</div>'}
        </div>
      </section>`;
  }

  function metric(icon, value, label, meta, tone = '') {
    return `<div class="v323-metric ${tone}"><span>${icon}</span><div><strong>${esc(value)}</strong><b>${esc(label)}</b><small>${esc(meta)}</small></div></div>`;
  }

  function renderNodes() {
    if (!snapshot || mode() !== 'nodes') return;
    syncSelectedFromCanonical();
    const s = summary();
    const nodes = filteredNodes();
    const key = `nodes:${JSON.stringify([snapshot?.updated_at, nodes.map(n => [n.node_id,n.battery,n.ble_reachable,n.log_due,n.update,n.captured_at]), [...selectedIds], searchInput?.value])}`;
    if (pageHost.querySelector('.rd-v323-nodes') && pageHost.dataset.v323Key === key) return;
    pageHost.dataset.v323Key = key;
    pageHost.innerHTML = `
      <div class="rd-v323-shell rd-v323-nodes">
        <header class="v323-page-head">
          <div><span class="v323-eyebrow">GERÄTEVERWALTUNG</span><h1>Nodes</h1><p>Alle gefundenen Mesh-Geräte verwalten, überwachen und konfigurieren.</p></div>
          <div class="v323-head-actions"><button data-page-action="refresh">↻ Aktualisieren</button><button class="primary" id="v323ScanMirror">⌁ Scannen</button></div>
        </header>
        <div class="v323-metrics">
          ${metric('◫', s.total, 'Nodes gesamt', `${s.online} erreichbar`, 'blue')}
          ${metric('●', s.online, 'Online', s.sleeping ? `${s.sleeping} im Sleep` : 'aktuell erreichbar', 'green')}
          ${metric('USB', s.usb, 'Über USB', s.usb ? 'bevorzugter Serviceweg' : 'kein USB-Gerät', 'blue')}
          ${metric('BLE', s.ble, 'Über BLE', s.ble ? 'verbunden / sichtbar' : 'kein BLE-Ziel', 'purple')}
        </div>
        <div class="v323-section-bar"><div><strong>Gefundene Nodes</strong><span>${nodes.length} angezeigt · USB wird immer bevorzugt</span></div><div class="v323-inline-actions"><button data-v323-view="logs">Log / Diagnose</button><button data-v323-view="firmware">Firmware</button><button data-v323-view="power">Power</button></div></div>
        ${nodeTable(nodes)}
        <div class="v323-bulkbar"><strong>${selectedIds.size} ausgewählt</strong><span></span><button class="primary" data-bulk="download_log">Logs laden</button><button data-bulk="ota">Firmware Update</button><button data-v323-view="service">Konfigurieren</button><button data-bulk="wake">Neustarten / Wecken</button>${selectedIds.size ? '<button class="danger" data-bulk="delete">Ausgewählte entfernen</button>' : ''}</div>
      </div>`;
  }

  function activityRows(nodes) {
    const rows = [...nodes]
      .sort((a,b) => String(b.captured_at || '').localeCompare(String(a.captured_at || '')))
      .slice(0, 5);
    if (!rows.length) return '<div class="v323-empty small">Noch keine Aktivität verfügbar.</div>';
    return rows.map(node => `<button class="v323-activity-row" data-action="inspect" data-node="${esc(node.node_id)}"><i class="${status(node).tone}"></i><span><strong>${esc(node.long_name || node.node_id)}</strong><small>${esc(node.sync_state || (node.log_due ? 'Log fällig' : 'Bereit'))}</small></span><time>${esc(formatTime(node.captured_at))}</time></button>`).join('');
  }

  function renderDashboard() {
    if (!snapshot || mode() !== 'dashboard') return;
    const s = summary();
    const nodes = filteredNodes();
    const key = `dashboard:${JSON.stringify([snapshot?.updated_at, nodes.map(n => [n.node_id,n.battery,n.ble_reachable,n.log_due,n.update,n.captured_at]), searchInput?.value])}`;
    if (pageHost.querySelector('.rd-v323-dashboard') && pageHost.dataset.v323Key === key) return;
    pageHost.dataset.v323Key = key;
    pageHost.innerHTML = `
      <div class="rd-v323-shell rd-v323-dashboard">
        <header class="v323-dashboard-title">
          <div><span class="v323-eyebrow">JARNSEN SERVICE TOOL</span><h1>Übersicht</h1><p>Zentrale Wartung, Diagnose und Firmwareverwaltung für deine Nodes.</p></div>
          <div class="v323-ready"><i></i><span><strong>${s.issues ? `${s.issues} Hinweise` : 'System bereit'}</strong><small>v${esc(VERSION)} · USB → BLE</small></span></div>
        </header>
        <div class="v323-metrics dashboard">
          ${metric('◫', s.total, 'Nodes', `${s.online} erreichbar`, 'blue')}
          ${metric('USB', s.usb, 'USB', s.usb ? 'seriell bevorzugt' : 'nicht verbunden', 'blue')}
          ${metric('▤', s.logs, 'Logs fällig', s.logs ? 'Download empfohlen' : 'alles aktuell', s.logs ? 'orange' : 'green')}
          ${metric('!', s.issues, 'Hinweise', s.issues ? 'prüfen' : 'keine offenen Punkte', s.issues ? 'orange' : 'green')}
        </div>
        <div class="v323-dashboard-grid">
          <section class="v323-panel v323-nodes-preview"><div class="v323-panel-head"><div><span class="v323-eyebrow">NODES</span><h2>Geräte im Blick</h2></div><button data-v323-view="nodes">Alle Nodes öffnen</button></div>${nodeTable(nodes.slice(0,4))}</section>
          <aside class="v323-side-stack">
            <section class="v323-panel"><div class="v323-panel-head"><div><span class="v323-eyebrow">SCHNELLZUGRIFF</span><h2>Serviceaktionen</h2></div></div><div class="v323-quick-grid"><button data-v323-view="logs"><span>▤</span><strong>Logs & Diagnose</strong></button><button data-v323-view="firmware"><span>⬡</span><strong>Firmware</strong></button><button data-v323-view="power"><span>ϟ</span><strong>Power</strong></button><button data-v323-view="service"><span>◈</span><strong>Profile</strong></button><button data-v323-view="network"><span>⌁</span><strong>Mesh / Netzwerk</strong></button><button data-v323-view="live"><span>▣</span><strong>Display</strong></button></div></section>
            <section class="v323-panel"><div class="v323-panel-head"><div><span class="v323-eyebrow">SYSTEM</span><h2>Status</h2></div></div><div class="v323-system-list"><div><span>USB-Erkennung</span><strong class="${s.usb ? 'ok' : ''}">${s.usb ? 'Aktiv' : 'Bereit'}</strong></div><div><span>BLE</span><strong class="${s.ble ? 'ok' : ''}">${s.ble} sichtbar</strong></div><div><span>Log-Automatik</span><strong class="ok">Bereit</strong></div><div><span>Priorität</span><strong>USB → BLE</strong></div></div></section>
          </aside>
        </div>
        <section class="v323-panel v323-activity"><div class="v323-panel-head"><div><span class="v323-eyebrow">AKTIVITÄT</span><h2>Letzte Vorgänge</h2></div><button id="v323ActivityMirror">Alle anzeigen</button></div><div class="v323-activity-list">${activityRows(nodes)}</div></section>
      </div>`;
  }

  function ensureTopStrip() {
    let strip = document.getElementById('v323TopStrip');
    if (!strip) {
      strip = document.createElement('div');
      strip.id = 'v323TopStrip';
      strip.className = 'v323-top-strip glass-panel';
      const topbar = mainColumn.querySelector('.topbar');
      mainColumn.insertBefore(strip, topbar || mainColumn.firstChild);
    }
    const s = summary();
    const github = snapshot?.github || snapshot?.update || {};
    const mesh = snapshot?.mesh || {};
    strip.innerHTML = `
      <div><span>USB</span><strong>${s.usb ? `${s.usb} Gerät${s.usb === 1 ? '' : 'e'}` : 'Bereit'}</strong><i class="${s.usb ? 'ok' : ''}"></i></div>
      <div><span>Bluetooth</span><strong>${s.ble} Gerät${s.ble === 1 ? '' : 'e'}</strong><i class="${s.ble ? 'ok' : ''}"></i></div>
      <div><span>Mesh-Netzwerk</span><strong>${esc(mesh.status || (s.online ? 'Online' : 'Bereit'))}</strong><i class="${s.online ? 'ok' : ''}"></i></div>
      <div><span>GitHub</span><strong>${esc(github.remote_version || github.version || 'Updateprüfung')}</strong><i></i></div>
      <div class="v323-top-spacer"></div><div class="v323-top-version"><span>Service Tool</span><strong>v${esc(VERSION)}</strong></div>`;
  }

  function renderCurrent() {
    if (!snapshot) return;
    ensureTopStrip();
    if (mode() === 'nodes') renderNodes();
    else if (mode() === 'dashboard') renderDashboard();
  }

  async function refresh() {
    if (busy || document.hidden) return;
    busy = true;
    try {
      snapshot = await request('/api/state');
      const sig = JSON.stringify({ updated: snapshot?.updated_at, nodes: snapshot?.nodes, connections: snapshot?.connections });
      if (sig !== lastSignature) {
        lastSignature = sig;
        renderCurrent();
      } else if (!pageHost.querySelector('.rd-v323-shell') && ['dashboard','nodes'].includes(mode())) {
        renderCurrent();
      }
    } catch (_error) {
      // Existing app handles connection errors; this layer must never block the tool.
    } finally {
      busy = false;
    }
  }

  document.addEventListener('click', event => {
    const viewButton = event.target.closest('[data-v323-view]');
    if (viewButton) {
      const view = viewButton.dataset.v323View;
      const selector = view === 'nodes'
        ? '.nav-item[data-rd-mode="nodes"]'
        : view === 'dashboard'
          ? '.nav-item[data-rd-mode="dashboard"]'
          : `.nav-item[data-view="${view}"]`;
      document.querySelector(selector)?.click();
      return;
    }
    if (event.target.closest('#v323ScanMirror')) {
      document.getElementById('scanBleButton')?.click();
      return;
    }
    if (event.target.closest('#v323ActivityMirror')) {
      document.getElementById('activityButton')?.click();
      return;
    }
    const select = event.target.closest('.v323-check[data-action="select"]');
    if (select) {
      const id = select.dataset.node;
      if (selectedIds.has(id)) selectedIds.delete(id); else selectedIds.add(id);
    }
  }, true);

  searchInput?.addEventListener('input', () => setTimeout(renderCurrent, 0));

  let scheduled = false;
  new MutationObserver(() => {
    if (!['dashboard','nodes'].includes(mode()) || scheduled) return;
    if (pageHost.querySelector('.rd-v323-shell')) return;
    scheduled = true;
    requestAnimationFrame(() => {
      scheduled = false;
      syncSelectedFromCanonical();
      renderCurrent();
    });
  }).observe(pageHost, { childList: true, subtree: false });

  setInterval(refresh, 2200);
  refresh();
  window.JarnsenVisualParityV323 = { refresh, renderCurrent, renderDashboard, renderNodes };
})();
