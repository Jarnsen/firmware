(() => {
  'use strict';

  const params = new URLSearchParams(location.search);
  const API = params.get('api') || 'http://127.0.0.1:0';
  const TOKEN = params.get('token') || '';
  let latest = null;
  let refreshBusy = false;
  let activeUsbSignature = '';
  let activeUsbSelectionSignature = '';
  let multiUsbSignature = '';
  let usbPromptOpen = false;
  let usbConflictOpen = false;
  let dismissedUsbConflictKey = '';

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

  function targetSignature(target) {
    if (!target) return '';
    return [target.identity, target.serial_number, target.device]
      .map(value => String(value || '').trim().toLowerCase())
      .filter(Boolean)
      .join('|');
  }

  function targetSelectionSignature(target) {
    const physical = targetSignature(target);
    const nodeId = String(target?.mapped_node_id || '').trim().toLowerCase();
    return physical && nodeId ? `${physical}|node:${nodeId}` : '';
  }

  function mappedNode(target) {
    const id = String(target?.mapped_node_id || '').trim().toLowerCase();
    if (!id) return null;
    return (latest?.nodes || []).find(node => String(node.node_id || '').trim().toLowerCase() === id) || null;
  }

  function noManagedTargetSelected() {
    const heading = document.querySelector('.service-target-head h3');
    return Boolean(heading && heading.textContent.trim() === 'Keine Node ausgewählt');
  }

  function setTextIfChanged(element, text) {
    if (!element) return false;
    const next = String(text ?? '');
    if (element.textContent === next) return false;
    element.textContent = next;
    return true;
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
      const node = mappedNode(targets[0]);
      setTextIfChanged(value, `USB ${targets[0].device} verbunden`);
      setTextIfChanged(
        meta,
        `${node ? node.long_name || node.node_id : 'Serielle Node'} · USB aktiv · BLE Fallback`
      );
    } else if (targets.length > 1) {
      setTextIfChanged(value, `${targets.length} USB-Nodes erkannt`);
      setTextIfChanged(meta, 'Zielwahl erforderlich · USB vor BLE');
    }
  }

  function enhanceServiceUsbSelectors() {
    const target = uniqueUsb();
    if (!target) return;

    const port = document.getElementById('parityPort');
    if (port && [...port.options].some(option => option.value === target.device)) {
      port.value = target.device;
    }

    const nodeId = String(target.mapped_node_id || '').trim();
    const node = document.getElementById('parityNode');
    if (nodeId && node && [...node.options].some(option => option.value === nodeId)) {
      node.value = nodeId;
    }
  }

  function enhanceProfilePage() {
    const target = uniqueUsb();
    if (!target || !noManagedTargetSelected()) return;

    const heading = document.querySelector('.service-target-head h3');
    const detail = document.querySelector('.service-target-head p');
    const node = mappedNode(target);
    setTextIfChanged(heading, node ? node.long_name || node.node_id : `USB ${target.device}`);
    setTextIfChanged(
      detail,
      target.mapped_node_id
        ? `${target.mapped_node_id} · USB ${target.device} · seriell bevorzugt`
        : `USB ${target.device} · neue/noch nicht verwaltete Node`
    );

    for (const command of ['capture', 'apply', 'provision']) {
      document.querySelectorAll(`[data-profile-action="${command}"]`).forEach(button => {
        if (button.disabled) button.disabled = false;
        if (button.hasAttribute('disabled')) button.removeAttribute('disabled');
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

  function selectMappedNode(target) {
    const nodeId = String(target?.mapped_node_id || '').trim();
    if (!nodeId) return;

    enhanceServiceUsbSelectors();

    const proxy = document.createElement('button');
    proxy.type = 'button';
    proxy.hidden = true;
    proxy.dataset.action = 'inspect';
    proxy.dataset.node = nodeId;
    proxy.setAttribute('aria-hidden', 'true');
    document.body.appendChild(proxy);
    proxy.click();
    proxy.remove();
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
      throw new Error('USB ist verbunden und wird für Service bevorzugt. Für reines BLE bitte USB trennen.');
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

  async function runUsbLog(nodeId = '') {
    const target = uniqueUsb();
    if (!target) throw new Error('USB-Ziel ist nicht eindeutig.');
    const effectiveNodeId = String(nodeId || target.mapped_node_id || '').trim();
    const result = await request('/api/action', {
      method: 'POST',
      body: JSON.stringify({ command: 'usb_log', node_ids: effectiveNodeId ? [effectiveNodeId] : [], node_id: effectiveNodeId }),
    });
    notify(`USB-Logdownload auf ${result.result?.target || target.device} gestartet`);
  }

  function closeUsbPrompt() {
    usbPromptOpen = false;
    document.getElementById('jarnsenUsbLogPrompt')?.remove();
  }

  function closeUsbConflict() {
    usbConflictOpen = false;
    document.getElementById('jarnsenUsbIdentityPrompt')?.remove();
  }

  function offerUsbLog(target) {
    if (!target || usbPromptOpen || usbConflictOpen || document.getElementById('jarnsenUsbLogPrompt')) return;
    usbPromptOpen = true;

    const node = mappedNode(target);
    const backdrop = document.createElement('div');
    backdrop.id = 'jarnsenUsbLogPrompt';
    backdrop.className = 'usb-log-prompt-backdrop';

    const box = document.createElement('div');
    box.className = 'usb-log-prompt';

    const eyebrow = document.createElement('div');
    eyebrow.className = 'usb-log-prompt-eyebrow';
    eyebrow.textContent = 'USB / SERIELL';

    const title = document.createElement('h3');
    title.textContent = 'Node automatisch erkannt';

    const identity = document.createElement('p');
    identity.className = 'usb-log-prompt-node';
    identity.textContent = node
      ? `${node.long_name || node.node_id} · ${node.node_id} · ${target.device}`
      : `${target.device} · neue/noch nicht zugeordnete Node`;

    const status = document.createElement('div');
    status.className = `usb-log-status ${node ? (node.log_due ? 'due' : 'current') : 'unknown'}`;
    status.textContent = node
      ? (node.log_due ? 'Logstatus: fällig' : 'Logstatus: aktuell')
      : 'Logstatus: noch nicht lokal bekannt';

    const question = document.createElement('p');
    question.className = 'usb-log-prompt-question';
    question.textContent = 'Soll der Log jetzt direkt über USB heruntergeladen werden?';

    const actions = document.createElement('div');
    actions.className = 'usb-log-prompt-actions';
    const later = document.createElement('button');
    later.type = 'button';
    later.textContent = 'Später';
    const download = document.createElement('button');
    download.type = 'button';
    download.className = 'primary';
    download.textContent = 'Log jetzt laden';

    later.addEventListener('click', closeUsbPrompt);
    download.addEventListener('click', () => {
      const nodeId = String(target.mapped_node_id || '').trim();
      closeUsbPrompt();
      runUsbLog(nodeId).catch(error => notify(error.message || String(error), true));
    });
    backdrop.addEventListener('click', event => {
      if (event.target === backdrop) closeUsbPrompt();
    });

    actions.append(later, download);
    box.append(eyebrow, title, identity, status, question, actions);
    backdrop.appendChild(box);
    document.body.appendChild(backdrop);
    download.focus();
  }

  async function resolveUsbConflict(conflict, decision) {
    const result = await request('/api/action', {
      method: 'POST',
      body: JSON.stringify({
        command: 'resolve_usb_identity',
        conflict_key: String(conflict?.key || ''),
        decision,
      }),
    });
    closeUsbConflict();
    dismissedUsbConflictKey = '';
    activeUsbSelectionSignature = '';
    notify(result.result?.message || 'Node-Zuordnung gespeichert');
    setTimeout(refresh, 120);
  }

  function offerUsbConflict(conflict) {
    const key = String(conflict?.key || '');
    if (!key || usbConflictOpen || key === dismissedUsbConflictKey) return;
    closeUsbPrompt();
    usbConflictOpen = true;

    const backdrop = document.createElement('div');
    backdrop.id = 'jarnsenUsbIdentityPrompt';
    backdrop.className = 'usb-log-prompt-backdrop';
    const box = document.createElement('div');
    box.className = 'usb-log-prompt usb-identity-prompt';

    const eyebrow = document.createElement('div');
    eyebrow.className = 'usb-log-prompt-eyebrow';
    eyebrow.textContent = 'NODE-ZUORDNUNG';
    const title = document.createElement('h3');
    title.textContent = 'Gleicher Name – andere Node-ID';
    const current = document.createElement('p');
    current.className = 'usb-log-prompt-node';
    current.textContent = `Angeschlossen: ${conflict.long_name || 'Node'} (${conflict.short_name || '—'}) · ${conflict.new_node_id || '—'} · ${conflict.port || 'USB'}`;

    const explanation = document.createElement('p');
    explanation.className = 'usb-log-prompt-question';
    explanation.textContent = 'Long Name und Short Name stimmen mit vorhandenen Daten überein, die Node-ID ist aber anders. Wie soll das Tool die Historie behandeln?';

    const list = document.createElement('div');
    list.className = 'usb-identity-matches';
    for (const old of conflict.matches || []) {
      const row = document.createElement('div');
      const id = document.createElement('strong');
      id.textContent = old.node_id || 'alte Node';
      const detail = document.createElement('span');
      detail.textContent = `${Number(old.log_count || 0)} Log(s)${old.last_seen ? ` · zuletzt ${String(old.last_seen).replace('T', ' ').slice(0, 16)}` : ''}`;
      row.append(id, detail);
      list.appendChild(row);
    }

    const hint = document.createElement('div');
    hint.className = 'usb-identity-hint';
    hint.innerHTML = '<strong>Zusammenführen</strong> behält die Historie und merkt sich alte IDs als Alias. <strong>Parallel</strong> lässt beide Einträge getrennt.';

    const actions = document.createElement('div');
    actions.className = 'usb-identity-actions';
    const merge = document.createElement('button');
    merge.type = 'button';
    merge.className = 'primary';
    merge.textContent = 'Zusammenführen';
    const parallel = document.createElement('button');
    parallel.type = 'button';
    parallel.textContent = 'Parallel behalten';
    const replace = document.createElement('button');
    replace.type = 'button';
    replace.className = 'destructive';
    replace.textContent = 'Alte Daten löschen';
    const later = document.createElement('button');
    later.type = 'button';
    later.textContent = 'Später';

    merge.addEventListener('click', () => resolveUsbConflict(conflict, 'merge').catch(error => notify(error.message || String(error), true)));
    parallel.addEventListener('click', () => resolveUsbConflict(conflict, 'parallel').catch(error => notify(error.message || String(error), true)));
    replace.addEventListener('click', () => {
      const count = (conflict.matches || []).reduce((sum, item) => sum + Number(item.log_count || 0), 0);
      if (!window.confirm(`${count} alte Logdatei(en) wirklich in den Windows-Papierkorb verschieben und die alten Node-Einträge entfernen?`)) return;
      resolveUsbConflict(conflict, 'replace').catch(error => notify(error.message || String(error), true));
    });
    later.addEventListener('click', () => {
      dismissedUsbConflictKey = key;
      closeUsbConflict();
    });

    actions.append(merge, parallel, replace, later);
    box.append(eyebrow, title, current, explanation, list, hint, actions);
    backdrop.appendChild(box);
    document.body.appendChild(backdrop);
    merge.focus();
  }

  function handleUsbConflict() {
    const conflict = latest?.connections?.usb_identity_conflict || null;
    if (!conflict) {
      closeUsbConflict();
      return;
    }
    offerUsbConflict(conflict);
  }

  function handleUsbAttachment() {
    const targets = usbTargets();
    if (targets.length === 0) {
      activeUsbSignature = '';
      activeUsbSelectionSignature = '';
      multiUsbSignature = '';
      dismissedUsbConflictKey = '';
      closeUsbPrompt();
      closeUsbConflict();
      return;
    }

    if (targets.length > 1) {
      activeUsbSignature = '';
      activeUsbSelectionSignature = '';
      closeUsbPrompt();
      const signature = targets.map(targetSignature).sort().join('||');
      if (signature && signature !== multiUsbSignature) {
        multiUsbSignature = signature;
        notify(`${targets.length} USB-Nodes erkannt – automatische Auswahl ist aus Sicherheitsgründen gesperrt.`, true);
      }
      return;
    }

    multiUsbSignature = '';
    const target = targets[0];
    const physicalSignature = targetSignature(target);
    const selectionSignature = targetSelectionSignature(target);

    if (selectionSignature && selectionSignature !== activeUsbSelectionSignature) {
      activeUsbSelectionSignature = selectionSignature;
      selectMappedNode(target);
    }

    if (!physicalSignature || physicalSignature === activeUsbSignature) return;
    activeUsbSignature = physicalSignature;
    setTimeout(() => offerUsbLog(target), 80);
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

    event.preventDefault();
    event.stopImmediatePropagation();
    runSerialProfileAction(button).catch(error => notify(error.message || String(error), true));
  }, true);

  function enhance() {
    enhanceConnectionCard();
    enhanceServiceUsbSelectors();
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
      handleUsbConflict();
      handleUsbAttachment();
    } catch (_error) {
      // The main app owns global connection error presentation.
    } finally {
      refreshBusy = false;
    }
  }

  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
  setInterval(refresh, 1500);
  setTimeout(refresh, 250);
})();
