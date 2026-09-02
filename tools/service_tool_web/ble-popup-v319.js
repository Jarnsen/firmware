(() => {
  'use strict';

  const params = new URLSearchParams(location.search);
  const API = params.get('api') || 'http://127.0.0.1:0';
  const TOKEN = params.get('token') || '';
  let checkGeneration = 0;
  let popupOpen = false;

  async function state() {
    const response = await fetch(`${API}/api/state`, {
      headers: { 'X-Jarnsen-Token': TOKEN },
      cache: 'no-store',
    });
    if (!response.ok) return null;
    return response.json().catch(() => null);
  }

  function messageFor(status) {
    const text = String(status || '');
    const lower = text.toLowerCase();
    if (lower.includes('bluetooth radio is not powered on') || lower.includes('powered_off') || lower.includes('powered off')) {
      return 'Bluetooth ist ausgeschaltet. Bitte Bluetooth in Windows einschalten und anschließend erneut „BLE prüfen“ drücken.';
    }
    if (lower.includes('ble-automatik derzeit nicht verfügbar') || lower.includes('ble-prüfung fehlgeschlagen') || lower.includes('ble-pruefung fehlgeschlagen')) {
      return text || 'Die BLE-Prüfung ist fehlgeschlagen. Bitte Bluetooth in Windows prüfen und erneut versuchen.';
    }
    return '';
  }

  function popup(message) {
    if (!message || popupOpen) return;
    popupOpen = true;
    const backdrop = document.createElement('div');
    backdrop.id = 'jarnsenBlePopup';
    Object.assign(backdrop.style, {
      position: 'fixed', inset: '0', zIndex: '100000', display: 'grid', placeItems: 'center',
      background: 'rgba(15, 18, 24, .34)', backdropFilter: 'blur(8px)'
    });
    const box = document.createElement('div');
    Object.assign(box.style, {
      width: 'min(420px, calc(100vw - 40px))', padding: '24px', borderRadius: '24px',
      background: 'var(--app-panel, #fff)', color: 'var(--app-fg, #111)',
      boxShadow: '0 24px 80px rgba(0,0,0,.28)', fontFamily: '-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif'
    });
    const title = document.createElement('h3');
    title.textContent = 'BLE-Prüfung fehlgeschlagen';
    title.style.margin = '0 0 12px';
    const body = document.createElement('p');
    body.textContent = message;
    body.style.margin = '0 0 20px';
    body.style.lineHeight = '1.45';
    const button = document.createElement('button');
    button.textContent = 'OK';
    Object.assign(button.style, {
      width: '100%', border: '0', borderRadius: '14px', padding: '12px 16px',
      background: '#0a84ff', color: '#fff', fontWeight: '700', fontSize: '16px', cursor: 'pointer'
    });
    const close = () => { popupOpen = false; backdrop.remove(); };
    button.addEventListener('click', close);
    backdrop.addEventListener('click', event => { if (event.target === backdrop) close(); });
    box.append(title, body, button);
    backdrop.appendChild(box);
    document.body.appendChild(backdrop);
    button.focus();
  }

  async function probe(generation) {
    if (generation !== checkGeneration || popupOpen) return;
    const data = await state();
    if (generation !== checkGeneration || !data) return;
    const message = messageFor(data.status);
    if (message) popup(message);
  }

  document.addEventListener('click', event => {
    const button = event.target.closest('#scanBleButton');
    if (!button) return;
    const generation = ++checkGeneration;
    for (const delay of [300, 700, 1400, 2600]) {
      setTimeout(() => probe(generation).catch(() => {}), delay);
    }
  }, true);
})();
