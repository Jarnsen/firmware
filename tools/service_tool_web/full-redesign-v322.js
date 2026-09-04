(() => {
  'use strict';

  const params = new URLSearchParams(location.search);
  const API = params.get('api') || 'http://127.0.0.1:0';
  const TOKEN = params.get('token') || '';
  const pageHost = document.getElementById('pageHost');
  if (!pageHost) return;

  let customView = '';
  let stateSnapshot = null;
  let profileSlot = Number(localStorage.getItem('jarnsen-redesign-profile-slot') || 0);
  let powerOriginal = {};
  let positionOriginal = {};
  let loraOriginal = {};
  let radioAuth = null;

  const esc = value => String(value ?? '')
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;').replaceAll("'", '&#039;');

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

  function toast(text, error = false) {
    const old = document.getElementById('redesignToastV322');
    old?.remove();
    const node = document.createElement('div');
    node.id = 'redesignToastV322';
    node.className = `redesign-toast-v322${error ? ' error' : ''}`;
    node.textContent = text;
    document.body.appendChild(node);
    setTimeout(() => node.remove(), error ? 4800 : 2400);
  }

  function setMode(mode) {
    document.body.dataset.redesignPage = mode || '';
  }

  function selectedNode() {
    const inspector = String(document.querySelector('.inspector-sub')?.textContent || '');
    const match = inspector.match(/![0-9a-f]{8,}/i);
    if (match) {
      return (stateSnapshot?.nodes || []).find(node => String(node.node_id || '').toLowerCase() === match[0].toLowerCase()) || null;
    }
    const selected = String(stateSnapshot?.selected_node_id || stateSnapshot?.connections?.selected_usb_node_id || '').trim();
    return (stateSnapshot?.nodes || []).find(node => String(node.node_id || '').toLowerCase() === selected.toLowerCase()) || null;
  }

  async function refreshState() {
    stateSnapshot = await request('/api/state');
    return stateSnapshot;
  }

  async function loadProfiles() {
    const data = await request('/api/profiles');
    const profiles = Array.isArray(data.profiles) ? data.profiles : [];
    const available = profiles.filter(profile => !profile.empty);
    if (available.length && !available.some(profile => Number(profile.slot) === profileSlot)) {
      profileSlot = Number(available[0].slot);
    }
    localStorage.setItem('jarnsen-redesign-profile-slot', String(profileSlot));
    return { profiles, available };
  }

  async function profileSection(slot, kind, name) {
    try {
      const section = await request(`/api/profile/${Number(slot)}/${encodeURIComponent(kind)}/${encodeURIComponent(name)}`);
      return section?.data && typeof section.data === 'object' ? section.data : {};
    } catch (_error) {
      return {};
    }
  }

  function clone(value) {
    try { return structuredClone(value); } catch (_error) { return JSON.parse(JSON.stringify(value || {})); }
  }

  function flatten(value, prefix = '') {
    const rows = [];
    Object.entries(value || {}).forEach(([key, item]) => {
      const path = prefix ? `${prefix}.${key}` : key;
      if (item !== null && typeof item === 'object' && !Array.isArray(item)) rows.push(...flatten(item, path));
      else rows.push({ path, value: item, kind: Array.isArray(item) ? 'array' : typeof item });
    });
    return rows;
  }

  function setByPath(target, path, value) {
    const parts = String(path).split('.');
    let cursor = target;
    parts.forEach((part, index) => {
      if (index === parts.length - 1) cursor[part] = value;
      else {
        if (!cursor[part] || typeof cursor[part] !== 'object' || Array.isArray(cursor[part])) cursor[part] = {};
        cursor = cursor[part];
      }
    });
  }

  const labels = {
    is_power_saving: 'Power Saving', on_battery_shutdown_after_secs: 'Akku-Abschaltung nach', adc_multiplier_override: 'ADC-Multiplikator',
    wait_bluetooth_secs: 'Bluetooth aktiv nach Start', sds_secs: 'Super Deep Sleep', ls_secs: 'Light Sleep', min_wake_secs: 'Minimale Wachzeit',
    position_broadcast_secs: 'Positionsintervall', smart_position_enabled: 'Smart Position', broadcast_smart_minimum_distance: 'Mindestdistanz Bewegung',
    broadcast_smart_minimum_interval_secs: 'Min. Sendeintervall Bewegung', gps_update_interval: 'GPS Update-Intervall', gps_attempt_time: 'GPS Fix-Zeit',
    fixed_position: 'Feste Position', gps_mode: 'GPS-Modus', position_flags: 'Positionsdaten',
    region: 'Region', modem_preset: 'Modem-Preset', channel_num: 'Frequenz-Slot', override_frequency: 'Frequenz-Override', tx_power: 'Sendeleistung',
    hop_limit: 'Hop-Limit', use_preset: 'Preset verwenden', tx_enabled: 'Senden aktiviert', bandwidth: 'Bandbreite', spread_factor: 'Spread Factor',
    coding_rate: 'Coding Rate', frequency_offset: 'Frequenz-Offset', override_duty_cycle: 'Duty-Cycle-Override', sx126x_rx_boosted_gain: 'RX Boosted Gain',
  };

  const unitFor = path => {
    const key = String(path).split('.').at(-1);
    if (/secs$|interval|attempt_time/.test(key)) return 's';
    if (/distance/.test(key)) return 'm';
    if (key === 'override_frequency' || key === 'frequency_offset') return 'MHz';
    if (key === 'tx_power') return 'dBm';
    return '';
  };

  function niceLabel(path) {
    const key = String(path).split('.').at(-1);
    return labels[key] || key.replaceAll('_', ' ').replace(/\b\w/g, char => char.toUpperCase());
  }

  function field(row, group) {
    const id = `${group}-${row.path.replace(/[^a-z0-9_-]+/gi, '-')}`;
    const common = `data-rd-field="${esc(row.path)}" data-rd-kind="${esc(row.kind)}" data-rd-group="${group}"`;
    if (row.kind === 'boolean') {
      return `<label class="rd-switch-field" for="${id}"><span><strong>${esc(niceLabel(row.path))}</strong><small>${esc(row.path)}</small></span><input id="${id}" ${common} type="checkbox" ${row.value ? 'checked' : ''}><i></i></label>`;
    }
    if (row.kind === 'array') {
      return `<label class="rd-form-field rd-wide"><span>${esc(niceLabel(row.path))}</span><textarea id="${id}" ${common} rows="3">${esc(JSON.stringify(row.value))}</textarea><small>${esc(row.path)}</small></label>`;
    }
    const type = row.kind === 'number' ? 'number' : 'text';
    const step = row.kind === 'number' ? ' step="any"' : '';
    const unit = unitFor(row.path);
    return `<label class="rd-form-field"><span>${esc(niceLabel(row.path))}</span><div class="rd-input-shell"><input id="${id}" ${common} type="${type}"${step} value="${esc(row.value ?? '')}">${unit ? `<b>${unit}</b>` : ''}</div><small>${esc(row.path)}</small></label>`;
  }

  function profileOptions(available) {
    return available.map(profile => `<option value="${Number(profile.slot)}" ${Number(profile.slot) === profileSlot ? 'selected' : ''}>${esc(profile.name || `Profil ${Number(profile.slot) + 1}`)}</option>`).join('');
  }

  function emptyCustom(title, text) {
    pageHost.innerHTML = `<div class="rd-page"><div class="rd-page-head"><div><span class="rd-eyebrow">JARNSEN SERVICE TOOL</span><h1>${esc(title)}</h1><p>${esc(text)}</p></div></div><div class="rd-empty"><strong>${esc(title)}</strong><span>${esc(text)}</span><button data-view="service">Profile & Service öffnen</button></div></div>`;
  }

  function readGroup(group, original) {
    const updated = clone(original);
    pageHost.querySelectorAll(`[data-rd-group="${group}"][data-rd-field]`).forEach(input => {
      const kind = input.dataset.rdKind;
      let value;
      if (kind === 'boolean') value = Boolean(input.checked);
      else if (kind === 'number') value = Number(input.value);
      else if (kind === 'array') value = JSON.parse(input.value || '[]');
      else value = input.value;
      setByPath(updated, input.dataset.rdField, value);
    });
    return updated;
  }

  async function saveSection(kind, name, group, original) {
    const data = readGroup(group, original);
    await request('/api/profile/section', {
      method: 'POST',
      body: JSON.stringify({ slot: profileSlot, kind, name, data }),
    });
    toast(`${niceLabel(name)} im Profil gespeichert`);
    return data;
  }

  async function renderPower() {
    customView = 'power';
    setMode('power');
    pageHost.innerHTML = '<div class="rd-loading">Power-Management wird geladen …</div>';
    try {
      await refreshState();
      const { available } = await loadProfiles();
      if (!available.length) return emptyCustom('Power Management', 'Lege zuerst ein Grundprofil an, damit Einstellungen sicher bearbeitet und auf Nodes übertragen werden können.');
      [powerOriginal, positionOriginal] = await Promise.all([
        profileSection(profileSlot, 'config', 'power'),
        profileSection(profileSlot, 'config', 'position'),
      ]);
      if (customView !== 'power') return;
      const node = selectedNode();
      const powerRows = flatten(powerOriginal);
      const positionRows = flatten(positionOriginal);
      pageHost.innerHTML = `
        <div class="rd-page rd-power-page">
          <div class="rd-page-head"><div><span class="rd-eyebrow">ENERGIE & BEREITSCHAFT</span><h1>Power Management</h1><p>Sleep, Wakeup, GPS-Intervalle und Akkuverhalten aus den bestehenden Profilen – ohne versteckte Sonderlogik.</p></div><div class="rd-head-actions"><label><span>Grundprofil</span><select id="rdPowerProfile">${profileOptions(available)}</select></label><button data-view="service">Profile verwalten</button></div></div>
          <div class="rd-status-strip">
            <div><span>Ziel-Node</span><strong>${esc(node?.long_name || 'Keine Node ausgewählt')}</strong><small>${esc(node?.node_id || 'Profil kann trotzdem bearbeitet werden')}</small></div>
            <div><span>Transport</span><strong>${esc(node?.transport || (stateSnapshot?.connections?.usb_count ? 'USB bevorzugt' : 'USB → BLE'))}</strong><small>USB wird beim Anwenden automatisch bevorzugt</small></div>
            <div><span>Akku</span><strong>${node?.battery == null ? '—' : `${Math.round(Number(node.battery))} %`}</strong><small>${esc(node?.metrics?.voltage || node?.voltage || '')}</small></div>
            <div><span>Firmware</span><strong>${esc(node?.firmware || '—')}</strong><small>${esc(node?.device_label || '')}</small></div>
          </div>
          <div class="rd-two-column">
            <section class="rd-panel"><div class="rd-panel-head"><div><span class="rd-eyebrow">POWER CONFIG</span><h2>Sleep & Wakeup</h2></div><span class="rd-panel-icon">⚡</span></div><div class="rd-form-grid">${powerRows.length ? powerRows.map(row => field(row, 'power')).join('') : '<div class="rd-inline-empty">Dieses Profil enthält noch keinen Power-Abschnitt.</div>'}</div><div class="rd-panel-actions"><button class="primary" data-rd-save="power" ${powerRows.length ? '' : 'disabled'}>Power-Werte speichern</button></div></section>
            <section class="rd-panel"><div class="rd-panel-head"><div><span class="rd-eyebrow">POSITION CONFIG</span><h2>GPS & Bewegung</h2></div><span class="rd-panel-icon">⌖</span></div><div class="rd-form-grid">${positionRows.length ? positionRows.map(row => field(row, 'position')).join('') : '<div class="rd-inline-empty">Dieses Profil enthält noch keinen Position-Abschnitt.</div>'}</div><div class="rd-panel-actions"><button class="primary" data-rd-save="position" ${positionRows.length ? '' : 'disabled'}>GPS/Bewegung speichern</button></div></section>
          </div>
          <div class="rd-info-banner"><strong>Wichtig:</strong><span>Hier werden die echten Profilwerte bearbeitet. Über „Profile verwalten“ wird das Profil anschließend mit der vorhandenen Rückprüfung auf die Node übertragen. Dadurch bleiben Tracker-, V3- und Repeater-spezifische Felder erhalten.</span></div>
        </div>`;
      pageHost.querySelector('#rdPowerProfile')?.addEventListener('change', event => {
        profileSlot = Number(event.target.value); localStorage.setItem('jarnsen-redesign-profile-slot', String(profileSlot)); renderPower();
      });
    } catch (error) {
      emptyCustom('Power Management', error.message || String(error));
    }
  }

  function radioMode() {
    const override = Number(pageHost.querySelector('[data-rd-field="override_frequency"]')?.value || 0);
    const hz = Math.round(override * 1000000);
    if (hz && hz === Number(radioAuth?.frequency_a_hz || 0)) return 'jarnsen1';
    if (hz && hz === Number(radioAuth?.frequency_b_hz || 0)) return 'jarnsen2';
    return 'standard';
  }

  function refreshRadioPolicy() {
    const mode = radioMode();
    const authorized = mode !== 'standard';
    const maxHops = authorized ? Number(radioAuth?.authorized_max_hops || 20) : Number(radioAuth?.standard_max_hops || 7);
    const hop = pageHost.querySelector('[data-rd-field="hop_limit"]');
    if (hop) {
      hop.max = String(maxHops);
      if (Number(hop.value || 0) > maxHops) hop.value = String(maxHops);
    }
    pageHost.querySelectorAll('[data-rd-radio-mode]').forEach(button => button.classList.toggle('active', button.dataset.rdRadioMode === mode));
    const badge = pageHost.querySelector('#rdRadioPolicyBadge');
    if (badge) {
      badge.className = `rd-policy-badge ${authorized ? 'authorized' : ''}`;
      badge.textContent = authorized ? `${mode === 'jarnsen1' ? 'Jarnsen 1' : 'Jarnsen 2'} · max. ${maxHops} Hops` : `Standard · max. ${maxHops} Hops`;
    }
  }

  async function renderNetwork() {
    customView = 'network';
    setMode('network');
    pageHost.innerHTML = '<div class="rd-loading">Mesh- und Funkkonfiguration wird geladen …</div>';
    try {
      const [{ available }, auth] = await Promise.all([loadProfiles(), request('/api/radio-authorization')]);
      radioAuth = auth;
      if (!available.length) return emptyCustom('Mesh / Netzwerk', 'Lege zuerst ein Grundprofil an. Die Funkwerte werden profilgebunden gespeichert.');
      loraOriginal = await profileSection(profileSlot, 'config', 'lora');
      if (customView !== 'network') return;
      const preferred = ['region','modem_preset','channel_num','override_frequency','tx_power','hop_limit','use_preset','tx_enabled','bandwidth','spread_factor','coding_rate','frequency_offset','override_duty_cycle','sx126x_rx_boosted_gain'];
      const rows = flatten(loraOriginal).sort((a, b) => {
        const ai = preferred.indexOf(a.path), bi = preferred.indexOf(b.path);
        return (ai < 0 ? 999 : ai) - (bi < 0 ? 999 : bi) || a.path.localeCompare(b.path);
      });
      pageHost.innerHTML = `
        <div class="rd-page rd-network-page">
          <div class="rd-page-head"><div><span class="rd-eyebrow">MESH / LORA</span><h1>Mesh / Netzwerk</h1><p>Region, Modem, Hops und die beiden frequenzgebundenen Jarnsen-Spezialfreigaben an einer Stelle.</p></div><div class="rd-head-actions"><label><span>Grundprofil</span><select id="rdNetworkProfile">${profileOptions(available)}</select></label><button data-view="service">Profil anwenden</button></div></div>
          <section class="rd-panel rd-radio-auth"><div class="rd-panel-head"><div><span class="rd-eyebrow">SPEZIALFREQUENZEN</span><h2>Jarnsen 1 / Jarnsen 2</h2><p>Global hinterlegt, aber ausschließlich bei exaktem Frequenztreffer freigeschaltet.</p></div><span class="rd-panel-icon">⌁</span></div>
            <div class="rd-frequency-grid"><label><span>Jarnsen 1 · Frequenz A</span><div class="rd-input-shell"><input id="rdFreqA" type="number" step="0.000001" min="100" max="2500" value="${Number(auth.frequency_a_mhz || 0) || ''}"><b>MHz</b></div></label><label><span>Jarnsen 2 · Frequenz B</span><div class="rd-input-shell"><input id="rdFreqB" type="number" step="0.000001" min="100" max="2500" value="${Number(auth.frequency_b_mhz || 0) || ''}"><b>MHz</b></div></label></div>
            <div class="rd-radio-rules"><div><span>Standard</span><strong>max. ${Number(auth.standard_max_hops || 7)} Hops</strong></div><div><span>Jarnsen 1 / 2</span><strong>max. ${Number(auth.authorized_max_hops || 20)} Hops</strong></div><div><span>Duty Cycle</span><strong>frequenzgebunden</strong></div><div><span>TX-Leistung</span><strong>frequenzgebunden</strong></div></div>
            <div class="rd-panel-actions"><button class="primary" data-rd-save="auth">Spezialfrequenzen speichern</button></div>
          </section>
          <section class="rd-panel"><div class="rd-panel-head"><div><span class="rd-eyebrow">PROFIL · LORA</span><h2>Funkkonfiguration</h2></div><div id="rdRadioPolicyBadge" class="rd-policy-badge">Standard</div></div>
            <div class="rd-radio-modes"><button type="button" data-rd-radio-mode="standard">Standard</button><button type="button" data-rd-radio-mode="jarnsen1" ${Number(auth.frequency_a_hz || 0) ? '' : 'disabled'}>Jarnsen 1</button><button type="button" data-rd-radio-mode="jarnsen2" ${Number(auth.frequency_b_hz || 0) ? '' : 'disabled'}>Jarnsen 2</button></div>
            <div class="rd-form-grid rd-radio-form">${rows.length ? rows.map(row => field(row, 'lora')).join('') : '<div class="rd-inline-empty">Dieses Profil enthält noch keine LoRa-Konfiguration.</div>'}</div>
            <div class="rd-info-banner compact"><strong>Sicherheitslogik:</strong><span>Das Backend begrenzt Standardprofile automatisch auf 7 Hops. Jarnsen 1/2 gelten nur bei exakt passender A/B-Frequenz; der globale Meshtastic-Lizenzschalter wird nicht verwendet.</span></div>
            <div class="rd-panel-actions"><button class="primary" data-rd-save="lora" ${rows.length ? '' : 'disabled'}>Funkwerte im Profil speichern</button></div>
          </section>
        </div>`;
      pageHost.querySelector('#rdNetworkProfile')?.addEventListener('change', event => {
        profileSlot = Number(event.target.value); localStorage.setItem('jarnsen-redesign-profile-slot', String(profileSlot)); renderNetwork();
      });
      pageHost.querySelector('[data-rd-field="override_frequency"]')?.addEventListener('input', refreshRadioPolicy);
      refreshRadioPolicy();
    } catch (error) {
      emptyCustom('Mesh / Netzwerk', error.message || String(error));
    }
  }

  async function renderTools() {
    customView = 'tools';
    setMode('tools');
    pageHost.innerHTML = '<div class="rd-loading">Servicefunktionen werden geprüft …</div>';
    let service = {};
    try {
      [stateSnapshot, service] = await Promise.all([request('/api/state'), request('/api/service-status')]);
    } catch (_error) {
      try { stateSnapshot = await request('/api/state'); } catch (_ignore) {}
    }
    if (customView !== 'tools') return;
    const usb = stateSnapshot?.connections?.usb || [];
    const critical = service?.critical || {};
    const criticalTotal = Object.keys(critical).length;
    const criticalOk = Object.values(critical).filter(Boolean).length;
    pageHost.innerHTML = `
      <div class="rd-page rd-tools-page">
        <div class="rd-page-head"><div><span class="rd-eyebrow">SERVICE & RECOVERY</span><h1>Tools</h1><p>Bestehende Servicefunktionen als klare Einstiegspunkte – kein Funktionsersatz, sondern dieselben Backend-Aktionen.</p></div><div class="rd-head-actions"><button data-rd-tool="service" class="primary">Service & Recovery öffnen</button></div></div>
        <div class="rd-status-strip"><div><span>USB</span><strong>${usb.length} Gerät${usb.length === 1 ? '' : 'e'}</strong><small>${usb.length === 1 ? esc(usb[0].device || 'seriell') : 'USB wird bevorzugt'}</small></div><div><span>Service-Parität</span><strong>${criticalTotal ? `${criticalOk}/${criticalTotal}` : '—'}</strong><small>stabile Tool-Funktionen</small></div><div><span>Backend</span><strong>${esc(stateSnapshot?.backend_version || 'aktiv')}</strong><small>${esc(stateSnapshot?.status || 'Bereit')}</small></div><div><span>Vorgang</span><strong>${stateSnapshot?.busy ? 'Läuft' : 'Bereit'}</strong><small>${esc(stateSnapshot?.busy ? stateSnapshot?.status : 'Keine Sperre')}</small></div></div>
        <div class="rd-tool-grid">
          <button data-rd-tool="service"><span>⌘</span><strong>Service & Recovery</strong><small>USB-Flash, serieller Monitor, Recovery, Diagnosepaket</small></button>
          <button data-rd-tool="scan"><span>⌁</span><strong>Geräte scannen</strong><small>BLE prüfen; USB-Erkennung läuft automatisch</small></button>
          <button data-rd-tool="logs"><span>▤</span><strong>Logs & Verlauf</strong><small>Downloads, Queue und vorhandene Diagnoselogs</small></button>
          <button data-rd-tool="diagnostics"><span>◎</span><strong>Diagnose</strong><small>Node-Analyse und technische Messwerte</small></button>
          <button data-rd-tool="firmware"><span>⬡</span><strong>Firmware</strong><small>OTA, Updateprüfung und Zielversionen</small></button>
          <button data-rd-tool="profiles"><span>⚙</span><strong>Profile & Provisioning</strong><small>Einlesen, anwenden, Werkreset + Neuaufsetzen</small></button>
          <button data-rd-tool="live"><span>▣</span><strong>Display / Live</strong><small>Livebild, Wakeup und Fernsteuerung</small></button>
          <button data-rd-tool="map"><span>◇</span><strong>Karte / Position</strong><small>Track, letzte Position und MGRS</small></button>
        </div>
      </div>`;
  }

  async function saveAuth() {
    radioAuth = await request('/api/radio-authorization', {
      method: 'POST',
      body: JSON.stringify({
        frequency_a_mhz: String(pageHost.querySelector('#rdFreqA')?.value || '').trim(),
        frequency_b_mhz: String(pageHost.querySelector('#rdFreqB')?.value || '').trim(),
      }),
    });
    toast('Jarnsen 1 / Jarnsen 2 global gespeichert');
    await renderNetwork();
  }

  function chooseRadioMode(mode) {
    const input = pageHost.querySelector('[data-rd-field="override_frequency"]');
    if (!input) return;
    if (mode === 'standard') input.value = '0';
    if (mode === 'jarnsen1') {
      if (!Number(radioAuth?.frequency_a_hz || 0)) return toast('Jarnsen 1 ist noch nicht global hinterlegt', true);
      input.value = String(radioAuth.frequency_a_mhz);
    }
    if (mode === 'jarnsen2') {
      if (!Number(radioAuth?.frequency_b_hz || 0)) return toast('Jarnsen 2 ist noch nicht global hinterlegt', true);
      input.value = String(radioAuth.frequency_b_mhz);
    }
    refreshRadioPolicy();
  }

  function openExisting(view) {
    customView = '';
    const button = document.querySelector(`.nav-item[data-view="${view}"]`);
    if (button) button.click();
  }

  function runTool(action) {
    if (action === 'service') return document.getElementById('parityServiceButton')?.click();
    if (action === 'scan') return document.getElementById('scanBleButton')?.click();
    if (action === 'logs') return openExisting('logs');
    if (action === 'diagnostics') return openExisting('diagnostics');
    if (action === 'firmware') return openExisting('firmware');
    if (action === 'profiles') return openExisting('service');
    if (action === 'live') return openExisting('live');
    if (action === 'map') return openExisting('map');
  }

  document.addEventListener('click', event => {
    const nav = event.target.closest('.nav-item[data-view]');
    if (nav) {
      const view = nav.dataset.view;
      const mode = nav.dataset.rdMode || view;
      customView = ['power','network','tools'].includes(view) ? view : '';
      setMode(mode);
      if (view === 'power') setTimeout(renderPower, 0);
      if (view === 'network') setTimeout(renderNetwork, 0);
      if (view === 'tools') setTimeout(renderTools, 0);
    }

    const save = event.target.closest('[data-rd-save]');
    if (save) {
      const kind = save.dataset.rdSave;
      save.disabled = true;
      const task = kind === 'power' ? saveSection('config', 'power', 'power', powerOriginal).then(data => { powerOriginal = data; })
        : kind === 'position' ? saveSection('config', 'position', 'position', positionOriginal).then(data => { positionOriginal = data; })
        : kind === 'lora' ? saveSection('config', 'lora', 'lora', loraOriginal).then(data => { loraOriginal = data; refreshRadioPolicy(); })
        : kind === 'auth' ? saveAuth() : Promise.resolve();
      task.catch(error => toast(error.message || String(error), true)).finally(() => { if (save.isConnected) save.disabled = false; });
      return;
    }

    const modeButton = event.target.closest('[data-rd-radio-mode]');
    if (modeButton) { chooseRadioMode(modeButton.dataset.rdRadioMode); return; }

    const tool = event.target.closest('[data-rd-tool]');
    if (tool) { runTool(tool.dataset.rdTool); return; }
  });

  // Keep the Dashboard/Nodes split while reusing the proven overview renderer and
  // its existing selection/bulk-action wiring. A node-page click still sets the
  // canonical app view to "overview"; only the presentation mode differs.
  new MutationObserver(() => {
    if (document.body.dataset.redesignPage === 'nodes') {
      pageHost.classList.add('rd-nodes-only');
    } else {
      pageHost.classList.remove('rd-nodes-only');
    }
  }).observe(pageHost, { childList: true, subtree: false });

  setMode('dashboard');
  refreshState().catch(() => {});
  window.JarnsenFullRedesignV322 = { renderPower, renderNetwork, renderTools, refreshState };
})();
