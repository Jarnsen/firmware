(() => {
  'use strict';

  const params = new URLSearchParams(location.search);
  const API = params.get('api') || 'http://127.0.0.1:0';
  const TOKEN = params.get('token') || '';
  let latest = null;
  let refreshBusy = false;

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

  function usbTargets() {
    return latest?.connections?.usb || [];
  }

  function uniqueUsb() {
    const targets = usbTargets();
    return targets.length === 1 ? targets[0] : null;
  }

  function noManagedTargetSelected() {
    const heading = document.querySelector('.service-target-head h3');
    return Boolean(heading && heading.textContent.trim() === 'Keine Node ausgewählt');
  }

  function notify(text, error = false) {
    const old = document.getElementById('legacyCompatToast');
    if (old) old.remove();
    const toast = document.createElement('div');
    toast.id = 'legacyCompatToast';
    toast.textContent = text;
    Object.assign(toast.style, {
      position: 'fixed',
      left: '50%',
      top: '24px',
      transform: 'translateX(-50%)',
      zIndex: '99999',
      maxWidth: '620px',
      padding: '11px 16px',
      borderRadius: '14px',
      background: error ? 'rgba(190, 30, 45, .94)' : 'rgba(30, 30, 34, .92)',
      color: '#fff',
      font: '600 13px/1.35 -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif',
      boxShadow: '0 12px 36px rgba(0,0,0,.22)',
      backdropFilter: 'blur(18px)',
    });
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), error ? 5200 : 2600);
  }

  function enhanceConnectionCard() {
    const value = document.getElementById('connectionValue');
    const meta = document.getElementById('connectionMeta');
    if (!value || !meta) return;
    const targets = usbTargets();
    if (targets.length === 1) {
      value.textContent = `USB ${targets[0].device} verbunden`;
      meta.textContent = 'USB aktiv · BLE Fallback · PIN 240180';
    } else if (targets.length > 1) {
      value.textContent = `${targets.length} USB-Nodes erkannt`;
      meta.textContent = 'Zielwahl erforderlich · BLE Fallback';
    }
  }

  function enhanceProfilePage() {
    const target = uniqueUsb();
    if (!target || !noManagedTargetSelected()) return;

    const heading = document.querySelector('.service-target-head h3');
    const detail = document.querySelector('.service-target-head p');
    if (heading) heading.textContent = `USB ${target.device}`;
    if (detail) {
      detail.textContent = target.mapped_node_id
        ? `Seriell verbunden · ${target.mapped_node_id}`
        : 'Seriell verbunden · neue/noch nicht verwaltete Node';
    }

    for (const command of ['capture', 'apply', 'provision']) {
      document.querySelectorAll(`[data-profile-action="${command}"]`).forEach(button => {
        button.disabled = false;
        button.removeAttribute('disabled');
      });
    }

    const actions = document.querySelector('.service-actions');
    if (actions && !actions.querySelector('[data-compat-action="usb-log"]')) {
      const button = document.createElement('button');
      button.className = 'service-button';
      button.dataset.compatAction = 'usb-log';
      button.textContent = 'USB-Log laden';
      actions.appendChild(button);
    }
  }

  function readProfilePayload(button) {
    return {
      command: String(button.dataset.profileAction || ''),
      slot: Number(button.dataset.slot),
      node_id: '',
      long_name: document.getElementById('profileLongName')?.value?.trim() || '',
      short_name: document.getElementById('profileShortName')?.value?.trim() || '',
      pin: document.getElementById('profilePin')?.value?.trim() || '240180',
      transport: document.getElementById('profileTransport')?.value || 'Automatisch',
      apply_pin: Boolean(document.getElementById('profileApplyPin')?.checked ?? true),
      apply_psk: Boolean(document.getElementById('profileApplyPsk')?.checked ?? false),
    };
  }

  async function runSerialProfileAction(button) {
    const payload = readProfilePayload(button);
    if (!Number.isInteger(payload.slot) || payload.slot < 0) throw new Error('Ungültiger Profil-Slot');
    if (payload.transport === 'Bluetooth') {
      throw new Error('Für eine neue/unbekannte Node ohne Auswahl bitte USB oder Automatisch verwenden.');
    }
    if (payload.short_name.length > 4) throw new Error('Der Short Name darf maximal 4 Zeichen lang sein.');
    if (!/^\d{6}$/.test(payload.pin)) throw new Error('Der Bluetooth-PIN muss genau 6 Ziffern haben.');

    if (payload.command === 'provision') {
      const target = uniqueUsb();
      const ok = window.confirm(
        `Werkreset auf ${target?.device || 'der USB-Node'} starten?\n\n` +
        'Die Node-Konfiguration wird gelöscht, danach werden passende Firmware und Grundprofil neu eingerichtet.'
      );
      if (!ok) return;
    }

    const result = await request('/api/profile/action', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    notify(result.message || result.result?.message || 'USB-Profilvorgang gestartet');
  }

  async function runUsbLog() {
    const target = uniqueUsb();
    if (!target) throw new Error('USB-Ziel ist nicht eindeutig.');
    const result = await request('/api/action', {
      method: 'POST',
      body: JSON.stringify({ command: 'usb_log', node_ids: [], node_id: '' }),
    });
    notify(`USB-Logdownload auf ${result.result?.target || target.device} gestartet`);
  }

  document.addEventListener('click', event => {
    const compat = event.target.closest('[data-compat-action="usb-log"]');
    if (compat) {
      event.preventDefault();
      event.stopImmediatePropagation();
      runUsbLog().catch(error => notify(error.message || String(error), true));
      return;
    }

    const button = event.target.closest('[data-profile-action]');
    if (!button || !['capture', 'apply', 'provision'].includes(button.dataset.profileAction)) return;
    if (!uniqueUsb() || !noManagedTargetSelected()) return;

    // app-v31.js intentionally blocks empty node_id. For a single physical USB
    // target the stable tool did not require a managed-node selection, so take
    // over this one click before the old client-side guard sees it.
    event.preventDefault();
    event.stopImmediatePropagation();
    runSerialProfileAction(button).catch(error => notify(error.message || String(error), true));
  }, true);

  function enhance() {
    enhanceConnectionCard();
    enhanceProfilePage();
  }

  const observer = new MutationObserver(enhance);
  observer.observe(document.documentElement, { childList: true, subtree: true });

  async function refresh() {
    if (refreshBusy || document.hidden) return;
    refreshBusy = true;
    try {
      latest = await request('/api/state');
      enhance();
    } catch (_error) {
      // The main app owns global connection error presentation.
    } finally {
      refreshBusy = false;
    }
  }

  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  setInterval(refresh, 2500);
  setTimeout(refresh, 300);
})();
