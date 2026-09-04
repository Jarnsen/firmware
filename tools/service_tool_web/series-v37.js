(() => {
  'use strict';

  const params = new URLSearchParams(location.search);
  const API = params.get('api') || 'http://127.0.0.1:0';
  const TOKEN = params.get('token') || '';
  const pageHost = document.getElementById('pageHost');
  const memory = {
    status: null,
    profiles: [],
    github: [],
    localFile: null,
    localBytes: null,
    localSha: '',
    lastHandledJob: '',
    busy: false,
    renderToken: 0,
    pollTimer: null,
    githubBusy: false,
    numbering: loadNumbering(),
  };

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
    document.getElementById('seriesToast')?.remove();
    const node = document.createElement('div');
    node.id = 'seriesToast';
    node.className = `series-toast ${error ? 'error' : ''}`;
    node.textContent = text;
    document.body.appendChild(node);
    setTimeout(() => node.remove(), error ? 5200 : 2800);
  }

  function loadNumbering() {
    try {
      const data = JSON.parse(localStorage.getItem('jarnsen-series-numbering') || '{}');
      return {
        enabled: Boolean(data.enabled),
        longPattern: String(data.longPattern || 'Node-{n:02}'),
        shortPattern: String(data.shortPattern || 'N{n:02}'),
        counter: Math.max(1, Number(data.counter) || 1),
      };
    } catch (_error) {
      return { enabled: false, longPattern: 'Node-{n:02}', shortPattern: 'N{n:02}', counter: 1 };
    }
  }

  function saveNumbering() {
    localStorage.setItem('jarnsen-series-numbering', JSON.stringify(memory.numbering));
  }

  function formatPattern(pattern, counter) {
    return String(pattern || '').replace(/\{n(?::(\d+))?\}/g, (_m, width) => {
      const raw = String(Math.max(0, Number(counter) || 0));
      return width ? raw.padStart(Math.min(8, Number(width) || 1), '0') : raw;
    });
  }

  function ensureNav() {
    const list = document.getElementById('navList');
    if (!list || list.querySelector('[data-view="series"]')) return;
    const service = list.querySelector('[data-view="service"]');
    const button = document.createElement('button');
    button.className = 'nav-item';
    button.dataset.view = 'series';
    button.innerHTML = '<span class="nav-icon">＋</span><span>Neue Nodes</span>';
    list.insertBefore(button, service || null);
  }

  function isSeriesView() {
    return Boolean(document.querySelector('.nav-item[data-view="series"].active'));
  }

  function activeSettings() {
    const last = memory.status?.last_settings || {};
    return {
      profile_slot: Number(document.getElementById('seriesProfile')?.value ?? last.profile_slot ?? 0),
      hardware: document.getElementById('seriesHardware')?.value || last.hardware || 'AUTO',
      pin: document.getElementById('seriesPin')?.value?.trim() || last.pin || '240180',
      apply_psk: Boolean(document.getElementById('seriesApplyPsk')?.checked ?? last.apply_psk ?? false),
      firmware_source: document.querySelector('input[name="seriesFirmwareSource"]:checked')?.value || last.firmware_source || 'latest',
      github_tag: document.getElementById('seriesGithubFirmware')?.selectedOptions?.[0]?.dataset.tag || last.github_tag || '',
      github_manifest: document.getElementById('seriesGithubFirmware')?.value || last.github_manifest || '',
      port: document.getElementById('seriesPort')?.value || last.port || '',
    };
  }

  function setSettings(settings = {}) {
    const setValue = (id, value) => { const el = document.getElementById(id); if (el && value !== undefined && value !== null) el.value = String(value); };
    setValue('seriesProfile', settings.profile_slot ?? 0);
    setValue('seriesHardware', settings.hardware || 'AUTO');
    setValue('seriesPin', settings.pin || '240180');
    setValue('seriesPort', settings.port || '');
    const psk = document.getElementById('seriesApplyPsk');
    if (psk) psk.checked = Boolean(settings.apply_psk);
    const source = ['latest', 'github', 'local'].includes(settings.firmware_source) ? settings.firmware_source : 'latest';
    const radio = document.querySelector(`input[name="seriesFirmwareSource"][value="${source}"]`);
    if (radio) radio.checked = true;
    updateSourceVisibility();
  }

  function profileOptions(selected) {
    const usable = memory.profiles.filter(profile => !profile.empty);
    if (!usable.length) return '<option value="">Kein Grundprofil gespeichert</option>';
    return usable.map(profile => `<option value="${Number(profile.slot)}" ${Number(profile.slot) === Number(selected) ? 'selected' : ''}>${esc(profile.name || `Profil ${Number(profile.slot) + 1}`)}${profile.source_hw ? ` · ${esc(profile.source_hw)}` : ''}</option>`).join('');
  }

  function usbOptions(selected) {
    const usb = memory.status?.usb || [];
    const rows = ['<option value="">Automatisch bei genau einer Node</option>'];
    usb.forEach(item => {
      const device = String(item.device || '');
      const description = String(item.description || item.label || 'USB Node');
      rows.push(`<option value="${esc(device)}" ${device === selected ? 'selected' : ''}>${esc(device)} · ${esc(description)}</option>`);
    });
    return rows.join('');
  }

  function githubOptions(selectedManifest, hardware) {
    const filtered = memory.github.filter(item => hardware === 'AUTO' || item.hardware === hardware);
    if (!filtered.length) return '<option value="">Noch keine GitHub-Auswahl geladen</option>';
    return filtered.map(item => `<option value="${esc(item.manifest)}" data-tag="${esc(item.tag)}" data-hardware="${esc(item.hardware)}" ${item.manifest === selectedManifest ? 'selected' : ''}>${esc(item.label)}</option>`).join('');
  }

  function sourceCard(value, title, text, recommended = false) {
    const checked = (memory.status?.last_settings?.firmware_source || 'latest') === value;
    return `<label class="series-source-card ${recommended ? 'recommended' : ''}">
      <input type="radio" name="seriesFirmwareSource" value="${value}" ${checked ? 'checked' : ''}>
      <span class="series-source-dot"></span><span><strong>${esc(title)}</strong><small>${esc(text)}</small></span>${recommended ? '<em>EMPFOHLEN</em>' : ''}
    </label>`;
  }

  function stageRows(job) {
    const steps = [
      ['Hardware erkennen', 5], ['Full Device Reset', 8], ['Firmware prüfen', 18],
      ['Firmware + otaBTupdate', 42], ['Node wiederfinden', 74], ['Grundprofil + Namen', 78],
      ['Rückprüfung', 92], ['Datenbank / Abschluss', 100],
    ];
    const progress = Number(job?.progress || 0);
    return steps.map(([label, point]) => {
      const done = progress >= point || job?.state === 'success';
      const active = !done && job?.state === 'running' && progress < point && (point === steps.find(step => progress < step[1])?.[1]);
      return `<div class="series-step ${done ? 'done' : active ? 'active' : ''}"><span>${done ? '✓' : active ? '●' : '○'}</span><strong>${label}</strong></div>`;
    }).join('');
  }

  function historyRows() {
    const rows = [...(memory.status?.history || [])].reverse();
    if (!rows.length) return '<tr><td colspan="7" class="series-empty-cell">Noch keine Serienbereitstellung ausgeführt.</td></tr>';
    return rows.slice(0, 40).map((row, index) => {
      const ok = row.status === 'success';
      const time = row.time ? new Date(row.time).toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'short' }) : '—';
      return `<tr><td>${index + 1}</td><td><strong>${esc(row.long_name || '—')}</strong><small>${esc(row.short_name || '')}</small></td><td>${esc(row.hardware || '—')}</td><td>${esc(row.profile_name || '—')}</td><td>${esc(row.firmware_label || row.firmware_source || '—')}</td><td>${esc(time)}</td><td><span class="series-result ${ok ? 'ok' : 'bad'}">${ok ? '✓ OK' : '⚠ Fehler'}</span></td></tr>`;
    }).join('');
  }

  function renderJob(job) {
    const running = job?.state === 'running';
    const success = job?.state === 'success';
    const failed = job?.state === 'failed';
    const progress = Math.max(0, Math.min(100, Number(job?.progress || 0)));
    return `<div class="series-job-card ${success ? 'success' : failed ? 'failed' : running ? 'running' : ''}">
      <div class="series-job-head"><div><span class="section-label">AKTUELLER VORGANG</span><h3>${job ? esc(job.long_name || 'Node') : 'Bereit für die nächste Node'}</h3><p>${job ? esc(job.stage || job.message || 'Vorbereitung') : 'Einstellungen bleiben erhalten. Nur Long/Short Name ändern und nächste Node anschließen.'}</p></div><div class="series-job-percent">${progress}%</div></div>
      <div class="series-progress"><div style="width:${progress}%"></div></div>
      <div class="series-steps">${stageRows(job)}</div>
      ${job?.message ? `<div class="series-job-message ${failed ? 'error' : success ? 'ok' : ''}">${esc(job.message)}</div>` : ''}
      ${running ? '<button class="series-secondary danger" id="seriesCancel">Vorgang abbrechen</button>' : ''}
    </div>`;
  }

  async function loadData() {
    const [status, profiles] = await Promise.all([
      request('/api/series/status'),
      request('/api/profiles'),
    ]);
    memory.status = status;
    memory.profiles = profiles.profiles || [];
  }

  async function renderSeries(preserveForm = false) {
    if (!pageHost) return;
    const token = ++memory.renderToken;
    const preserved = preserveForm ? captureForm() : null;
    pageHost.innerHTML = '<div class="page-header"><div class="page-title-wrap"><h1>Neue Nodes</h1><p>Serienbereitstellung wird geladen …</p></div></div><div class="empty-state"><h3>Servicekern wird geprüft …</h3></div>';
    try {
      await loadData();
      if (token !== memory.renderToken || !isSeriesView()) return;
      const last = preserved?.settings || memory.status.last_settings || {};
      const usableProfiles = memory.profiles.filter(profile => !profile.empty);
      const job = memory.status.job;
      const running = job?.state === 'running';
      pageHost.innerHTML = `
        <div class="series-page">
          <div class="page-header series-header"><div class="page-title-wrap"><h1>Neue Nodes / Serienbereitstellung</h1><p>Einmal Grundsetup wählen. Danach Node für Node nur noch Long Name und Short Name ändern.</p></div><div class="series-mode-pill"><span></span> Serienmodus · Einstellungen bleiben</div></div>
          <div class="series-hero">
            <div><span class="section-label">SICHERER USB-ABLAUF</span><h2>Anschließen → Namen → Bespielen → Prüfen → nächste Node</h2><p>„Fertig“ erscheint erst nach Hardwareprüfung, Firmware, Profil-Readback und Datenbankkontrolle.</p></div>
            <div class="series-hero-badges"><span>USB zuerst</span><span>SHA-256</span><span>Hardware-Guard</span><span>Soll/Ist</span></div>
          </div>
          <div class="series-grid">
            <section class="series-card series-config-card">
              <div class="series-card-head"><div><span class="section-label">1 · GRUNDSETUP</span><h3>Bleibt für die ganze Serie erhalten</h3></div><button class="series-secondary" id="seriesReload">USB neu prüfen</button></div>
              <div class="series-form-grid">
                <label><span>Grundprofil</span><select id="seriesProfile">${profileOptions(last.profile_slot ?? 0)}</select></label>
                <label><span>Hardware</span><select id="seriesHardware"><option value="AUTO">Automatisch erkennen</option><option value="TRACKER">Tracker V1.1</option><option value="V3">Heltec V3</option></select></label>
                <label class="wide"><span>USB / COM-Port</span><select id="seriesPort">${usbOptions(last.port || '')}</select><small>${(memory.status.usb || []).length} kompatible USB-Verbindung(en) erkannt</small></label>
                <label><span>Bluetooth-PIN</span><input id="seriesPin" inputmode="numeric" maxlength="6" value="${esc(last.pin || '240180')}"></label>
                <label class="series-check"><input id="seriesApplyPsk" type="checkbox" ${last.apply_psk ? 'checked' : ''}><span>PSK aus Grundprofil mit übertragen</span></label>
              </div>
              <div class="series-template-row"><select id="seriesTemplate"><option value="">Bespielvorlage wählen …</option>${(memory.status.templates || []).map(item => `<option value="${esc(item.id)}">${esc(item.name)}</option>`).join('')}</select><input id="seriesTemplateName" placeholder="Neue Vorlage, z. B. TAK Tracker Einsatz"><button class="series-secondary" id="seriesTemplateSave">Vorlage speichern</button><button class="series-secondary danger" id="seriesTemplateDelete" disabled>Löschen</button></div>
            </section>

            <section class="series-card series-firmware-card">
              <div class="series-card-head"><div><span class="section-label">2 · FIRMWARE</span><h3>Quelle festlegen</h3></div><span class="series-safety-label">Passende Hardware wird vor Reset geprüft</span></div>
              <div class="series-source-grid">
                ${sourceCard('latest', 'Aktuellste geprüfte Firmware', 'Passende Jarnsen-Firmware automatisch über das bestehende Manifest laden.', true)}
                ${sourceCard('github', 'Andere von GitHub', 'Einen anderen Jarnsen-Release/Manifeststand gezielt auswählen.')}
                ${sourceCard('local', 'Vom Rechner', 'Lokales ZIP mit Manifest oder eindeutig benannte ESP32-S3 .bin verwenden.')}
              </div>
              <div id="seriesGithubPanel" class="series-source-panel"><div class="series-inline"><select id="seriesGithubFirmware">${githubOptions(last.github_manifest || '', last.hardware || 'AUTO')}</select><button class="series-secondary" id="seriesGithubLoad">GitHub-Liste laden</button></div><small>Release und Manifest werden vor Download erneut geprüft; Firmwaregröße und SHA-256 müssen stimmen.</small></div>
              <div id="seriesLocalPanel" class="series-source-panel"><label class="series-file"><input id="seriesLocalFile" type="file" accept=".zip,.bin"><span>Datei auswählen</span><strong id="seriesLocalName">${memory.localFile ? esc(memory.localFile.name) : 'Keine Datei ausgewählt'}</strong></label><div id="seriesLocalMeta" class="series-file-meta">${memory.localFile ? `${esc(memory.localFile.name)} · SHA-256 ${esc(memory.localSha.slice(0, 16))}…` : 'Empfohlen: ZIP mit passendem .ota.json-Manifest.'}</div></div>
            </section>

            <section class="series-card series-names-card">
              <div class="series-card-head"><div><span class="section-label">3 · DIESE NODE</span><h3>Nur diese Werte ändern</h3></div><label class="series-switch"><input id="seriesAutoNumber" type="checkbox" ${memory.numbering.enabled ? 'checked' : ''}><span>Namensautomatik</span></label></div>
              <div class="series-name-grid">
                <label><span>Long Name</span><input id="seriesLongName" autocomplete="off" value="${esc(preserved?.longName || '')}" placeholder="z. B. RiKrTrp MrsZg26"></label>
                <label><span>Short Name</span><input id="seriesShortName" autocomplete="off" maxlength="4" value="${esc(preserved?.shortName || '')}" placeholder="max. 4 Zeichen"></label>
              </div>
              <div id="seriesNumberPanel" class="series-number-panel">
                <label><span>Long-Muster</span><input id="seriesLongPattern" value="${esc(memory.numbering.longPattern)}"></label><label><span>Short-Muster</span><input id="seriesShortPattern" value="${esc(memory.numbering.shortPattern)}"></label><label><span>Nächste Nummer</span><input id="seriesCounter" type="number" min="1" max="999999" value="${memory.numbering.counter}"></label><button class="series-secondary" id="seriesGenerateNames">Namen erzeugen</button>
                <small>Platzhalter: <code>{n}</code> oder <code>{n:02}</code>. Short Name bleibt auf maximal 4 Zeichen begrenzt.</small>
              </div>
              <div class="series-start-summary" id="seriesStartSummary"></div>
              <button class="series-primary" id="seriesStart" ${running || !usableProfiles.length ? 'disabled' : ''}>${running ? 'Einrichtung läuft …' : 'Node sicher bespielen'}</button>
              <p class="series-warning"><strong>Full Device Reset:</strong> Die bisherige Meshtastic-Identität und Konfiguration dieser angeschlossenen Node wird gelöscht. Vor dem ersten destruktiven Schritt wird der Gerätetyp geprüft.</p>
            </section>

            <section class="series-card series-job-wrap">${renderJob(job)}</section>
          </div>

          <section class="series-card series-history-card">
            <div class="series-card-head"><div><span class="section-label">SERIENÜBERSICHT</span><h3>Was wurde wirklich fertig?</h3></div><button class="series-secondary danger" id="seriesHistoryClear">Verlauf leeren</button></div>
            <div class="series-history-scroll"><table class="series-history"><thead><tr><th>#</th><th>Node</th><th>Hardware</th><th>Profil</th><th>Firmware</th><th>Zeit</th><th>Ergebnis</th></tr></thead><tbody>${historyRows()}</tbody></table></div>
          </section>
        </div>`;
      setSettings({ ...last, ...(preserved?.settings || {}) });
      bindPage();
      updateSourceVisibility();
      updateNumberVisibility();
      if (memory.numbering.enabled && !preserved?.longName && !job?.state) generateNames();
      updateStartSummary();
      handleJobTransition(job);
      schedulePoll(running ? 650 : 2200);
    } catch (error) {
      if (token !== memory.renderToken) return;
      pageHost.innerHTML = `<div class="page-header"><div class="page-title-wrap"><h1>Neue Nodes</h1><p>Serienbereitstellung</p></div></div><div class="empty-state"><h3>Serienbereich nicht verfügbar</h3><p>${esc(error.message || error)}</p><button class="service-button primary" id="seriesRetry">Erneut versuchen</button></div>`;
      document.getElementById('seriesRetry')?.addEventListener('click', () => renderSeries());
      schedulePoll(3500);
    }
  }

  function captureForm() {
    return {
      settings: activeSettings(),
      longName: document.getElementById('seriesLongName')?.value || '',
      shortName: document.getElementById('seriesShortName')?.value || '',
    };
  }

  function updateSourceVisibility() {
    const source = document.querySelector('input[name="seriesFirmwareSource"]:checked')?.value || 'latest';
    document.getElementById('seriesGithubPanel')?.classList.toggle('visible', source === 'github');
    document.getElementById('seriesLocalPanel')?.classList.toggle('visible', source === 'local');
    document.querySelectorAll('.series-source-card').forEach(card => card.classList.toggle('selected', card.querySelector('input')?.checked));
    updateStartSummary();
  }

  function updateNumberVisibility() {
    const enabled = Boolean(document.getElementById('seriesAutoNumber')?.checked);
    document.getElementById('seriesNumberPanel')?.classList.toggle('visible', enabled);
  }

  function generateNames() {
    const counter = Math.max(1, Number(document.getElementById('seriesCounter')?.value || memory.numbering.counter || 1));
    const longPattern = document.getElementById('seriesLongPattern')?.value || memory.numbering.longPattern;
    const shortPattern = document.getElementById('seriesShortPattern')?.value || memory.numbering.shortPattern;
    const longName = formatPattern(longPattern, counter);
    const shortName = formatPattern(shortPattern, counter);
    const longEl = document.getElementById('seriesLongName');
    const shortEl = document.getElementById('seriesShortName');
    if (longEl) longEl.value = longName;
    if (shortEl) shortEl.value = shortName;
    updateStartSummary();
  }

  function rememberNumbering() {
    memory.numbering = {
      enabled: Boolean(document.getElementById('seriesAutoNumber')?.checked),
      longPattern: document.getElementById('seriesLongPattern')?.value || 'Node-{n:02}',
      shortPattern: document.getElementById('seriesShortPattern')?.value || 'N{n:02}',
      counter: Math.max(1, Number(document.getElementById('seriesCounter')?.value) || 1),
    };
    saveNumbering();
  }

  function updateStartSummary() {
    const box = document.getElementById('seriesStartSummary');
    if (!box) return;
    const settings = activeSettings();
    const profile = memory.profiles.find(item => Number(item.slot) === Number(settings.profile_slot));
    const hardware = { AUTO: 'Automatisch', TRACKER: 'Tracker V1.1', V3: 'Heltec V3' }[settings.hardware] || settings.hardware;
    const source = settings.firmware_source === 'latest' ? 'Aktuellste geprüfte Firmware' : settings.firmware_source === 'github' ? 'GitHub-Auswahl' : (memory.localFile ? `Lokal: ${memory.localFile.name}` : 'Lokale Datei fehlt');
    box.innerHTML = `<span><small>Profil</small><strong>${esc(profile?.name || '—')}</strong></span><span><small>Hardware</small><strong>${esc(hardware)}</strong></span><span><small>Firmware</small><strong>${esc(source)}</strong></span><span><small>USB</small><strong>${esc(settings.port || 'automatisch')}</strong></span>`;
  }

  async function readLocalFile(file) {
    if (!file) return;
    if (file.size > 10 * 1024 * 1024) throw new Error('Lokale Datei ist größer als 10 MiB.');
    const bytes = new Uint8Array(await file.arrayBuffer());
    const digest = await crypto.subtle.digest('SHA-256', bytes);
    memory.localFile = file;
    memory.localBytes = bytes;
    memory.localSha = [...new Uint8Array(digest)].map(value => value.toString(16).padStart(2, '0')).join('');
    const name = document.getElementById('seriesLocalName');
    const meta = document.getElementById('seriesLocalMeta');
    if (name) name.textContent = file.name;
    if (meta) meta.textContent = `${file.name} · ${(file.size / 1024 / 1024).toFixed(2)} MiB · SHA-256 ${memory.localSha.slice(0, 20)}…`;
    updateStartSummary();
  }

  function bytesToBase64(bytes) {
    let binary = '';
    const chunk = 0x8000;
    for (let offset = 0; offset < bytes.length; offset += chunk) binary += String.fromCharCode(...bytes.subarray(offset, offset + chunk));
    return btoa(binary);
  }

  async function loadGithubOptions() {
    if (memory.githubBusy) return;
    memory.githubBusy = true;
    const button = document.getElementById('seriesGithubLoad');
    if (button) { button.disabled = true; button.textContent = 'GitHub wird geladen …'; }
    try {
      const data = await request('/api/series/github');
      memory.github = data.options || [];
      const settings = activeSettings();
      const select = document.getElementById('seriesGithubFirmware');
      if (select) select.innerHTML = githubOptions(settings.github_manifest, settings.hardware);
      toast(`${memory.github.length} passende Firmware-Manifeste gefunden`);
    } catch (error) { toast(error.message || String(error), true); }
    finally {
      memory.githubBusy = false;
      if (button) { button.disabled = false; button.textContent = 'GitHub-Liste laden'; }
      updateStartSummary();
    }
  }

  function confirmReset(name) {
    return new Promise(resolve => {
      document.querySelector('.series-confirm-overlay')?.remove();
      const overlay = document.createElement('div');
      overlay.className = 'series-confirm-overlay';
      overlay.innerHTML = `<div class="series-confirm"><div class="series-confirm-icon">!</div><h3>${esc(name)} wirklich neu einrichten?</h3><p>Der Full Device Reset löscht die bisherige Meshtastic-Identität und Konfiguration der angeschlossenen Node. Hardware und Firmware werden vor bzw. während des Vorgangs geprüft.</p><div><button data-series-confirm="no">Abbrechen</button><button class="danger" data-series-confirm="yes">Werkreset & Bespielen</button></div></div>`;
      document.body.appendChild(overlay);
      overlay.addEventListener('click', event => {
        const action = event.target.closest('[data-series-confirm]')?.dataset.seriesConfirm;
        if (!action) return;
        overlay.remove();
        resolve(action === 'yes');
      });
    });
  }

  async function startSeries() {
    const settings = activeSettings();
    const longName = document.getElementById('seriesLongName')?.value?.trim() || '';
    const shortName = document.getElementById('seriesShortName')?.value?.trim() || '';
    if (!longName) return toast('Long Name fehlt', true);
    if (!shortName || shortName.length > 4) return toast('Short Name muss 1 bis 4 Zeichen haben', true);
    if (!/^\d{6}$/.test(settings.pin)) return toast('Bluetooth-PIN muss genau 6 Ziffern haben', true);
    if (!memory.profiles.some(item => !item.empty && Number(item.slot) === Number(settings.profile_slot))) return toast('Bitte ein gespeichertes Grundprofil auswählen', true);
    if (settings.firmware_source === 'github' && (!settings.github_tag || !settings.github_manifest)) return toast('Bitte zuerst eine GitHub-Firmware auswählen', true);
    if (settings.firmware_source === 'local' && (!memory.localFile || !memory.localBytes)) return toast('Bitte die lokale Firmwaredatei auswählen', true);
    rememberNumbering();
    if (!(await confirmReset(longName))) return;
    const button = document.getElementById('seriesStart');
    if (button) { button.disabled = true; button.textContent = 'Sicherheitsprüfung läuft …'; }
    const payload = { command: 'start', ...settings, long_name: longName, short_name: shortName };
    if (settings.firmware_source === 'local') {
      payload.local_file = { name: memory.localFile.name, sha256: memory.localSha, data_b64: bytesToBase64(memory.localBytes) };
    }
    try {
      const result = await request('/api/series/action', { method: 'POST', body: JSON.stringify(payload) });
      memory.lastHandledJob = '';
      toast(result.message || 'Serienbereitstellung gestartet');
      await renderSeries(true);
    } catch (error) {
      toast(error.message || String(error), true);
      if (button) { button.disabled = false; button.textContent = 'Node sicher bespielen'; }
    }
  }

  async function saveTemplate() {
    const name = document.getElementById('seriesTemplateName')?.value?.trim() || '';
    if (!name) return toast('Bitte einen Vorlagennamen eingeben', true);
    const settings = activeSettings();
    try {
      const result = await request('/api/series/action', { method: 'POST', body: JSON.stringify({ command: 'save_template', name, settings }) });
      toast(result.message || 'Vorlage gespeichert');
      await renderSeries(true);
    } catch (error) { toast(error.message || String(error), true); }
  }

  async function deleteTemplate() {
    const select = document.getElementById('seriesTemplate');
    const id = select?.value || '';
    if (!id) return;
    try {
      const result = await request('/api/series/action', { method: 'POST', body: JSON.stringify({ command: 'delete_template', id }) });
      toast(result.message || 'Vorlage gelöscht');
      await renderSeries(true);
    } catch (error) { toast(error.message || String(error), true); }
  }

  function applyTemplate(id) {
    const template = (memory.status?.templates || []).find(item => item.id === id);
    const del = document.getElementById('seriesTemplateDelete');
    if (del) del.disabled = !template;
    if (!template) return;
    setSettings(template.settings || {});
    if (template.settings?.firmware_source === 'local' && !memory.localFile) toast('Vorlage geladen · lokale Firmwaredatei bitte erneut auswählen');
    updateStartSummary();
  }

  async function clearHistory() {
    if (!window.confirm('Serienverlauf wirklich leeren? Die eingerichteten Nodes bleiben unverändert.')) return;
    try {
      await request('/api/series/action', { method: 'POST', body: JSON.stringify({ command: 'clear_history' }) });
      await renderSeries(true);
    } catch (error) { toast(error.message || String(error), true); }
  }

  async function cancelJob() {
    try {
      const result = await request('/api/series/action', { method: 'POST', body: JSON.stringify({ command: 'cancel' }) });
      toast(result.message || 'Abbruch angefordert');
    } catch (error) { toast(error.message || String(error), true); }
  }

  function handleJobTransition(job) {
    if (!job || !job.id || job.state === 'running' || memory.lastHandledJob === job.id) return;
    memory.lastHandledJob = job.id;
    if (job.state === 'success') {
      toast(`${job.long_name} vollständig eingerichtet`);
      if (memory.numbering.enabled) {
        memory.numbering.counter += 1;
        saveNumbering();
        const counter = document.getElementById('seriesCounter');
        if (counter) counter.value = memory.numbering.counter;
        generateNames();
      } else {
        const longEl = document.getElementById('seriesLongName');
        const shortEl = document.getElementById('seriesShortName');
        if (longEl) longEl.value = '';
        if (shortEl) shortEl.value = '';
        setTimeout(() => longEl?.focus(), 80);
      }
    } else if (job.state === 'failed') toast(job.message || 'Serienbereitstellung fehlgeschlagen', true);
  }

  function schedulePoll(delay) {
    clearTimeout(memory.pollTimer);
    if (!isSeriesView()) return;
    memory.pollTimer = setTimeout(async () => {
      if (!isSeriesView() || memory.busy) return;
      memory.busy = true;
      try {
        const oldJob = memory.status?.job;
        const oldHistory = (memory.status?.history || []).length;
        const status = await request('/api/series/status');
        memory.status = status;
        const jobChanged = JSON.stringify([oldJob?.id, oldJob?.state, oldJob?.progress, oldJob?.stage, oldJob?.message, oldHistory]) !== JSON.stringify([status.job?.id, status.job?.state, status.job?.progress, status.job?.stage, status.job?.message, (status.history || []).length]);
        if (jobChanged) await renderSeries(true);
        else schedulePoll(status.job?.state === 'running' ? 650 : 2200);
      } catch (_error) { schedulePoll(3200); }
      finally { memory.busy = false; }
    }, delay);
  }

  function bindPage() {
    document.querySelectorAll('input[name="seriesFirmwareSource"]').forEach(input => input.addEventListener('change', updateSourceVisibility));
    document.getElementById('seriesHardware')?.addEventListener('change', () => {
      const select = document.getElementById('seriesGithubFirmware');
      if (select && memory.github.length) select.innerHTML = githubOptions('', document.getElementById('seriesHardware').value);
      updateStartSummary();
    });
    ['seriesProfile', 'seriesPort', 'seriesPin', 'seriesApplyPsk', 'seriesLongName', 'seriesShortName', 'seriesGithubFirmware'].forEach(id => document.getElementById(id)?.addEventListener('input', updateStartSummary));
    document.getElementById('seriesLocalFile')?.addEventListener('change', async event => {
      try { await readLocalFile(event.target.files?.[0]); } catch (error) { toast(error.message || String(error), true); }
    });
    document.getElementById('seriesGithubLoad')?.addEventListener('click', loadGithubOptions);
    document.getElementById('seriesStart')?.addEventListener('click', startSeries);
    document.getElementById('seriesReload')?.addEventListener('click', () => renderSeries(true));
    document.getElementById('seriesCancel')?.addEventListener('click', cancelJob);
    document.getElementById('seriesTemplateSave')?.addEventListener('click', saveTemplate);
    document.getElementById('seriesTemplateDelete')?.addEventListener('click', deleteTemplate);
    document.getElementById('seriesTemplate')?.addEventListener('change', event => applyTemplate(event.target.value));
    document.getElementById('seriesHistoryClear')?.addEventListener('click', clearHistory);
    document.getElementById('seriesAutoNumber')?.addEventListener('change', event => { memory.numbering.enabled = event.target.checked; rememberNumbering(); updateNumberVisibility(); if (event.target.checked) generateNames(); });
    ['seriesLongPattern', 'seriesShortPattern', 'seriesCounter'].forEach(id => document.getElementById(id)?.addEventListener('input', () => { rememberNumbering(); if (memory.numbering.enabled) generateNames(); }));
    document.getElementById('seriesGenerateNames')?.addEventListener('click', () => { rememberNumbering(); generateNames(); });
  }

  function injectServiceLauncher() {
    const host = document.getElementById('pageHost');
    if (!host || host.querySelector('.series-launch-card')) return;
    const title = host.querySelector('.page-title-wrap h1');
    if (title?.textContent.trim() !== 'Profile & Service') return;
    const header = host.querySelector('.page-header');
    if (!header) return;
    const card = document.createElement('button');
    card.className = 'series-launch-card';
    card.innerHTML = '<span class="series-launch-icon">＋</span><span><strong>Neue Nodes / Serienbereitstellung</strong><small>Ein Setup wählen und mehrere Nodes nacheinander nur mit neuen Namen bespielen.</small></span><em>Öffnen ›</em>';
    header.after(card);
    card.addEventListener('click', () => document.querySelector('.nav-item[data-view="series"]')?.click());
  }

  document.addEventListener('click', event => {
    if (event.target.closest('.nav-item[data-view="series"]')) setTimeout(() => renderSeries(), 0);
  });

  const observer = new MutationObserver(() => {
    ensureNav();
    injectServiceLauncher();
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });
  window.addEventListener('beforeunload', () => clearTimeout(memory.pollTimer));
  ensureNav();
  setTimeout(() => { ensureNav(); injectServiceLauncher(); }, 180);
})();
