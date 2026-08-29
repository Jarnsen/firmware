(() => {
  'use strict';

  const params = new URLSearchParams(location.search);
  const API = params.get('api') || 'http://127.0.0.1:0';
  const TOKEN = params.get('token') || '';
  const VERSION = params.get('version') || '3.0.0';

  const app = new Framework7({
    el: '#app',
    name: 'Jarnsen Node Service Tool',
    version: VERSION,
    theme: 'ios',
    autoDarkTheme: false,
    touch: { tapHold: true },
  });

  const activitySheet = app.sheet.create({ el: '#activitySheet', backdrop: true, closeByBackdropClick: true });
  const state = {
    data: null,
    view: 'overview',
    selected: null,
    selectedSet: new Set(),
    filter: 'all',
    search: '',
    theme: localStorage.getItem('jarnsen-theme') || 'light',
    poll: null,
  };

  const pageHost = document.getElementById('pageHost');
  const inspector = document.getElementById('inspector');
  const searchInput = document.getElementById('globalSearch');

  function esc(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function fmtDate(value) {
    if (!value) return '—';
    const d = new Date(String(value).replace(' ', 'T'));
    if (Number.isNaN(d.getTime())) return esc(String(value).slice(0, 19));
    return new Intl.DateTimeFormat('de-DE', { day:'2-digit', month:'2-digit', year:'2-digit', hour:'2-digit', minute:'2-digit' }).format(d);
  }

  function batteryText(value) {
    return value === null || value === undefined ? '—' : `${Math.round(Number(value))} %`;
  }

  function batteryTone(value) {
    if (value === null || value === undefined) return '';
    if (Number(value) <= 20) return 'red';
    if (Number(value) <= 40) return 'orange';
    return 'green';
  }

  async function request(path, options = {}) {
    const response = await fetch(`${API}${path}`, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        'X-Jarnsen-Token': TOKEN,
        ...(options.headers || {}),
      },
      cache: 'no-store',
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
    return body;
  }

  async function apiAction(command, nodeIds = [], extra = {}) {
    const ids = [...new Set(nodeIds.filter(Boolean))];
    app.preloader.show();
    try {
      const result = await request('/api/action', {
        method: 'POST',
        body: JSON.stringify({ command, node_ids: ids, ...extra }),
      });
      const labels = {
        scan_ble: 'BLE-Prüfung gestartet', refresh: 'Aktualisiert', download_log: 'Logdownload gestartet',
        wake: 'Wakeup gesendet', ota: 'OTA gestartet', live: 'Live-Anfrage gestartet',
        firmware_check: 'Firmwareprüfung gestartet', delete: 'Node entfernt',
      };
      app.toast.create({ text: labels[command] || 'Aktion gestartet', position: 'top', closeTimeout: 1800 }).open();
      setTimeout(fetchState, 350);
      return result;
    } catch (error) {
      app.dialog.alert(esc(error.message || error), 'Aktion fehlgeschlagen');
      throw error;
    } finally {
      app.preloader.hide();
    }
  }

  function getNode(id) {
    return state.data?.nodes?.find(n => n.node_id === id) || null;
  }

  function filteredNodes() {
    const nodes = state.data?.nodes || [];
    const q = state.search.trim().toLowerCase();
    return nodes.filter(node => {
      if (state.filter === 'ble' && !node.ble_reachable) return false;
      if (state.filter === 'due' && !node.log_due) return false;
      if (state.filter === 'updates' && !node.update) return false;
      if (state.filter === 'warnings' && !node.attention) return false;
      if (!q) return true;
      return [node.long_name, node.short_name, node.node_id, node.device_label, node.firmware, node.sync_state]
        .some(value => String(value || '').toLowerCase().includes(q));
    });
  }

  function chip(text, tone = '') {
    return `<span class="status-chip ${tone}">${esc(text)}</span>`;
  }

  function nodeCard(node) {
    const selected = state.selectedSet.has(node.node_id);
    const classes = ['node-card'];
    if (selected) classes.push('selected');
    if (node.attention) classes.push('attention');
    else if (node.update || node.log_due) classes.push('update');
    const chips = [
      chip(node.device_label.includes('V3') ? 'V3' : 'Tracker', 'blue'),
      chip(node.ble_reachable ? 'In Reichweite' : 'Offline', node.ble_reachable ? 'green' : ''),
      node.log_due ? chip('Log fällig', 'orange') : chip('Log aktuell', 'green'),
      node.update ? chip('Update', 'purple') : '',
      node.attention ? chip('Hinweis', 'red') : '',
    ].join('');
    return `
      <article class="${classes.join(' ')}" data-node="${esc(node.node_id)}">
        <div class="node-card-head">
          <button class="select-circle" data-action="select" data-node="${esc(node.node_id)}">${selected ? '✓' : ''}</button>
          <div class="node-heading" data-action="inspect" data-node="${esc(node.node_id)}">
            <div class="node-title">${esc(node.long_name)}</div>
            <div class="node-subtitle">${esc(node.short_name || '—')} · ${esc(node.node_id)}</div>
          </div>
          <button class="card-menu" data-action="menu" data-node="${esc(node.node_id)}">•••</button>
        </div>
        <div class="chip-row">${chips}</div>
        <div class="node-facts">
          <div><div class="fact-label">Akku</div><div class="fact-value">${batteryText(node.battery)}</div></div>
          <div><div class="fact-label">BLE</div><div class="fact-value">${node.ble_reachable ? 'Erreichbar' : 'Nicht sichtbar'}</div></div>
          <div><div class="fact-label">Letzter Log</div><div class="fact-value">${fmtDate(node.captured_at)}</div></div>
          <div><div class="fact-label">Firmware</div><div class="fact-value">${esc(node.firmware)}</div></div>
        </div>
        <div class="sync-line"><span class="status-dot ${node.ble_reachable ? 'ok' : node.log_due ? 'warn' : ''}"></span>${esc(node.sync_state || (node.log_due ? 'Log wartet auf Synchronisierung' : 'Synchronisiert'))}</div>
        <div class="card-actions">
          <button class="primary" data-action="inspect" data-node="${esc(node.node_id)}">Öffnen</button>
          <button data-action="log" data-node="${esc(node.node_id)}">Log</button>
          <button data-action="live" data-node="${esc(node.node_id)}">Live</button>
          <button data-action="ota" data-node="${esc(node.node_id)}">OTA</button>
        </div>
      </article>`;
  }

  function renderOverview() {
    const s = state.data?.summary || { nodes:0, ble:0, logs_due:0, updates:0, warnings:0 };
    const nodes = filteredNodes();
    pageHost.innerHTML = `
      <div class="page-header">
        <div class="page-title-wrap"><h1>Node-Übersicht</h1><p>Alles Wichtige auf einen Blick. Details erst bei Bedarf.</p></div>
        <div class="page-actions"><button class="mini-button" data-page-action="refresh">Aktualisieren</button><button class="mini-button" data-page-action="select-visible">Alle auswählen</button></div>
      </div>
      <div class="kpi-grid">
        <div class="kpi-card"><div class="kpi-icon blue">◫</div><div><div class="kpi-label">Nodes</div><div class="kpi-value">${s.nodes}</div><div class="kpi-meta">Gesamt verwaltet</div></div></div>
        <div class="kpi-card"><div class="kpi-icon green">⌁</div><div><div class="kpi-label">BLE in Reichweite</div><div class="kpi-value">${s.ble}</div><div class="kpi-meta">Aktuell sichtbar</div></div></div>
        <div class="kpi-card"><div class="kpi-icon orange">▤</div><div><div class="kpi-label">Logs fällig</div><div class="kpi-value">${s.logs_due}</div><div class="kpi-meta">Automatik kümmert sich</div></div></div>
        <div class="kpi-card"><div class="kpi-icon red">!</div><div><div class="kpi-label">Aufmerksamkeit</div><div class="kpi-value">${s.warnings + s.updates}</div><div class="kpi-meta">Hinweise & Updates</div></div></div>
      </div>
      <div class="toolbar-row">
        <div class="segmented segmented-strong filter-segments">
          ${[['all','Alle'],['ble','In Reichweite'],['due','Logs fällig'],['updates','Updates'],['warnings','Warnungen']].map(([v,l]) => `<button class="button ${state.filter===v?'button-active':''}" data-filter="${v}">${l}</button>`).join('')}
        </div>
        <div class="bulk-actions"><span class="bulk-count">${state.selectedSet.size} ausgewählt</span><button class="bulk-action primary" data-bulk="download_log">Logs laden</button><button class="bulk-action" data-bulk="ota">OTA</button><button class="bulk-action" data-bulk="wake">Wecken</button>${state.selectedSet.size ? '<button class="bulk-action danger" data-bulk="delete">Löschen</button>' : ''}</div>
      </div>
      <div class="node-grid">${nodes.length ? nodes.map(nodeCard).join('') : '<div class="empty-state"><h3>Keine Nodes gefunden</h3><p>Filter oder Suche ändern – oder BLE erneut prüfen.</p></div>'}</div>`;
  }

  function renderInspector() {
    const node = getNode(state.selected);
    inspector.classList.toggle('open', Boolean(node));
    if (!node) {
      inspector.innerHTML = '<div class="inspector-empty"><div class="empty-glyph">◎</div><h3>Node auswählen</h3><p>Details und Schnellaktionen erscheinen hier, ohne die Übersicht zu verlassen.</p></div>';
      return;
    }
    inspector.innerHTML = `
      <div class="inspector-head"><div class="inspector-caption">DETAILS</div><button class="inspector-close" data-inspector-close>×</button></div>
      <div class="inspector-name">${esc(node.long_name)}</div><div class="inspector-sub">${esc(node.short_name || '—')} · ${esc(node.node_id)}</div>
      <div class="chip-row">${chip(node.device_label,'blue')}${chip(node.ble_reachable?'In Reichweite':'Offline',node.ble_reachable?'green':'')}${chip(node.log_due?'Log fällig':'Log aktuell',node.log_due?'orange':'green')}</div>
      <div class="inspector-facts"><div class="inspector-fact"><span class="fact-label">Akku</span><strong>${batteryText(node.battery)}</strong></div><div class="inspector-fact"><span class="fact-label">Firmware</span><strong>${esc(node.firmware)}</strong></div><div class="inspector-fact"><span class="fact-label">Hinweise</span><strong>${node.warning_count || 0}</strong></div></div>
      <div class="inspector-section-title">Schnellaktionen</div><div class="inspector-actions"><button class="primary" data-action="log" data-node="${esc(node.node_id)}">Log laden</button><button data-action="live" data-node="${esc(node.node_id)}">Live</button><button data-action="ota" data-node="${esc(node.node_id)}">OTA</button><button data-action="wake" data-node="${esc(node.node_id)}">Wecken</button></div>
      <div class="inspector-section-title">BLE & Log-Automatik</div><div class="auto-panel"><div class="auto-row"><span>BLE</span><strong>${node.ble_reachable?'Erkannt':'Nicht in Reichweite'}</strong></div><div class="auto-row"><span>Log</span><strong style="color:${node.log_due?'var(--app-orange)':'var(--app-green)'}">${node.log_due?'Fällig':'Aktuell'}</strong></div><div class="auto-row"><span>Status</span><strong>${esc(node.sync_state || 'Bereit')}</strong></div></div>
      <div class="inspector-section-title">Weitere Bereiche</div><div class="inspector-actions"><button data-nav="details">Node-Details</button><button data-nav="logs">Log-Historie</button><button data-nav="diagnostics">Diagnose</button><button data-nav="firmware">Firmware</button></div>`;
  }

  function renderDetails() {
    const node = getNode(state.selected);
    if (!node) return emptyPage('Node-Details', 'Wähle zuerst eine Node aus der Übersicht aus.');
    const metrics = node.metrics || {};
    pageHost.innerHTML = `<div class="page-header"><div class="page-title-wrap"><h1>${esc(node.long_name)}</h1><p>${esc(node.node_id)} · ${esc(node.device_label)}</p></div></div><div class="generic-grid"><div class="generic-card"><h3>Status</h3><div class="chip-row">${chip(node.ble_reachable?'In Reichweite':'Offline',node.ble_reachable?'green':'')}${chip(node.log_due?'Log fällig':'Log aktuell',node.log_due?'orange':'green')}${node.update?chip('Update verfügbar','purple'):''}</div><p>${esc(node.sync_state || state.data?.status || 'Bereit')}</p></div><div class="generic-card"><h3>Schnellaktionen</h3><p>Die wichtigsten Node-Aktionen ohne Wechsel in technische Untermenüs.</p><div class="inspector-actions"><button class="primary" data-action="log" data-node="${esc(node.node_id)}">Log laden</button><button data-action="wake" data-node="${esc(node.node_id)}">Wecken</button><button data-action="live" data-node="${esc(node.node_id)}">Live</button><button data-action="ota" data-node="${esc(node.node_id)}">OTA</button></div></div></div><h3 style="margin:18px 0 9px">Aktuelle Daten</h3><div class="data-list">${Object.entries(metrics).sort(([a],[b])=>a.localeCompare(b)).map(([k,v])=>`<div class="data-row"><div class="key">${esc(k)}</div><div class="value">${esc(typeof v==='object'?JSON.stringify(v):v)}</div></div>`).join('')}</div>`;
  }

  async function renderLogs() {
    const node = getNode(state.selected);
    if (!node) return emptyPage('Logs & Verlauf', 'Wähle eine Node aus, um ihre Historie zu sehen.');
    pageHost.innerHTML = `<div class="page-header"><div class="page-title-wrap"><h1>Logs & Verlauf</h1><p>${esc(node.long_name)} · ${esc(node.node_id)}</p></div><div class="page-actions"><button class="mini-button" data-action="log" data-node="${esc(node.node_id)}">Neuen Log laden</button></div></div><div class="empty-state"><h3>Historie wird geladen …</h3></div>`;
    try {
      const data = await request(`/api/node/${encodeURIComponent(node.node_id)}/logs`);
      const logs = data.logs || [];
      pageHost.innerHTML = `<div class="page-header"><div class="page-title-wrap"><h1>Logs & Verlauf</h1><p>${esc(node.long_name)} · ${logs.length} gespeicherte Logs</p></div><div class="page-actions"><button class="mini-button" data-action="log" data-node="${esc(node.node_id)}">Neuen Log laden</button></div></div><div class="data-list">${logs.length ? logs.map((log,i)=>`<div class="data-row"><div class="key">${fmtDate(log.captured_at || log.created_at || '')}</div><div class="value">${esc(log.firmware || '')} ${esc(log.build || '')}<br><span style="color:var(--app-muted)">${esc(log.path || log.file_path || `Log ${i+1}`)}</span></div></div>`).join('') : '<div class="empty-state"><h3>Noch keine Logs</h3><p>Der erste BLE- oder USB-Download legt die Historie automatisch an.</p></div>'}</div>`;
    } catch (e) { emptyPage('Logs & Verlauf', e.message); }
  }

  function renderFirmware() {
    const nodes = filteredNodes();
    pageHost.innerHTML = `<div class="page-header"><div class="page-title-wrap"><h1>Firmware</h1><p>Versionen, GitHub-Stand und OTA zentral verwalten.</p></div><div class="page-actions"><button class="mini-button" data-page-action="firmware-check">GitHub prüfen</button></div></div><div class="generic-grid">${nodes.map(n=>`<div class="generic-card"><h3>${esc(n.long_name)}</h3><p>${esc(n.device_label)} · ${esc(n.node_id)}</p><div class="chip-row">${chip(n.firmware,'blue')}${n.update?chip('Update verfügbar','purple'):chip('Aktuell','green')}</div><p>${esc(n.update_text || 'Firmwarestatus wird automatisch geprüft.')}</p><button class="button button-fill" data-action="ota" data-node="${esc(n.node_id)}">OTA starten</button></div>`).join('')}</div>`;
  }

  function renderDiagnostics() {
    const node = getNode(state.selected);
    if (!node) return emptyPage('Diagnose', 'Wähle eine Node aus, um ihre Diagnosewerte zu sehen.');
    const metrics = node.metrics || {};
    const important = Object.entries(metrics).filter(([k]) => /battery|volt|power|gps|move|park|tx|rx|runtime|warning|error|temperature|rssi|snr/i.test(k));
    pageHost.innerHTML = `<div class="page-header"><div class="page-title-wrap"><h1>Diagnose</h1><p>${esc(node.long_name)} · automatisch aus dem letzten Log</p></div></div><div class="kpi-grid"><div class="kpi-card"><div class="kpi-icon ${batteryTone(node.battery)||'blue'}">⌁</div><div><div class="kpi-label">Akku</div><div class="kpi-value">${batteryText(node.battery)}</div></div></div><div class="kpi-card"><div class="kpi-icon blue">◎</div><div><div class="kpi-label">BLE</div><div class="kpi-value" style="font-size:18px">${node.ble_reachable?'Online':'Offline'}</div></div></div><div class="kpi-card"><div class="kpi-icon orange">▤</div><div><div class="kpi-label">Log</div><div class="kpi-value" style="font-size:18px">${node.log_due?'Fällig':'Aktuell'}</div></div></div><div class="kpi-card"><div class="kpi-icon red">!</div><div><div class="kpi-label">Hinweise</div><div class="kpi-value">${node.warning_count||0}</div></div></div></div><div class="data-list">${(important.length?important:Object.entries(metrics)).map(([k,v])=>`<div class="data-row"><div class="key">${esc(k)}</div><div class="value">${esc(typeof v==='object'?JSON.stringify(v):v)}</div></div>`).join('')}</div>`;
  }

  function renderService() {
    const node = getNode(state.selected);
    pageHost.innerHTML = `<div class="page-header"><div class="page-title-wrap"><h1>Profile & Service</h1><p>Geräteaktionen werden über den bestehenden Python-Servicekern ausgeführt.</p></div></div><div class="generic-grid"><div class="generic-card"><h3>${node?esc(node.long_name):'Node auswählen'}</h3><p>${node?`${esc(node.device_label)} · ${esc(node.node_id)}`:'Wähle in der Übersicht eine Node für gerätespezifische Aktionen.'}</p>${node?`<div class="inspector-actions"><button class="primary" data-action="log" data-node="${esc(node.node_id)}">Log laden</button><button data-action="wake" data-node="${esc(node.node_id)}">Wecken</button><button data-action="ota" data-node="${esc(node.node_id)}">OTA</button><button data-action="live" data-node="${esc(node.node_id)}">Live</button></div>`:''}</div><div class="generic-card"><h3>Transport-Automatik</h3><p>USB wird bevorzugt, BLE dient automatisch als Fallback. Bekannte BLE-Nodes werden selbstständig geprüft und bei fälligem Log in die Queue aufgenommen.</p>${chip('USB → BLE','blue')} ${chip('PIN 240180','green')}</div><div class="generic-card"><h3>Grundeinstellungen</h3><p>Profile, Readback-Verifikation und Virgin-Node-Provisioning bleiben im Python-Servicekern erhalten und werden schrittweise als Framework7-Formulare bereitgestellt.</p></div><div class="generic-card"><h3>Sichere Verwaltung</h3><p>Destruktive Aktionen bleiben bestätigt. Node-Entfernen löscht weiterhin die verwalteten Datensätze und optionalen Zuordnungen über die bestehende Lifecycle-Logik.</p></div></div>`;
  }

  function renderMap() {
    const node = getNode(state.selected);
    if (!node) return emptyPage('Karte', 'Wähle eine Node mit Positionsdaten aus.');
    const m = node.metrics || {};
    const lat = m.latitude ?? m.lat ?? m.gps_lat;
    const lon = m.longitude ?? m.lon ?? m.lng ?? m.gps_lon;
    pageHost.innerHTML = `<div class="page-header"><div class="page-title-wrap"><h1>Karte</h1><p>${esc(node.long_name)} · letzte bekannte Position</p></div></div><div class="generic-card" style="min-height:280px;display:grid;place-items:center;text-align:center"><div><div style="font-size:46px;color:var(--app-blue)">◇</div><h3>${lat!=null&&lon!=null?`${esc(lat)}, ${esc(lon)}`:'Keine Position im letzten Log'}</h3><p>${esc(m.mgrs || m.position || 'Die vollständige historische Kartenfunktion bleibt im Backend erhalten; die native Framework7-Kartenansicht wird aus den Positionslogs gespeist.')}</p></div></div>`;
  }

  function renderLive() {
    const node = getNode(state.selected);
    pageHost.innerHTML = `<div class="page-header"><div class="page-title-wrap"><h1>Live</h1><p>Live-Daten ohne die Nodeübersicht zu verlassen.</p></div></div>${node?`<div class="generic-card"><h3>${esc(node.long_name)}</h3><p>${node.ble_reachable?'BLE ist in Reichweite.':'Die Node ist momentan nicht als BLE-erreichbar markiert.'}</p><button class="button button-fill" data-action="live" data-node="${esc(node.node_id)}">Live-Ansicht starten</button></div>`:'<div class="empty-state"><h3>Node auswählen</h3><p>Wähle eine Node in der Übersicht aus.</p></div>'}`;
  }

  function renderSettings() {
    const cfg = state.data?.settings || {};
    pageHost.innerHTML = `<div class="page-header"><div class="page-title-wrap"><h1>Einstellungen</h1><p>Automatik, Darstellung und Service-Grundlagen.</p></div></div><div class="data-list"><div class="data-row"><div class="key">Oberfläche</div><div class="value">Framework7 9.1.3 · iOS Theme · v${esc(VERSION)}</div></div><div class="data-row"><div class="key">Darstellung</div><div class="value"><button class="mini-button" data-page-action="theme">${state.theme==='dark'?'Hell':'Dunkel'} verwenden</button></div></div><div class="data-row"><div class="key">BLE-Automatik</div><div class="value">Aktiv · Scan ca. ${cfg.ble_scan_seconds||30} s · Log frisch ${cfg.log_freshness_minutes||15} min</div></div><div class="data-row"><div class="key">Bluetooth PIN</div><div class="value">${esc(cfg.pin||'240180')}</div></div><div class="data-row"><div class="key">Transport-Priorität</div><div class="value">${esc(cfg.transport_priority||'USB → BLE')}</div></div><div class="data-row"><div class="key">Backend</div><div class="value">Python Service Core ${esc(state.data?.backend_version||'')}</div></div></div>`;
  }

  function emptyPage(title, text) {
    pageHost.innerHTML = `<div class="page-header"><div class="page-title-wrap"><h1>${esc(title)}</h1></div></div><div class="empty-state"><h3>${esc(title)}</h3><p>${esc(text)}</p></div>`;
  }

  function renderPage() {
    if (!state.data) return;
    if (state.view === 'overview') renderOverview();
    else if (state.view === 'details') renderDetails();
    else if (state.view === 'logs') renderLogs();
    else if (state.view === 'firmware') renderFirmware();
    else if (state.view === 'map') renderMap();
    else if (state.view === 'live') renderLive();
    else if (state.view === 'service') renderService();
    else if (state.view === 'diagnostics') renderDiagnostics();
    else if (state.view === 'settings') renderSettings();
    renderInspector();
  }

  function setView(view) {
    state.view = view;
    document.querySelectorAll('.nav-item').forEach(item => item.classList.toggle('active', item.dataset.view === view));
    renderPage();
  }

  function toggleTheme() {
    state.theme = state.theme === 'dark' ? 'light' : 'dark';
    localStorage.setItem('jarnsen-theme', state.theme);
    document.documentElement.classList.toggle('theme-dark', state.theme === 'dark');
    document.body.classList.toggle('theme-dark', state.theme === 'dark');
    renderPage();
  }

  async function fetchState() {
    try {
      const data = await request('/api/state');
      state.data = data;
      document.getElementById('visibleBleCount').textContent = data.summary?.ble ?? 0;
      document.getElementById('connectionValue').textContent = data.busy ? data.status : 'BLE-Automatik aktiv';
      document.getElementById('connectionMeta').textContent = data.busy ? 'Vorgang läuft …' : 'USB → BLE · PIN 240180';
      if (state.selected && !getNode(state.selected)) state.selected = null;
      renderPage();
      renderActivity();
    } catch (error) {
      document.getElementById('connectionValue').textContent = 'Backend nicht erreichbar';
      document.getElementById('connectionValue').style.color = 'var(--app-red)';
    }
  }

  function renderActivity() {
    const items = state.data?.activity || [];
    document.getElementById('activityStream').innerHTML = items.length ? items.slice().reverse().map(item => `<div class="activity-item"><div class="time">Automatik</div>${esc(item)}</div>`).join('') : '<div class="empty-state"><h3>Noch keine Aktivität</h3><p>BLE-Scans, Pairing, Logdownloads und OTA erscheinen hier.</p></div>';
  }

  function openNodeMenu(node) {
    app.actions.create({
      buttons: [
        [{ text: `<b>${esc(node.long_name)}</b>`, label: true }],
        [
          { text: 'Öffnen', onClick: () => { state.selected = node.node_id; setView('details'); } },
          { text: 'Log laden', onClick: () => apiAction('download_log', [node.node_id]) },
          { text: 'Live', onClick: () => apiAction('live', [node.node_id]) },
          { text: 'OTA Update', onClick: () => apiAction('ota', [node.node_id]) },
          { text: 'Wecken', onClick: () => apiAction('wake', [node.node_id]) },
        ],
        [{ text: 'Node entfernen …', color: 'red', onClick: () => confirmDelete([node.node_id]) }],
        [{ text: 'Abbrechen', color: 'blue' }],
      ],
    }).open();
  }

  function confirmDelete(ids) {
    if (!ids.length) return;
    app.dialog.confirm(`${ids.length === 1 ? 'Diese Node' : `${ids.length} Nodes`} aus dem Node Tool entfernen?`, 'Node entfernen', async () => {
      await apiAction('delete', ids);
      ids.forEach(id => state.selectedSet.delete(id));
      if (ids.includes(state.selected)) state.selected = null;
      fetchState();
    });
  }

  document.addEventListener('click', event => {
    const nav = event.target.closest('[data-view]');
    if (nav) { setView(nav.dataset.view); return; }
    const nav2 = event.target.closest('[data-nav]');
    if (nav2) { setView(nav2.dataset.nav); return; }
    const filter = event.target.closest('[data-filter]');
    if (filter) { state.filter = filter.dataset.filter; renderOverview(); return; }
    const pageAction = event.target.closest('[data-page-action]');
    if (pageAction) {
      const action = pageAction.dataset.pageAction;
      if (action === 'refresh') fetchState();
      if (action === 'select-visible') { filteredNodes().forEach(node => state.selectedSet.add(node.node_id)); renderOverview(); }
      if (action === 'firmware-check') apiAction('firmware_check');
      if (action === 'theme') toggleTheme();
      return;
    }
    const bulk = event.target.closest('[data-bulk]');
    if (bulk) {
      const ids = [...state.selectedSet];
      if (!ids.length) return app.toast.create({ text:'Keine Nodes ausgewählt', position:'top', closeTimeout:1400 }).open();
      if (bulk.dataset.bulk === 'delete') confirmDelete(ids); else apiAction(bulk.dataset.bulk, ids);
      return;
    }
    const action = event.target.closest('[data-action]');
    if (action) {
      const id = action.dataset.node;
      const kind = action.dataset.action;
      if (kind === 'select') { state.selectedSet.has(id) ? state.selectedSet.delete(id) : state.selectedSet.add(id); renderOverview(); return; }
      if (kind === 'inspect') { state.selected = id; renderInspector(); if (state.view !== 'overview') renderPage(); return; }
      if (kind === 'menu') { const node = getNode(id); if (node) openNodeMenu(node); return; }
      if (kind === 'log') apiAction('download_log',[id]);
      if (kind === 'live') apiAction('live',[id]);
      if (kind === 'ota') apiAction('ota',[id]);
      if (kind === 'wake') apiAction('wake',[id]);
      return;
    }
    if (event.target.closest('[data-inspector-close]')) { state.selected = null; renderInspector(); }
  });

  document.getElementById('scanBleButton').addEventListener('click', () => apiAction('scan_ble'));
  document.getElementById('activityButton').addEventListener('click', () => { renderActivity(); activitySheet.open(); });
  document.getElementById('themeButton').addEventListener('click', toggleTheme);
  searchInput.addEventListener('input', () => { state.search = searchInput.value; if (state.view !== 'overview') setView('overview'); else renderOverview(); });
  document.addEventListener('keydown', event => { if (event.ctrlKey && event.key.toLowerCase() === 'k') { event.preventDefault(); searchInput.focus(); searchInput.select(); } });

  document.documentElement.classList.toggle('theme-dark', state.theme === 'dark');
  document.body.classList.toggle('theme-dark', state.theme === 'dark');
  pageHost.innerHTML = '<div class="empty-state"><h3>Service Tool startet …</h3><p>Framework7 verbindet sich mit dem lokalen Python-Servicekern.</p></div>';
  fetchState();
  state.poll = setInterval(fetchState, 3000);
})();
