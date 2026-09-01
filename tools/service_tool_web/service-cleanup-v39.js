(() => {
  'use strict';

  let activeTab = localStorage.getItem('jarnsen-service-tab') || 'connection';
  let bodyScrollTop = 0;
  let serialScrollTop = 0;
  let serialPinned = true;
  let decorating = false;

  const tabs = [
    ['connection', 'Verbindung'],
    ['firmware', 'Firmware'],
    ['diagnostics', 'Diagnose'],
    ['security', 'Schutz'],
    ['all', 'Alle'],
  ];

  function groupFor(card) {
    const title = card.querySelector('h3')?.textContent.trim() || '';
    if (title === 'USB / Ziel' || title === 'Monitor') return 'connection';
    if (title === 'USB / Bluetooth' || title === 'App-Update') return 'firmware';
    if (title === 'Service-Dateien' || title === 'Stabiles Tool → Framework7') return 'diagnostics';
    if (title === 'PIN & Vollsperre') return 'security';
    return 'other';
  }

  function rememberScroll(event) {
    const target = event.target;
    if (!(target instanceof Element)) return;
    if (target.classList.contains('parity-body')) {
      bodyScrollTop = target.scrollTop;
    }
    if (target.classList.contains('serial-tail')) {
      serialScrollTop = target.scrollTop;
      serialPinned = (target.scrollHeight - target.clientHeight - target.scrollTop) < 28;
    }
  }

  function restoreScroll(body) {
    body.scrollTop = Math.min(bodyScrollTop, Math.max(0, body.scrollHeight - body.clientHeight));
    const tail = body.querySelector('.serial-tail');
    if (!tail) return;
    if (serialPinned) {
      tail.scrollTop = tail.scrollHeight;
      serialScrollTop = tail.scrollTop;
    } else {
      tail.scrollTop = Math.min(serialScrollTop, Math.max(0, tail.scrollHeight - tail.clientHeight));
    }
  }

  function applyTab(body) {
    body.querySelectorAll('.parity-card').forEach(card => {
      const group = groupFor(card);
      card.dataset.serviceGroup = group;
      card.hidden = activeTab !== 'all' && group !== activeTab;
    });
    body.querySelectorAll('.parity-grid').forEach(grid => {
      const visible = [...grid.querySelectorAll(':scope > .parity-card')].some(card => !card.hidden);
      grid.hidden = !visible;
    });
    body.querySelectorAll('.service-tab').forEach(button => {
      const selected = button.dataset.serviceTab === activeTab;
      button.classList.toggle('active', selected);
      button.setAttribute('aria-selected', selected ? 'true' : 'false');
    });
  }

  function installTabs(body) {
    if (body.querySelector('.service-tabs')) return;
    const summary = body.querySelector('.parity-summary');
    if (!summary) return;
    const nav = document.createElement('div');
    nav.className = 'service-tabs';
    nav.setAttribute('role', 'tablist');
    nav.innerHTML = tabs.map(([key, label]) =>
      `<button class="service-tab" type="button" role="tab" data-service-tab="${key}">${label}</button>`
    ).join('');
    summary.after(nav);
    nav.addEventListener('click', event => {
      const button = event.target.closest('[data-service-tab]');
      if (!button) return;
      activeTab = button.dataset.serviceTab || 'connection';
      localStorage.setItem('jarnsen-service-tab', activeTab);
      bodyScrollTop = 0;
      applyTab(body);
      body.scrollTop = 0;
    });
  }

  function decorate() {
    if (decorating) return;
    const body = document.querySelector('.parity-body');
    if (!body) return;
    decorating = true;
    try {
      installTabs(body);
      applyTab(body);
      body.classList.add('service-cleanup-ready');
      restoreScroll(body);
    } finally {
      decorating = false;
    }
  }

  document.addEventListener('scroll', rememberScroll, true);
  document.addEventListener('wheel', event => {
    const tail = event.target.closest?.('.serial-tail');
    if (tail) {
      serialPinned = false;
      serialScrollTop = tail.scrollTop;
    }
  }, { passive: true, capture: true });

  const observer = new MutationObserver(() => queueMicrotask(decorate));
  observer.observe(document.documentElement, { childList: true, subtree: true });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) decorate(); });
  setTimeout(decorate, 80);
})();
