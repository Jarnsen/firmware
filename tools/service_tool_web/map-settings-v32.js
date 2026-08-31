(() => {
  'use strict';

  const REGIONS = [
    'UNSET','US','EU_433','EU_868','CN','JP','ANZ','KR','TW','RU','IN','NZ_865','TH','LORA_24',
    'UA_433','MY_433','MY_919','SG_923','PH_433','PH_868','PH_915','ANZ_433','KZ_433','KZ_863','NP_865','BR_902'
  ];
  const PRESETS = [
    'LONG_FAST','LONG_SLOW','VERY_LONG_SLOW','MEDIUM_SLOW','MEDIUM_FAST','SHORT_SLOW','SHORT_FAST','LONG_MODERATE'
  ];

  const MAP_STYLES = {
    topo: { label: 'OpenTopoMap' },
    satellite: { label: 'Satellit' },
    hybrid: { label: 'Hybrid' },
  };

  function safeNumber(value, fallback = 0) {
    const n = Number(value);
    return Number.isFinite(n) ? n : fallback;
  }

  function formatMgrs(raw) {
    const value = String(raw || '').replace(/\s+/g, '').toUpperCase();
    if (value.length < 5) return value || '—';
    const prefix = value.slice(0, 3);
    const grid = value.slice(3, 5);
    const digits = value.slice(5);
    if (!digits) return `${prefix} ${grid}`;
    const half = Math.floor(digits.length / 2);
    return `${prefix} ${grid} ${digits.slice(0, half)} ${digits.slice(half)}`.trim();
  }

  function mgrsFor(lat, lon, fallback = '') {
    if (fallback && fallback !== '---') return formatMgrs(fallback);
    try {
      if (window.mgrs && typeof window.mgrs.forward === 'function') {
        return formatMgrs(window.mgrs.forward([Number(lon), Number(lat)], 5));
      }
    } catch (_error) {}
    return '—';
  }

  function distanceText(meters) {
    const value = safeNumber(meters, 0);
    if (value >= 1000) return `${(value / 1000).toFixed(value >= 10000 ? 1 : 2)} km`;
    return `${Math.round(value)} m`;
  }

  function mapPointIcon(kind = 'picked') {
    const cls = kind === 'end' ? 'end' : kind === 'start' ? 'start' : kind === 'node' ? 'node' : 'picked';
    return L.divIcon({
      className: `jarnsen-map-pin ${cls}`,
      html: '<span></span>',
      iconSize: [28, 28],
      iconAnchor: [14, 14],
    });
  }

  function makeTileLayer(type) {
    if (type === 'topo') {
      return L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', {
        subdomains: 'abc',
        maxZoom: 17,
        attribution: 'Kartendaten © OpenStreetMap-Mitwirkende, SRTM | © OpenTopoMap (CC-BY-SA)',
      });
    }
    return L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
      maxZoom: 19,
      attribution: 'Tiles © Esri — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community',
    });
  }

  function makeHybridLabels() {
    return L.tileLayer('https://services.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}', {
      maxZoom: 19,
      pane: 'overlayPane',
      attribution: 'Reference © Esri',
    });
  }

  async function renderMap(ctx) {
    const node = ctx.getNode(ctx.state.selected);
    if (!node) {
      ctx.pageHost.innerHTML = '<div class="empty-state"><h3>Keine Node ausgewählt</h3><p>Wähle zuerst eine Node mit Positionsdaten aus.</p></div>';
      return;
    }

    ctx.pageHost.innerHTML = `
      <div class="page-header map-page-header">
        <div class="page-title-wrap"><h1>Karte</h1><p>${ctx.esc(node.long_name)} · Track, Kartenwahl und MGRS-Punktabgriff</p></div>
        <div class="map-style-switch" role="group" aria-label="Kartenstil">
          ${Object.entries(MAP_STYLES).map(([key, item]) => `<button data-map-style="${key}">${item.label}</button>`).join('')}
        </div>
      </div>
      <div class="map-workspace">
        <div class="interactive-map-card soft-card">
          <div id="interactiveMap" class="interactive-map"></div>
          <div class="map-hint">Scrollen/+/− = Zoom · Ziehen = Karte verschieben · Klick = Punkt markieren</div>
        </div>
        <aside class="map-side-panel">
          <div class="map-coordinate-card soft-card">
            <div class="section-label">MARKIERTER PUNKT</div>
            <div id="pickedMgrs" class="picked-mgrs">Noch kein Punkt</div>
            <div id="pickedLatLon" class="picked-latlon">In die Karte klicken</div>
            <div class="map-side-actions">
              <button id="copyMgrsButton" class="service-button" disabled>MGRS kopieren</button>
              <button id="clearMapPointButton" class="service-button">Marker löschen</button>
            </div>
          </div>
          <div class="map-track-card soft-card">
            <div class="section-label">TRACK</div>
            <div id="mapTrackStats" class="map-track-stats"><span>Wird geladen …</span></div>
            <button id="fitTrackButton" class="service-button primary">Track zentrieren</button>
          </div>
          <div class="map-info-note">Der Kartenhintergrund benötigt Internet. Track, Node-Positionen und MGRS-Punktabgriff bleiben auch ohne Kartendaten bedienbar.</div>
        </aside>
      </div>`;

    if (!window.L) {
      ctx.pageHost.querySelector('#interactiveMap').innerHTML = '<div class="empty-state"><h3>Kartenmodul fehlt</h3><p>Leaflet wurde in diesem Build nicht geladen.</p></div>';
      return;
    }

    let data;
    try {
      data = await ctx.request(`/api/node/${encodeURIComponent(node.node_id)}/positions`);
    } catch (error) {
      ctx.app.dialog.alert(ctx.esc(error.message || error), 'Positionsdaten konnten nicht geladen werden');
      data = { points: [], count: 0, distance_m: 0, logs_scanned: 0 };
    }

    const points = Array.isArray(data.points) ? data.points.filter(p => Number.isFinite(Number(p.latitude)) && Number.isFinite(Number(p.longitude))) : [];
    const map = L.map('interactiveMap', {
      zoomControl: true,
      preferCanvas: true,
      attributionControl: true,
      minZoom: 2,
      worldCopyJump: true,
    });

    let activeBase = null;
    let activeLabels = null;
    let pickedMarker = null;
    let picked = null;
    let tileErrors = 0;

    function updateStyleButtons(type) {
      ctx.pageHost.querySelectorAll('[data-map-style]').forEach(button => {
        button.classList.toggle('active', button.dataset.mapStyle === type);
      });
    }

    function setMapStyle(type) {
      const style = MAP_STYLES[type] ? type : 'topo';
      if (activeBase) map.removeLayer(activeBase);
      if (activeLabels) map.removeLayer(activeLabels);
      activeBase = makeTileLayer(style);
      activeBase.on('tileerror', () => {
        tileErrors += 1;
        if (tileErrors === 1) {
          const hint = ctx.pageHost.querySelector('.map-hint');
          if (hint) hint.textContent = 'Kartenserver nicht erreichbar – Track und MGRS funktionieren weiter.';
        }
      });
      activeBase.addTo(map);
      activeLabels = null;
      if (style === 'hybrid') {
        activeLabels = makeHybridLabels().addTo(map);
      }
      localStorage.setItem('jarnsen-map-style', style);
      updateStyleButtons(style);
    }

    function updatePicked(lat, lon, sourceMgrs = '') {
      picked = { lat: Number(lat), lon: Number(lon), mgrs: mgrsFor(lat, lon, sourceMgrs) };
      const mgrsEl = ctx.pageHost.querySelector('#pickedMgrs');
      const latLonEl = ctx.pageHost.querySelector('#pickedLatLon');
      const copy = ctx.pageHost.querySelector('#copyMgrsButton');
      if (mgrsEl) mgrsEl.textContent = picked.mgrs;
      if (latLonEl) latLonEl.textContent = `${picked.lat.toFixed(6)}, ${picked.lon.toFixed(6)}`;
      if (copy) copy.disabled = picked.mgrs === '—';
      if (pickedMarker) map.removeLayer(pickedMarker);
      pickedMarker = L.marker([picked.lat, picked.lon], { icon: mapPointIcon('picked'), keyboard: false, zIndexOffset: 1200 }).addTo(map);
    }

    map.on('click', event => updatePicked(event.latlng.lat, event.latlng.lng));

    let trackLine = null;
    let trackBounds = null;
    if (points.length) {
      const latLngs = points.map(p => [Number(p.latitude), Number(p.longitude)]);
      trackLine = L.polyline(latLngs, { color: '#0a84ff', weight: 4, opacity: 0.9, lineJoin: 'round' }).addTo(map);
      trackBounds = trackLine.getBounds();

      const first = points[0];
      const last = points[points.length - 1];
      L.marker([Number(first.latitude), Number(first.longitude)], { icon: mapPointIcon('start'), keyboard: false })
        .addTo(map)
        .bindTooltip('Track Start', { direction: 'top' })
        .on('click', () => updatePicked(first.latitude, first.longitude, first.mgrs));
      L.marker([Number(last.latitude), Number(last.longitude)], { icon: mapPointIcon('end'), keyboard: false })
        .addTo(map)
        .bindTooltip('Letzte Position', { direction: 'top' })
        .on('click', () => updatePicked(last.latitude, last.longitude, last.mgrs));

      const step = Math.max(1, Math.ceil(points.length / 220));
      for (let i = 0; i < points.length; i += step) {
        const point = points[i];
        L.circleMarker([Number(point.latitude), Number(point.longitude)], {
          radius: 3,
          color: '#ffffff',
          weight: 1,
          fillColor: '#0a84ff',
          fillOpacity: 0.75,
          interactive: true,
        }).addTo(map).on('click', () => updatePicked(point.latitude, point.longitude, point.mgrs));
      }

      map.fitBounds(trackBounds.pad(0.12), { maxZoom: 16, animate: false });
      updatePicked(last.latitude, last.longitude, last.mgrs);
    } else {
      map.setView([50.5, 10.0], 5, { animate: false });
    }

    const latestMgrs = points.length ? mgrsFor(points.at(-1).latitude, points.at(-1).longitude, points.at(-1).mgrs) : '—';
    const stats = ctx.pageHost.querySelector('#mapTrackStats');
    if (stats) {
      stats.innerHTML = `
        <div><span>Punkte</span><strong>${Number(data.count || points.length)}</strong></div>
        <div><span>Strecke</span><strong>${distanceText(data.distance_m)}</strong></div>
        <div><span>Logs</span><strong>${Number(data.logs_scanned || 0)}</strong></div>
        <div class="wide"><span>Letzte MGRS</span><strong>${ctx.esc(latestMgrs)}</strong></div>`;
    }

    setMapStyle(localStorage.getItem('jarnsen-map-style') || 'topo');

    ctx.pageHost.querySelectorAll('[data-map-style]').forEach(button => {
      button.addEventListener('click', () => setMapStyle(button.dataset.mapStyle));
    });
    ctx.pageHost.querySelector('#fitTrackButton')?.addEventListener('click', () => {
      if (trackBounds && trackBounds.isValid()) map.fitBounds(trackBounds.pad(0.12), { maxZoom: 16 });
    });
    ctx.pageHost.querySelector('#clearMapPointButton')?.addEventListener('click', () => {
      if (pickedMarker) map.removeLayer(pickedMarker);
      pickedMarker = null;
      picked = null;
      const mgrsEl = ctx.pageHost.querySelector('#pickedMgrs');
      const latLonEl = ctx.pageHost.querySelector('#pickedLatLon');
      const copy = ctx.pageHost.querySelector('#copyMgrsButton');
      if (mgrsEl) mgrsEl.textContent = 'Noch kein Punkt';
      if (latLonEl) latLonEl.textContent = 'In die Karte klicken';
      if (copy) copy.disabled = true;
    });
    ctx.pageHost.querySelector('#copyMgrsButton')?.addEventListener('click', async () => {
      if (!picked || picked.mgrs === '—') return;
      try {
        await navigator.clipboard.writeText(picked.mgrs);
        ctx.toast('MGRS kopiert');
      } catch (_error) {
        ctx.app.dialog.alert(ctx.esc(picked.mgrs), 'MGRS-Koordinate');
      }
    });

    setTimeout(() => map.invalidateSize(false), 60);
  }

  function selectOptions(values, current) {
    const list = [...new Set([String(current || ''), ...values].filter(Boolean))];
    return list.map(value => `<option value="${value}" ${String(current || '') === value ? 'selected' : ''}>${value}</option>`).join('');
  }

  async function loadRadioEditor(ctx, slot) {
    const host = ctx.pageHost.querySelector('#radioEditorHost');
    if (!host) return;
    host.innerHTML = '<div class="settings-loading">LoRa-Konfiguration wird geladen …</div>';
    try {
      const section = await ctx.request(`/api/profile/${Number(slot)}/config/lora`);
      const data = section?.data && typeof section.data === 'object' ? section.data : {};
      host.innerHTML = `
        <form id="radioSettingsForm" class="radio-settings-form">
          <div class="settings-form-grid">
            <label><span>Region</span><select name="region">${selectOptions(REGIONS, data.region || 'EU_868')}</select><small>Legt das zulässige Frequenzband fest. Für Deutschland normalerweise EU_868.</small></label>
            <label><span>Modem-Preset</span><select name="modem_preset">${selectOptions(PRESETS, data.modem_preset || 'LONG_FAST')}</select><small>Bestimmt Reichweite, Datenrate und Airtime.</small></label>
            <label><span>Frequenz-Slot</span><input name="channel_num" type="number" min="0" step="1" value="${safeNumber(data.channel_num, 0)}" /><small>0 = automatisch aus dem Primary-Channel; sonst fester Slot innerhalb der Region.</small></label>
            <label><span>Frequenz-Override</span><div class="input-with-unit"><input name="override_frequency" type="number" min="0" step="0.001" value="${safeNumber(data.override_frequency, 0)}" /><b>MHz</b></div><small>0 = aus. Nur für gezielte Sonder-/HAM-Konfiguration; umgeht die normale Frequenzberechnung.</small></label>
            <label><span>Sendeleistung</span><div class="input-with-unit"><input name="tx_power" type="number" step="1" value="${safeNumber(data.tx_power, 0)}" /><b>dBm</b></div><small>0 = zulässiger Geräte-/Regionsstandard.</small></label>
            <label><span>Hop-Limit</span><input name="hop_limit" type="number" min="0" max="7" step="1" value="${safeNumber(data.hop_limit, 3)}" /><small>Maximal 7. Üblicher Standard ist 3.</small></label>
          </div>
          <div class="settings-switch-row">
            <label><input name="use_preset" type="checkbox" ${data.use_preset !== false ? 'checked' : ''} /> Preset verwenden</label>
            <label><input name="tx_enabled" type="checkbox" ${data.tx_enabled !== false ? 'checked' : ''} /> LoRa TX aktiv</label>
            <label><input name="sx126x_rx_boosted_gain" type="checkbox" ${data.sx126x_rx_boosted_gain ? 'checked' : ''} /> RX Boosted Gain</label>
          </div>
          <details class="advanced-radio-settings">
            <summary>Erweiterte Funkwerte</summary>
            <div class="settings-form-grid advanced-grid">
              <label><span>Bandbreite</span><input name="bandwidth" type="number" min="0" step="1" value="${safeNumber(data.bandwidth, 0)}" /><small>Nur relevant, wenn „Preset verwenden“ aus ist.</small></label>
              <label><span>Spreading Factor</span><input name="spread_factor" type="number" min="7" max="12" step="1" value="${safeNumber(data.spread_factor, 0)}" /></label>
              <label><span>Coding Rate</span><input name="coding_rate" type="number" min="0" max="8" step="1" value="${safeNumber(data.coding_rate, 0)}" /><small>z. B. 5 für 4/5.</small></label>
              <label><span>Frequenz-Offset</span><input name="frequency_offset" type="number" step="0.001" value="${safeNumber(data.frequency_offset, 0)}" /><small>Nur zur Kalibrierung mit geeignetem Messequipment.</small></label>
            </div>
          </details>
          <div class="radio-warning"><strong>Wichtig:</strong> Ein Tracker/V3 hat einen LoRa-Transceiver. Er hört nicht mehrere unabhängige Funkfrequenzen gleichzeitig. Der Primary-Channel bestimmt den Funkkanal; Secondary-Channels teilen dieselbe RF-Frequenz und unterscheiden sich hauptsächlich durch Kanal/PSK.</div>
          <div class="settings-actions"><button type="submit" class="service-button primary">Funkwerte im Profil speichern</button><button type="button" id="openProfileService" class="service-button">Profile & Service öffnen</button></div>
        </form>`;

      const form = host.querySelector('#radioSettingsForm');
      form?.addEventListener('submit', async event => {
        event.preventDefault();
        const fd = new FormData(form);
        const updated = { ...data };
        const intFields = ['channel_num','tx_power','hop_limit','bandwidth','spread_factor','coding_rate'];
        for (const field of intFields) updated[field] = Math.trunc(safeNumber(fd.get(field), 0));
        updated.override_frequency = safeNumber(fd.get('override_frequency'), 0);
        updated.frequency_offset = safeNumber(fd.get('frequency_offset'), 0);
        updated.region = String(fd.get('region') || data.region || 'EU_868');
        updated.modem_preset = String(fd.get('modem_preset') || data.modem_preset || 'LONG_FAST');
        updated.use_preset = form.elements.use_preset.checked;
        updated.tx_enabled = form.elements.tx_enabled.checked;
        updated.sx126x_rx_boosted_gain = form.elements.sx126x_rx_boosted_gain.checked;
        ctx.app.preloader.show();
        try {
          await ctx.request('/api/profile/section', {
            method: 'POST',
            body: JSON.stringify({ slot: Number(slot), kind: 'config', name: 'lora', data: updated }),
          });
          ctx.state.profiles = null;
          ctx.toast('Funkwerte im Profil gespeichert');
        } catch (error) {
          ctx.app.dialog.alert(ctx.esc(error.message || error), 'Funkwerte konnten nicht gespeichert werden');
        } finally {
          ctx.app.preloader.hide();
        }
      });
      host.querySelector('#openProfileService')?.addEventListener('click', () => {
        document.querySelector('.nav-item[data-view="service"]')?.click();
      });
    } catch (error) {
      host.innerHTML = `<div class="settings-empty"><strong>Profil enthält noch keine LoRa-Konfiguration.</strong><span>${ctx.esc(error.message || error)}</span><button id="openProfileService" class="service-button">Profil von Node einlesen</button></div>`;
      host.querySelector('#openProfileService')?.addEventListener('click', () => document.querySelector('.nav-item[data-view="service"]')?.click());
    }
  }

  async function renderSettings(ctx) {
    const cfg = ctx.state.data?.settings || {};
    const currentMap = localStorage.getItem('jarnsen-map-style') || 'topo';
    ctx.pageHost.innerHTML = `
      <div class="page-header"><div class="page-title-wrap"><h1>Einstellungen</h1><p>Nach Aufgaben gebündelt – App, Funk, Karte und technische Optionen.</p></div></div>
      <div class="settings-hub">
        <section class="settings-card soft-card">
          <div class="settings-card-head"><div><div class="section-label">VERBINDUNG & AUTOMATIK</div><h2>USB, Bluetooth und Logs</h2></div><span class="settings-card-icon">⌁</span></div>
          <div class="settings-summary-grid">
            <div><span>BLE-Automatik</span><strong>${cfg.auto_ble === false ? 'Aus' : 'Aktiv'}</strong><small>Scan etwa alle ${cfg.ble_scan_seconds || 30} s</small></div>
            <div><span>Log-Frische</span><strong>${cfg.log_freshness_minutes || 15} min</strong><small>Ältere Logs werden automatisch nachgeladen</small></div>
            <div><span>Bluetooth PIN</span><strong>${ctx.esc(cfg.pin || '240180')}</strong><small>Standard-PIN der Nodes</small></div>
            <div><span>Priorität</span><strong>${ctx.esc(cfg.transport_priority || 'USB → BLE')}</strong><small>USB bevorzugt, BLE als Fallback</small></div>
          </div>
        </section>

        <section class="settings-card soft-card settings-card-wide">
          <div class="settings-card-head"><div><div class="section-label">FUNK & MESH</div><h2>LoRa-Frequenz und Reichweite</h2><p>Diese Werte gehören zur Node bzw. zum Grundprofil – nicht zur App selbst.</p></div><span class="settings-card-icon">⌁</span></div>
          <div class="profile-radio-selector"><label><span>Grundprofil</span><select id="radioProfileSelect"><option>Lade Profile …</option></select></label><div class="profile-radio-help">Hier findest du jetzt Frequenz-Slot und Frequenz-Override direkt, statt versteckt im JSON-Profil.</div></div>
          <div id="radioEditorHost"></div>
        </section>

        <section class="settings-card soft-card">
          <div class="settings-card-head"><div><div class="section-label">KARTE & POSITION</div><h2>Kartenstandard</h2></div><span class="settings-card-icon">◇</span></div>
          <label class="settings-select-row"><span>Standardkarte</span><select id="defaultMapStyle"><option value="topo" ${currentMap === 'topo' ? 'selected' : ''}>OpenTopoMap</option><option value="satellite" ${currentMap === 'satellite' ? 'selected' : ''}>Satellit</option><option value="hybrid" ${currentMap === 'hybrid' ? 'selected' : ''}>Hybrid</option></select></label>
          <div class="settings-feature-list"><div>✓ Zoombar und frei verschiebbar</div><div>✓ Track und letzte Position</div><div>✓ Klick setzt Kartenmarker</div><div>✓ MGRS + Lat/Lon für markierten Punkt</div></div>
        </section>

        <section class="settings-card soft-card">
          <div class="settings-card-head"><div><div class="section-label">DARSTELLUNG & APP</div><h2>Oberfläche</h2></div><span class="settings-card-icon">◐</span></div>
          <div class="settings-action-row"><div><strong>${ctx.state.theme === 'dark' ? 'Dunkle' : 'Helle'} Darstellung</strong><span>Framework7 iOS-Theme</span></div><button class="mini-button" data-page-action="theme">${ctx.state.theme === 'dark' ? 'Hell verwenden' : 'Dunkel verwenden'}</button></div>
          <details class="technical-settings"><summary>Technische Details</summary><div class="technical-values"><span>Frontend <strong>Framework7 9.1.3 · v${ctx.esc(ctx.VERSION)}</strong></span><span>Backend <strong>${ctx.esc(ctx.state.data?.backend_version || '—')}</strong></span></div></details>
        </section>
      </div>`;

    ctx.pageHost.querySelector('#defaultMapStyle')?.addEventListener('change', event => {
      localStorage.setItem('jarnsen-map-style', event.target.value);
      ctx.toast(`Standardkarte: ${MAP_STYLES[event.target.value]?.label || event.target.value}`);
    });

    try {
      const profilesData = await ctx.request('/api/profiles');
      const profiles = Array.isArray(profilesData.profiles) ? profilesData.profiles : [];
      const select = ctx.pageHost.querySelector('#radioProfileSelect');
      const available = profiles.filter(profile => !profile.empty);
      if (!select) return;
      if (!available.length) {
        select.innerHTML = '<option value="">Kein Grundprofil vorhanden</option>';
        const host = ctx.pageHost.querySelector('#radioEditorHost');
        if (host) host.innerHTML = '<div class="settings-empty"><strong>Noch kein Profil vorhanden.</strong><span>Unter „Profile & Service“ zuerst eine Node in einen Profil-Slot einlesen.</span></div>';
        return;
      }
      let selectedSlot = Number(ctx.state.profileSlot || 0);
      if (!available.some(profile => Number(profile.slot) === selectedSlot)) selectedSlot = Number(available[0].slot);
      ctx.state.profileSlot = selectedSlot;
      select.innerHTML = available.map(profile => `<option value="${Number(profile.slot)}" ${Number(profile.slot) === selectedSlot ? 'selected' : ''}>${ctx.esc(profile.name || `Profil ${Number(profile.slot) + 1}`)}</option>`).join('');
      select.addEventListener('change', () => {
        ctx.state.profileSlot = Number(select.value);
        loadRadioEditor(ctx, ctx.state.profileSlot);
      });
      await loadRadioEditor(ctx, selectedSlot);
    } catch (error) {
      const host = ctx.pageHost.querySelector('#radioEditorHost');
      if (host) host.innerHTML = `<div class="settings-empty"><strong>Profile konnten nicht geladen werden.</strong><span>${ctx.esc(error.message || error)}</span></div>`;
    }
  }

  window.JarnsenMapSettings = { renderMap, renderSettings };
})();
