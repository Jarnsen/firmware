(() => {
  'use strict';

  const params = new URLSearchParams(location.search);
  const version = String(params.get('version') || '3.1.1-beta.1').trim();
  const lower = version.toLowerCase();
  let stage = 'Release';
  let stageClass = 'release';
  let buildLabel = 'Release';

  const beta = lower.match(/-beta\.(\d+)/);
  const alpha = lower.match(/-alpha\.(\d+)/);
  const rc = lower.match(/-rc\.(\d+)/);
  if (beta) { stage = 'Beta'; stageClass = 'beta'; buildLabel = `Beta Build ${beta[1]}`; }
  else if (alpha) { stage = 'Alpha'; stageClass = 'alpha'; buildLabel = `Alpha Build ${alpha[1]}`; }
  else if (rc) { stage = 'Release Candidate'; stageClass = 'rc'; buildLabel = `RC Build ${rc[1]}`; }

  function installVersionBadge() {
    const brand = document.querySelector('.brand-subtitle');
    if (brand && !brand.querySelector('.app-version-inline')) {
      const badge = document.createElement('span');
      badge.className = `app-version-inline ${stageClass}`;
      badge.textContent = `v${version}`;
      brand.append(' · ', badge);
    }

    const top = document.querySelector('.top-actions');
    if (top && !document.getElementById('appBuildBadge')) {
      const badge = document.createElement('div');
      badge.id = 'appBuildBadge';
      badge.className = `app-build-badge ${stageClass}`;
      badge.title = `Jarnsen Node Service Tool v${version}`;
      badge.innerHTML = `<strong>${stage}</strong><span>${buildLabel}</span><small>v${version}</small>`;
      top.prepend(badge);
    }
  }

  const observer = new MutationObserver(installVersionBadge);
  observer.observe(document.documentElement, { childList: true, subtree: true });
  installVersionBadge();
  setTimeout(installVersionBadge, 150);
})();
