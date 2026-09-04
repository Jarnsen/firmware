import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { chromium } from 'playwright-core';

const root = path.resolve('tools/service_tool_web');
const outDir = path.resolve('artifact/ui-checks');
fs.mkdirSync(outDir, { recursive: true });

const requestsSeen = [];
const now = new Date();
const ago = mins => new Date(now.getTime() - mins * 60000).toISOString();

const state = {
  updated_at: now.toISOString(),
  backend_version: '3.1.1b-test',
  status: 'Bereit',
  busy: false,
  summary: { nodes: 4, ble: 3, logs_due: 1, updates: 1, warnings: 0 },
  connections: {
    selected_usb_node_id: '!666634c6',
    usb: [{ device: 'COM7', identity: 'Tracker V1.1', serial_number: 'A1B2C3D4', mapped_node_id: '!666634c6' }],
  },
  nodes: [
    {
      node_id: '!666634c6', long_name: 'RiKrTrp MrsZg26', short_name: 'RK26', device_label: 'Tracker V1.1',
      battery: 100, voltage: 4.32, firmware: '2.8.0', build: '36b3ba3b', ble_reachable: true,
      log_due: false, update: false, attention: false, captured_at: ago(2), sync_state: 'Synchronisiert',
      position: { latitude: 49.4812, longitude: 8.4419 },
    },
    {
      node_id: '!a4d2e3f1', long_name: 'TAK-Repeater', short_name: 'TAKR', device_label: 'Heltec V3',
      battery: 78, voltage: 3.98, firmware: '2.8.0', ble_reachable: true,
      log_due: false, update: false, attention: false, captured_at: ago(9), sync_state: 'Online',
      position: { latitude: 49.4871, longitude: 8.4562 },
    },
    {
      node_id: '!b7f8c9d0', long_name: 'Tracker Wald', short_name: 'WALD', device_label: 'Tracker V1.1',
      battery: 56, voltage: 3.76, firmware: '2.8.0', ble_reachable: true,
      log_due: true, update: false, attention: false, captured_at: ago(31), sync_state: 'Log fällig',
      position: { latitude: 49.5001, longitude: 8.4201 },
    },
    {
      node_id: '!c1d2e3f4', long_name: 'Test Node', short_name: 'TEST', device_label: 'Heltec V3',
      battery: 41, voltage: 3.65, firmware: '2.7.1', ble_reachable: false,
      log_due: false, update: true, attention: false, captured_at: ago(180), sync_state: 'Offline',
    },
  ],
  mesh: { status: 'Online' },
  github: { remote_version: 'v3.1.1b' },
};

const profiles = {
  profiles: [
    { slot: 0, name: 'TAK Standard', empty: false },
    { slot: 1, name: 'Tracker Patrol', empty: false },
    { slot: 2, name: 'Leer', empty: true },
    { slot: 3, name: 'Leer', empty: true },
  ],
};

const sections = {
  power: { is_power_saving: true, wait_bluetooth_secs: 90, ls_secs: 300, min_wake_secs: 8 },
  position: { position_broadcast_secs: 3600, smart_position_enabled: true, broadcast_smart_minimum_distance: 75, gps_update_interval: 120 },
  lora: { region: 'US', modem_preset: 'LONG_FAST', override_frequency: 0, tx_power: 20, hop_limit: 7, use_preset: true, tx_enabled: true },
};

function json(res, status, body) {
  const text = JSON.stringify(body);
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(text),
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': '*',
    'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
  });
  res.end(text);
}

function mime(file) {
  const ext = path.extname(file).toLowerCase();
  return ({ '.html':'text/html; charset=utf-8', '.js':'text/javascript; charset=utf-8', '.css':'text/css; charset=utf-8', '.png':'image/png', '.svg':'image/svg+xml', '.json':'application/json; charset=utf-8' })[ext] || 'application/octet-stream';
}

async function bodyOf(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  const text = Buffer.concat(chunks).toString('utf8');
  try { return JSON.parse(text || '{}'); } catch { return { raw: text }; }
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url || '/', 'http://127.0.0.1');
  if (req.method === 'OPTIONS') return json(res, 200, {});
  if (url.pathname.startsWith('/api/')) {
    const body = req.method === 'POST' ? await bodyOf(req) : null;
    requestsSeen.push({ method: req.method, path: url.pathname, body });

    if (url.pathname === '/api/state') return json(res, 200, state);
    if (url.pathname === '/api/profiles') return json(res, 200, profiles);
    if (/^\/api\/profile\/\d+\/config\/power$/.test(url.pathname)) return json(res, 200, { data: sections.power });
    if (/^\/api\/profile\/\d+\/config\/position$/.test(url.pathname)) return json(res, 200, { data: sections.position });
    if (/^\/api\/profile\/\d+\/config\/lora$/.test(url.pathname)) return json(res, 200, { data: sections.lora });
    if (url.pathname === '/api/profile/section') return json(res, 200, { ok: true, data: body?.data || {} });
    if (url.pathname === '/api/profile/action') return json(res, 200, { ok: true, message: 'Profilaktion gestartet' });
    if (url.pathname === '/api/radio-authorization') return json(res, 200, {
      frequency_a_mhz: 914.8, frequency_b_mhz: 915.6, frequency_a_hz: 914800000, frequency_b_hz: 915600000,
      standard_max_hops: 7, authorized_max_hops: 20, is_licensed: true,
    });
    if (url.pathname === '/api/service-status') return json(res, 200, {
      usb: state.connections.usb, serial: { active: false, status: 'Bereit', bytes: 0, log_path: '', tail: '' },
      app_update: { available: false, remote_version: '3.1.1b', url_ready: true }, critical: { serial_flash: true, diagnostic_bundle: true, app_update: true }, security_profiles: [],
    });
    if (url.pathname === '/api/service/action') return json(res, 200, { ok: true, message: 'Serviceaktion gestartet' });
    if (/^\/api\/node\/[^/]+\/logs$/.test(url.pathname)) return json(res, 200, { logs: [{ captured_at: ago(2), firmware: '2.8.0', build: '36b3ba3b', path: 'mock-log.txt' }] });
    if (url.pathname === '/api/positions') return json(res, 200, { positions: [] });
    if (url.pathname === '/api/live/state') return json(res, 200, { connected: false, width: 128, height: 64, frame: '' });
    if (url.pathname === '/api/live/action') return json(res, 200, { ok: true });
    if (url.pathname === '/api/action') return json(res, 200, { result: { started: true, target: 'COM7' }, ok: true });
    return json(res, 200, { ok: true, result: {}, settings: {}, data: {} });
  }

  let rel = url.pathname === '/' ? 'index.html' : url.pathname.replace(/^\/ui\/?/, '');
  rel = rel.replace(/^\/+/, '');
  const file = path.resolve(root, rel || 'index.html');
  if (!file.startsWith(root) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
    res.writeHead(404); res.end('not found'); return;
  }
  const data = fs.readFileSync(file);
  res.writeHead(200, { 'Content-Type': mime(file), 'Content-Length': data.length, 'Cache-Control': 'no-store' });
  res.end(data);
});

function findBrowser() {
  const candidates = [
    path.join(process.env['PROGRAMFILES(X86)'] || '', 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
    path.join(process.env.PROGRAMFILES || '', 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
    path.join(process.env.LOCALAPPDATA || '', 'Microsoft', 'Edge', 'Application', 'msedge.exe'),
    path.join(process.env.PROGRAMFILES || '', 'Google', 'Chrome', 'Application', 'chrome.exe'),
    path.join(process.env['PROGRAMFILES(X86)'] || '', 'Google', 'Chrome', 'Application', 'chrome.exe'),
  ].filter(Boolean);
  const found = candidates.find(file => fs.existsSync(file));
  if (!found) throw new Error(`No Edge/Chrome executable found. Checked: ${candidates.join(', ')}`);
  return found;
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function layoutSnapshot(page) {
  return page.evaluate(() => {
    const rect = selector => {
      const el = document.querySelector(selector);
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { x:r.x, y:r.y, width:r.width, height:r.height };
    };
    return {
      width: innerWidth,
      height: innerHeight,
      documentScrollWidth: document.documentElement.scrollWidth,
      bodyScrollWidth: document.body.scrollWidth,
      sidebar: rect('.sidebar'),
      main: rect('.main-column'),
      inspector: rect('.inspector'),
      topStrip: rect('#v323TopStrip'),
      content: rect('.content-card'),
    };
  });
}

async function waitForRequest(predicate, timeoutMs = 3000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const item = requestsSeen.find(predicate);
    if (item) return item;
    await new Promise(resolve => setTimeout(resolve, 50));
  }
  throw new Error('Expected UI-triggered API request was not observed');
}

const port = await new Promise((resolve, reject) => {
  server.listen(0, '127.0.0.1', () => resolve(server.address().port));
  server.on('error', reject);
});

let browser;
try {
  browser = await chromium.launch({ executablePath: findBrowser(), headless: true, args: ['--disable-gpu'] });
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 }, deviceScaleFactor: 1 });
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(String(error)));
  page.on('console', msg => { if (msg.type() === 'error') pageErrors.push(`console: ${msg.text()}`); });

  const url = `http://127.0.0.1:${port}/ui/index.html?api=${encodeURIComponent(`http://127.0.0.1:${port}`)}&token=ui-test&version=3.1.1b`;
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.rd-v323-dashboard', { timeout: 10000 });
  await page.screenshot({ path: path.join(outDir, 'dashboard-1600x900.png'), fullPage: true });

  let layout = await layoutSnapshot(page);
  assert(layout.sidebar && layout.sidebar.width >= 190 && layout.sidebar.width <= 260, `Sidebar width outside target: ${JSON.stringify(layout.sidebar)}`);
  assert(layout.main && layout.main.width >= 760, `Main column too narrow: ${JSON.stringify(layout.main)}`);
  assert(layout.inspector && layout.inspector.width >= 300, `Inspector missing/too narrow: ${JSON.stringify(layout.inspector)}`);
  assert(layout.topStrip && layout.topStrip.height >= 45, 'Top transport/status strip missing');
  assert(layout.documentScrollWidth <= layout.width + 2, `Dashboard horizontal overflow: ${layout.documentScrollWidth} > ${layout.width}`);
  assert(await page.locator('.v323-metric').count() === 4, 'Dashboard must show exactly four KPI cards');
  assert(await page.locator('.v323-quick-grid button').count() >= 6, 'Dashboard quick actions missing');

  await page.locator('.nav-item[data-rd-mode="nodes"]').click();
  await page.waitForSelector('.rd-v323-nodes');
  await page.screenshot({ path: path.join(outDir, 'nodes-1600x900.png'), fullPage: true });
  assert(await page.locator('.v323-node-row').count() === 4, 'Nodes page did not render all four mock nodes');
  assert(await page.locator('.v323-node-table.v323-table-head > div').count() === 8, 'Nodes table does not have the expected eight columns');
  layout = await layoutSnapshot(page);
  assert(layout.documentScrollWidth <= layout.width + 2, `Nodes page horizontal overflow: ${layout.documentScrollWidth} > ${layout.width}`);

  const firstRow = page.locator('.v323-node-row').first();
  await firstRow.locator('button[data-action="inspect"]').first().click();
  await page.waitForFunction(() => document.querySelector('.inspector-sub')?.textContent?.includes('!666634c6'));
  assert((await page.locator('.inspector').innerText()).includes('RiKrTrp MrsZg26'), 'Inspector did not open selected Node');

  const beforeLog = requestsSeen.length;
  await firstRow.locator('button[data-action="log"]').click();
  const logRequest = await waitForRequest(item => item.path === '/api/action' && item.body?.command === 'download_log' && requestsSeen.indexOf(item) >= beforeLog);
  assert(logRequest.body.node_ids?.includes('!666634c6'), 'Log button did not target selected Node');

  await page.locator('.nav-item[data-view="power"]').click();
  await page.waitForSelector('.rd-power-page');
  assert(await page.locator('[data-rd-save="power"]').count() === 1, 'Power save button missing');
  const beforePower = requestsSeen.length;
  await page.locator('[data-rd-save="power"]').click();
  await waitForRequest(item => item.path === '/api/profile/section' && item.body?.name === 'power' && requestsSeen.indexOf(item) >= beforePower);
  await page.screenshot({ path: path.join(outDir, 'power-1600x900.png'), fullPage: true });

  await page.locator('.nav-item[data-view="network"]').click();
  await page.waitForSelector('.rd-network-page');
  assert(await page.locator('[data-rd-radio-mode]').count() === 3, 'Standard/Jarnsen1/Jarnsen2 radio mode buttons missing');
  assert(await page.locator('#rdFreqA').count() === 1 && await page.locator('#rdFreqB').count() === 1, 'Special-frequency inputs missing');
  await page.screenshot({ path: path.join(outDir, 'network-1600x900.png'), fullPage: true });

  const navigation = [
    ['logs', 'Logs'], ['firmware', 'Firmware'], ['service', 'Profile'], ['live', 'Live'], ['tools', 'Tools'], ['settings', 'Einstellungen'],
  ];
  for (const [view, expected] of navigation) {
    await page.locator(`.nav-item[data-view="${view}"]`).first().click();
    await page.waitForTimeout(250);
    const text = await page.locator('#pageHost').innerText();
    assert(text.toLowerCase().includes(expected.toLowerCase()), `Navigation ${view} did not render expected content containing ${expected}`);
  }

  await page.setViewportSize({ width: 1366, height: 768 });
  await page.locator('.nav-item[data-rd-mode="dashboard"]').click();
  await page.waitForSelector('.rd-v323-dashboard');
  await page.screenshot({ path: path.join(outDir, 'dashboard-1366x768.png'), fullPage: true });
  layout = await layoutSnapshot(page);
  assert(layout.documentScrollWidth <= layout.width + 2, `1366 dashboard horizontal overflow: ${layout.documentScrollWidth} > ${layout.width}`);

  await page.locator('.nav-item[data-rd-mode="nodes"]').click();
  await page.waitForSelector('.rd-v323-nodes');
  await page.screenshot({ path: path.join(outDir, 'nodes-1366x768.png'), fullPage: true });
  layout = await layoutSnapshot(page);
  assert(layout.documentScrollWidth <= layout.width + 2, `1366 nodes horizontal overflow: ${layout.documentScrollWidth} > ${layout.width}`);

  assert(pageErrors.length === 0, `Browser console/page errors detected:\n${pageErrors.join('\n')}`);
  fs.writeFileSync(path.join(outDir, 'ui-check-summary.json'), JSON.stringify({
    ok: true,
    browser: findBrowser(),
    screenshots: fs.readdirSync(outDir).filter(name => name.endsWith('.png')),
    requestsTested: requestsSeen.filter(item => item.method === 'POST'),
  }, null, 2));
  console.log(`Browser UI validation OK: ${fs.readdirSync(outDir).filter(name => name.endsWith('.png')).length} screenshots, ${requestsSeen.length} API calls observed.`);
} finally {
  if (browser) await browser.close();
  await new Promise(resolve => server.close(resolve));
}
