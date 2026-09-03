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

  function mappedNode(target) {
    const id = String(target?.mapped_node_id || '').trim().toLowerCase();
    if (!id) return null;
    return (latest?.nodes || []).find(node => String(node.node_id || '').trim().toLowerCase() === id) || null;
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

    const nodeId = String(target.mapped_node_id || '').trim();
    try {
      const result = await request('/api/action', {
        method: 'POST',
        body: JSON.stringify({
          command: 'usb_log',
          node_ids: nodeId ? [nodeId] : [],
          node_id: nodeId,
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
    const busy = Boolean(latest?.busy);
    if (busy) downloadSawBusy = true;

    if (statusText === '__MANUAL_PATH__') {
      finishDownload(false, 'Interner Fehler: manueller USB-Pfad aktiv. Der Export muss automatisch gestartet werden.');
      return;
    }
    if (statusText) setProgressText(statusText);

    const lower = rawStatus.toLowerCase();
    if (/fehler|konnte nicht|abgebrochen|fehlgeschlagen/.test(lower)) {
      finishDownload(false, rawStatus);
      return;
    }
    if (/gespeichert|erfolgreich|abgeschlossen|fertig/.test(lower)) {
      finishDownload(true, rawStatus);
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
