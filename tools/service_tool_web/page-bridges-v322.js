(() => {
  'use strict';

  const pageHost = document.getElementById('pageHost');
  if (!pageHost) return;

  function openView(view) {
    const button = document.querySelector(`.nav-item[data-view="${view}"]`);
    if (button) button.click();
  }

  function openServiceTab(tab) {
    const serviceButton = document.getElementById('parityServiceButton');
    if (!serviceButton) return;
    serviceButton.click();
    setTimeout(() => {
      document.querySelector(`.service-tab[data-service-tab="${tab}"]`)?.click();
    }, 120);
  }

  function appendButton(host, label, attrs, primary = false) {
    if (!host) return;
    const marker = Object.entries(attrs).map(([key, value]) => `[${key}="${value}"]`).join('');
    if (marker && host.querySelector(marker)) return;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `mini-button${primary ? ' primary' : ''}`;
    Object.entries(attrs).forEach(([key, value]) => button.setAttribute(key, value));
    button.textContent = label;
    host.appendChild(button);
  }

  function decorate() {
    if (['power', 'network', 'tools'].includes(document.body.dataset.redesignPage || '')) return;
    const title = pageHost.querySelector('.page-title-wrap h1')?.textContent?.trim() || '';
    const header = pageHost.querySelector('.page-header');
    if (!header) return;
    let actions = header.querySelector('.page-actions');
    if (!actions) {
      actions = document.createElement('div');
      actions.className = 'page-actions';
      header.appendChild(actions);
    }

    if (title === 'Firmware') {
      appendButton(actions, 'Seriell flashen / Recovery', { 'data-rd-service-tab': 'firmware' }, true);
      header.dataset.rdBridge = 'firmware';
    } else if (title === 'Logs & Verlauf') {
      appendButton(actions, 'Diagnose öffnen', { 'data-rd-open-view': 'diagnostics' });
      appendButton(actions, 'Diagnosepaket / Service', { 'data-rd-service-tab': 'diagnostics' });
      header.dataset.rdBridge = 'logs';
    } else if (title === 'Profile & Service') {
      appendButton(actions, 'Power Management', { 'data-rd-open-view': 'power' });
      appendButton(actions, 'Mesh / Netzwerk', { 'data-rd-open-view': 'network' });
      header.dataset.rdBridge = 'profiles';
    } else if (title === 'Live') {
      appendButton(actions, 'Power Management', { 'data-rd-open-view': 'power' });
      header.dataset.rdBridge = 'live';
    } else if (title === 'Diagnose') {
      appendButton(actions, 'Service-Diagnose', { 'data-rd-service-tab': 'diagnostics' });
      header.dataset.rdBridge = 'diagnostics';
    }
  }

  document.addEventListener('click', event => {
    const service = event.target.closest('[data-rd-service-tab]');
    if (service) {
      openServiceTab(service.dataset.rdServiceTab);
      return;
    }
    const view = event.target.closest('[data-rd-open-view]');
    if (view) {
      openView(view.dataset.rdOpenView);
    }
  });

  let queued = false;
  function schedule() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => {
      queued = false;
      decorate();
    });
  }

  new MutationObserver(schedule).observe(pageHost, { childList: true, subtree: true });
  schedule();
})();
