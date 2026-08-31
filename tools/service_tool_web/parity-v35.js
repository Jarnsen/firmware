(() => {
  'use strict';

  const params = new URLSearchParams(location.search);
  const API = params.get('api') || 'http://127.0.0.1:0';
  const TOKEN = params.get('token') || '';
  let overlay = null;
  let status = null;
  let appState = null;
  let poll = null;
  let busy = false;

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
    const old = document.getElementById('parityToast');
    if (old) old.remove();
    const node = document.createElement('div');
    node.id = 'parityToast';
    node.className = `parity-toast ${error ? 'error' : ''}`;
    node.textContent = text;
    document.body.appendChild(node);
    setTimeout(() => node.remove(), error ? 5200 : 2800);
  }

  function selected(id) {
    return overlay?.querySelector(`#${id}`)?.value || '';
  }

  function checked(id) {
    return Boolean(overlay?.querySelector(`#${id}`)?.checked);
  }

  function nodeOptions() {
    return (appState?.nodes || []).map(node =>
      `<option value="${esc(node.node_id)}">${esc(node.long_name || node.node_id)} · ${esc(node.node_id)}</option>`
    ).join('');
  }

  function usbOptions() {
    const items = status?.usb || [];
    return items.map(item => `<option value="${esc(item.device)}">${esc(item.device)}${item.mapped_node_id ? ` · ${esc(item.mapped_node_id)}` : ''}${item.description ? ` · ${esc(item.description)}` : ''}</option>`).join('');
  }

  function securityOptions() {
    return (status?.security_profiles || []).map(profile =>
      `<option value="${profile.slot}">${esc(profile.name)} · Profil ${Number(profile.slot) + 1}</option>`
    ).join('');
  }

  function parityRows() {
    return (status?.parity || []).map(group => {
      const tone = group.ok ? 'ok' : 'bad';
      const mode = group.mode === 'inherited' ? 'Backend übernommen' : group.mode === 'improved' ? 'Verbessert' : 'Framework7';
      return `<div class="parity-matrix-row"><div><strong>${esc(group.group)}</strong><span>${group.features.length} Funktionen</span></div><span class="parity-status ${tone}">${esc(mode)}</span></div>`;
    }).join('');
  }

  function render() {
    if (!overlay) return;
    const usb = status?.usb || [];
    const serial = status?.serial || {};
    const update = status?.app_update || {};
    const critical = status?.critical || {};
    const allCritical = Object.values(critical).every(Boolean);
    const previousPort = selected('parityPort');
    const previousNode = selected('parityNode');
    const previousHardware = selected('parityHardware') || 'TRACKER';
    const previousBaud = selected('parityBaud') || '115200';
    const previousProfile = selected('paritySecurityProfile');

    overlay.querySelector('.parity-body').innerHTML = `
      <div class="parity-summary ${allCritical ? 'ok' : 'bad'}">
        <div><strong>${allCritical ? 'Alte Servicefunktionen angebunden' : 'Servicefunktion fehlt im Backend'}</strong><span>${esc(status?.stable_reference || '')}</span></div>
        <span>${Object.values(critical).filter(Boolean).length}/${Object.keys(critical).length}</span>
      </div>

      <section class="parity-grid two">
        <article class="parity-card">
          <div class="parity-card-head"><div><span class="eyebrow">VERBINDUNG</span><h3>USB / Ziel</h3></div><span class="parity-pill ${usb.length === 1 ? 'green' : usb.length > 1 ? 'orange' : ''}">${usb.length} USB</span></div>
          <label><span>COM-Port</span><select id="parityPort"><option value="">Automatisch / eindeutig</option>${usbOptions()}</select></label>
          <label><span>Node</span><select id="parityNode"><option value="">Keine / serielle neue Node</option>${nodeOptions()}</select></label>
          <p>${usb.length === 1 ? `Eindeutiges Ziel: ${esc(usb[0].device)}` : usb.length > 1 ? 'Mehrere Nodes: Port bewusst auswählen.' : 'Keine kompatible USB-Node erkannt.'}</p>
          <div class="parity-actions"><button data-parity-action="usb_log">USB-Log laden</button><button data-parity-action="full_log_resync">Vollständig neu synchronisieren</button></div>
        </article>

        <article class="parity-card">
          <div class="parity-card-head"><div><span class="eyebrow">SERIELL</span><h3>Monitor</h3></div><span class="parity-pill ${serial.active ? 'green' : ''}">${serial.active ? 'Verbunden' : 'Gestoppt'}</span></div>
          <div class="parity-inline"><label><span>Baud</span><select id="parityBaud">${[9600,19200,38400,57600,115200,230400,460800,921600].map(v => `<option>${v}</option>`).join('')}</select></label><div class="parity-actions compact"><button class="primary" data-parity-action="serial_monitor_start">Start</button><button data-parity-action="serial_monitor_stop">Stop</button></div></div>
          <div class="serial-tail"><pre id="paritySerialTail">${esc(serial.tail || 'Noch keine seriellen Daten.')}</pre></div>
          <div class="serial-command"><input id="paritySerialCommand" placeholder="Befehl senden …"><label class="check"><input id="paritySerialNewline" type="checkbox" checked><span>CR/LF</span></label><button data-parity-action="serial_monitor_send">Senden</button></div>
          <div class="parity-actions compact"><button data-parity-action="serial_monitor_marker">Marker</button><button data-parity-action="serial_monitor_clear">Anzeige löschen</button></div>
          <p>${esc(serial.status || '')}${serial.log_path ? ` · Log: ${esc(serial.log_path)}` : ''}</p>
        </article>
      </section>

      <section class="parity-grid two">
        <article class="parity-card">
          <div class="parity-card-head"><div><span class="eyebrow">FIRMWARE & RECOVERY</span><h3>USB / Bluetooth</h3></div></div>
          <label><span>Hardware für USB-Flash</span><select id="parityHardware"><option value="TRACKER">Tracker V1.1</option><option value="V3">Heltec V3</option></select></label>
          <p>USB-Recovery schreibt die passende aktuelle Firmware plus OTA-Loader. NVS/Diagnoselogs bleiben nach der bewährten alten Logik erhalten.</p>
          <div class="parity-actions"><button class="primary" data-parity-action="serial_flash">Firmware + OTA-Loader über USB</button><button data-parity-action="ble_recovery">Bluetooth-Recovery / OTA</button></div>
        </article>

        <article class="parity-card">
          <div class="parity-card-head"><div><span class="eyebrow">DIAGNOSE & BACKUP</span><h3>Service-Dateien</h3></div></div>
          <p>Diagnosepaket und Konfig-Snapshot verwenden dieselben Datenquellen wie das stabile Tool; die Dateien landen im bisherigen Service-Tool-Ausgabeordner.</p>
          <div class="parity-actions"><button class="primary" data-parity-action="diagnostic_bundle">Diagnosepaket erstellen</button><button data-parity-action="config_snapshot">Konfig-Snapshot sichern</button></div>
        </article>
      </section>

      <section class="parity-grid two">
        <article class="parity-card">
          <div class="parity-card-head"><div><span class="eyebrow">JARNSEN SCHUTZ</span><h3>PIN & Vollsperre</h3></div><span class="parity-pill green">PIN 240180</span></div>
          <label><span>Grundprofil</span><select id="paritySecurityProfile">${securityOptions() || '<option value="">Kein gespeichertes Profil</option>'}</select></label>
          <div class="policy-fixed"><div><span>Admin-Freigabe</span><strong>15 Minuten</strong></div><div><span>Vollsperre</span><strong>Doppelklick + 3. Druck 3 s</strong></div></div>
          <label class="check wide"><input id="parityFullLockAlert" type="checkbox" checked><span>Vollsperren-Alarm über Mesh senden</span></label>
          <button class="primary wide-button" data-parity-action="save_security_policy">Schutz-Policy speichern</button>
        </article>

        <article class="parity-card">
          <div class="parity-card-head"><div><span class="eyebrow">SERVICE TOOL</span><h3>App-Update</h3></div><span class="parity-pill ${update.available ? 'orange' : 'green'}">${update.available ? `v${esc(update.remote_version || '?')}` : 'Aktuell'}</span></div>
          <p>${update.available ? 'Eine neuere Service-Tool-Version wurde gefunden.' : 'Updateprüfung kann jederzeit manuell gestartet werden.'}</p>
          <div class="parity-actions"><button data-parity-action="app_update_check">Update prüfen</button>${update.available && update.url_ready ? '<button class="primary" data-parity-action="app_update_install">Update installieren & neu starten</button>' : ''}</div>
        </article>
      </section>

      <section class="parity-card parity-matrix">
        <div class="parity-card-head"><div><span class="eyebrow">FUNKTIONS-PARITÄT</span><h3>Stabiles Tool → Framework7</h3></div></div>
        ${parityRows()}
        <p>${esc(status?.backend_strategy || '')}</p>
      </section>`;

    const port = overlay.querySelector('#parityPort');
    if (port) port.value = [...port.options].some(o => o.value === previousPort) ? previousPort : (usb.length === 1 ? usb[0].device : '');
    const node = overlay.querySelector('#parityNode');
    if (node && [...node.options].some(o => o.value === previousNode)) node.value = previousNode;
    const hw = overlay.querySelector('#parityHardware'); if (hw) hw.value = previousHardware;
    const baud = overlay.querySelector('#parityBaud'); if (baud) baud.value = previousBaud;
    const profile = overlay.querySelector('#paritySecurityProfile');
    if (profile) {
      if ([...profile.options].some(o => o.value === previousProfile)) profile.value = previousProfile;
      syncSecurityToggle();
    }
    const tail = overlay.querySelector('#paritySerialTail'); if (tail) tail.scrollTop = tail.scrollHeight;
  }

  function syncSecurityToggle() {
    if (!overlay || !status) return;
    const slot = Number(selected('paritySecurityProfile'));
    const profile = (status.security_profiles || []).find(item => Number(item.slot) === slot);
    const box = overlay.querySelector('#parityFullLockAlert');
    if (box && profile) box.checked = Boolean(profile.full_lock_alert_mesh);
  }

  async function refresh() {
    if (!overlay || busy || document.hidden) return;
    busy = true;
    try {
      [status, appState] = await Promise.all([request('/api/service-status'), request('/api/state')]);
      render();
    } catch (error) {
      toast(error.message || String(error), true);
    } finally { busy = false; }
  }

  async function action(command) {
    const payload = {
      command,
      port: selected('parityPort'),
      node_id: selected('parityNode'),
      hardware: selected('parityHardware') || 'TRACKER',
      baud: Number(selected('parityBaud') || 115200),
      newline: checked('paritySerialNewline'),
      text: overlay?.querySelector('#paritySerialCommand')?.value || '',
      slot: Number(selected('paritySecurityProfile')),
      full_lock_alert_mesh: checked('parityFullLockAlert'),
    };

    if (command === 'serial_flash') {
      if (!window.confirm(`Aktuelle ${payload.hardware === 'TRACKER' ? 'Tracker V1.1' : 'Heltec V3'} Firmware plus OTA-Loader über ${payload.port || 'den eindeutigen USB-Port'} schreiben?`)) return;
    }
    if (command === 'ble_recovery' && !payload.node_id) throw new Error('Für Bluetooth-Recovery bitte eine Node auswählen.');
    if (command === 'config_snapshot' && !payload.node_id) throw new Error('Für den Konfig-Snapshot bitte eine Node auswählen.');
    if (command === 'app_update_install' && !window.confirm('Service Tool aktualisieren und anschließend neu starten?')) return;

    const result = await request('/api/service/action', { method: 'POST', body: JSON.stringify(payload) });
    toast(result.message || 'Service-Aktion gestartet');
    if (command === 'serial_monitor_send') {
      const input = overlay?.querySelector('#paritySerialCommand'); if (input) input.value = '';
    }
    setTimeout(refresh, command.includes('monitor') ? 250 : 700);
  }

  function close() {
    if (!overlay) return;
    overlay.remove();
    overlay = null;
    if (poll) clearInterval(poll);
    poll = null;
  }

  function open() {
    if (overlay) return;
    overlay = document.createElement('div');
    overlay.className = 'parity-overlay';
    overlay.innerHTML = `<div class="parity-window"><header class="parity-header"><div><span class="eyebrow">JARNSEN NODE SERVICE TOOL</span><h2>Service & Recovery</h2><p>Alle Funktionen des stabilen Tools – im Framework7-Frontend.</p></div><button class="parity-close" data-parity-close>×</button></header><main class="parity-body"><div class="parity-loading">Servicefunktionen werden geprüft …</div></main></div>`;
    document.body.appendChild(overlay);
    refresh();
    poll = setInterval(refresh, 1500);
  }

  function installButton() {
    const top = document.querySelector('.top-actions');
    if (!top || document.getElementById('parityServiceButton')) return;
    const button = document.createElement('button');
    button.id = 'parityServiceButton';
    button.className = 'button button-round quiet-action';
    button.innerHTML = '⌘&nbsp; Service';
    button.addEventListener('click', open);
    top.insertBefore(button, document.getElementById('activityButton') || top.firstChild);
  }

  document.addEventListener('click', event => {
    if (event.target.closest('[data-parity-close]')) { close(); return; }
    const button = event.target.closest('[data-parity-action]');
    if (!button) return;
    button.disabled = true;
    action(button.dataset.parityAction).catch(error => toast(error.message || String(error), true)).finally(() => { if (button.isConnected) button.disabled = false; });
  });

  document.addEventListener('change', event => {
    if (event.target?.id === 'paritySecurityProfile') syncSecurityToggle();
  });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && overlay) close(); });
  document.addEventListener('visibilitychange', () => { if (!document.hidden && overlay) refresh(); });

  const observer = new MutationObserver(installButton);
  observer.observe(document.documentElement, { childList: true, subtree: true });
  setTimeout(installButton, 100);
})();
