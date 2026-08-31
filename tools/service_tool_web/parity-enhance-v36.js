(() => {
  'use strict';

  const params = new URLSearchParams(location.search);
  const API = params.get('api') || 'http://127.0.0.1:0';
  const TOKEN = params.get('token') || '';
  let serialPaused = false;
  let frozenTail = '';
  let filterText = '';
  let searchText = '';
  let lastStatus = null;
  let statusBusy = false;
  let decorateQueued = false;
  const zoomValues = [80, 90, 100, 110, 125];

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

  function notify(text, error = false) {
    const old = document.getElementById('parityEnhanceToast');
    if (old) old.remove();
    const node = document.createElement('div');
    node.id = 'parityEnhanceToast';
    node.className = `parity-toast ${error ? 'error' : ''}`;
    node.textContent = text;
    document.body.appendChild(node);
    setTimeout(() => node.remove(), error ? 5200 : 2800);
  }

  function applyZoom(value) {
    const parsed = Number(value);
    const zoom = zoomValues.includes(parsed) ? parsed : 100;
    localStorage.setItem('jarnsen-ui-zoom', String(zoom));
    document.documentElement.style.zoom = `${zoom}%`;
    const select = document.getElementById('globalUiZoom');
    if (select) select.value = String(zoom);
  }

  function installZoom() {
    const top = document.querySelector('.top-actions');
    if (!top || document.getElementById('globalUiZoom')) return;
    const wrapper = document.createElement('label');
    wrapper.className = 'global-zoom-control';
    wrapper.title = 'Oberflächen-Zoom';
    wrapper.innerHTML = `<span>Zoom</span><select id="globalUiZoom">${zoomValues.map(value => `<option value="${value}">${value}%</option>`).join('')}</select>`;
    const theme = document.getElementById('themeButton');
    top.insertBefore(wrapper, theme || null);
    const saved = Number(localStorage.getItem('jarnsen-ui-zoom') || 100);
    applyZoom(saved);
    wrapper.querySelector('select').addEventListener('change', event => applyZoom(event.target.value));
  }

  function monitorCard() {
    return [...document.querySelectorAll('.parity-card')].find(card => card.querySelector('h3')?.textContent.trim() === 'Monitor') || null;
  }

  function highlightLine(line, query) {
    if (!query) return esc(line);
    const lower = line.toLowerCase();
    const needle = query.toLowerCase();
    let cursor = 0;
    let out = '';
    while (cursor < line.length) {
      const at = lower.indexOf(needle, cursor);
      if (at < 0) {
        out += esc(line.slice(cursor));
        break;
      }
      out += esc(line.slice(cursor, at));
      out += `<mark>${esc(line.slice(at, at + needle.length))}</mark>`;
      cursor = at + needle.length;
    }
    return out;
  }

  function filteredTail(raw) {
    const lines = String(raw || '').split(/\r?\n/);
    const needle = filterText.trim().toLowerCase();
    const shown = needle ? lines.filter(line => line.toLowerCase().includes(needle)) : lines;
    return shown.map(line => highlightLine(line, searchText.trim())).join('\n');
  }

  function updateTail() {
    const pre = document.getElementById('paritySerialTail');
    if (!pre) return;
    let raw = pre.dataset.rawTail;
    if (!raw) {
      raw = pre.textContent || '';
      pre.dataset.rawTail = raw;
    }
    if (serialPaused) raw = frozenTail;
    else frozenTail = raw;
    pre.innerHTML = filteredTail(raw);
    const shell = pre.parentElement;
    if (shell && !serialPaused) shell.scrollTop = shell.scrollHeight;
    const state = document.getElementById('serialPauseState');
    if (state) state.textContent = serialPaused ? 'Anzeige pausiert · Mitschnitt läuft weiter' : 'Anzeige live';
  }

  function drawPower() {
    const canvas = document.getElementById('serialPowerCanvas');
    if (!canvas) return;
    const samples = lastStatus?.serial?.power_samples || [];
    const latest = samples[samples.length - 1] || {};
    const labels = document.getElementById('serialPowerLatest');
    if (labels) {
      const fmt = (value, suffix, digits = 1) => value === null || value === undefined ? '—' : `${Number(value).toFixed(digits)} ${suffix}`;
      labels.innerHTML = `<span>${fmt(latest.voltage_v, 'V', 3)}</span><span>${fmt(latest.current_ma, 'mA')}</span><span>${fmt(latest.power_mw, 'mW')}</span>`;
    }
    const ctx = canvas.getContext('2d');
    const ratio = window.devicePixelRatio || 1;
    const width = Math.max(280, canvas.clientWidth || 520);
    const height = 112;
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const values = samples.map(item => item.current_ma).filter(value => Number.isFinite(value));
    if (values.length < 2) {
      ctx.font = '12px -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif';
      ctx.fillStyle = getComputedStyle(document.body).color || '#6e6e73';
      ctx.globalAlpha = .55;
      ctx.fillText('Noch nicht genug Strommesswerte für den Verlauf', 12, 58);
      ctx.globalAlpha = 1;
      return;
    }
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = Math.max(1, max - min);
    const accent = getComputedStyle(document.documentElement).getPropertyValue('--app-blue').trim() || '#007aff';
    ctx.strokeStyle = accent;
    ctx.lineWidth = 2;
    ctx.beginPath();
    values.forEach((value, index) => {
      const x = 10 + index * (width - 20) / Math.max(1, values.length - 1);
      const y = 10 + (max - value) * (height - 20) / span;
      if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
  }

  function decorateMonitor() {
    const card = monitorCard();
    if (!card) return;
    const serialTail = card.querySelector('.serial-tail');
    if (serialTail && !card.querySelector('.serial-enhance-tools')) {
      const tools = document.createElement('div');
      tools.className = 'serial-enhance-tools';
      tools.innerHTML = `
        <div class="serial-tool-row">
          <label><span>Filter</span><input id="serialViewFilter" value="${esc(filterText)}" placeholder="nur passende Zeilen"></label>
          <label><span>Suche</span><input id="serialViewSearch" value="${esc(searchText)}" placeholder="Treffer markieren"></label>
        </div>
        <div class="serial-tool-actions"><button id="serialPauseButton">${serialPaused ? 'Fortsetzen' : 'Anzeige pausieren'}</button><button id="serialExportButton">Sitzungslog exportieren</button><span id="serialPauseState">${serialPaused ? 'Anzeige pausiert · Mitschnitt läuft weiter' : 'Anzeige live'}</span></div>`;
      serialTail.before(tools);
      tools.querySelector('#serialViewFilter').addEventListener('input', event => { filterText = event.target.value; updateTail(); });
      tools.querySelector('#serialViewSearch').addEventListener('input', event => { searchText = event.target.value; updateTail(); });
      tools.querySelector('#serialPauseButton').addEventListener('click', event => {
        const pre = document.getElementById('paritySerialTail');
        if (!serialPaused) frozenTail = pre?.dataset.rawTail || pre?.textContent || '';
        serialPaused = !serialPaused;
        event.target.textContent = serialPaused ? 'Fortsetzen' : 'Anzeige pausieren';
        updateTail();
      });
      tools.querySelector('#serialExportButton').addEventListener('click', async event => {
        event.target.disabled = true;
        try {
          const result = await request('/api/service/action', { method: 'POST', body: JSON.stringify({ command: 'serial_monitor_export' }) });
          notify(`${result.message || 'Sitzungslog exportiert'}${result.path ? ` · ${result.path}` : ''}`);
        } catch (error) { notify(error.message || String(error), true); }
        finally { event.target.disabled = false; }
      });
    }

    if (serialTail && !card.querySelector('.serial-power-panel')) {
      const panel = document.createElement('div');
      panel.className = 'serial-power-panel';
      panel.innerHTML = `<div class="serial-power-head"><strong>Live-Leistung</strong><div id="serialPowerLatest"><span>— V</span><span>— mA</span><span>— mW</span></div></div><canvas id="serialPowerCanvas"></canvas>`;
      serialTail.after(panel);
    }
    updateTail();
    drawPower();
  }

  function decorate() {
    installZoom();
    decorateMonitor();
  }

  async function refreshStatus() {
    if (statusBusy || document.hidden || !document.querySelector('.parity-overlay')) return;
    statusBusy = true;
    try {
      lastStatus = await request('/api/service-status');
      drawPower();
    } catch (_error) {
      // Main parity window owns connection error presentation.
    } finally { statusBusy = false; }
  }

  const observer = new MutationObserver(() => {
    if (decorateQueued) return;
    decorateQueued = true;
    requestAnimationFrame(() => { decorateQueued = false; decorate(); });
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });

  document.addEventListener('visibilitychange', () => { if (!document.hidden) { decorate(); refreshStatus(); } });
  setInterval(refreshStatus, 1600);
  setTimeout(() => { installZoom(); decorate(); }, 120);
})();
