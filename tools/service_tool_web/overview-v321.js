(() => {
  'use strict';

  const pageHost = document.getElementById('pageHost');
  if (!pageHost) return;

  const numberFrom = (node) => {
    const value = Number.parseInt((node?.textContent || '').replace(/[^0-9-]/g, ''), 10);
    return Number.isFinite(value) ? value : 0;
  };

  const overviewIsVisible = () => pageHost.querySelector('.page-title-wrap h1')?.textContent?.trim() === 'Node-Übersicht';

  function overallState(values) {
    if (!values.nodes) {
      return {
        tone: 'neutral',
        eyebrow: 'SERVICE-ZENTRALE',
        title: 'Bereit für die erste Node',
        text: 'Neue Nodes hinzufügen oder per BLE suchen. USB bleibt automatisch der bevorzugte Serviceweg.',
      };
    }
    if (values.attention > 0) {
      return {
        tone: 'warning',
        eyebrow: 'HANDLUNGSBEDARF',
        title: `${values.attention} ${values.attention === 1 ? 'Hinweis braucht' : 'Hinweise brauchen'} Aufmerksamkeit`,
        text: 'Updates und Warnungen sind direkt an den betroffenen Node-Karten markiert.',
      };
    }
    if (values.logsDue > 0) {
      return {
        tone: 'notice',
        eyebrow: 'AUTOMATIK AKTIV',
        title: `${values.logsDue} ${values.logsDue === 1 ? 'Log wartet' : 'Logs warten'} auf Synchronisierung`,
        text: 'Die Log-Automatik übernimmt erreichbare Nodes; manuelle Aktionen bleiben jederzeit möglich.',
      };
    }
    if (values.ble > 0) {
      return {
        tone: 'ok',
        eyebrow: 'SYSTEM BEREIT',
        title: 'Alle sichtbaren Nodes im Blick',
        text: 'Keine offenen Hinweise. USB wird bevorzugt, BLE steht für die übrigen Servicewege bereit.',
      };
    }
    return {
      tone: 'neutral',
      eyebrow: 'NODES VERWALTET',
      title: 'Aktuell keine Node in Reichweite',
      text: 'Die bekannten Nodes bleiben vollständig verwaltet. Starte bei Bedarf eine neue BLE-Prüfung.',
    };
  }

  function button(icon, label, attrs, primary = false) {
    return `<button class="dashboard-quick-action${primary ? ' primary' : ''}" ${attrs}><span>${icon}</span><strong>${label}</strong></button>`;
  }

  function enhanceOverview() {
    const root = pageHost;
    if (root.querySelector(':scope > .dashboard-hero')) {
      root.classList.add('overview-dashboard-v321');
      return;
    }
    if (!overviewIsVisible()) {
      root.classList.remove('overview-dashboard-v321');
      return;
    }

    const header = root.querySelector('.page-header');
    const kpiGrid = root.querySelector('.kpi-grid');
    const toolbar = root.querySelector('.toolbar-row');
    const nodeGrid = root.querySelector('.node-grid');
    if (!header || !kpiGrid || !toolbar || !nodeGrid) return;

    root.classList.add('overview-dashboard-v321');

    const kpis = [...kpiGrid.querySelectorAll('.kpi-card')];
    const values = {
      nodes: numberFrom(kpis[0]?.querySelector('.kpi-value')),
      ble: numberFrom(kpis[1]?.querySelector('.kpi-value')),
      logsDue: numberFrom(kpis[2]?.querySelector('.kpi-value')),
      attention: numberFrom(kpis[3]?.querySelector('.kpi-value')),
    };
    const status = overallState(values);

    const hero = document.createElement('section');
    hero.className = `dashboard-hero dashboard-tone-${status.tone}`;
    hero.innerHTML = `
      <div class="dashboard-hero-copy">
        <div class="dashboard-eyebrow"><span class="dashboard-state-dot"></span>${status.eyebrow}</div>
        <h1>${status.title}</h1>
        <p>${status.text}</p>
        <div class="dashboard-status-line">
          <span><strong>${values.nodes}</strong> verwaltet</span>
          <span><strong>${values.ble}</strong> erreichbar</span>
          <span><strong>${values.logsDue}</strong> Logs offen</span>
          <span><strong>${values.attention}</strong> Hinweise</span>
        </div>
      </div>
      <div class="dashboard-hero-controls">
        <button class="dashboard-hero-button primary" data-dashboard-action="scan-ble"><span>⌁</span> BLE prüfen</button>
        <button class="dashboard-hero-button" data-page-action="refresh"><span>↻</span> Aktualisieren</button>
      </div>`;

    root.insertBefore(hero, header);
    hero.appendChild(kpiGrid);

    header.classList.add('dashboard-node-header');
    const title = header.querySelector('h1');
    const subtitle = header.querySelector('p');
    if (title) title.textContent = 'Nodes';
    if (subtitle) subtitle.textContent = 'Auswählen, prüfen und Serviceaktionen direkt aus der Übersicht starten.';

    const quick = document.createElement('section');
    quick.className = 'dashboard-quick-strip';
    quick.innerHTML = `
      <div class="dashboard-quick-label"><span>SCHNELLZUGRIFF</span><small>Häufige Bereiche ohne Umwege öffnen</small></div>
      <div class="dashboard-quick-actions">
        ${button('⌘', 'Firmware', 'data-nav="firmware"')}
        ${button('⚙', 'Profile & Service', 'data-nav="service"')}
        ${button('＋', 'Neue Nodes', 'data-nav="series"')}
        ${button('◷', 'Aktivität', 'data-dashboard-action="activity"')}
      </div>`;
    header.parentNode.insertBefore(quick, header.nextSibling);

    toolbar.classList.add('dashboard-commandbar');
    nodeGrid.classList.add('dashboard-node-grid');

    const cards = [...nodeGrid.querySelectorAll('.node-card')];
    cards.forEach((card) => {
      card.classList.add('dashboard-node-card');
      const sync = card.querySelector('.sync-line');
      if (sync) sync.setAttribute('title', sync.textContent.trim());
    });
  }

  let scheduled = false;
  function scheduleEnhance() {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => {
      scheduled = false;
      enhanceOverview();
    });
  }

  document.addEventListener('click', (event) => {
    const action = event.target.closest('[data-dashboard-action]')?.dataset.dashboardAction;
    if (!action) return;
    if (action === 'scan-ble') document.getElementById('scanBleButton')?.click();
    if (action === 'activity') document.getElementById('activityButton')?.click();
  });

  new MutationObserver(scheduleEnhance).observe(pageHost, { childList: true, subtree: false });
  scheduleEnhance();
})();
