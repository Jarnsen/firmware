(() => {
  'use strict';

  const params = new URLSearchParams(location.search);
  const API = params.get('api') || 'http://127.0.0.1:0';
  const TOKEN = params.get('token') || '';
  let latest = null;
  let pollBusy = false;
  let downloadActive = false;
  let downloadStartedAt = 0;
  let downloadSawBusy = false;
  let downloadNodeId = '';
  let downloadStartCapturedAt = '';
  let downloadStartCapturedByNode = new Map();
  let successCloseTimer = null;
  let lastSelectionKey = '';

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

  function targets() {
    return Array.isArray(latest?.connections?.usb) ? latest.connections.usb : [];
  }

  function normalizeHardwareId(value) {
    const text = String(value ?? '').trim();
    const mac = text.match(/(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}/i);
    if (mac) return mac[0].toLowerCase().replace(/[^0-9a-f]/g, '');
    const compact = text.toLowerCase().replace(/[^0-9a-f]/g, '');
    return compact.length === 12 ? compact : '';
  }

  function collectHardwareIds(value, out = new Set()) {
    if (typeof value === 'string') {
      const id = normalizeHardwareId(value);
      if (id) out.add(id);
      return out;
    }
    if (Array.isArray(value)) {
      value.forEach(item => collectHardwareIds(item, out));
      return out;
    }
    if (value && typeof value === 'object') {
      Object.values(value).forEach(item => collectHardwareIds(item, out));
    }
    return out;
  }

  function mappedNodeId(target) {
    const explicit = String(target?.mapped_node_id || '').trim();
    if (explicit) return explicit;

    const needles = new Set([
      normalizeHardwareId(target?.serial_number),
      normalizeHardwareId(target?.hwid),
    ].filter(Boolean));
    if (!needles.size) return '';

    const matches = (latest?.nodes || []).filter(node => {
      const ids = collectHardwareIds(node);
      return [...needles].some(needle => ids.has(needle));
    });
    if (matches.length !== 1) return '';

    const nodeId = String(matches[0]?.node_id || '').trim();
    if (nodeId && target) target.mapped_node_id = nodeId;
    return nodeId;
  }

  function mappedNode(target) {
    const id = mappedNodeId(target).toLowerCase();
    if (!id) return null;
    return (latest?.nodes || []).find(node => String(node.node_id || '').trim().toLowerCase() === id) || null;
  }

  function nodeById(nodeId) {
    const id = String(nodeId || '').trim().toLowerCase();
    if (!id) return null;
    return (latest?.nodes || []).find(node => String(node.node_id || '').trim().toLowerCase() === id) || null;
  }

  function autoSelectMappedNode(target) {
    const nodeId = mappedNodeId(target);
    if (!nodeId) {
      lastSelectionKey = '';
      return;
    }

    const key = `${String(target?.device || target?.port || '')}|${nodeId}`;
    const inspectorSub = String(document.querySelector('.inspector-sub')?.textContent || '').toLowerCase();
    const alreadySelected = inspectorSub.includes(nodeId.toLowerCase());
    if (lastSelectionKey === key && alreadySelected) return;

    // app-v31.js owns the canonical selected-node state through its delegated
    // inspect action. Re-apply it when a page render or transient state refresh
    // has dropped the inspector selection while the same unique USB node remains
    // attached. This never changes navigation; it only restores the active node.
    const proxy = document.createElement('button');
    proxy.type = 'button';
    proxy.hidden = true;
    proxy.dataset.action = 'inspect';
    proxy.dataset.node = nodeId;
    proxy.setAttribute('aria-hidden', 'true');
    document.body.appendChild(proxy);
    proxy.click();
    proxy.remove();
    lastSelectionKey = key;
  }

  function setText(element, text) {
    if (element && element.textContent !== text) element.textContent = text;
  }

  function paintConnection() {
    const value = document.getElementById('connectionValue');
    const meta = document.getElementById('connectionMeta');
    if (!value || !meta) return;
    const usb = targets();
    if (usb.length === 1) {
      const target = usb[0];
      const node = mappedNode(target);
      setText(value, `USB ${target.device || 'seriell'} verbunden`);
      if (value.style.color !== 'var(--app-green)') value.style.color = 'var(--app-green)';
      setText(
        meta,
        node
          ? `${node.long_name || node.node_id} · USB aktiv · BLE Fallback`
          : 'Serielle Node erkannt · Zuordnung läuft · USB vor BLE',
      );
      if (value.dataset.usbOwned !== '1') value.dataset.usbOwned = '1';
      return;
    }
    if (usb.length > 1) {
      setText(value, `${usb.length} USB-Nodes erkannt`);
      if (value.style.color !== 'var(--app-orange)') value.style.color = 'var(--app-orange)';
      setText(meta, 'Zielwahl erforderlich · USB vor BLE');
      if (value.dataset.usbOwned !== '1') value.dataset.usbOwned = '1';
      return;
    }
    if (value.dataset.usbOwned === '1') {
      delete value.dataset.usbOwned;
      value.style.color = '';
    }
  }

  function promptParts() {
    const root = document.getElementById('jarnsenUsbLogPrompt');
    if (!root) return null;
    return {
      root,
      box: root.querySelector('.usb-log-prompt'),
      title: root.querySelector('h3'),
      identity: root.querySelector('.usb-log-prompt-node'),
      status: root.querySelector('.usb-log-status'),
      question: root.querySelector('.usb-log-prompt-question'),
      actions: root.querySelector('.usb-log-prompt-actions'),
      primary: root.querySelector('.usb-log-prompt-actions .primary'),
    };
  }

  function ensureProgress(parts) {
    if (!parts?.box) return null;
    let wrap = parts.box.querySelector('.usb-download-progress-v320');
    if (wrap) return wrap;
    wrap = document.createElement('div');
    wrap.className = 'usb-download-progress-v320';
    Object.assign(wrap.style, {
      margin: '12px 0 4px',
      padding: '11px 12px',
      borderRadius: '12px',
      background: 'rgba(0,122,255,.08)',
      border: '1px solid rgba(0,122,255,.16)',
    });
    const line = document.createElement('div');
    line.className = 'usb-download-progress-line';
    line.textContent = 'Logdownload wird vorbereitet …';
    Object.assign(line.style, { fontWeight: '700', fontSize: '13px', marginBottom: '8px' });
    const track = document.createElement('div');
    Object.assign(track.style, {
      height: '7px',
      borderRadius: '999px',
      overflow: 'hidden',
      background: 'rgba(120,120,128,.18)',
    });
    const bar = document.createElement('div');
    bar.className = 'usb-download-progress-bar';
    Object.assign(bar.style, {
      height: '100%',
      width: '38%',
      borderRadius: '999px',
      background: 'var(--app-blue, #0a84ff)',
      animation: 'usbLogSlideV320 1.15s ease-in-out infinite alternate',
      transform: 'translateX(0)',
    });
    track.appendChild(bar);
    wrap.append(line, track);
    parts.question?.insertAdjacentElement('afterend', wrap);
    if (!document.getElementById('usbLogProgressStyleV320')) {
      const style = document.createElement('style');
      style.id = 'usbLogProgressStyleV320';
      style.textContent = '@keyframes usbLogSlideV320{from{transform:translateX(0)}to{transform:translateX(160%)}}';
      document.head.appendChild(style);
    }
    return wrap;
  }

  function setProgressText(text) {
    const parts = promptParts();
    const wrap = ensureProgress(parts);
    const line = wrap?.querySelector('.usb-download-progress-line');
    if (line) setText(line, text || 'Logdownload läuft …');
  }

  function automaticStatusText(raw) {
    const text = String(raw || '').trim();
    const lower = text.toLowerCase();
    if (!text) return '';
    if (lower.includes('jetzt export am gerät bestätigen')) {
      return '__MANUAL_PATH__';
    }
    if (lower.includes('warte auf diagnostikexport') || lower.includes('warte auf export')) {
      return 'Export automatisch angefordert – warte auf Daten …';
    }
    return text;
  }

  function finishDownload(ok, message) {
    downloadActive = false;
    downloadSawBusy = false;
    downloadNodeId = '';
    downloadStartCapturedAt = '';
    downloadStartCapturedByNode = new Map();
    const parts = promptParts();
    if (!parts) return;
    if (parts.title) setText(parts.title, ok ? 'Logdownload abgeschlossen' : 'Logdownload fehlgeschlagen');
    if (parts.status) {
      parts.status.className = `usb-log-status ${ok ? 'current' : 'due'}`;
      setText(parts.status, ok ? 'Logstatus: aktualisiert' : 'Logstatus: Fehler');
    }
    setProgressText(message || (ok ? 'Log wurde erfolgreich übernommen.' : 'Der Log konnte nicht geladen werden.'));
    const bar = parts.box?.querySelector('.usb-download-progress-bar');
    if (bar) {
      bar.style.animation = 'none';
      bar.style.transform = 'none';
      bar.style.width = ok ? '100%' : '0%';
    }

    if (successCloseTimer) clearTimeout(successCloseTimer);
    if (ok) {
      // A successful transfer is terminal: stop the moving bar immediately and
      // close the modal automatically instead of leaving a stale "läuft" window.
      successCloseTimer = setTimeout(() => {
        if (parts.root?.isConnected) parts.root.remove();
        successCloseTimer = null;
      }, 850);
      return;
    }

    if (parts.actions) {
      parts.actions.innerHTML = '';
      const close = document.createElement('button');
      close.type = 'button';
      close.className = 'primary';
      close.textContent = 'Schließen';
      close.addEventListener('click', () => parts.root.remove(), { once: true });
      parts.actions.appendChild(close);
      close.focus();
    }
  }

  async function startUsbLogFromPrompt(event) {
    if (downloadActive) return;
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();

    const usb = targets();
    if (usb.length !== 1) {
      finishDownload(false, usb.length ? 'Mehrere USB-Ziele erkannt.' : 'Keine USB-Node erkannt.');
      return;
    }

    const target = usb[0];
    const parts = promptParts();
    downloadActive = true;
    downloadStartedAt = Date.now();
    downloadSawBusy = false;
    downloadStartCapturedByNode = new Map(
      (latest?.nodes || []).map(node => [
        String(node?.node_id || '').trim().toLowerCase(),
        String(node?.captured_at || ''),
      ]),
    );
    downloadNodeId = mappedNodeId(target);
    downloadStartCapturedAt = downloadStartCapturedByNode.get(downloadNodeId.toLowerCase()) || '';

    if (parts?.title) setText(parts.title, 'Logdownload läuft');
    if (parts?.question) {
      setText(
        parts.question,
        `Der Export wird auf der Node automatisch über ${target.device || 'USB'} angefordert. Keine Bedienung an der Node nötig – bitte nur angeschlossen lassen.`,
      );
    }
    if (parts?.status) {
      parts.status.className = 'usb-log-status unknown';
      setText(parts.status, 'USB-Log: automatischer Export wird angefordert …');
    }
    if (parts?.actions) {
      [...parts.actions.querySelectorAll('button')].forEach(button => { button.disabled = true; });
    }
    setProgressText('USB-Port öffnen und Export automatisch anfordern …');

    try {
      const result = await request('/api/action', {
        method: 'POST',
        body: JSON.stringify({
          command: 'usb_log',
          node_ids: downloadNodeId ? [downloadNodeId] : [],
          node_id: downloadNodeId,
        }),
      });
      if (result?.result?.started === false) {
        throw new Error('Der automatische USB-Logdownload wurde nicht gestartet.');
      }
      setProgressText(`Export auf ${result?.result?.target || target.device || 'USB'} automatisch angefordert – warte auf Daten …`);
    } catch (error) {
      finishDownload(false, error.message || String(error));
    }
  }

  function bindPrompt() {
    const parts = promptParts();
    const button = parts?.primary;
    if (!button || button.dataset.usbProgressV320 === '1') return;
    button.dataset.usbProgressV320 = '1';
    button.addEventListener('click', startUsbLogFromPrompt, true);
  }

  function updateDownloadProgress() {
    if (!downloadActive) return;

    const rawStatus = String(latest?.status || '').trim();
    const statusText = automaticStatusText(rawStatus);
    const busy = Boolean(latest?.busy || latest?.connections?.usb_worker_busy);
    if (busy) downloadSawBusy = true;

    // A previously unknown physical USB target gets its persistent node mapping
    // only after _finish_payload has parsed and saved the first diagnostic log.
    // Re-resolve that mapping on every poll instead of freezing node_id='' from
    // the moment the popup button was pressed.
    const usb = targets();
    if (!downloadNodeId && usb.length === 1) {
      const resolvedNodeId = mappedNodeId(usb[0]);
      if (resolvedNodeId) {
        downloadNodeId = resolvedNodeId;
        downloadStartCapturedAt = downloadStartCapturedByNode.get(resolvedNodeId.toLowerCase()) || '';
      }
    }

    // A newly imported log is the strongest completion signal. The headless
    // service state can briefly retain a busy/status string after the worker has
    // already emitted "done", but captured_at changes only after _finish_payload
    // successfully saved and indexed the new payload.
    const node = nodeById(downloadNodeId);
    const capturedAt = String(node?.captured_at || '');
    if (downloadNodeId && capturedAt && capturedAt !== downloadStartCapturedAt) {
      finishDownload(true, 'Log wurde gespeichert und der Node-Historie zugeordnet.');
      return;
    }

    if (statusText === '__MANUAL_PATH__') {
      finishDownload(false, 'Die installierte Node-Firmware unterstützt den automatischen USB-Export noch nicht. Firmware aktualisieren; danach ist keine Bedienung an der Node mehr nötig.');
      return;
    }
    if (statusText) setProgressText(statusText);

    const lower = rawStatus.toLowerCase();
    if (/fehler|konnte nicht|abgebrochen|fehlgeschlagen/.test(lower)) {
      finishDownload(false, rawStatus);
      return;
    }
    // The legacy worker's actual success event is "DONE - Verbindung geschlossen".
    // Accept it explicitly instead of waiting forever for German words that this
    // backend path never emits into state.status.
    if (/\bdone\b|gespeichert|erfolgreich|abgeschlossen|fertig|verbindung geschlossen/.test(lower)) {
      finishDownload(true, rawStatus || 'Logdownload beendet.');
      return;
    }
    if (downloadSawBusy && !busy && Date.now() - downloadStartedAt > 1200) {
      finishDownload(true, rawStatus || 'Logdownload beendet.');
    }
  }

  async function poll() {
    if (pollBusy || document.hidden) return;
    pollBusy = true;
    try {
      latest = await request('/api/state');
      const usb = targets();
      if (usb.length === 1) autoSelectMappedNode(usb[0]);
      else lastSelectionKey = '';
      paintConnection();
      bindPrompt();
      updateDownloadProgress();
    } catch (_error) {
      // The main UI already owns backend error presentation.
    } finally {
      pollBusy = false;
    }
  }

  // Do not observe arbitrary DOM mutations here. paintConnection() changes DOM text
  // itself, so a subtree MutationObserver can recursively schedule itself and pin
  // the WebView UI thread. The bounded poll is sufficient for USB state + prompt binding.
  document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });
  setInterval(poll, 750);
  setTimeout(poll, 120);
})();