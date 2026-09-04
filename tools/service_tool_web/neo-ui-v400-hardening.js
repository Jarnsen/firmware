(() => {
  'use strict';

  const host = document.getElementById('pageHost');
  if (!host) return;

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

  let queued = false;
  function schedule() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; harden(); });
  }

  new MutationObserver(schedule).observe(host, { childList: true, subtree: true });
  new MutationObserver(schedule).observe(document.querySelector('.topbar') || document.body, { childList: true, subtree: true });
  schedule();
  window.JarnsenNeoHardeningV400 = { harden };
})();
