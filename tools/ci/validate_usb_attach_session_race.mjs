import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { chromium } from 'playwright-core';

const usbScript = path.resolve('tools/service_tool_web/usb-attach-v322.js');

let state = {
  busy: false,
  connections: {
    selected_usb_node_id: '!old0001',
    usb: [{
      device: 'COM7',
      identity: 'tracker-v11-a',
      serial_number: 'A1B2C3D4',
      mapped_node_id: '!old0001',
    }],
  },
  nodes: [
    { node_id: '!old0001', long_name: 'Old USB Node', short_name: 'OLD', log_due: false },
    { node_id: '!new0002', long_name: 'New USB Node', short_name: 'NEW', log_due: true },
  ],
};

function json(res, status, body) {
  const text = JSON.stringify(body);
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(text),
    'Cache-Control': 'no-store',
  });
  res.end(text);
}

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

const html = `<!doctype html>
<html>
<head><meta charset="utf-8"><title>USB attach race regression</title></head>
<body>
  <div id="inspector"><div class="inspector-name">No node</div><div class="inspector-sub">Detached</div></div>
  <script src="/usb-attach-v322.js"></script>
</body>
</html>`;

const server = http.createServer((req, res) => {
  const url = new URL(req.url || '/', 'http://127.0.0.1');
  if (url.pathname === '/api/state') return json(res, 200, state);
  if (url.pathname === '/api/action') return json(res, 200, { ok: true });
  if (url.pathname === '/usb-attach-v322.js') {
    const data = fs.readFileSync(usbScript);
    res.writeHead(200, {
      'Content-Type': 'application/javascript; charset=utf-8',
      'Content-Length': data.length,
      'Cache-Control': 'no-store',
    });
    res.end(data);
    return;
  }
  if (url.pathname === '/') {
    const data = Buffer.from(html, 'utf8');
    res.writeHead(200, {
      'Content-Type': 'text/html; charset=utf-8',
      'Content-Length': data.length,
      'Cache-Control': 'no-store',
    });
    res.end(data);
    return;
  }
  res.writeHead(404);
  res.end('not found');
});

const port = await new Promise((resolve, reject) => {
  server.listen(0, '127.0.0.1', () => resolve(server.address().port));
  server.on('error', reject);
});

let browser;
try {
  browser = await chromium.launch({ executablePath: findBrowser(), headless: true, args: ['--disable-gpu'] });
  const page = await browser.newPage({ viewport: { width: 900, height: 600 } });
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(String(error)));

  await page.goto(
    `http://127.0.0.1:${port}/?api=${encodeURIComponent(`http://127.0.0.1:${port}`)}&token=race-test`,
    { waitUntil: 'domcontentloaded' },
  );
  await page.waitForFunction(() => Boolean(window.JarnsenUsbAttachV322));
  await page.evaluate(async () => { await window.JarnsenUsbAttachV322.refresh(); });

  let selected = await page.evaluate(() => document.documentElement.dataset.neoUsbSelectedNode || '');
  assert(selected === '!old0001', `Initial USB mapping missing: ${selected}`);

  // Detach inside the module's delayed 120 ms selection synchronization window.
  // The old implementation could run that timer after resetSession() and restore
  // the stale selection data attributes for a device that was already gone.
  state.connections.usb = [];
  state.connections.selected_usb_node_id = '';
  await page.evaluate(async () => { await window.JarnsenUsbAttachV322.refresh(); });
  selected = await page.evaluate(() => document.documentElement.dataset.neoUsbSelectedNode || '');
  assert(selected === '', `USB selection was not cleared immediately on detach: ${selected}`);

  await page.waitForTimeout(260);
  selected = await page.evaluate(() => document.documentElement.dataset.neoUsbSelectedNode || '');
  const inspectorSelected = await page.evaluate(() => document.getElementById('inspector')?.dataset.usbSelectedNode || '');
  assert(selected === '', `Stale delayed callback revived detached USB node: ${selected}`);
  assert(inspectorSelected === '', `Inspector stale USB selection revived after detach: ${inspectorSelected}`);

  // Reattach the same physical device quickly with a new authoritative node id.
  // Session generation, not only the physical key, must distinguish this session.
  state.connections.selected_usb_node_id = '!new0002';
  state.connections.usb = [{
    device: 'COM7',
    identity: 'tracker-v11-a',
    serial_number: 'A1B2C3D4',
    mapped_node_id: '!new0002',
  }];
  await page.evaluate(async () => { await window.JarnsenUsbAttachV322.refresh(); });
  await page.waitForTimeout(260);

  selected = await page.evaluate(() => document.documentElement.dataset.neoUsbSelectedNode || '');
  const selectedName = await page.evaluate(() => document.documentElement.dataset.neoUsbSelectedName || '');
  assert(selected === '!new0002', `Fast reattach did not keep new node mapping: ${selected}`);
  assert(selectedName === 'New USB Node', `Fast reattach kept stale display identity: ${selectedName}`);
  assert(pageErrors.length === 0, `USB attach race test produced page errors: ${pageErrors.join(' | ')}`);

  console.log('USB attach session race regression OK');
} finally {
  if (browser) await browser.close();
  await new Promise(resolve => server.close(resolve));
}
