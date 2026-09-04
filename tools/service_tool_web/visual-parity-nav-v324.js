(() => {
  'use strict';

  // app-v31 installs a capture-phase compatibility router. Dashboard and Nodes
  // intentionally share the canonical "overview" view, so the presentation mode
  // has to be set before that router renders the legacy overview. Window capture
  // runs before document capture and makes the visual mode deterministic for both
  // real pointer clicks and programmatic .click() calls from quick actions.
  let renderTimer = null;

  function requestedMode(target) {
    if (!(target instanceof Element)) return '';
    const nav = target.closest('.nav-item[data-rd-mode]');
    return nav?.dataset?.rdMode || '';
  }

  function scheduleVisualRender() {
    if (renderTimer) clearTimeout(renderTimer);
    renderTimer = setTimeout(() => {
      renderTimer = null;
      const visual = window.JarnsenVisualParityV323;
      if (!visual) return;
      visual.renderCurrent?.();
      visual.refresh?.();
    }, 0);
  }

  function primeMode(event) {
    const next = requestedMode(event.target);
    if (!next || !['dashboard', 'nodes'].includes(next)) return;
    document.body.dataset.redesignPage = next;
    scheduleVisualRender();
  }

  window.addEventListener('pointerdown', primeMode, true);
  window.addEventListener('click', primeMode, true);

  window.JarnsenVisualParityNavV324 = {
    setMode(next) {
      if (!['dashboard', 'nodes'].includes(next)) return false;
      document.body.dataset.redesignPage = next;
      scheduleVisualRender();
      return true;
    },
  };
})();
