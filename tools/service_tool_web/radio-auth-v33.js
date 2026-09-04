(() => {
  'use strict';

  if (!window.JarnsenMapSettings) return;

  const originalRenderSettings = window.JarnsenMapSettings.renderSettings;

  function num(value, fallback = 0) {
    const n = Number(String(value ?? '').replace(',', '.'));
    return Number.isFinite(n) ? n : fallback;
  }

  function mhzToHz(value) {
    const mhz = num(value, 0);
    return mhz > 0 ? Math.round(mhz * 1000000) : 0;
  }

  function displayMhz(value) {
    const n = num(value, 0);
    if (!n) return '';
    return n.toFixed(6).replace(/0+$/, '').replace(/\.$/, '');
  }

  function modeFor(auth, overrideMhz) {
    const hz = mhzToHz(overrideMhz);
    if (hz && hz === Number(auth.frequency_a_hz || 0)) return 'jarnsen_1';
    if (hz && hz === Number(auth.frequency_b_hz || 0)) return 'jarnsen_2';
    return 'standard';
  }

  function modeLabel(mode) {
    if (mode === 'jarnsen_1') return 'Jarnsen 1';
    if (mode === 'jarnsen_2') return 'Jarnsen 2';
    return 'Standard';
  }

  function injectGlobalCard(ctx, auth) {
    const radioSection = ctx.pageHost.querySelector('#radioEditorHost')?.closest('section');
    if (!radioSection || ctx.pageHost.querySelector('#radioAuthorizationCard')) return;

    const card = document.createElement('section');
    card.id = 'radioAuthorizationCard';
    card.className = 'settings-card soft-card settings-card-wide radio-auth-global-card';
    card.innerHTML = `
      <div class="settings-card-head">
        <div>
          <div class="section-label">LIZENZIERTE FUNKFREIGABE</div>
          <h2>Jarnsen 1 / Jarnsen 2</h2>
          <p>Einmal hier eintragen. Die beiden Frequenzen werden zentral gespeichert und bei allen Grundprofilen berücksichtigt.</p>
        </div>
        <span class="settings-card-icon">⌁</span>
      </div>
      <form id="radioAuthorizationForm" class="radio-auth-form">
        <div class="radio-auth-frequency-grid">
          <label>
            <span>Jarnsen 1 · Frequenz A</span>
            <div class="input-with-unit"><input name="frequency_a_mhz" type="number" inputmode="decimal" step="0.000001" min="100" max="2500" value="${displayMhz(auth.frequency_a_mhz)}" placeholder="noch nicht zugewiesen" /><b>MHz</b></div>
            <small>Nur ein exakter Treffer auf diese Frequenz aktiviert die Sonderfreigabe.</small>
          </label>
          <label>
            <span>Jarnsen 2 · Frequenz B</span>
            <div class="input-with-unit"><input name="frequency_b_mhz" type="number" inputmode="decimal" step="0.000001" min="100" max="2500" value="${displayMhz(auth.frequency_b_mhz)}" placeholder="noch nicht zugewiesen" /><b>MHz</b></div>
            <small>Bleibt das Feld leer, gibt es für Jarnsen 2 keine Sonderfreigabe.</small>
          </label>
        </div>
        <div class="radio-auth-rule-strip">
          <div><span>Standard</span><strong>max. 7 Hops</strong><small>normale Leistungs- und Duty-Cycle-Regeln</small></div>
          <div><span>Jarnsen 1 / 2</span><strong>max. 20 Hops</strong><small>nur bei exakt passender Frequenz A/B</small></div>
          <div><span>Duty Cycle</span><strong>freigegeben</strong><small>Override wird im passenden Profil automatisch gesetzt</small></div>
          <div><span>Sendeleistung</span><strong>freigegeben</strong><small>frequenzgebundene Firmware-Freigabe, niemals global</small></div>
        </div>
        <div class="radio-auth-notice">
          <strong>Sicherheitslogik:</strong> Ohne eingetragene Frequenz oder bei jeder anderen Frequenz gelten automatisch die Standardregeln. Der globale Meshtastic-Schalter <code>is_licensed</code> wird absichtlich nicht verwendet, weil er die Leistungsbegrenzung auf allen Frequenzen aufheben würde.
        </div>
        <div class="settings-actions">
          <button type="submit" class="service-button primary">Frequenzen global speichern</button>
          <span class="radio-auth-profile-count">${Number(auth.profiles_seen || 0)} Grundprofile werden automatisch mitgeführt</span>
        </div>
      </form>`;
    radioSection.insertAdjacentElement('beforebegin', card);

    card.querySelector('#radioAuthorizationForm')?.addEventListener('submit', async event => {
      event.preventDefault();
      const form = event.currentTarget;
      const fd = new FormData(form);
      ctx.app.preloader.show();
      try {
        const saved = await ctx.request('/api/radio-authorization', {
          method: 'POST',
          body: JSON.stringify({
            frequency_a_mhz: String(fd.get('frequency_a_mhz') || '').trim(),
            frequency_b_mhz: String(fd.get('frequency_b_mhz') || '').trim(),
          }),
        });
        Object.assign(auth, saved);
        ctx.toast('Jarnsen-Frequenzen global gespeichert');
        enhanceRadioForm(ctx, auth, true);
      } catch (error) {
        ctx.app.dialog.alert(ctx.esc(error.message || error), 'Funkfreigabe konnte nicht gespeichert werden');
      } finally {
        ctx.app.preloader.hide();
      }
    });
  }

  function enhanceRadioForm(ctx, auth, forceRefresh = false) {
    const form = ctx.pageHost.querySelector('#radioSettingsForm');
    if (!form) return;

    const overrideInput = form.elements.override_frequency;
    const hopInput = form.elements.hop_limit;
    const txPowerInput = form.elements.tx_power;
    if (!overrideInput || !hopInput) return;

    let panel = form.querySelector('.radio-auth-profile-policy');
    if (!panel) {
      panel = document.createElement('div');
      panel.className = 'radio-auth-profile-policy';
      panel.innerHTML = `
        <div class="radio-auth-profile-head">
          <div><span class="section-label">FUNKMODUS DIESES PROFILS</span><strong id="radioAuthModeTitle">Standard</strong></div>
          <div class="radio-mode-buttons" role="group">
            <button type="button" data-radio-mode="standard">Standard</button>
            <button type="button" data-radio-mode="jarnsen_1">Jarnsen 1</button>
            <button type="button" data-radio-mode="jarnsen_2">Jarnsen 2</button>
          </div>
        </div>
        <div class="radio-auth-profile-status">
          <div><span>Frequenz</span><strong id="radioAuthFrequencyStatus">automatisch</strong></div>
          <div><span>Hop-Limit</span><strong id="radioAuthHopStatus">max. 7</strong></div>
          <div><span>Duty Cycle</span><strong id="radioAuthDutyStatus">Standard</strong></div>
          <div><span>Sendeleistung</span><strong id="radioAuthPowerStatus">Standard</strong></div>
        </div>
        <div id="radioAuthCompatibilityNote" class="radio-auth-compat-note"></div>`;
      const advanced = form.querySelector('.advanced-radio-settings');
      if (advanced) advanced.insertAdjacentElement('beforebegin', panel);
      else form.prepend(panel);

      panel.querySelectorAll('[data-radio-mode]').forEach(button => {
        button.addEventListener('click', () => {
          const requested = button.dataset.radioMode;
          if (requested === 'standard') {
            overrideInput.value = '0';
          } else if (requested === 'jarnsen_1') {
            if (!Number(auth.frequency_a_hz || 0)) {
              ctx.app.dialog.alert('Frequenz A ist noch nicht global eingetragen.', 'Jarnsen 1 nicht verfügbar');
              return;
            }
            overrideInput.value = displayMhz(auth.frequency_a_mhz);
          } else if (requested === 'jarnsen_2') {
            if (!Number(auth.frequency_b_hz || 0)) {
              ctx.app.dialog.alert('Frequenz B ist noch nicht global eingetragen.', 'Jarnsen 2 nicht verfügbar');
              return;
            }
            overrideInput.value = displayMhz(auth.frequency_b_mhz);
          }
          refreshPolicy();
        });
      });

      overrideInput.addEventListener('input', () => refreshPolicy());
      overrideInput.addEventListener('change', () => refreshPolicy());
    }

    function refreshPolicy() {
      const mode = modeFor(auth, overrideInput.value);
      const authorized = mode !== 'standard';
      const maxHops = authorized ? 20 : 7;
      hopInput.max = String(maxHops);
      hopInput.min = '0';
      if (num(hopInput.value, 0) > maxHops) hopInput.value = String(maxHops);

      panel.querySelectorAll('[data-radio-mode]').forEach(button => {
        const requested = button.dataset.radioMode;
        button.classList.toggle('active', requested === mode);
        if (requested === 'jarnsen_1') button.disabled = !Number(auth.frequency_a_hz || 0);
        if (requested === 'jarnsen_2') button.disabled = !Number(auth.frequency_b_hz || 0);
      });

      const modeTitle = panel.querySelector('#radioAuthModeTitle');
      const freqStatus = panel.querySelector('#radioAuthFrequencyStatus');
      const hopStatus = panel.querySelector('#radioAuthHopStatus');
      const dutyStatus = panel.querySelector('#radioAuthDutyStatus');
      const powerStatus = panel.querySelector('#radioAuthPowerStatus');
      const note = panel.querySelector('#radioAuthCompatibilityNote');
      if (modeTitle) modeTitle.textContent = modeLabel(mode);
      if (freqStatus) freqStatus.textContent = num(overrideInput.value, 0) > 0 ? `${displayMhz(overrideInput.value)} MHz` : 'automatisch / Standard';
      if (hopStatus) hopStatus.textContent = `frei wählbar · max. ${maxHops}`;
      if (dutyStatus) dutyStatus.textContent = authorized ? 'Freigabe aktiv' : 'Standardbegrenzung';
      if (powerStatus) powerStatus.textContent = authorized ? 'Frequenzfreigabe aktiv' : 'Standardbegrenzung';
      if (note) {
        note.innerHTML = authorized
          ? `<strong>${modeLabel(mode)}:</strong> Beim Speichern setzt das Tool den Duty-Cycle-Override automatisch und erlaubt bis zu 20 Hops. Die Sendeleistungsfreigabe bleibt an genau diese Frequenz gebunden und wird nicht über einen globalen Lizenzmodus geöffnet.`
          : '<strong>Standard:</strong> maximal 7 Hops. Duty-Cycle-Override wird beim Speichern deaktiviert; die normalen Leistungsgrenzen bleiben aktiv.';
      }

      const help = hopInput.closest('label')?.querySelector('small');
      if (help) help.textContent = authorized ? `Maximal 20. ${modeLabel(mode)} ist durch exakten Frequenztreffer freigegeben.` : 'Maximal 7 im Standardbetrieb.';
      if (txPowerInput) {
        const txHelp = txPowerInput.closest('label')?.querySelector('small');
        if (txHelp) txHelp.textContent = authorized
          ? 'Gewünschte Leistung; die frequenzgebundene Jarnsen-Firmware entscheidet über die tatsächliche Freigabe und Hardwaregrenze.'
          : '0 = Geräte-/Regionsstandard; Standard-Leistungsbegrenzung bleibt aktiv.';
      }
    }

    if (forceRefresh || !form.dataset.radioAuthReady) {
      form.dataset.radioAuthReady = '1';
      refreshPolicy();
    } else {
      refreshPolicy();
    }
  }

  async function renderSettingsWithRadioAuthorization(ctx) {
    await originalRenderSettings(ctx);
    let auth;
    try {
      auth = await ctx.request('/api/radio-authorization');
    } catch (error) {
      const host = ctx.pageHost.querySelector('.settings-hub');
      if (host) {
        const warning = document.createElement('div');
        warning.className = 'radio-auth-load-error';
        warning.textContent = `Globale Funkfreigabe konnte nicht geladen werden: ${error.message || error}`;
        host.prepend(warning);
      }
      return;
    }

    injectGlobalCard(ctx, auth);
    enhanceRadioForm(ctx, auth, true);

    const radioHost = ctx.pageHost.querySelector('#radioEditorHost');
    if (radioHost) {
      const observer = new MutationObserver(() => enhanceRadioForm(ctx, auth, true));
      observer.observe(radioHost, { childList: true, subtree: true });
    }
  }

  window.JarnsenMapSettings.renderSettings = renderSettingsWithRadioAuthorization;
})();
