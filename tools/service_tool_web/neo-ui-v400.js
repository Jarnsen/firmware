(() => {
  'use strict';

  const params = new URLSearchParams(location.search);
  const API = params.get('api') || 'http://127.0.0.1:0';
  const TOKEN = params.get('token') || '';
  const host = document.getElementById('pageHost');
  if (!host) return;

  document.body.dataset.neoUi = 'v400';
  let snapshot = null;
  let serviceStatus = null;
  let profiles = [];
  let radioAuth = null;
  let currentPage = 'dashboard';
  let selectedNodeId = '';
  let nodeFilter = 'all';
  let profileSlot = Number(localStorage.getItem('jarnsen-neo-profile-slot') || 0);
  let powerOriginal = {};
  let positionOriginal = {};
  let loraOriginal = {};
  let refreshTimer = null;

  const esc = value => String(value ?? '')
    .replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')
    .replaceAll('"','&quot;').replaceAll("'",'&#039;');

  async function request(path, options = {}) {
    const response = await fetch(`${API}${path}`, {
      ...options,
      headers: {'Content-Type':'application/json','X-Jarnsen-Token':TOKEN,...(options.headers || {})},
      cache:'no-store',
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
    return body;
  }

  function toast(text, error = false) {
    document.getElementById('neoToastV400')?.remove();
    const el = document.createElement('div');
    el.id = 'neoToastV400';
    el.className = `neo-toast${error ? ' error' : ''}`;
    el.textContent = text;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), error ? 4500 : 2400);
  }

  function fmtTime(value) {
    if (!value) return '—';
    const date = new Date(String(value).replace(' ','T'));
    if (Number.isNaN(date.getTime())) return esc(String(value).slice(0,16));
    const diff = Math.max(0, Date.now() - date.getTime());
    const min = Math.round(diff / 60000);
    if (min < 1) return 'gerade';
    if (min < 60) return `vor ${min} min`;
    if (min < 1440) return `vor ${Math.round(min/60)} h`;
    return date.toLocaleDateString('de-DE');
  }

  function pct(value) { return value == null || Number.isNaN(Number(value)) ? '—' : `${Math.round(Number(value))} %`; }
  function nodes() { return Array.isArray(snapshot?.nodes) ? snapshot.nodes : []; }
  function nodeById(id) { return nodes().find(n => String(n.node_id || '').toLowerCase() === String(id || '').toLowerCase()) || null; }
  function selectedNode() { return nodeById(selectedNodeId) || nodeById(snapshot?.connections?.selected_usb_node_id) || nodes()[0] || null; }
  function isOnline(node) { return Boolean(node?.ble_reachable || node?.transport === 'USB' || node?.usb_connected || node?.online); }
  function connection(node) {
    const usbId = String(snapshot?.connections?.selected_usb_node_id || '').toLowerCase();
    if (String(node?.node_id || '').toLowerCase() === usbId) return 'USB';
    if (node?.ble_reachable) return 'BLE';
    if (snapshot?.mesh?.status === 'Online') return 'Mesh';
    return 'Offline';
  }
  function deviceType(node) { return String(node?.device_label || '').toLowerCase().includes('v3') ? 'Heltec V3' : String(node?.device_label || 'Tracker V1.1'); }
  function statusSummary() {
    const s = snapshot?.summary || {};
    return {
      total: Number(s.nodes ?? nodes().length),
      online: nodes().filter(isOnline).length,
      ble: Number(s.ble ?? nodes().filter(n => n.ble_reachable).length),
      logs: Number(s.logs_due ?? nodes().filter(n => n.log_due).length),
      updates: Number(s.updates ?? nodes().filter(n => n.update).length),
    };
  }

  async function refreshCore() {
    snapshot = await request('/api/state');
    if (!selectedNodeId) selectedNodeId = String(snapshot?.connections?.selected_usb_node_id || snapshot?.selected_node_id || nodes()[0]?.node_id || '');
    updateTopStrip();
    return snapshot;
  }

  function topChip(label, value, tone='') {
    return `<div class="neo-status-chip ${tone}"><i></i><div><strong>${esc(label)}</strong><small>${esc(value)}</small></div></div>`;
  }

  function updateTopStrip() {
    const strip = document.getElementById('v323TopStrip');
    if (!strip) return;
    const usb = snapshot?.connections?.usb || [];
    const s = statusSummary();
    strip.innerHTML = [
      topChip('USB', `${usb.length} Gerät${usb.length === 1 ? '' : 'e'}`, usb.length ? 'ok' : ''),
      topChip('BLE', `${s.ble} sichtbar`, s.ble ? 'blue' : ''),
      topChip('Mesh', snapshot?.mesh?.status || '—', snapshot?.mesh?.status === 'Online' ? 'ok' : ''),
      topChip('System', snapshot?.busy ? snapshot?.status || 'Beschäftigt' : 'Bereit', snapshot?.busy ? '' : 'ok'),
    ].join('');
  }

  function installShell() {
    const brand = document.querySelector('.brand');
    if (brand) brand.innerHTML = '<div class="neo-brand-mark" aria-label="Jarnsen Logo"></div><div><div class="brand-name">Jarnsen</div><div class="brand-subtitle">Service Tool</div></div>';
    const nav = document.getElementById('navList');
    if (nav) nav.innerHTML = [
      ['dashboard','overview','⌂','Übersicht','dashboard'],['nodes','overview','▱','Nodes','nodes'],['logs','logs','▤','Log / Diagnose',''],['firmware','firmware','⬡','Firmware',''],
      ['power','power','ϟ','Power Management',''],['profiles','service','◈','Profile',''],['network','network','⌁','Mesh / Netzwerk',''],['display','live','▣','Display',''],['tools','tools','⌘','Tools',''],['settings','settings','⚙','Einstellungen','']
    ].map(([page,view,icon,label,mode]) => `<button class="nav-item ${page === 'dashboard' ? 'active' : ''}" data-neo-page="${page}" data-view="${view}"${mode ? ` data-rd-mode="${mode}"` : ''}><span class="nav-icon">${icon}</span><span>${label}</span></button>`).join('') + '<div class="rd-hidden-nav" hidden><button class="nav-item" data-view="details">Node-Details</button><button class="nav-item" data-view="diagnostics">Diagnose</button><button class="nav-item" data-view="map">Karte</button><button class="nav-item" data-view="series">Neue Nodes</button></div>';
    const topbar = document.querySelector('.topbar');
    if (topbar) topbar.innerHTML = `<div id="v323TopStrip"></div><div class="search-shell"><span class="search-symbol">⌕</span><input id="globalSearch" type="search" placeholder="Nach Nodes, Aktionen oder Einstellungen suchen …" autocomplete="off"></div><div class="top-actions"><button class="button primary-action" id="scanBleButton">↻ Scannen</button><button class="button quiet-action" id="activityButton">Aktivität</button><div class="top-status-pill"><span class="status-dot ok"></span><strong id="visibleBleCount">0</strong></div><button class="button icon-button" id="themeButton">◐</button></div>`;
  }

  function neutralizeOldRenderer() {
    if (window.JarnsenVisualParityV323) {
      window.JarnsenVisualParityV323.renderCurrent = () => {};
      window.JarnsenVisualParityV323.refresh = () => {};
    }
    const proxy = document.createElement('button');
    proxy.type = 'button'; proxy.className = 'neo-hidden-proxy'; proxy.dataset.view = 'logs';
    document.body.appendChild(proxy); proxy.click(); proxy.remove();
  }

  function setActive(page) {
    currentPage = page;
    document.body.dataset.redesignPage = page === 'profiles' ? 'service' : page === 'display' ? 'live' : page;
    document.querySelectorAll('.nav-item[data-neo-page]').forEach(btn => btn.classList.toggle('active', btn.dataset.neoPage === page));
  }

  function head(title, subtitle, actions='') {
    return `<div class="neo-page-head"><div><span class="neo-eyebrow">JARNSEN SERVICE TOOL</span><h1>${esc(title)}</h1><p>${esc(subtitle)}</p></div><div class="neo-head-actions">${actions}</div></div>`;
  }

  function panel(title, subtitle, body, cls='') {
    return `<section class="neo-panel ${cls}"><div class="neo-panel-head"><div><h2>${esc(title)}</h2>${subtitle ? `<span>${esc(subtitle)}</span>` : ''}</div></div><div class="neo-panel-body">${body}</div></section>`;
  }

  function actionButton(label, action, cls='') { return `<button class="neo-btn ${cls}" data-neo-action="${action}">${label}</button>`; }

  function renderDashboard() {
    setActive('dashboard');
    const s = statusSummary();
    const usb = snapshot?.connections?.usb || [];
    const rows = nodes().slice(0,5).map((n,i) => `<div class="neo-activity-row"><i style="background:${i===0?'#31df7b':'#1687ff'}"></i><time>${fmtTime(n.captured_at)}</time><span>${esc(n.long_name || n.node_id)} · ${esc(connection(n))} · ${esc(n.sync_state || 'Bereit')}</span></div>`).join('') || '<div class="neo-empty">Noch keine Aktivität</div>';
    const storage = snapshot?.storage || {};
    const storageRows = [['Logs',storage.logs_percent],['Firmware',storage.firmware_percent],['Sonstiges',storage.other_percent],['Frei',storage.free_percent]].map(([label,value]) => `<div class="neo-storage-row"><span>${label}</span><div class="neo-bar"><i style="width:${Number(value || 0)}%"></i></div><b>${value == null ? '—' : `${Math.round(Number(value))}%`}</b></div>`).join('');
    host.innerHTML = `<div class="neo-page neo-dashboard rd-v323-dashboard rd-v323-shell">
      ${head('Guten Tag!','Willkommen im JARNSEN Service Tool. Verwalten, diagnostizieren, konfigurieren – bereit für den Einsatz.')}
      <div class="neo-hero"><h2>Ein Netzwerk. Mehr Möglichkeiten.</h2><p>USB zuerst, BLE als Fallback, Mesh im Blick – alle Wartungsfunktionen in einer Oberfläche.</p><div class="neo-hero-badge">Alle Systeme ${snapshot?.busy ? 'beschäftigt' : 'bereit'}<br><span style="color:#49e78b">●</span> ${usb.length} USB · ${s.ble} BLE</div></div>
      <div class="neo-kpis v323-metrics">
        <div class="neo-kpi v323-metric"><div class="neo-kpi-icon">△</div><div><strong>${s.total}</strong><span>Nodes gesamt</span><small>verwaltet</small></div></div>
        <div class="neo-kpi green v323-metric"><div class="neo-kpi-icon">✓</div><div><strong>${s.online}</strong><span>Online</span><small>${Math.max(0,s.total-s.online)} offline/sleep</small></div></div>
        <div class="neo-kpi purple v323-metric"><div class="neo-kpi-icon">▤</div><div><strong>${s.logs}</strong><span>Logs fällig</span><small>Download verfügbar</small></div></div>
        <div class="neo-kpi orange v323-metric"><div class="neo-kpi-icon">⬡</div><div><strong>${s.updates}</strong><span>Updates</span><small>Firmware prüfen</small></div></div>
      </div>
      <div class="neo-dashboard-main">
        ${panel('Schnellaktionen','Häufige Aufgaben',`<div class="neo-quick v323-quick-grid"><button data-neo-action="scan"><b>◌</b>Scannen</button><button data-neo-page="firmware"><b>⬡</b>Firmware Update</button><button data-neo-page="logs"><b>▤</b>Logs laden</button><button data-neo-page="profiles"><b>◈</b>Profile verwalten</button><button data-neo-page="network"><b>⌁</b>Mesh konfigurieren</button><button data-neo-action="configure-selected"><b>⚙</b>Node konfigurieren</button></div>`)}
        ${panel('Speicher & Daten','lokale Service-Daten',storageRows)}
        ${panel('Letzte Aktivitäten','automatische und manuelle Vorgänge',`<div class="neo-activity">${rows}</div>`)}
        ${panel('Systemstatus','Transport und Updatezustand',`<div class="neo-stat-list"><div class="neo-stat"><span>USB</span><strong>${usb.length} Gerät(e)</strong></div><div class="neo-stat"><span>BLE</span><strong>${s.ble} sichtbar</strong></div><div class="neo-stat"><span>Mesh</span><strong>${esc(snapshot?.mesh?.status || '—')}</strong></div><div class="neo-stat"><span>Backend</span><strong>${esc(snapshot?.backend_version || 'bereit')}</strong></div></div>`)}
      </div><div class="neo-footer-note">connect · track · explore</div>
    </div>`;
  }

  function filteredNodes() {
    const q = String(document.getElementById('neoNodeSearch')?.value || '').trim().toLowerCase();
    return nodes().filter(n => {
      if (nodeFilter === 'online' && !isOnline(n)) return false;
      if (nodeFilter === 'offline' && isOnline(n)) return false;
      if (nodeFilter === 'usb' && connection(n) !== 'USB') return false;
      if (nodeFilter === 'ble' && connection(n) !== 'BLE') return false;
      if (!q) return true;
      return [n.node_id,n.long_name,n.short_name,n.device_label,n.firmware].some(v => String(v||'').toLowerCase().includes(q));
    });
  }

  function nodeRow(n) {
    const conn = connection(n); const online = isOnline(n); const battery = n.battery == null ? '—' : `${Math.round(Number(n.battery))}%`;
    return `<div class="neo-node-table v323-node-table v323-node-row" data-node-id="${esc(n.node_id)}"><div><input type="checkbox" data-neo-select-node="${esc(n.node_id)}"></div><div class="neo-node-name"><div class="neo-device-thumb"></div><div><strong>${esc(n.node_id)}</strong><small>${esc(n.long_name || n.short_name || 'Unbenannte Node')}</small><span class="neo-badge">${esc(deviceType(n))}</span></div></div><div><span class="neo-badge ${conn==='USB'?'green':''}">${esc(conn)}</span></div><div><strong>${battery}</strong><small style="display:block;color:#6e8aa3">${n.voltage == null ? '—' : `${Number(n.voltage).toFixed(2)} V`}</small></div><div><strong>${esc(n.firmware || '—')}</strong><small style="display:block;color:#6e8aa3">${esc(n.build || '')}</small></div><div><span class="neo-status-dot ${online?'ok':''}"></span>${online?'Online':'Offline'}</div><div>${fmtTime(n.captured_at || n.last_seen)}<small style="display:block;color:#6e8aa3">${n.position ? 'Position vorhanden' : '—'}</small></div><div><button class="neo-row-action" data-action="inspect" data-node="${esc(n.node_id)}" title="Auswählen">›</button><button class="neo-hidden-proxy" data-action="log" data-node="${esc(n.node_id)}"></button></div></div>`;
  }

  function renderNodes() {
    setActive('nodes'); const list = filteredNodes(); const s = statusSummary();
    host.innerHTML = `<div class="neo-page neo-nodes rd-v323-nodes rd-v323-shell">
      ${head('Nodes','Alle verbundenen und verwalteten Geräte im Überblick.',`<input class="neo-search" id="neoNodeSearch" placeholder="Nodes durchsuchen …"><button class="neo-btn primary" data-neo-action="scan">↻ Scannen</button>`)}
      <div class="neo-toolbar"><div class="neo-filter-row">${[['all','Alle'],['online','Online'],['offline','Offline'],['usb','USB'],['ble','BLE']].map(([id,label])=>`<button class="neo-filter ${nodeFilter===id?'active':''}" data-neo-filter="${id}">${label}${id==='all'?` (${s.total})`:''}</button>`).join('')}</div><div class="neo-head-actions">${actionButton('Logs laden','bulk-log')}${actionButton('Firmware Update','bulk-ota')}${actionButton('Konfigurieren','configure-selected')}</div></div>
      <div class="neo-table-shell v323-table-shell"><div class="neo-node-table v323-node-table v323-table-head"><div></div><div>Node / Name</div><div>Verbindung</div><div>Akku</div><div>Firmware</div><div>Status</div><div>Letzter Kontakt</div><div></div></div>${list.length ? list.map(nodeRow).join('') : '<div class="neo-empty">Keine Nodes für diesen Filter.</div>'}</div>
      <div class="neo-footer-note">${list.length} Nodes angezeigt · USB wird automatisch bevorzugt</div>
    </div>`;
  }

  function renderDetails() {
    setActive('details'); const n = selectedNode();
    if (!n) { host.innerHTML = `<div class="neo-page">${head('Node Details','Wähle zuerst eine Node aus.')}${panel('Keine Node','', '<div class="neo-empty">Keine Node ausgewählt</div>')}</div>`; return; }
    const p = n.position || {}; const metrics = n.metrics || {};
    host.innerHTML = `<div class="neo-page neo-details rd-v323-shell">
      <div class="neo-details-head"><div class="neo-node-identity"><div class="neo-device-thumb"></div><div><span class="neo-eyebrow">NODE DETAILS</span><h1>${esc(n.node_id)}</h1><p>${esc(n.long_name || n.short_name || '')} · ${esc(deviceType(n))}</p><span class="neo-badge ${connection(n)==='USB'?'green':''}">${esc(connection(n))}</span> <span class="neo-badge ${isOnline(n)?'green':'gray'}">${isOnline(n)?'Online':'Offline'}</span></div></div><div class="neo-head-actions">${actionButton('← Nodes','nodes-page')}${actionButton('Log laden','log-selected','primary')}</div></div>
      <div class="neo-detail-tabs"><button class="neo-tab active">Übersicht</button><button class="neo-tab">Position</button><button class="neo-tab">System</button><button class="neo-tab">Power</button><button class="neo-tab">Logs</button><button class="neo-tab">Konfiguration</button></div>
      <div class="neo-details-grid">
        ${panel('Geräteinformationen','Identität & Firmware',`<div class="neo-stat-list"><div class="neo-stat"><span>Gerätename</span><strong>${esc(n.long_name || '—')}</strong></div><div class="neo-stat"><span>Typ</span><strong>${esc(deviceType(n))}</strong></div><div class="neo-stat"><span>Firmware</span><strong>${esc(n.firmware || '—')}</strong></div><div class="neo-stat"><span>Hardware</span><strong>${esc(n.build || n.hardware || '—')}</strong></div><div class="neo-stat"><span>Letzter Kontakt</span><strong>${fmtTime(n.captured_at || n.last_seen)}</strong></div><div class="neo-stat"><span>Transport</span><strong>${esc(connection(n))}</strong></div></div>`)}
        ${panel('Akku & Status','Live-Zustand',`<div class="neo-kpi green" style="height:78px"><div class="neo-kpi-icon">▯</div><div><strong>${pct(n.battery)}</strong><span>${n.voltage == null ? 'Spannung unbekannt' : `${Number(n.voltage).toFixed(2)} V`}</span><small>${esc(n.charge_state || 'Ladezustand')}</small></div></div><div class="neo-stat-list"><div class="neo-stat"><span>GPS</span><strong>${p.latitude != null ? 'Position vorhanden' : '—'}</strong></div><div class="neo-stat"><span>Signal</span><strong>${esc(metrics.snr ?? n.snr ?? '—')}</strong></div></div>`)}
        ${panel('Position','GPS / letzte bekannte Position',`<div class="neo-map-mini"><i class="neo-map-pin"></i></div><div class="neo-stat-list"><div class="neo-stat"><span>Breite</span><strong>${p.latitude == null ? '—' : Number(p.latitude).toFixed(5)}</strong></div><div class="neo-stat"><span>Länge</span><strong>${p.longitude == null ? '—' : Number(p.longitude).toFixed(5)}</strong></div></div>`)}
      </div>
      <div class="neo-detail-actions">${actionButton('Live-Ansicht','display-page','green')}${actionButton('Log laden','log-selected','primary')}${actionButton('Neustarten','wake-selected','orange')}${actionButton('Power','power-page','purple')}${actionButton('Mehr …','tools-page')}</div>
    </div>`;
  }

  function renderLogs() {
    setActive('logs'); const list = nodes();
    const rows = list.map((n,i)=>`<div class="neo-log-row"><div><input type="checkbox"></div><div class="neo-node-name"><div class="neo-device-thumb"></div><div><strong>${esc(n.node_id)}</strong><small>${esc(n.long_name || '')}</small></div></div><div>${n.log_due?'Log fällig':'Bereit'}</div><div><div class="neo-progress"><i style="width:${i===0&&n.log_due?'66':'0'}%"></i></div></div><div>${n.log_size || '—'}</div><div><button class="neo-row-action" data-action="log" data-node="${esc(n.node_id)}">↓</button> <button class="neo-row-action" data-neo-action="details-node" data-node="${esc(n.node_id)}">›</button></div></div>`).join('');
    host.innerHTML = `<div class="neo-page rd-v323-shell">${head('Logs & Diagnose','Logs herunterladen, analysieren und Probleme schnell erkennen.',`${actionButton('Diagnosepaket','diagnostic-bundle')}`)}<div class="neo-tabs"><button class="neo-tab active">Logdownload</button><button class="neo-tab">Analyse</button><button class="neo-tab">Diagnose</button><button class="neo-tab">Verlauf</button></div><div class="neo-logs-grid">${panel('Logdownload','USB bevorzugt · BLE als Fallback',`<div>${rows}</div><div class="neo-head-actions" style="margin-top:10px">${actionButton('+ Weitere Nodes','nodes-page')}${actionButton('Download abbrechen','noop','danger')}</div>`)}${panel('Schnell-Analyse','letzte Diagnoseergebnisse',`<div class="neo-analyse-list"><div class="neo-analyse-row"><span>Fehler</span><strong style="color:#31df7b">0</strong></div><div class="neo-analyse-row"><span>Warnungen</span><strong style="color:#ff9e3d">${snapshot?.summary?.warnings ?? 0}</strong></div><div class="neo-analyse-row"><span>Hinweise</span><strong>${statusSummary().logs}</strong></div></div><div style="margin-top:10px">${actionButton('Analyse starten','diagnostic-bundle','primary')}</div>`)} </div></div>`;
  }

  async function loadServiceStatus() { try { serviceStatus = await request('/api/service-status'); } catch (_) { serviceStatus = {}; } return serviceStatus; }

  function renderFirmware() {
    setActive('firmware'); const n = selectedNode(); const available = snapshot?.github?.remote_version || serviceStatus?.app_update?.remote_version || '—';
    host.innerHTML = `<div class="neo-page rd-v323-shell">${head('Firmware','Firmware-Versionen verwalten, vergleichen und sicher aufspielen.')}<div class="neo-tabs"><button class="neo-tab active">Update</button><button class="neo-tab" data-neo-action="serial-flash-focus">Seriell flashen</button><button class="neo-tab">OTA (BLE)</button><button class="neo-tab">Versionsvergleich</button></div><div class="neo-firmware-grid">${panel('Aktuelle Firmware','ausgewählte Node',`<div class="neo-stat-list"><div class="neo-stat"><span>Version</span><strong>${esc(n?.firmware || '—')}</strong></div><div class="neo-stat"><span>Build</span><strong>${esc(n?.build || '—')}</strong></div><div class="neo-stat"><span>Gerät</span><strong>${esc(n?.device_label || '—')}</strong></div><div class="neo-stat"><span>Status</span><strong style="color:#31df7b">${n?.update?'Update verfügbar':'Aktuell'}</strong></div></div>`)}${panel('Verfügbare Version','GitHub / Updatequelle',`<div class="neo-stat-list"><div class="neo-stat"><span>Version</span><strong>${esc(available)}</strong></div><div class="neo-stat"><span>Quelle</span><strong>GitHub</strong></div></div><div style="margin-top:10px">${actionButton('Update prüfen','firmware-check','primary')}</div>`)}${panel('Zielgeräte','Mehrfachauswahl möglich',nodes().map(x=>`<label class="neo-switch"><span>${esc(x.node_id)} · ${esc(connection(x))}</span><input type="checkbox" data-neo-fw-target="${esc(x.node_id)}" ${x===n?'checked':''}></label>`).join(''))}${panel('Update-Methode','USB zuerst',`<label class="neo-switch"><span>Automatisch (empfohlen)</span><input type="radio" name="neoFwMethod" checked></label><label class="neo-switch"><span>OTA über BLE</span><input type="radio" name="neoFwMethod"></label><label class="neo-switch"><span>Seriell (USB)</span><input type="radio" name="neoFwMethod"></label><div class="neo-head-actions" style="margin-top:10px">${actionButton('Firmware aktualisieren','ota-selected','primary')}${actionButton('Seriell flashen','serial-flash','orange')}</div>`)} </div></div>`;
  }

  async function loadProfiles() { const data = await request('/api/profiles').catch(()=>({profiles:[]})); profiles = Array.isArray(data.profiles)?data.profiles:[]; if (!profiles.some(p=>Number(p.slot)===profileSlot&&!p.empty)) profileSlot=Number(profiles.find(p=>!p.empty)?.slot||0); return profiles; }
  async function profileSection(slot,kind,name) { try { const r=await request(`/api/profile/${Number(slot)}/${encodeURIComponent(kind)}/${encodeURIComponent(name)}`); return r?.data&&typeof r.data==='object'?r.data:{}; } catch(_) { return {}; } }
  function flatten(obj,prefix='') { const out=[]; Object.entries(obj||{}).forEach(([k,v])=>{const path=prefix?`${prefix}.${k}`:k;if(v!==null&&typeof v==='object'&&!Array.isArray(v))out.push(...flatten(v,path));else out.push({path,value:v,kind:Array.isArray(v)?'array':typeof v});});return out; }
  function setByPath(target,path,value){const parts=String(path).split('.');let cur=target;parts.forEach((p,i)=>{if(i===parts.length-1)cur[p]=value;else{if(!cur[p]||typeof cur[p]!=='object'||Array.isArray(cur[p]))cur[p]={};cur=cur[p];}});}
  function clone(v){try{return structuredClone(v)}catch(_){return JSON.parse(JSON.stringify(v||{}));}}
  function fieldLabel(path){const key=String(path).split('.').at(-1);const map={is_power_saving:'Power Saving',wait_bluetooth_secs:'Bluetooth nach Start',ls_secs:'Light Sleep',sds_secs:'Deep Sleep',min_wake_secs:'Min. Wachzeit',position_broadcast_secs:'GPS-Intervall (Stand)',smart_position_enabled:'Smart Position',broadcast_smart_minimum_distance:'Mindestdistanz Bewegung',gps_update_interval:'GPS Update',region:'Region',modem_preset:'Modem-Preset',override_frequency:'Frequenz',tx_power:'Sendeleistung',hop_limit:'Hop-Limit'};return map[key]||key.replaceAll('_',' ');}
  function formFields(obj,group){return flatten(obj).map(row=>{const attr=`data-neo-field="${esc(row.path)}" data-neo-kind="${esc(row.kind)}" data-neo-group="${group}"`;if(row.kind==='boolean')return `<label class="neo-switch"><span>${esc(fieldLabel(row.path))}</span><input type="checkbox" ${attr} ${row.value?'checked':''}></label>`;return `<label class="neo-field"><span>${esc(fieldLabel(row.path))}</span><input ${attr} type="${row.kind==='number'?'number':'text'}" ${row.kind==='number'?'step="any"':''} value="${esc(Array.isArray(row.value)?JSON.stringify(row.value):(row.value??''))}"></label>`;}).join('') || '<div class="neo-empty">Keine Werte in diesem Profilabschnitt.</div>';}
  function readGroup(group,original){const next=clone(original);host.querySelectorAll(`[data-neo-group="${group}"][data-neo-field]`).forEach(input=>{let v;if(input.dataset.neoKind==='boolean')v=Boolean(input.checked);else if(input.dataset.neoKind==='number')v=Number(input.value);else if(input.dataset.neoKind==='array'){try{v=JSON.parse(input.value||'[]')}catch(_){v=[]}}else v=input.value;setByPath(next,input.dataset.neoField,v);});return next;}

  async function renderPower() {
    setActive('power'); await loadProfiles();
    [powerOriginal,positionOriginal]=await Promise.all([profileSection(profileSlot,'config','power'),profileSection(profileSlot,'config','position')]);
    const n=selectedNode();
    host.innerHTML=`<div class="neo-page rd-power-page rd-v323-shell">${head('Power Management','Energieverbrauch optimieren und Verhalten in Standby steuern.',`<select class="neo-btn" id="neoPowerProfile">${profiles.filter(p=>!p.empty).map(p=>`<option value="${p.slot}" ${Number(p.slot)===profileSlot?'selected':''}>${esc(p.name||`Profil ${Number(p.slot)+1}`)}</option>`).join('')}</select>`)}<div class="neo-tabs"><button class="neo-tab active">Einstellungen</button><button class="neo-tab">Zeitpläne</button><button class="neo-tab">Deep/Light Sleep</button><button class="neo-tab">Anzeige/LED</button></div><div class="neo-power-grid">${panel('Allgemein','Power & Sleep',`<div class="neo-form-grid">${formFields(powerOriginal,'power')}</div><div style="margin-top:10px">${actionButton('Power speichern','save-power','primary').replace('data-neo-action="save-power"','data-neo-action="save-power" data-rd-save="power" data-neo-save-section="power"')}</div>`)}${panel('GPS & Bewegung','Positions- und Wakeup-Verhalten',`<div class="neo-form-grid">${formFields(positionOriginal,'position')}</div><div style="margin-top:10px">${actionButton('Position speichern','save-position','primary')}</div>`)}${panel('Akku & Spannung','aktuelle Node',`<div class="neo-kpi green" style="height:80px"><div class="neo-kpi-icon">▯</div><div><strong>${pct(n?.battery)}</strong><span>${n?.voltage==null?'—':`${Number(n.voltage).toFixed(2)} V`}</span><small>${esc(n?.charge_state||'Ladezustand')}</small></div></div><div class="neo-chart"><svg viewBox="0 0 300 120"><line x1="0" y1="30" x2="300" y2="30"/><line x1="0" y1="60" x2="300" y2="60"/><line x1="0" y1="90" x2="300" y2="90"/><polyline points="0,32 45,31 90,31 135,32 170,38 205,31 250,30 300,30"/></svg></div>`)}${panel('Ziel','Anwenden auf Node',`<div class="neo-stat-list"><div class="neo-stat"><span>Node</span><strong>${esc(n?.long_name||n?.node_id||'—')}</strong></div><div class="neo-stat"><span>Transport</span><strong>${esc(n?connection(n):'—')}</strong></div></div><div style="margin-top:10px">${actionButton('Einstellungen auf Node übertragen','apply-profile','primary')}</div>`)} </div></div>`;
  }

  async function renderProfiles() {
    setActive('profiles'); await loadProfiles(); const n=selectedNode();
    const cards=profiles.slice(0,4).map(p=>`<div class="neo-profile-card ${Number(p.slot)===profileSlot?'active':''}" data-neo-profile-slot="${p.slot}"><div class="neo-profile-icon">${p.empty?'+':'◈'}</div><strong>${esc(p.name||`Profil ${Number(p.slot)+1}`)}</strong><p>${p.empty?'Leer – Profil erfassen':'Gespeichertes Grundprofil'}</p><span class="neo-badge ${Number(p.slot)===profileSlot?'green':''}">${Number(p.slot)===profileSlot?'Aktiv':'Profil'}</span></div>`).join('');
    host.innerHTML=`<div class="neo-page rd-v323-shell">${head('Profile','Vordefinierte Profile für verschiedene Einsatzszenarien.')}<div class="neo-tabs"><button class="neo-tab active">Vordefinierte Profile</button><button class="neo-tab">Eigene Profile</button><button class="neo-tab">Import / Export</button></div><div class="neo-profiles">${cards}</div><div class="neo-special-grid"><div class="neo-special"><b>Standard</b><small>normale Region / Preset</small></div><div class="neo-special"><b>Jarnsen 1</b><small>Spezialfrequenz A · Primär</small></div><div class="neo-special"><b>Jarnsen 2</b><small>Spezialfrequenz B · Reserve</small></div></div><div class="neo-head-actions" style="margin-top:12px">${actionButton('Profil von Node erfassen','capture-profile')}${actionButton(`Auf ${esc(n?.long_name||'ausgewählte Node')} übertragen`,'apply-profile','primary')}</div></div>`;
  }

  function currentRadioMode(){const f=Number(loraOriginal?.override_frequency||0);const hz=Math.round(f*1e6);if(hz&&hz===Number(radioAuth?.frequency_a_hz||0))return'jarnsen1';if(hz&&hz===Number(radioAuth?.frequency_b_hz||0))return'jarnsen2';return'standard';}
  async function renderNetwork(){setActive('network');await loadProfiles();[loraOriginal,radioAuth]=await Promise.all([profileSection(profileSlot,'config','lora'),request('/api/radio-authorization').catch(()=>({}))]);const mode=currentRadioMode();const neighbors=(snapshot?.mesh?.neighbors||nodes().slice(0,3)).slice(0,4);host.innerHTML=`<div class="neo-page rd-network-page rd-v323-shell">${head('Mesh / Netzwerk','Netzwerk- und Funk-Einstellungen verwalten.')}<div class="neo-tabs"><button class="neo-tab active">Netzwerk</button><button class="neo-tab">Funk / LoRa</button><button class="neo-tab">Spezialfrequenzen</button><button class="neo-tab">Nachbarn</button></div><div class="neo-network-grid">${panel('Funkprofil','Standard oder autorisierte Spezialfrequenz',`<div class="neo-radio-modes"><button class="neo-radio-mode ${mode==='standard'?'active':''}" data-rd-radio-mode="standard">Standard<br><small>Region / Preset</small></button><button class="neo-radio-mode ${mode==='jarnsen1'?'active':''}" data-rd-radio-mode="jarnsen1">Jarnsen 1<br><small>Primärfrequenz</small></button><button class="neo-radio-mode ${mode==='jarnsen2'?'active':''}" data-rd-radio-mode="jarnsen2">Jarnsen 2<br><small>Reservefrequenz</small></button></div><div class="neo-form-grid">${formFields(loraOriginal,'lora')}</div><div style="margin-top:10px">${actionButton('Funkwerte speichern','save-lora','primary')}</div>`)}${panel('Spezialfrequenzen','Werte aus der vorhandenen Autorisierungslogik',`<div class="neo-form-grid"><label class="neo-field"><span>Jarnsen 1 · Primär</span><input id="rdFreqA" value="${esc(radioAuth?.frequency_a_mhz??'—')}" readonly></label><label class="neo-field"><span>Jarnsen 2 · Reserve</span><input id="rdFreqB" value="${esc(radioAuth?.frequency_b_mhz??'—')}" readonly></label></div><p style="font-size:8px;color:#708aa1">Keine automatische Umschaltung: das gesamte Mesh nutzt gemeinsam Standard, Jarnsen 1 oder Jarnsen 2.</p>`)}${panel(`Nachbarn (${neighbors.length})`,'Mesh-Sichtbarkeit',neighbors.map((x,i)=>`<div class="neo-neighbor"><span class="neo-status-dot ok"></span><span>${esc(x.long_name||x.node_id||`Nachbar ${i+1}`)}</span><strong>${esc(x.rssi??x.snr??'—')}</strong></div>`).join('')||'<div class="neo-empty">Keine Nachbarn gemeldet</div>')}${panel('Mesh-Topologie','vereinfachte Übersicht',`<div class="neo-mesh-graphic"><i class="neo-mesh-node" style="left:48%;top:42%"></i><i class="neo-mesh-node" style="left:18%;top:65%"></i><i class="neo-mesh-node" style="left:76%;top:68%"></i><i class="neo-mesh-node" style="left:72%;top:12%"></i></div><div style="margin-top:8px">${actionButton('Einstellungen auf Nodes übertragen','apply-profile','primary')}</div>`)} </div></div>`;}

  function renderDisplay(){setActive('display');const n=selectedNode();host.innerHTML=`<div class="neo-page rd-v323-shell">${head('Display','Live-Ansicht und Fernsteuerung der Display-Seiten.')}<div class="neo-display-grid">${panel('Live-Ansicht',n?.long_name||n?.node_id||'Keine Node',`<div class="neo-display-shell"><div class="neo-display-screen"><span>GPS</span><strong>${n?.position?.latitude==null?'—':Number(n.position.latitude).toFixed(4)} N</strong><strong>${n?.position?.longitude==null?'—':Number(n.position.longitude).toFixed(4)} E</strong><span>${esc(n?.long_name||'JARNSEN')}</span></div></div><div class="neo-head-actions" style="margin-top:8px">${actionButton('Live verbinden','live-start','green')}${actionButton('Trennen','live-stop')}</div>`)}${panel('Display-Steuerung','Seiten und Wakeup',`<div class="neo-remote">${['Nächste Seite','Vorherige Seite','Display an','Screenshot','Wakeup','Live groß'].map((x,i)=>`<button class="neo-btn ${i===0?'primary':''}" data-neo-live="${['NEXT','PREV','WAKE','SCREENSHOT','WAKE','START'][i]}">${x}</button>`).join('')}</div>`)} </div><div class="neo-pages-preview"><div class="neo-page-preview">1<br>GPS / MGRS</div><div class="neo-page-preview">2<br>Position</div><div class="neo-page-preview">3<br>Funk / LoRa</div><div class="neo-page-preview">4<br>Nachbarn</div><div class="neo-page-preview">5<br>System/Akku</div></div><div class="neo-footer-note">Live · pixelgenaue 128×64 Ansicht, sofern vom Gerät geliefert</div></div>`;}

  function renderTools(){setActive('tools');const items=[['◌','Geräte scannen','USB, BLE und Netzwerk','scan'],['⚙','Node konfigurieren','Kanäle, Module, Parameter','configure-selected'],['▤','Diagnose Export','Logs & Snapshot','diagnostic-bundle'],['▱','Datenbank','Lokale Node-Daten','noop'],['⌂','GitHub prüfen','Auf Updates überprüfen','firmware-check'],['✓','Self-Check','Status und Tests','diagnostic-bundle'],['⬡','Seriell flashen','Recovery + OTA-Loader','serial-flash'],['◈','Profile','Grundprofile verwalten','profiles-page'],['⌁','Mesh','Funk & Spezialfrequenzen','network-page']];host.innerHTML=`<div class="neo-page rd-v323-shell">${head('Tools','Zusätzliche Funktionen und Dienstprogramme.')}<div class="neo-tools-grid">${items.map(([icon,title,sub,action])=>`<div class="neo-tool-card" data-neo-action="${action}"><b>${icon}</b><div><strong>${title}</strong><span>${sub}</span></div></div>`).join('')}</div></div>`;}

  function renderSettings(){setActive('settings');host.innerHTML=`<div class="neo-page rd-v323-shell">${head('Einstellungen','Allgemeine Einstellungen und Optionen.')}<div class="neo-settings-grid">${panel('Bereiche','',`<div class="neo-settings-nav"><button class="active">Allgemein</button><button>Verbindung</button><button>Oberfläche</button><button>Daten</button><button>Erweitert</button></div>`)}${panel('Allgemein','Service Tool',`<div class="neo-setting-row"><div><span>Sprache</span><small>Oberflächensprache</small></div><select><option>Deutsch</option></select></div><div class="neo-setting-row"><div><span>Design</span><small>Neues dunkles JARNSEN Design</small></div><select><option>Dunkel</option></select></div><div class="neo-setting-row"><div><span>Beim Start auf Updates prüfen</span><small>GitHub automatisch prüfen</small></div><label class="neo-switch"><input type="checkbox" checked></label></div><div class="neo-setting-row"><div><span>Automatisch nach neuem Log fragen</span><small>Bei USB-Anstecken genau einmal pro Session</small></div><label class="neo-switch"><input type="checkbox" checked></label></div><div class="neo-setting-row"><div><span>USB vor BLE bevorzugen</span><small>Service und Logdownload</small></div><label class="neo-switch"><input type="checkbox" checked disabled></label></div><div class="neo-setting-row"><div><span>Standard-Speicherpfad</span><small>Logs, Exporte, Snapshots</small></div><input type="text" value="${esc(snapshot?.settings?.storage_path||'JARNSEN-Service-Tool')}" readonly></div><div style="margin-top:10px">${actionButton('Einstellungen speichern','noop','primary')}</div>`)} </div></div>`;}

  async function renderPage(page=currentPage){
    try{
      if(!snapshot)await refreshCore();
      if(page==='dashboard')renderDashboard();else if(page==='nodes')renderNodes();else if(page==='details')renderDetails();else if(page==='logs')renderLogs();else if(page==='firmware'){await loadServiceStatus();renderFirmware();}else if(page==='power')await renderPower();else if(page==='profiles')await renderProfiles();else if(page==='network')await renderNetwork();else if(page==='display')renderDisplay();else if(page==='tools')renderTools();else if(page==='settings')renderSettings();
    }catch(error){host.innerHTML=`<div class="neo-page">${head('Fehler','Die Seite konnte nicht geladen werden.')}${panel('Fehler','',`<div class="neo-empty">${esc(error.message||error)}</div>`)}</div>`;toast(error.message||String(error),true);}
  }

  async function apiAction(command,ids=[]){const body=await request('/api/action',{method:'POST',body:JSON.stringify({command,node_ids:ids.filter(Boolean),node_id:ids[0]||''})});toast(body.message||body.result?.message||'Aktion gestartet');setTimeout(async()=>{await refreshCore().catch(()=>{});if(['dashboard','nodes','details'].includes(currentPage))renderPage(currentPage);},500);return body;}
  async function serviceAction(command){const n=selectedNode();const usb=snapshot?.connections?.usb||[];const target=usb.length===1?usb[0]:{};const payload={command,port:target.device||'',node_id:n?.node_id||'',hardware:String(n?.device_label||'').toLowerCase().includes('v3')?'V3':'TRACKER',baud:115200};if(command==='serial_flash'&&!confirm(`Aktuelle ${payload.hardware==='V3'?'Heltec V3':'Tracker V1.1'} Firmware plus OTA-Loader über ${payload.port||'USB'} schreiben?`))return;const r=await request('/api/service/action',{method:'POST',body:JSON.stringify(payload)});toast(r.message||'Service-Aktion gestartet');}
  async function profileAction(command){const n=selectedNode();if(!n)throw new Error('Keine Node ausgewählt.');const payload={command,slot:profileSlot,node_id:n.node_id,long_name:'',short_name:'',pin:'240180',transport:'Automatisch',apply_pin:true,apply_psk:false};const r=await request('/api/profile/action',{method:'POST',body:JSON.stringify(payload)});toast(r.message||'Profilaktion gestartet');}
  async function saveProfileSection(name,group,original){const data=readGroup(group,original);await request('/api/profile/section',{method:'POST',body:JSON.stringify({slot:profileSlot,kind:'config',name,data})});if(name==='power')powerOriginal=data;if(name==='position')positionOriginal=data;if(name==='lora')loraOriginal=data;toast(`${fieldLabel(name)} gespeichert`);}
  async function liveAction(command){const n=selectedNode();if(!n)throw new Error('Keine Node ausgewählt.');const map={START:'start',STOP:'stop',NEXT:'NEXT',PREV:'PREV',WAKE:'WAKE',SCREENSHOT:'SCREENSHOT'};const c=map[command]||command;await request('/api/live/action',{method:'POST',body:JSON.stringify({command:c,node_id:n.node_id})});toast('Display-Aktion gesendet');}

  function selectedTargets(){return [...host.querySelectorAll('[data-neo-select-node]:checked')].map(x=>x.dataset.neoSelectNode);}
  function firmwareTargets(){const ids=[...host.querySelectorAll('[data-neo-fw-target]:checked')].map(x=>x.dataset.neoFwTarget);return ids.length?ids:[selectedNode()?.node_id].filter(Boolean);}

  window.addEventListener('click', event => {
    const nav=event.target.closest('[data-neo-page]');
    if(nav){event.preventDefault();event.stopImmediatePropagation();const page=nav.dataset.neoPage;setActive(page);renderPage(page);return;}
    const filter=event.target.closest('[data-neo-filter]');
    if(filter){event.preventDefault();event.stopImmediatePropagation();nodeFilter=filter.dataset.neoFilter;renderNodes();return;}
    const mode=event.target.closest('[data-rd-radio-mode]');
    if(mode&&document.body.dataset.neoUi==='v400'){event.preventDefault();event.stopImmediatePropagation();const id=mode.dataset.rdRadioMode;const freq=id==='jarnsen1'?Number(radioAuth?.frequency_a_mhz||0):id==='jarnsen2'?Number(radioAuth?.frequency_b_mhz||0):0;setByPath(loraOriginal,'override_frequency',freq);host.querySelectorAll('[data-rd-radio-mode]').forEach(b=>b.classList.toggle('active',b===mode));const input=host.querySelector('[data-neo-group="lora"][data-neo-field="override_frequency"]');if(input)input.value=String(freq);return;}
    const save=event.target.closest('[data-neo-save-section]');
    if(save){event.preventDefault();event.stopImmediatePropagation();saveProfileSection(save.dataset.neoSaveSection,save.dataset.neoSaveSection,save.dataset.neoSaveSection==='power'?powerOriginal:positionOriginal).catch(e=>toast(e.message,true));return;}
  },true);

  document.addEventListener('click', event => {
    const inspect=event.target.closest('button[data-action="inspect"][data-node]');
    if(inspect){selectedNodeId=inspect.dataset.node;setTimeout(()=>{setActive('details');renderDetails();},40);return;}
    const detail=event.target.closest('[data-neo-action="details-node"]');if(detail){selectedNodeId=detail.dataset.node;renderPage('details');return;}
    const slot=event.target.closest('[data-neo-profile-slot]');if(slot){profileSlot=Number(slot.dataset.neoProfileSlot);localStorage.setItem('jarnsen-neo-profile-slot',String(profileSlot));renderProfiles();return;}
    const live=event.target.closest('[data-neo-live]');if(live){liveAction(live.dataset.neoLive).catch(e=>toast(e.message,true));return;}
    const action=event.target.closest('[data-neo-action]');if(!action)return;const cmd=action.dataset.neoAction;
    const one=()=>[selectedNode()?.node_id].filter(Boolean);
    if(cmd==='scan')apiAction('scan_ble').catch(e=>toast(e.message,true));
    else if(cmd==='bulk-log')apiAction('download_log',selectedTargets().length?selectedTargets():one()).catch(e=>toast(e.message,true));
    else if(cmd==='bulk-ota')apiAction('ota',selectedTargets().length?selectedTargets():one()).catch(e=>toast(e.message,true));
    else if(cmd==='log-selected')apiAction('download_log',one()).catch(e=>toast(e.message,true));
    else if(cmd==='ota-selected')apiAction('ota',firmwareTargets()).catch(e=>toast(e.message,true));
    else if(cmd==='firmware-check')apiAction('firmware_check',one()).catch(e=>toast(e.message,true));
    else if(cmd==='wake-selected')apiAction('wake',one()).catch(e=>toast(e.message,true));
    else if(cmd==='diagnostic-bundle')serviceAction('diagnostic_bundle').catch(e=>toast(e.message,true));
    else if(cmd==='serial-flash'||cmd==='serial-flash-focus')serviceAction('serial_flash').catch(e=>toast(e.message,true));
    else if(cmd==='capture-profile')profileAction('capture').catch(e=>toast(e.message,true));
    else if(cmd==='apply-profile')profileAction('apply').catch(e=>toast(e.message,true));
    else if(cmd==='save-power')saveProfileSection('power','power',powerOriginal).catch(e=>toast(e.message,true));
    else if(cmd==='save-position')saveProfileSection('position','position',positionOriginal).catch(e=>toast(e.message,true));
    else if(cmd==='save-lora')saveProfileSection('lora','lora',loraOriginal).catch(e=>toast(e.message,true));
    else if(cmd==='configure-selected')renderPage('details');
    else if(cmd==='nodes-page')renderPage('nodes');
    else if(cmd==='power-page')renderPage('power');
    else if(cmd==='display-page')renderPage('display');
    else if(cmd==='tools-page')renderPage('tools');
    else if(cmd==='profiles-page')renderPage('profiles');
    else if(cmd==='network-page')renderPage('network');
    else if(cmd==='live-start')liveAction('START').catch(e=>toast(e.message,true));
    else if(cmd==='live-stop')liveAction('STOP').catch(e=>toast(e.message,true));
  });

  document.addEventListener('input', event=>{if(event.target?.id==='neoNodeSearch'&&currentPage==='nodes'){const value=event.target.value;renderNodes();const input=document.getElementById('neoNodeSearch');if(input){input.value=value;input.focus();input.setSelectionRange(value.length,value.length);}}});
  document.addEventListener('change',event=>{if(event.target?.id==='neoPowerProfile'){profileSlot=Number(event.target.value);localStorage.setItem('jarnsen-neo-profile-slot',String(profileSlot));renderPower();}});

  installShell();
  neutralizeOldRenderer();
  refreshCore().then(()=>renderDashboard()).catch(error=>toast(error.message||String(error),true));
  refreshTimer=setInterval(async()=>{if(document.hidden)return;try{await refreshCore();if(['dashboard','nodes','details'].includes(currentPage))renderPage(currentPage);}catch(_){/* keep UI usable */}},5000);
  window.addEventListener('beforeunload',()=>refreshTimer&&clearInterval(refreshTimer));
  window.JarnsenNeoUIV400={renderPage,refresh:refreshCore,get currentPage(){return currentPage;}};
})();
