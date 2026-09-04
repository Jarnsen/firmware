(() => {
  'use strict';

  const params = new URLSearchParams(location.search);
  const API = params.get('api') || 'http://127.0.0.1:0';
  const TOKEN = params.get('token') || '';

  let latest = null;
  let busy = false;
  let sessionKey = '';
  let sessionStartedAt = 0;
  let sessionDecision = '';
  let selectedKey = '';
  let fallbackOpen = false;

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

  const usbTargets = () => Array.isArray(latest?.connections?.usb) ? latest.connections.usb : [];

  function physicalKey(target) {
    return [target?.identity, target?.serial_number, target?.hwid, target?.device]
      .map(value => String(value || '').trim().toLowerCase())
      .filter(Boolean)
      .join('|');
  }

  function mappedNodeId(target) {
    const explicit = String(target?.mapped_node_id || '').trim();
    if (explicit) return explicit;
    const selectedUsb = String(latest?.connections?.selected_usb_node_id || '').trim();
    if (selectedUsb) return selectedUsb;
    return '';
  }

  function nodeFor(target) {
    const id = mappedNodeId(target).toLowerCase();
    if (!id) return null;
    return (latest?.nodes || []).find(node => String(node?.node_id || '').trim().toLowerCase() === id) || null;
  }

  function selectNode(nodeId) {
    const id = String(nodeId || '').trim();
    if (!id) return;
    const key = id.toLowerCase();
    const current = String(document.querySelector('.inspector-sub')?.textContent || '').toLowerCase();
    if (selectedKey === key && current.includes(key)) return;

    const proxy = document.createElement('button');
    proxy.type = 'button';
    proxy.hidden = true;
    proxy.dataset.action = 'inspect';
    proxy.dataset.node = id;
    proxy.setAttribute('aria-hidden', 'true');
    document.body.appendChild(proxy);
    proxy.click();
    proxy.remove();
    selectedKey = key;
  }

  function markDecision(value) {
    if (!sessionKey) return;
    sessionDecision = value;
    document.documentElement.dataset.usbAttachDecision = value;
  }

  function resetSession() {
    sessionKey = '';
    sessionStartedAt = 0;
    sessionDecision = '';
    selectedKey = '';
    fallbackOpen = false;
    delete document.documentElement.dataset.usbAttachSession;
    delete document.documentElement.dataset.usbAttachDecision;
    const fallback = document.querySelector('#jarnsenUsbLogPrompt[data-v322-owned="1"]');
    fallback?.remove();
  }

  function decoratePrompt(root) {
    if (!root || root.dataset.v322Decorated === '1') return;
    root.dataset.v322Decorated = '1';
    root.dataset.usbSession = sessionKey;
    const buttons = [...root.querySelectorAll('.usb-log-prompt-actions button')];
    const decline = buttons.find(button => !button.classList.contains('primary'));
    const primary = buttons.find(button => button.classList.contains('primary'));
    if (decline) decline.textContent = 'Nicht herunterladen';
    if (primary) primary.textContent = 'Log herunterladen';
    const question = root.querySelector('.usb-log-prompt-question');
    if (question && !/heruntergeladen/i.test(question.textContent || '')) {
      question.textContent = 'Soll der Diagnose-Log dieser Node jetzt direkt über USB heruntergeladen werden?';
    }
  }

  function fallbackPrompt(target) {
    if (fallbackOpen || sessionDecision || document.getElementById('jarnsenUsbLogPrompt')) return;
    if (latest?.connections?.usb_identity_conflict) return;
    fallbackOpen = true;

    const node = nodeFor(target);
    const root = document.createElement('div');
    root.id = 'jarnsenUsbLogPrompt';
    root.dataset.v322Owned = '1';
    root.className = 'usb-log-prompt-backdrop';
    const box = document.createElement('div');
    box.className = 'usb-log-prompt';
    box.innerHTML = `
      <div class="usb-log-prompt-eyebrow">USB / SERIELL</div>
      <h3>Node automatisch erkannt</h3>
      <p class="usb-log-prompt-node"></p>
      <div class="usb-log-status"></div>
      <p class="usb-log-prompt-question">Soll der Diagnose-Log dieser Node jetzt direkt über USB heruntergeladen werden?</p>
      <div class="usb-log-prompt-actions"><button type="button">Nicht herunterladen</button><button type="button" class="v322-download">Log herunterladen</button></div>`;
    const identity = box.querySelector('.usb-log-prompt-node');
    identity.textContent = node
      ? `${node.long_name || node.node_id} · ${node.node_id} · ${target.device || 'USB'}`
      : `${target.device || 'USB'} · Node wird automatisch zugeordnet`;
    const status = box.querySelector('.usb-log-status');
    status.className = `usb-log-status ${node ? (node.log_due ? 'due' : 'current') : 'unknown'}`;
    status.textContent = node ? (node.log_due ? 'Logstatus: fällig' : 'Logstatus: aktuell') : 'Logstatus: noch nicht lokal bekannt';

    const [decline, download] = box.querySelectorAll('.usb-log-prompt-actions button');
    decline.addEventListener('click', () => {
      markDecision('declined');
      root.remove();
      fallbackOpen = false;
    });
    download.addEventListener('click', async () => {
      if (sessionDecision === 'download') return;
      markDecision('download');
      decline.disabled = true;
      download.disabled = true;
      download.textContent = 'Download wird gestartet …';
      try {
        const nodeId = mappedNodeId(target);
        await request('/api/action', {
          method: 'POST',
          body: JSON.stringify({ command: 'usb_log', node_ids: nodeId ? [nodeId] : [], node_id: nodeId }),
        });
        const question = box.querySelector('.usb-log-prompt-question');
        if (question) question.textContent = 'Download gestartet. Die Node bleibt automatisch ausgewählt.';
        setTimeout(() => root.remove(), 650);
      } catch (error) {
        markDecision('');
        decline.disabled = false;
        download.disabled = false;
        download.textContent = 'Erneut versuchen';
        status.className = 'usb-log-status due';
        status.textContent = `Start fehlgeschlagen: ${error.message || error}`;
      } finally {
        fallbackOpen = false;
      }
    });
    root.addEventListener('click', event => {
      if (event.target !== root) return;
      markDecision('declined');
      root.remove();
      fallbackOpen = false;
    });
    root.appendChild(box);
    document.body.appendChild(root);
    download.focus();
  }

  function handleSession() {
    const targets = usbTargets();
    if (targets.length === 0) {
      resetSession();
      return;
    }
    if (targets.length !== 1) {
      document.querySelector('#jarnsenUsbLogPrompt[data-v322-owned="1"]')?.remove();
      fallbackOpen = false;
      return;
    }

    const target = targets[0];
    const key = physicalKey(target);
    if (!key) return;
    if (key !== sessionKey) {
      sessionKey = key;
      sessionStartedAt = Date.now();
      sessionDecision = '';
      selectedKey = '';
      document.documentElement.dataset.usbAttachSession = key;
      delete document.documentElement.dataset.usbAttachDecision;
    }

    const nodeId = mappedNodeId(target);
    if (nodeId) selectNode(nodeId);

    const prompt = document.getElementById('jarnsenUsbLogPrompt');
    if (prompt) {
      decoratePrompt(prompt);
      return;
    }

    if (sessionDecision) return;
    const transferActive = Boolean(latest?.busy || latest?.connections?.usb_worker_busy || latest?.transfer_progress?.active);
    if (transferActive) {
      markDecision('download');
      return;
    }

    // legacy-compat normally creates the prompt after ~80 ms. This fallback makes
    // attach -> ask deterministic even if that compatibility hook is temporarily
    // delayed by a page rerender or WebView scheduling hiccup.
    if (Date.now() - sessionStartedAt > 2200) fallbackPrompt(target);
  }

  document.addEventListener('click', event => {
    const prompt = event.target.closest('#jarnsenUsbLogPrompt');
    if (!prompt) return;
    const button = event.target.closest('button');
    if (!button) return;
    if (button.classList.contains('primary') || /log.*laden|log.*herunterladen/i.test(button.textContent || '')) {
      markDecision('download');
      return;
    }
    if (/später|nicht herunterladen|abbrechen|schließen/i.test(button.textContent || '')) {
      markDecision('declined');
    }
  }, true);

  async function poll() {
    if (busy || document.hidden) return;
    busy = true;
    try {
      latest = await request('/api/state');
      handleSession();
    } catch (_error) {
      // Main UI owns global backend error state.
    } finally {
      busy = false;
    }
  }

  const observer = new MutationObserver(() => {
    const prompt = document.getElementById('jarnsenUsbLogPrompt');
    if (prompt) decoratePrompt(prompt);
  });
  observer.observe(document.documentElement, { childList: true, subtree: true });

  document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });
  setInterval(poll, 600);
  setTimeout(poll, 100);

  window.JarnsenUsbAttachV322 = {
    get session() { return sessionKey; },
    get decision() { return sessionDecision; },
    refresh: poll,
  };
})();
