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
  }

  // The visible v4 node-open control deliberately keeps data-action="inspect"
  // for old functional parity. Legacy capture listeners would otherwise consume
  // a real user click before the v4 document handler can select the requested
  // node and render its new details page. For trusted/user clicks only, translate
  // the control into the v4 details-node action while the event travels through
  // the document. Synthetic .click() calls from usb-attach-v322 stay untouched,
  // so USB auto-selection still updates legacy state without forcing navigation.
  function routeTrustedNodeOpen(event) {
    if (!event.isTrusted || document.body.dataset.neoUi !== 'v400') return;
    const inspect = event.target?.closest?.('#pageHost .v323-node-row button[data-action="inspect"][data-node]');
    if (!inspect) return;

    const previousNeoAction = inspect.getAttribute('data-neo-action');
    inspect.setAttribute('data-neo-action', 'details-node');
    inspect.removeAttribute('data-action');

    setTimeout(() => {
      if (!inspect.isConnected) return;
      inspect.setAttribute('data-action', 'inspect');
      if (previousNeoAction == null) inspect.removeAttribute('data-neo-action');
      else inspect.setAttribute('data-neo-action', previousNeoAction);
    }, 0);
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

        // usb-attach-v322 uses the proven legacy inspect action to update all old
        // selection state. In v4 that action also opens details. Auto-select must
        // not unexpectedly move the user away from the page they were viewing,
        // so restore the page while keeping the selected Node state intact.
        setTimeout(() => {
          const neo = window.JarnsenNeoUIV400;
          if (!neo || !pageBeforeUsbAttach || pageBeforeUsbAttach === 'details') return;
          if (neo.currentPage === 'details') neo.renderPage(pageBeforeUsbAttach);
        }, 140);
      }

      // The legacy inspector is hidden in v4, but old parity checks still use it
      // as the canonical selection mirror. Keep its identity synchronized without
      // changing the visible v4 layout.
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

  // window capture runs before the legacy document capture layer. The handler
  // only mutates trusted/manual node-open events and intentionally does not stop
  // propagation; the v4 document handler then receives details-node normally.
  window.addEventListener('click', routeTrustedNodeOpen, true);
  new MutationObserver(schedule).observe(host, { childList: true, subtree: true });
  new MutationObserver(() => { schedule(); syncUsbSelection(); }).observe(document.querySelector('.topbar') || document.body, { childList: true, subtree: true });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) syncUsbSelection(); });
  setInterval(syncUsbSelection, 500);
  setTimeout(syncUsbSelection, 120);
  schedule();
  window.JarnsenNeoHardeningV400 = { harden, syncUsbSelection };
})();