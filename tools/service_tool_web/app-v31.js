(() => {
  'use strict';

  const params = new URLSearchParams(location.search);
  const API = params.get('api') || 'http://127.0.0.1:0';
  const TOKEN = params.get('token') || '';
  const VERSION = params.get('version') || '3.1.0';

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
    profiles: null,
    profileSlot: 0,
    liveTimer: null,
    live: null,
    map: null,
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
    return new Intl.DateTimeFormat('de-DE', {
      day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit'
    }).format(d);
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

  function toast(text) {
    app.toast.create({ text, position: 'top', closeTimeout: 1800 }).open();
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
        wake: 'Wakeup gesendet', ota: 'OTA gestartet', firmware_check: 'Firmwareprüfung gestartet', delete: 'Node entfernt',
      };
      toast(labels[command] || 'Aktion gestartet');
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
          <button data-action="live-view" data-node="${esc(node.node_id)}">Live</button>
          <button data-action="ota" data-node="${esc(node.node_id)}">OTA</button>
        </div>
      </article>`;
  }

  function renderOverview() {
    const s = state.data?.summary || { nodes: 0, ble: 0, logs_due: 0, updates: 0, warnings: 0 };
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
          ${[['all','Alle'],['ble','In Reichweite'],['due','Logs fällig'],['updates','Updates'],['warnings','Warnungen']].map(([v,l]) => `<button class="button ${state.filter === v ? 'button-active' : ''}" data-filter="${v}">${l}</button>`).join('')}
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
      <div class="chip-row">${chip(node.device_label, 'blue')}${chip(node.ble_reachable ? 'In Reichweite' : 'Offline', node.ble_reachable ? 'green' : '')}${chip(node.log_due ? 'Log fällig' : 'Log aktuell', node.log_due ? 'orange' : 'green')}</div>
      <div class="inspector-facts"><div class="inspector-fact"><span class="fact-label">Akku</span><strong>${batteryText(node.battery)}</strong></div><div class="inspector-fact"><span class="fact-label">Firmware</span><strong>${esc(node.firmware)}</strong></div><div class="inspector-fact"><span class="fact-label">Hinweise</span><strong>${node.warning_count || 0}</strong></div></div>
      <div class="inspector-section-title">Schnellaktionen</div><div class="inspector-actions"><button class="primary" data-action="log" data-node="${esc(node.node_id)}">Log laden</button><button data-action="live-view" data-node="${esc(node.node_id)}">Live</button><button data-action="ota" data-node="${esc(node.node_id)}">OTA</button><button data-action="wake" data-node="${esc(node.node_id)}">Wecken</button></div>
      <div class="inspector-section-title">BLE & Log-Automatik</div><div class="auto-panel"><div class="auto-row"><span>BLE</span><strong>${node.ble_reachable ? 'Erkannt' : 'Nicht in Reichweite'}</strong></div><div class="auto-row"><span>Log</span><strong style="color:${node.log_due ? 'var(--app-orange)' : 'var(--app-green)'}">${node.log_due ? 'Fällig' : 'Aktuell'}</strong></div><div class="auto-row"><span>Status</span><strong>${esc(node.sync_state || 'Bereit')}</strong></div></div>
      <div class="inspector-section-title">Weitere Bereiche</div><div class="inspector-actions"><button data-nav="details">Node-Details</button><button data-nav="logs">Log-Historie</button><button data-nav="diagnostics">Diagnose</button><button data-nav="firmware">Firmware</button><button data-nav="service">Profile</button><button data-nav="map">Karte</button></div>`;
  }

  function renderDetails() {
    const node = getNode(state.selected);
    if (!node) return emptyPage('Node-Details', 'Wähle zuerst eine Node aus der Übersicht aus.');
    const metrics = node.metrics || {};
    pageHost.innerHTML = `<div class="page-header"><div class="page-title-wrap"><h1>${esc(node.long_name)}</h1><p>${esc(node.node_id)} · ${esc(node.device_label)}</p></div></div><div class="generic-grid"><div class="generic-card"><h3>Status</h3><div class="chip-row">${chip(node.ble_reachable ? 'In Reichweite' : 'Offline', node.ble_reachable ? 'green' : '')}${chip(node.log_due ? 'Log fällig' : 'Log aktuell', node.log_due ? 'orange' : 'green')}${node.update ? chip('Update verfügbar', 'purple') : ''}</div><p>${esc(node.sync_state || state.data?.status || 'Bereit')}</p></div><div class="generic-card"><h3>Schnellaktionen</h3><p>Die wichtigsten Node-Aktionen ohne Wechsel in technische Untermenüs.</p><div class="inspector-actions"><button class="primary" data-action="log" data-node="${esc(node.node_id)}">Log laden</button><button data-action="wake" data-node="${esc(node.node_id)}">Wecken</button><button data-action="live-view" data-node="${esc(node.node_id)}">Live</button><button data-action="ota" data-node="${esc(node.node_id)}">OTA</button></div></div></div><h3 style="margin:18px 0 9px">Aktuelle Daten</h3><div class="data-list">${Object.entries(metrics).sort(([a],[b]) => a.localeCompare(b)).map(([k,v]) => `<div class="data-row"><div class="key">${esc(k)}</div><div class="value">${esc(typeof v === 'object' ? JSON.stringify(v) : v)}</div></div>`).join('')}</div>`;
  }

  async function renderLogs() {
    const node = getNode(state.selected);
    if (!node) return emptyPage('Logs & Verlauf', 'Wähle eine Node aus, um ihre Historie zu sehen.');
    pageHost.innerHTML = `<div class="page-header"><div class="page-title-wrap"><h1>Logs & Verlauf</h1><p>${esc(node.long_name)} · ${esc(node.node_id)}</p></div><div class="page-actions"><button class="mini-button" data-action="log" data-node="${esc(node.node_id)}">Neuen Log laden</button></div></div><div class="empty-state"><h3>Historie wird geladen …</h3></div>`;
    try {
      const data = await request(`/api/node/${encodeURIComponent(node.node_id)}/logs`);
      if (state.view !== 'logs') return;
      const logs = data.logs || [];
      pageHost.innerHTML = `<div class="page-header"><div class="page-title-wrap"><h1>Logs & Verlauf</h1><p>${esc(node.long_name)} · ${logs.length} gespeicherte Logs</p></div><div class="page-actions"><button class="mini-button" data-action="log" data-node="${esc(node.node_id)}">Neuen Log laden</button></div></div><div class="data-list">${logs.length ? logs.slice().reverse().map((log, i) => `<div class="data-row"><div class="key">${fmtDate(log.captured_at || log.created_at || '')}</div><div class="value"><strong>${esc(log.firmware || '')} ${esc(log.build || '')}</strong><br><span style="color:var(--app-muted)">${esc(log.path || log.file_path || `Log ${i + 1}`)}</span></div></div>`).join('') : '<div class="empty-state"><h3>Noch keine Logs</h3><p>Der erste BLE- oder USB-Download legt die Historie automatisch an.</p></div>'}</div>`;
    } catch (e) { emptyPage('Logs & Verlauf', e.message); }
  }

  function renderFirmware() {
    const nodes = filteredNodes();
    pageHost.innerHTML = `<div class="page-header"><div class="page-title-wrap"><h1>Firmware</h1><p>Versionen, GitHub-Stand und OTA zentral verwalten.</p></div><div class="page-actions"><button class="mini-button" data-page-action="firmware-check">GitHub prüfen</button></div></div><div class="generic-grid">${nodes.map(n => `<div class="generic-card"><h3>${esc(n.long_name)}</h3><p>${esc(n.device_label)} · ${esc(n.node_id)}</p><div class="chip-row">${chip(n.firmware, 'blue')}${n.update ? chip('Update verfügbar', 'purple') : chip('Aktuell', 'green')}</div><p>${esc(n.update_text || 'Firmwarestatus wird automatisch geprüft.')}</p><button class="button button-fill button-round" data-action="ota" data-node="${esc(n.node_id)}">OTA starten</button></div>`).join('')}</div>`;
  }

  function renderDiagnostics() {
    const node = getNode(state.selected);
    if (!node) return emptyPage('Diagnose', 'Wähle eine Node aus, um ihre Diagnosewerte zu sehen.');
    const metrics = node.metrics || {};
    const important = Object.entries(metrics).filter(([k]) => /battery|volt|power|gps|move|park|tx|rx|runtime|warning|error|temperature|rssi|snr/i.test(k));
    pageHost.innerHTML = `<div class="page-header"><div class="page-title-wrap"><h1>Diagnose</h1><p>${esc(node.long_name)} · automatisch aus dem letzten Log</p></div></div><div class="kpi-grid"><div class="kpi-card"><div class="kpi-icon ${batteryTone(node.battery) || 'blue'}">⌁</div><div><div class="kpi-label">Akku</div><div class="kpi-value">${batteryText(node.battery)}</div></div></div><div class="kpi-card"><div class="kpi-icon blue">◎</div><div><div class="kpi-label">BLE</div><div class="kpi-value compact">${node.ble_reachable ? 'Online' : 'Offline'}</div></div></div><div class="kpi-card"><div class="kpi-icon orange">▤</div><div><div class="kpi-label">Log</div><div class="kpi-value compact">${node.log_due ? 'Fällig' : 'Aktuell'}</div></div></div><div class="kpi-card"><div class="kpi-icon red">!</div><div><div class="kpi-label">Hinweise</div><div class="kpi-value">${node.warning_count || 0}</div></div></div></div><div class="data-list">${(important.length ? important : Object.entries(metrics)).map(([k,v]) => `<div class="data-row"><div class="key">${esc(k)}</div><div class="value">${esc(typeof v === 'object' ? JSON.stringify(v) : v)}</div></div>`).join('')}</div>`;
  }

  async function loadProfiles(force = false) {
    if (state.profiles && !force) return state.profiles;
    state.profiles = await request('/api/profiles');
    return state.profiles;
  }

  function profileCard(profile) {
    const active = Number(profile.slot) === Number(state.profileSlot);
    if (profile.empty) {
      return `<button class="profile-card empty ${active ? 'active' : ''}" data-profile-slot="${profile.slot}"><div class="profile-icon">＋</div><div><strong>${esc(profile.name)}</strong><span>Noch leer</span></div></button>`;
    }
    return `<button class="profile-card ${active ? 'active' : ''}" data-profile-slot="${profile.slot}"><div class="profile-icon">${Number(profile.slot) + 1}</div><div><strong>${esc(profile.name)}</strong><span>${esc(profile.source_hw || 'Unbekannte Hardware')} · ${fmtDate(profile.saved_at)}</span></div>${profile.psk_included ? chip('PSK', 'orange') : ''}</button>`;
  }

  function profileCategoryHtml(profile) {
    return (profile.categories || []).map(category => {
      const items = (category.items || []).map(item => `<button class="section-pill" data-profile-section="1" data-slot="${profile.slot}" data-kind="${esc(item.kind)}" data-name="${esc(item.name)}">${esc(item.name)}</button>`).join('');
      return `<div class="profile-category"><div class="profile-category-head"><strong>${esc(category.name)}</strong><span>${(category.items || []).length}</span></div><div class="profile-section-pills">${items || '<span class="muted-copy">Keine Werte</span>'}</div></div>`;
    }).join('');
  }

  async function renderService() {
    const node = getNode(state.selected);
    pageHost.innerHTML = `<div class="page-header"><div class="page-title-wrap"><h1>Profile & Service</h1><p>Grundprofile, Rückprüfung und Werkreset direkt in Framework7.</p></div></div><div class="empty-state"><h3>Profile werden geladen …</h3></div>`;
    try {
      const data = await loadProfiles();
      if (state.view !== 'service') return;
      const profiles = data.profiles || [];
      if (!profiles.some(p => Number(p.slot) === Number(state.profileSlot))) state.profileSlot = profiles[0]?.slot ?? 0;
      const profile = profiles.find(p => Number(p.slot) === Number(state.profileSlot)) || profiles[0];
      const targetLong = node?.long_name || '';
      const targetShort = node?.short_name || '';
      pageHost.innerHTML = `
        <div class="page-header"><div class="page-title-wrap"><h1>Profile & Service</h1><p>Profile bearbeiten, von einer Node einlesen, übertragen oder vollständig neu provisionieren.</p></div><div class="page-actions"><button class="mini-button" data-page-action="profiles-refresh">Neu laden</button></div></div>
        <div class="profile-layout">
          <aside class="profile-sidebar-card soft-card"><div class="section-label">GRUNDPROFILE</div><div class="profile-list">${profiles.map(profileCard).join('')}</div></aside>
          <section class="profile-main-card soft-card">
            ${profile && !profile.empty ? `
              <div class="profile-title-row"><div><h2>${esc(profile.name)}</h2><p>${esc(profile.source_hw || 'Hardware offen')} · Quelle ${esc(profile.source_long_name || '—')} · ${fmtDate(profile.saved_at)}</p></div><div class="profile-title-actions"><button class="mini-button" data-profile-action="rename" data-slot="${profile.slot}">Umbenennen</button><button class="mini-button danger-text" data-profile-action="delete_profile" data-slot="${profile.slot}">Profil löschen</button></div></div>
              <div class="profile-meta-grid"><div><span>Config</span><strong>${profile.config_count}</strong></div><div><span>Module</span><strong>${profile.module_count}</strong></div><div><span>Kanäle</span><strong>${profile.channel_count}</strong></div><div><span>PSK gespeichert</span><strong>${profile.psk_included ? 'Ja' : 'Nein'}</strong></div></div>
              <div class="service-target-card">
                <div class="service-target-head"><div><span class="section-label">ZIEL-NODE</span><h3>${node ? esc(node.long_name) : 'Keine Node ausgewählt'}</h3><p>${node ? `${esc(node.node_id)} · ${esc(node.device_label)}` : 'Wähle links in der Node-Übersicht zuerst eine Node.'}</p></div>${node ? chip(node.ble_reachable ? 'BLE erreichbar' : 'BLE offline', node.ble_reachable ? 'green' : '') : ''}</div>
                <div class="form-grid">
                  <label><span>Long Name</span><input id="profileLongName" value="${esc(targetLong)}" placeholder="Long Name" /></label>
                  <label><span>Short Name</span><input id="profileShortName" maxlength="4" value="${esc(targetShort)}" placeholder="4 Zeichen" /></label>
                  <label><span>Bluetooth-PIN</span><input id="profilePin" inputmode="numeric" maxlength="6" value="240180" /></label>
                  <label><span>Transport</span><select id="profileTransport"><option>Automatisch</option><option>USB</option><option>Bluetooth</option></select></label>
                </div>
                <div class="switch-row"><label class="switch-item"><input id="profileApplyPin" type="checkbox" checked><span>PIN beim Übertragen setzen</span></label><label class="switch-item"><input id="profileApplyPsk" type="checkbox"><span>PSK ausdrücklich mit übertragen</span></label></div>
                <div class="service-actions"><button class="service-button" data-profile-action="capture" data-slot="${profile.slot}" ${node ? '' : 'disabled'}>Von Node einlesen</button><button class="service-button primary" data-profile-action="apply" data-slot="${profile.slot}" ${node ? '' : 'disabled'}>Profil übertragen</button><button class="service-button destructive-soft" data-profile-action="provision" data-slot="${profile.slot}" ${node ? '' : 'disabled'}>Werkreset + neu aufsetzen</button></div>
                <p class="service-note">USB wird automatisch bevorzugt. Provisioning ist absichtlich nur über USB erlaubt. Namen, PIN und PSK-Regel werden vor dem Start geprüft; anschließend läuft die vorhandene Rückprüfung des Python-Servicekerns.</p>
              </div>
              <div class="section-label profile-values-label">PROFILINHALT</div>
              <div class="profile-categories">${profileCategoryHtml(profile)}</div>`
              : `<div class="empty-state"><div class="empty-glyph">＋</div><h3>${esc(profile?.name || 'Profil')}</h3><p>Dieser Slot ist leer. Wähle eine Node und lies deren aktuelle Grundeinstellungen als neues Profil ein.</p>${node ? `<button class="service-button primary" data-profile-action="capture" data-slot="${profile?.slot ?? 0}">Von ${esc(node.long_name)} einlesen</button>` : '<p>Keine Node ausgewählt.</p>'}</div>`}
          </section>
        </div>`;
    } catch (error) {
      emptyPage('Profile & Service', error.message || String(error));
    }
  }

  function readProfileTarget(slot, command) {
    const node = getNode(state.selected);
    return {
      command,
      slot: Number(slot),
      node_id: node?.node_id || '',
      long_name: document.getElementById('profileLongName')?.value?.trim() || node?.long_name || '',
      short_name: document.getElementById('profileShortName')?.value?.trim() || node?.short_name || '',
      pin: document.getElementById('profilePin')?.value?.trim() || '240180',
      transport: document.getElementById('profileTransport')?.value || 'Automatisch',
      apply_pin: Boolean(document.getElementById('profileApplyPin')?.checked ?? true),
      apply_psk: Boolean(document.getElementById('profileApplyPsk')?.checked ?? false),
    };
  }

  async function profileAction(button) {
    const command = button.dataset.profileAction;
    const slot = Number(button.dataset.slot);
    if (command === 'rename') {
      const profile = state.profiles?.profiles?.find(p => Number(p.slot) === slot);
      app.dialog.prompt('Neuer Profilname', 'Profil umbenennen', async name => {
        try {
          await request('/api/profile/action', { method: 'POST', body: JSON.stringify({ command, slot, name }) });
          state.profiles = null; await renderService(); toast('Profil umbenannt');
        } catch (e) { app.dialog.alert(esc(e.message), 'Fehler'); }
      }, null, profile?.name || '');
      return;
    }
    if (command === 'delete_profile') {
      app.dialog.confirm('Dieses Grundprofil wirklich löschen?', 'Profil löschen', async () => {
        try {
          await request('/api/profile/action', { method: 'POST', body: JSON.stringify({ command, slot }) });
          state.profiles = null; await renderService(); toast('Profil gelöscht');
        } catch (e) { app.dialog.alert(esc(e.message), 'Fehler'); }
      });
      return;
    }
    const payload = readProfileTarget(slot, command);
    if (!payload.node_id) return app.dialog.alert('Bitte zuerst eine Node auswählen.', 'Kein Ziel');
    if (command === 'provision') {
      return app.dialog.confirm('Werkreset löscht die aktuelle Node-Konfiguration. Danach werden Firmware und Grundprofil neu eingerichtet. Fortfahren?', 'Werkreset + Neuaufsetzen', async () => runProfileAction(payload));
    }
    await runProfileAction(payload);
  }

  async function runProfileAction(payload) {
    app.preloader.show();
    try {
      const result = await request('/api/profile/action', { method: 'POST', body: JSON.stringify(payload) });
      toast(result.message || 'Profilaktion gestartet');
      if (payload.command === 'capture') { state.profiles = null; setTimeout(() => { if (state.view === 'service') renderService(); }, 1800); }
      setTimeout(fetchState, 600);
    } catch (e) {
      app.dialog.alert(esc(e.message || e), 'Profilaktion fehlgeschlagen');
    } finally { app.preloader.hide(); }
  }

  function flattenFields(value, prefix = '') {
    const rows = [];
    Object.entries(value || {}).forEach(([key, item]) => {
      const path = prefix ? `${prefix}.${key}` : key;
      if (item !== null && typeof item === 'object' && !Array.isArray(item)) rows.push(...flattenFields(item, path));
      else rows.push({ path, value: item, kind: Array.isArray(item) ? 'array' : typeof item });
    });
    return rows;
  }

  function setByPath(target, path, value) {
    const parts = path.split('.');
    let cursor = target;
    parts.forEach((part, index) => {
      if (index === parts.length - 1) cursor[part] = value;
      else { if (!cursor[part] || typeof cursor[part] !== 'object') cursor[part] = {}; cursor = cursor[part]; }
    });
  }

  async function openProfileSectionEditor(slot, kind, name) {
    app.preloader.show();
    try {
      const section = await request(`/api/profile/${slot}/${encodeURIComponent(kind)}/${encodeURIComponent(name)}`);
      const original = structuredClone(section.data || {});
      const fields = flattenFields(original);
      const form = fields.map(field => {
        const id = `field-${Math.random().toString(36).slice(2)}`;
        const common = `data-field-path="${esc(field.path)}" data-field-kind="${esc(field.kind)}"`;
        if (field.kind === 'boolean') return `<label class="editor-row boolean-row"><span>${esc(field.path)}</span><input ${common} type="checkbox" ${field.value ? 'checked' : ''}></label>`;
        if (field.kind === 'number') return `<label class="editor-row"><span>${esc(field.path)}</span><input ${common} id="${id}" type="number" step="any" value="${esc(field.value)}"></label>`;
        if (field.kind === 'array') return `<label class="editor-row editor-wide"><span>${esc(field.path)}</span><textarea ${common} rows="3">${esc(JSON.stringify(field.value))}</textarea></label>`;
        return `<label class="editor-row"><span>${esc(field.path)}</span><input ${common} id="${id}" value="${esc(field.value ?? '')}"></label>`;
      }).join('');
      const notes = (section.notes || []).map(note => `<div class="editor-note">${esc(note)}</div>`).join('');
      const popupEl = document.createElement('div');
      popupEl.className = 'popup profile-editor-popup';
      popupEl.innerHTML = `<div class="view"><div class="page"><div class="navbar"><div class="navbar-bg"></div><div class="navbar-inner"><div class="title">${esc(section.title || name)}</div><div class="right"><a class="link popup-close">Abbrechen</a></div></div></div><div class="page-content"><div class="profile-editor-content">${notes}<div class="editor-grid">${form || '<div class="empty-state"><h3>Keine editierbaren Werte</h3></div>'}</div><div class="editor-footer"><button class="service-button primary" data-save-profile-section>Änderungen speichern</button></div></div></div></div></div>`;
      document.body.appendChild(popupEl);
      const popup = app.popup.create({ el: popupEl, backdrop: true, closeByBackdropClick: false, on: { closed() { popup.destroy(); popupEl.remove(); } } });
      popupEl.querySelector('[data-save-profile-section]')?.addEventListener('click', async () => {
        const updated = structuredClone(original);
        try {
          popupEl.querySelectorAll('[data-field-path]').forEach(input => {
            const fieldPath = input.dataset.fieldPath;
            const fieldKind = input.dataset.fieldKind;
            let value;
            if (fieldKind === 'boolean') value = input.checked;
            else if (fieldKind === 'number') value = Number(input.value);
            else if (fieldKind === 'array') value = JSON.parse(input.value || '[]');
            else value = input.value;
            setByPath(updated, fieldPath, value);
          });
        } catch (error) {
          app.dialog.alert(esc(error.message || error), 'Ungültiger Wert');
          return;
        }
        app.preloader.show();
        try {
          await request('/api/profile/section', { method: 'POST', body: JSON.stringify({ slot, kind, name, data: updated }) });
          state.profiles = null;
          toast('Profilabschnitt gespeichert');
          popup.close();
          if (state.view === 'service') renderService();
        } catch (e) { app.dialog.alert(esc(e.message || e), 'Speichern fehlgeschlagen'); }
        finally { app.preloader.hide(); }
      });
      popup.open();
    } catch (e) { app.dialog.alert(esc(e.message || e), 'Profilabschnitt'); }
    finally { app.preloader.hide(); }
  }

  function projectTrack(points, width = 920, height = 520) {
    if (!points.length) return { points: [], width, height };
    const lats = points.map(p => Number(p.latitude));
    const lons = points.map(p => Number(p.longitude));
    let minLat = Math.min(...lats), maxLat = Math.max(...lats), minLon = Math.min(...lons), maxLon = Math.max(...lons);
    if (Math.abs(maxLat - minLat) < 0.00001) { minLat -= 0.00001; maxLat += 0.00001; }
    if (Math.abs(maxLon - minLon) < 0.00001) { minLon -= 0.00001; maxLon += 0.00001; }
    const pad = 42;
    return {
      width, height,
      points: points.map((p, i) => ({ ...p, i, x: pad + (Number(p.longitude) - minLon) / (maxLon - minLon) * (width - pad * 2), y: height - pad - (Number(p.latitude) - minLat) / (maxLat - minLat) * (height - pad * 2) }))
    };
  }

  async function renderMap() {
    const node = getNode(state.selected);
    if (!node) return emptyPage('Karte', 'Wähle eine Node mit Positionsdaten aus.');
    pageHost.innerHTML = `<div class="page-header"><div class="page-title-wrap"><h1>Karte</h1><p>${esc(node.long_name)} · historische Trackpunkte aus allen Logs</p></div></div><div class="empty-state"><h3>Track wird geladen …</h3></div>`;
    try {
      const data = await request(`/api/node/${encodeURIComponent(node.node_id)}/positions`);
      if (state.view !== 'map') return;
      state.map = data;
      const projection = projectTrack(data.points || []);
      const polyline = projection.points.map(p => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
      const circles = projection.points.map((p, i) => `<circle cx="${p.x}" cy="${p.y}" r="${i === 0 || i === projection.points.length - 1 ? 7 : 4}" class="${i === 0 ? 'start' : i === projection.points.length - 1 ? 'end' : 'mid'}"><title>${esc(p.mgrs || '')} · ${esc(p.latitude)}, ${esc(p.longitude)}</title></circle>`).join('');
      const latest = projection.points.at(-1);
      pageHost.innerHTML = `<div class="page-header"><div class="page-title-wrap"><h1>Karte</h1><p>${esc(node.long_name)} · ${data.count || 0} Punkte aus ${data.logs_scanned || 0} Logs</p></div><div class="page-actions">${chip(`${((data.distance_m || 0) / 1000).toFixed(2)} km`, 'blue')}</div></div>
      ${data.count ? `<div class="track-layout"><div class="track-map soft-card"><svg viewBox="0 0 ${projection.width} ${projection.height}" preserveAspectRatio="xMidYMid meet"><defs><pattern id="grid" width="60" height="60" patternUnits="userSpaceOnUse"><path d="M 60 0 L 0 0 0 60" class="grid-line" fill="none"/></pattern></defs><rect x="0" y="0" width="100%" height="100%" rx="24" class="map-bg"/><rect x="0" y="0" width="100%" height="100%" rx="24" fill="url(#grid)"/><polyline points="${polyline}" class="track-line"/>${circles}</svg></div><aside class="track-info soft-card"><div class="section-label">TRACK</div><div class="track-stat"><span>Punkte</span><strong>${data.count}</strong></div><div class="track-stat"><span>Strecke</span><strong>${((data.distance_m || 0) / 1000).toFixed(2)} km</strong></div><div class="track-stat"><span>Letzter MGRS</span><strong>${esc(latest?.mgrs || '—')}</strong></div><div class="track-stat"><span>Position</span><strong>${latest ? `${Number(latest.latitude).toFixed(6)}, ${Number(latest.longitude).toFixed(6)}` : '—'}</strong></div><div class="track-stat"><span>Genauigkeit</span><strong>${latest?.accuracy_mm ? `${Math.round(Number(latest.accuracy_mm) / 1000)} m` : '—'}</strong></div></aside></div>` : '<div class="empty-state"><h3>Noch keine Trackpunkte</h3><p>Trackpunkte werden aus den gespeicherten Diagnose-Logs zusammengesetzt.</p></div>'}`;
    } catch (e) { emptyPage('Karte', e.message); }
  }

  async function liveAction(command, extra = {}) {
    const node = getNode(state.selected);
    if (!node) return;
    try {
      const result = await request('/api/live/action', { method: 'POST', body: JSON.stringify({ command, node_id: node.node_id, ...extra }) });
      toast(result.message || 'Live-Aktion gesendet');
      setTimeout(refreshLiveState, 250);
    } catch (e) { app.dialog.alert(esc(e.message || e), 'Live'); }
  }

  function decodeB64(value) {
    const raw = atob(value || '');
    const out = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i += 1) out[i] = raw.charCodeAt(i);
    return out;
  }

  function drawLiveFrame(snapshot) {
    const canvas = document.getElementById('liveCanvas');
    if (!canvas || !snapshot?.frame_b64) return;
    const width = Number(snapshot.width || 0), height = Number(snapshot.height || 0);
    if (!width || !height) return;
    const bytes = decodeB64(snapshot.frame_b64);
    const ctx = canvas.getContext('2d');
    canvas.width = width;
    canvas.height = height;
    ctx.imageSmoothingEnabled = false;
    ctx.fillStyle = '#05070a';
    ctx.fillRect(0, 0, width, height);
    ctx.fillStyle = '#f7f9ff';
    for (let y = 0; y < height; y += 1) {
      const page = Math.floor(y / 8);
      const bit = 1 << (y % 8);
      for (let x = 0; x < width; x += 1) {
        const index = page * width + x;
        if (index < bytes.length && (bytes[index] & bit)) ctx.fillRect(x, y, 1, 1);
      }
    }
  }

  async function refreshLiveState() {
    const node = getNode(state.selected);
    if (!node || state.view !== 'live') return;
    try {
      const data = await request(`/api/live/${encodeURIComponent(node.node_id)}`);
      state.live = data;
      const badge = document.getElementById('liveStatusBadge');
      if (badge) badge.innerHTML = data.connected ? chip('Verbunden', 'green') : data.running ? chip('Verbindung läuft', 'orange') : chip('Nicht verbunden', '');
      const meta = document.getElementById('liveMeta');
      if (meta) meta.textContent = data.snapshot ? `Frame ${data.snapshot.sequence || 0} · OLED ${data.snapshot.screen_on ? 'an' : 'aus'}` : 'Noch kein Frame empfangen';
      drawLiveFrame(data.snapshot || {});
    } catch (_) { /* status is retried automatically */ }
  }

  function startLivePolling() {
    stopLivePolling();
    refreshLiveState();
    state.liveTimer = setInterval(refreshLiveState, 450);
  }

  function stopLivePolling() {
    if (state.liveTimer) clearInterval(state.liveTimer);
    state.liveTimer = null;
  }

  function renderLive() {
    const node = getNode(state.selected);
    if (!node) return emptyPage('Live', 'Wähle eine Node in der Übersicht aus.');
    pageHost.innerHTML = `<div class="page-header"><div class="page-title-wrap"><h1>Live</h1><p>${esc(node.long_name)} · pixelgenaue Spiegelung des Geräte-Displays</p></div><div class="page-actions"><div id="liveStatusBadge">${chip('Status wird geprüft', 'orange')}</div></div></div>
      <div class="live-layout"><div class="live-display-card soft-card"><div class="device-display-shell"><canvas id="liveCanvas" width="128" height="64"></canvas></div><div id="liveMeta" class="live-meta">Noch kein Frame empfangen</div><div class="live-session-actions"><button class="service-button primary" data-live-action="start">Verbinden</button><button class="service-button" data-live-action="stop">Trennen</button></div></div><div class="live-control-card soft-card"><div class="section-label">BEDIENUNG</div><div class="remote-pad"><button data-live-control="UP">▲</button><button data-live-control="PREV">◀</button><button class="select" data-live-control="SELECT">OK</button><button data-live-control="NEXT">▶</button><button data-live-control="DOWN">▼</button></div><div class="remote-secondary"><button data-live-control="WAKE">Display wecken</button><button data-live-control="BACK">Zurück</button></div><p>Die Befehle werden über den vorhandenen sicheren BLE-Service an die Node gesendet. Die Node muss ihr Servicefenster geöffnet haben.</p></div></div>`;
    startLivePolling();
  }

  function renderSettings() {
    const cfg = state.data?.settings || {};
    pageHost.innerHTML = `<div class="page-header"><div class="page-title-wrap"><h1>Einstellungen</h1><p>Automatik, Darstellung und Service-Grundlagen.</p></div></div><div class="data-list"><div class="data-row"><div class="key">Oberfläche</div><div class="value">Framework7 9.1.3 · iOS Theme · v${esc(VERSION)}</div></div><div class="data-row"><div class="key">Darstellung</div><div class="value"><button class="mini-button" data-page-action="theme">${state.theme === 'dark' ? 'Hell' : 'Dunkel'} verwenden</button></div></div><div class="data-row"><div class="key">BLE-Automatik</div><div class="value">Aktiv · Scan ca. ${cfg.ble_scan_seconds || 30} s · Log frisch ${cfg.log_freshness_minutes || 15} min</div></div><div class="data-row"><div class="key">Bluetooth PIN</div><div class="value">${esc(cfg.pin || '240180')}</div></div><div class="data-row"><div class="key">Transport-Priorität</div><div class="value">${esc(cfg.transport_priority || 'USB → BLE')}</div></div><div class="data-row"><div class="key">Backend</div><div class="value">Python Service Core ${esc(state.data?.backend_version || '')}</div></div></div>`;
  }

  function emptyPage(title, text) {
    pageHost.innerHTML = `<div class="page-header"><div class="page-title-wrap"><h1>${esc(title)}</h1></div></div><div class="empty-state"><h3>${esc(title)}</h3><p>${esc(text)}</p></div>`;
  }

  function renderPage() {
    if (!state.data) return;
    if (state.view !== 'live') stopLivePolling();
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

  function renderActivity() {
    const items = state.data?.activity || [];
    document.getElementById('activityStream').innerHTML = items.length ? items.slice().reverse().map(item => `<div class="activity-item"><div class="time">Automatik</div>${esc(item)}</div>`).join('') : '<div class="empty-state"><h3>Noch keine Aktivität</h3><p>BLE-Scans, Pairing, Logdownloads, Profile und OTA erscheinen hier.</p></div>';
  }

  function openNodeMenu(node) {
    app.actions.create({
      buttons: [
        [{ text: `<b>${esc(node.long_name)}</b>`, label: true }],
        [
          { text: 'Öffnen', onClick: () => { state.selected = node.node_id; setView('details'); } },
          { text: 'Log laden', onClick: () => apiAction('download_log', [node.node_id]) },
          { text: 'Live', onClick: () => { state.selected = node.node_id; setView('live'); } },
          { text: 'Profile & Service', onClick: () => { state.selected = node.node_id; setView('service'); } },
          { text: 'Historische Karte', onClick: () => { state.selected = node.node_id; setView('map'); } },
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
    app.dialog.confirm(`${ids.length === 1 ? 'Diese Node inklusive ihrer verwalteten Logs' : `${ids.length} Nodes inklusive ihrer verwalteten Logs`} in den Papierkorb verschieben?`, 'Node entfernen', async () => {
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

    const profileSlot = event.target.closest('[data-profile-slot]');
    if (profileSlot) { state.profileSlot = Number(profileSlot.dataset.profileSlot); renderService(); return; }
    const profileSection = event.target.closest('[data-profile-section]');
    if (profileSection) { openProfileSectionEditor(Number(profileSection.dataset.slot), profileSection.dataset.kind, profileSection.dataset.name); return; }
    const profileActionButton = event.target.closest('[data-profile-action]');
    if (profileActionButton) { profileAction(profileActionButton); return; }
    const liveActionButton = event.target.closest('[data-live-action]');
    if (liveActionButton) { liveAction(liveActionButton.dataset.liveAction); return; }
    const liveControlButton = event.target.closest('[data-live-control]');
    if (liveControlButton) { liveAction('command', { control: liveControlButton.dataset.liveControl }); return; }

    const pageAction = event.target.closest('[data-page-action]');
    if (pageAction) {
      const action = pageAction.dataset.pageAction;
      if (action === 'refresh') fetchState();
      if (action === 'select-visible') { filteredNodes().forEach(node => state.selectedSet.add(node.node_id)); renderOverview(); }
      if (action === 'firmware-check') apiAction('firmware_check');
      if (action === 'theme') toggleTheme();
      if (action === 'profiles-refresh') { state.profiles = null; renderService(); }
      return;
    }

    const bulk = event.target.closest('[data-bulk]');
    if (bulk) {
      const ids = [...state.selectedSet];
      if (!ids.length) return toast('Keine Nodes ausgewählt');
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
      if (kind === 'log') apiAction('download_log', [id]);
      if (kind === 'ota') apiAction('ota', [id]);
      if (kind === 'wake') apiAction('wake', [id]);
      if (kind === 'live-view') { state.selected = id; setView('live'); }
      return;
    }
    if (event.target.closest('[data-inspector-close]')) { state.selected = null; renderInspector(); }
  });

  document.getElementById('scanBleButton').addEventListener('click', () => apiAction('scan_ble'));
  document.getElementById('activityButton').addEventListener('click', () => { renderActivity(); activitySheet.open(); });
  document.getElementById('themeButton').addEventListener('click', toggleTheme);
  searchInput.addEventListener('input', () => { state.search = searchInput.value; if (state.view !== 'overview') setView('overview'); else renderOverview(); });
  document.addEventListener('keydown', event => { if (event.ctrlKey && event.key.toLowerCase() === 'k') { event.preventDefault(); searchInput.focus(); searchInput.select(); } });
  window.addEventListener('beforeunload', stopLivePolling);

  document.documentElement.classList.toggle('theme-dark', state.theme === 'dark');
  document.body.classList.toggle('theme-dark', state.theme === 'dark');
  pageHost.innerHTML = '<div class="empty-state"><h3>Service Tool startet …</h3><p>Framework7 verbindet sich mit dem lokalen Python-Servicekern.</p></div>';
  fetchState();
  state.poll = setInterval(fetchState, 3000);
})();
