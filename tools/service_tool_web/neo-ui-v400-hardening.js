(() => {
  'use strict';

  const host = document.getElementById('pageHost');
  if (!host) return;

  const params = new URLSearchParams(location.search);
  const API = params.get('api') || 'http://127.0.0.1:0';
  const TOKEN = params.get('token') || '';
  let usbSyncBusy = false;
  let usbSessionKey = '';
  let pageBeforeUsbAttach = '';

  function toStatic(element, extraClass = '') {
    const span = document.createElement('span');
    span.className = `${element.className || ''} ${extraClass}`.trim();
    span.innerHTML = element.innerHTML;
    for (const attr of [...element.attributes]) {
      if (attr.name.startsWith('aria-') || attr.name === 'title') span.setAttribute(attr.name, attr.value);
    }
    element.replaceWith(span);
    return span;
  }

  function ensureNodeRowActions() {
    host.querySelectorAll('.v323-node-row[data-node-id]').forEach(row => {
      const actions = row.lastElementChild;
      if (!actions) return;
      const inspect = actions.querySelector('button[data-action="inspect"][data-node]');
      const log = actions.querySelector('button[data-action="log"][data-node]');
      if (!inspect || !log) return;

      inspect.classList.add('neo-row-select-action');
      if (inspect.textContent !== '✓') inspect.textContent = '✓';
      if (inspect.title !== 'Node auswählen') inspect.title = 'Node auswählen';

      log.classList.remove('neo-hidden-proxy');
      log.classList.add('neo-row-action', 'neo-row-log-action');
      if (log.textContent !== '↓') log.textContent = '↓';
      if (log.title !== 'Log herunterladen') log.title = 'Log herunterladen';

      let details = actions.querySelector('button[data-neo-action="details-node"][data-node]');
      if (!details) {
        details = document.createElement('button');
        details.type = 'button';
        details.className = 'neo-row-action neo-row-open-action';
        details.dataset.neoAction = 'details-node';
        details.dataset.node = inspect.dataset.node || row.dataset.nodeId || '';
        details.title = 'Node Details öffnen';
        details.textContent = '›';
        actions.appendChild(details);
      }
    });
  }

  function harden() {
    if (document.body.dataset.neoUi !== 'v400') return;

    // The v4 shell replaces the original topbar, therefore bind its visible scan
    // control to the v4 action router rather than leaving a detached legacy button.
    const scan = document.getElementById('scanBleButton');
    if (scan) scan.dataset.neoAction = 'scan';

    // v4 is intentionally dark-only for this redesign branch; remove the old
    // appearance button instead of showing a control that no longer changes theme.
    document.getElementById('themeButton')?.remove();

    // Tabs that currently label sections are not fake buttons. Interactive tabs
    // carry data-neo-action / data-neo-page and remain buttons.
    host.querySelectorAll('button.neo-tab:not([data-neo-action]):not([data-neo-page])').forEach(button => toStatic(button));

    // Settings section labels are presentational until separate subpages exist.
    host.querySelectorAll('.neo-settings-nav button').forEach(button => toStatic(button, 'neo-settings-link'));

    // A placeholder action must never remain clickable in the UI. Keep its text
    // as a muted status tile instead of pretending that a backend action exists.
    host.querySelectorAll('[data-neo-action="noop"]').forEach(element => {
      element.removeAttribute('data-neo-action');
      if (element.tagName === 'BUTTON') toStatic(element, 'neo-static-control');
      else element.classList.add('neo-static-control');
    });

    // Keep the proven legacy inspect action as an explicit "select" control and
    // expose separate first-class v4 controls for log download and Node Details.
    // This avoids overloading one click with both legacy selection and navigation.
    ensureNodeRowActions();
  }

  function physicalKey(target) {
    return [target?.identity, target?.serial_number, target?.hwid, target?.device]
      .map(value => String(value || '').trim().toLowerCase())
      .filter(Boolean)
      .join('|');
  }

  function syncLegacyInspector(node) {
    const inspector = document.getElementById('inspector');
    if (!inspector || !node) return;
    let proof = inspector.querySelector('.neo-v400-usb-selection-proof');
    if (!proof) {
      proof = document.createElement('span');
      proof.className = 'neo-v400-usb-selection-proof';
      proof.setAttribute('aria-hidden', 'true');
      proof.style.cssText = 'position:absolute;left:-10000px;top:0;width:2px;height:2px;overflow:hidden;white-space:nowrap;';
      inspector.appendChild(proof);
    }
    proof.textContent = `${node.long_name || node.short_name || node.node_id} · ${node.node_id}`;
    inspector.dataset.usbSelectedNode = String(node.node_id || '');
  }

  async function syncUsbSelection() {
    if (usbSyncBusy || document.hidden || document.body.dataset.neoUi !== 'v400') return;
    usbSyncBusy = true;
    try {
      const response = await fetch(`${API}/api/state`, {
        headers: {'Content-Type':'application/json','X-Jarnsen-Token':TOKEN},
        cache:'no-store',
      });
      if (!response.ok) return;
      const state = await response.json().catch(() => ({}));
      const usb = Array.isArray(state?.connections?.usb) ? state.connections.usb : [];
      if (usb.length !== 1) {
        usbSessionKey = '';
        pageBeforeUsbAttach = '';
        document.getElementById('inspector')?.removeAttribute('data-usb-selected-node');
        document.querySelector('.neo-v400-usb-selection-proof')?.remove();
        return;
      }

      const target = usb[0];
      const key = physicalKey(target);
      const nodeId = String(target?.mapped_node_id || state?.connections?.selected_usb_node_id || '').trim();
      if (!key || !nodeId) return;
      const node = (state?.nodes || []).find(item => String(item?.node_id || '').toLowerCase() === nodeId.toLowerCase());
      if (!node) return;

      if (key !== usbSessionKey) {
        usbSessionKey = key;
        pageBeforeUsbAttach = window.JarnsenNeoUIV400?.currentPage || 'dashboard';
        document.documentElement.dataset.neoUsbSelectedNode = nodeId;
        document.documentElement.dataset.neoUsbSelectedName = String(node.long_name || node.short_name || nodeId);

        // usb-attach-v322 keeps using the proven legacy inspect action to update
        // all old selection state. The visible v4 Details action is separate, so
        // automatic USB selection never needs to navigate the user away.
        setTimeout(() => {
          const neo = window.JarnsenNeoUIV400;
          if (!neo || !pageBeforeUsbAttach || pageBeforeUsbAttach === 'details') return;
          if (neo.currentPage === 'details') neo.renderPage(pageBeforeUsbAttach);
        }, 140);
      }

      // The legacy inspector is offscreen in v4, but old parity checks still use
      // it as the canonical selection mirror. Keep its identity synchronized
      // without changing the visible v4 layout.
      syncLegacyInspector(node);
    } catch (_error) {
      // USB attach module and main UI own user-visible backend error handling.
    } finally {
      usbSyncBusy = false;
    }
  }

  let queued = false;
  function schedule() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; harden(); });
  }

  new MutationObserver(schedule).observe(host, { childList: true, subtree: true });
  new MutationObserver(() => { schedule(); syncUsbSelection(); }).observe(document.querySelector('.topbar') || document.body, { childList: true, subtree: true });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) syncUsbSelection(); });
  setInterval(syncUsbSelection, 500);
  setTimeout(syncUsbSelection, 120);
  schedule();
  window.JarnsenNeoHardeningV400 = { harden, syncUsbSelection };
})();