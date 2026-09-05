(() => {
  'use strict';

  // app-v31 installs the proven legacy router first. Dashboard/Nodes intentionally
  // share the canonical "overview" view, while Power/Network/Tools are redesign-
  // only pages. Prime every redesign route at window-capture level so late legacy
  // handlers can never leave the page in an indeterminate presentation state.
  //
  // v4 owns every visible navigation button itself. Those buttons deliberately
  // retain data-view for old functional selectors/parity, but v3.24 must not render
  // its older presentation for the same physical click. Otherwise async v4 pages
  // such as Power can briefly expose the legacy .rd-power-page before the v4 page
  // is ready, producing both visual flicker and nondeterministic screenshots.
  let renderTimer = null;
  let requestedCustom = '';

  function requestedRoute(target) {
    if (!(target instanceof Element)) return { mode: '', custom: '' };
    const nav = target.closest('.nav-item[data-view]');
    if (!nav) return { mode: '', custom: '' };

    // Visible v4 navigation is authoritative. Hidden compatibility routes do not
    // carry data-neo-page and therefore continue through the proven legacy layer.
    if (document.body.dataset.neoUi === 'v400' && nav.hasAttribute('data-neo-page')) {
      return { mode: '', custom: '' };
    }

    const mode = nav.dataset.rdMode || '';
    const view = nav.dataset.view || '';
    return {
      mode: ['dashboard', 'nodes'].includes(mode) ? mode : '',
      custom: ['power', 'network', 'tools'].includes(view) ? view : '',
    };
  }

  function scheduleRender(route) {
    if (renderTimer) clearTimeout(renderTimer);
    if (route.custom) requestedCustom = route.custom;
    renderTimer = setTimeout(() => {
      renderTimer = null;
      if (requestedCustom) {
        const custom = requestedCustom;
        requestedCustom = '';
        const redesign = window.JarnsenFullRedesignV322;
        if (custom === 'power') redesign?.renderPower?.();
        else if (custom === 'network') redesign?.renderNetwork?.();
        else if (custom === 'tools') redesign?.renderTools?.();
        return;
      }
      const visual = window.JarnsenVisualParityV323;
      visual?.renderCurrent?.();
      visual?.refresh?.();
    }, 0);
  }

  function primeRoute(event) {
    const route = requestedRoute(event.target);
    if (!route.mode && !route.custom) return;
    const next = route.custom || route.mode;
    document.body.dataset.redesignPage = next;
    scheduleRender(route);
  }

  window.addEventListener('pointerdown', primeRoute, true);
  window.addEventListener('click', primeRoute, true);

  window.JarnsenVisualParityNavV324 = {
    setMode(next) {
      // Once v4 is active, programmatic redesign navigation should use the same
      // renderer as visible user navigation instead of reviving a legacy page.
      if (document.body.dataset.neoUi === 'v400' && window.JarnsenNeoUIV400?.renderPage) {
        if (['dashboard', 'nodes', 'power', 'network', 'tools'].includes(next)) {
          window.JarnsenNeoUIV400.renderPage(next);
          return true;
        }
      }
      if (['dashboard', 'nodes'].includes(next)) {
        document.body.dataset.redesignPage = next;
        scheduleRender({ mode: next, custom: '' });
        return true;
      }
      if (['power', 'network', 'tools'].includes(next)) {
        document.body.dataset.redesignPage = next;
        scheduleRender({ mode: '', custom: next });
        return true;
      }
      return false;
    },
  };
})();
