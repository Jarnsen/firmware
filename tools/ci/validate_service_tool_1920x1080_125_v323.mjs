import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { chromium } from 'playwright-core';

// 1920x1080 at Windows 125% scaling presents roughly a 1536x864 CSS viewport.
// deviceScaleFactor 1.25 recreates the physical-pixel density while layout still
// uses the effective CSS dimensions the user actually sees.
const VIEWPORT = { width: 1536, height: 864 };
const SCALE = 1.25;
const root = path.resolve('tools/service_tool_web');
const outDir = path.resolve('artifact/ui-checks');
fs.mkdirSync(outDir, { recursive: true });

const now = new Date();
const ago = mins => new Date(now.getTime() - mins * 60000).toISOString();
const state = {
  updated_at: now.toISOString(),
  backend_version: '3.1.1b-test', status: 'Bereit', busy: false,
  summary: { nodes: 4, ble: 3, logs_due: 1, updates: 1, warnings: 0 },
  connections: { selected_usb_node_id: '!666634c6', usb: [{ device: 'COM7', mapped_node_id: '!666634c6', identity: 'Tracker V1.1', serial_number: 'A1B2C3D4' }] },
  nodes: [
    { node_id:'!666634c6', long_name:'RiKrTrp MrsZg26', short_name:'RK26', device_label:'Tracker V1.1', battery:100, voltage:4.32, firmware:'2.8.0', build:'36b3ba3b', ble_reachable:true, log_due:false, update:false, attention:false, captured_at:ago(2), sync_state:'Synchronisiert', position:{latitude:49.4812,longitude:8.4419} },
    { node_id:'!a4d2e3f1', long_name:'TAK-Repeater', short_name:'TAKR', device_label:'Heltec V3', battery:78, voltage:3.98, firmware:'2.8.0', ble_reachable:true, log_due:false, update:false, attention:false, captured_at:ago(9), sync_state:'Online', position:{latitude:49.4871,longitude:8.4562} },
    { node_id:'!b7f8c9d0', long_name:'Tracker Wald', short_name:'WALD', device_label:'Tracker V1.1', battery:56, voltage:3.76, firmware:'2.8.0', ble_reachable:true, log_due:true, update:false, attention:false, captured_at:ago(31), sync_state:'Log fällig', position:{latitude:49.5001,longitude:8.4201} },
    { node_id:'!c1d2e3f4', long_name:'Test Node', short_name:'TEST', device_label:'Heltec V3', battery:41, voltage:3.65, firmware:'2.7.1', ble_reachable:false, log_due:false, update:true, attention:false, captured_at:ago(180), sync_state:'Offline' },
  ],
  mesh: { status: 'Online' }, github: { remote_version: 'v3.1.1b' },
};

const profiles = { profiles: [{slot:0,name:'TAK Standard',empty:false}] };
const radio = { frequency_a_mhz:914.8, frequency_b_mhz:915.6, frequency_a_hz:914800000, frequency_b_hz:915600000, standard_max_hops:7, authorized_max_hops:20 };

function json(res, status, body) {
  const text = JSON.stringify(body);
  res.writeHead(status, {'Content-Type':'application/json; charset=utf-8','Content-Length':Buffer.byteLength(text),'Access-Control-Allow-Origin':'*','Access-Control-Allow-Headers':'*','Access-Control-Allow-Methods':'GET,POST,OPTIONS'});
  res.end(text);
}
function mime(file) {
  return ({'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.png':'image/png','.svg':'image/svg+xml'})[path.extname(file).toLowerCase()] || 'application/octet-stream';
}
function findBrowser() {
  const candidates = [
    path.join(process.env['PROGRAMFILES(X86)'] || '', 'Microsoft','Edge','Application','msedge.exe'),
    path.join(process.env.PROGRAMFILES || '', 'Microsoft','Edge','Application','msedge.exe'),
    path.join(process.env.LOCALAPPDATA || '', 'Microsoft','Edge','Application','msedge.exe'),
    path.join(process.env.PROGRAMFILES || '', 'Google','Chrome','Application','chrome.exe'),
  ];
  const found = candidates.find(p => p && fs.existsSync(p));
  if (!found) throw new Error('Edge/Chrome not found for 125% scale test');
  return found;
}
function assert(value, message) { if (!value) throw new Error(message); }

const server = http.createServer((req, res) => {
  const url = new URL(req.url || '/', 'http://127.0.0.1');
  if (req.method === 'OPTIONS') return json(res, 200, {});
  if (url.pathname === '/api/state') return json(res, 200, state);
  if (url.pathname === '/api/profiles') return json(res, 200, profiles);
  if (url.pathname === '/api/radio-authorization') return json(res, 200, radio);
  if (/^\/api\/profile\/\d+\/config\/power$/.test(url.pathname)) return json(res, 200, {data:{is_power_saving:true,ls_secs:300}});
  if (/^\/api\/profile\/\d+\/config\/position$/.test(url.pathname)) return json(res, 200, {data:{position_broadcast_secs:3600,smart_position_enabled:true}});
  if (/^\/api\/profile\/\d+\/config\/lora$/.test(url.pathname)) return json(res, 200, {data:{region:'US',override_frequency:0,hop_limit:7,tx_power:20}});
  if (url.pathname === '/api/service-status') return json(res, 200, {usb:state.connections.usb,critical:{serial_flash:true,diagnostic_bundle:true},serial:{active:false},app_update:{available:false},security_profiles:[]});
  if (url.pathname.startsWith('/api/')) return json(res, 200, {ok:true,data:{},result:{},logs:[],positions:[]});

  let rel = url.pathname === '/' ? 'index.html' : url.pathname.replace(/^\/ui\/?/, '').replace(/^\/+/, '');
  const file = path.resolve(root, rel || 'index.html');
  if (!file.startsWith(root) || !fs.existsSync(file) || !fs.statSync(file).isFile()) { res.writeHead(404); res.end('not found'); return; }
  const data = fs.readFileSync(file);
  res.writeHead(200, {'Content-Type':mime(file),'Content-Length':data.length,'Cache-Control':'no-store'});
  res.end(data);
});

const port = await new Promise((resolve, reject) => { server.listen(0,'127.0.0.1',()=>resolve(server.address().port)); server.on('error',reject); });
let browser;
try {
  browser = await chromium.launch({executablePath:findBrowser(),headless:true,args:['--disable-gpu']});
  const context = await browser.newContext({viewport:VIEWPORT,deviceScaleFactor:SCALE});
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', msg => { if (msg.type() === 'error') errors.push(`console: ${msg.text()}`); });
  const url = `http://127.0.0.1:${port}/ui/index.html?api=${encodeURIComponent(`http://127.0.0.1:${port}`)}&token=scale-test&version=3.1.1b`;
  await page.goto(url, {waitUntil:'domcontentloaded'});
  await page.waitForSelector('.rd-v323-dashboard', {timeout:10000});

  const assertLayout = async label => {
    const data = await page.evaluate(() => {
      const rect = sel => { const e=document.querySelector(sel); if(!e) return null; const r=e.getBoundingClientRect(); return {x:r.x,y:r.y,width:r.width,height:r.height,right:r.right,bottom:r.bottom}; };
      return {
        innerWidth, innerHeight,
        scrollWidth:document.documentElement.scrollWidth,
        sidebar:rect('.sidebar'), main:rect('.main-column'), inspector:rect('.inspector'), top:rect('#v323TopStrip'), content:rect('.content-card'), shell:rect('.rd-v323-shell'),
      };
    });
    assert(data.innerWidth === 1536 && data.innerHeight === 864, `${label}: effective viewport is ${data.innerWidth}x${data.innerHeight}, expected 1536x864`);
    assert(data.scrollWidth <= 1538, `${label}: horizontal overflow ${data.scrollWidth}px at 125% scaling`);
    assert(data.sidebar?.width >= 200 && data.sidebar?.width <= 250, `${label}: sidebar width ${data.sidebar?.width}`);
    assert(data.inspector?.width >= 300, `${label}: inspector disappeared or too narrow (${data.inspector?.width})`);
    assert(data.main?.width >= 850, `${label}: main area too narrow (${data.main?.width})`);
    assert(data.top?.height >= 45 && data.top?.height <= 70, `${label}: top status strip height ${data.top?.height}`);
    assert(data.content?.right <= 1536 && data.inspector?.right <= 1536, `${label}: panels exceed effective screen width`);
    return data;
  };

  // At the user's real scaling the critical USB prompt must be fully usable and
  // must not make the layout inaccessible once the user chooses "Nicht herunterladen".
  const prompt = page.locator('#jarnsenUsbLogPrompt');
  await prompt.waitFor({state:'visible', timeout:7000});
  const promptText = await prompt.innerText();
  assert(promptText.includes('Nicht herunterladen'), '125%: decline button missing in USB attach prompt');
  assert(promptText.includes('Log herunterladen'), '125%: download button missing in USB attach prompt');
  await page.waitForFunction(() => document.querySelector('.inspector-sub')?.textContent?.includes('!666634c6'));
  await page.screenshot({path:path.join(outDir,'usb-log-prompt-1920x1080-125pct.png'),fullPage:true});
  await prompt.getByRole('button', {name:'Nicht herunterladen', exact:true}).click();
  await prompt.waitFor({state:'detached', timeout:3000});
  const decision = await page.evaluate(() => document.documentElement.dataset.usbAttachDecision || '');
  assert(decision === 'declined', `125%: USB decline decision not retained (${decision})`);

  await assertLayout('Dashboard');
  assert(await page.locator('.v323-metric').count() === 4, 'Dashboard KPI layout incomplete at 125% scaling');
  assert(await page.locator('.v323-quick-grid button').count() >= 6, 'Dashboard quick actions incomplete at 125% scaling');
  await page.screenshot({path:path.join(outDir,'dashboard-1920x1080-125pct.png'),fullPage:true});

  await page.locator('.nav-item[data-rd-mode="nodes"]').click();
  await page.waitForSelector('.rd-v323-nodes');
  await assertLayout('Nodes');
  assert(await page.locator('.v323-node-row').count() === 4, 'Nodes rows missing at 125% scaling');
  assert(await page.locator('.v323-node-table.v323-table-head > div').count() === 8, 'Nodes columns missing at 125% scaling');
  const table = await page.locator('.v323-table-shell').evaluate(el => ({clientWidth:el.clientWidth,scrollWidth:el.scrollWidth}));
  assert(table.scrollWidth <= table.clientWidth + 2, `Nodes table needs horizontal scrolling at 125% scaling: ${table.scrollWidth} > ${table.clientWidth}`);
  await page.locator('.v323-node-row').first().locator('button[data-action="inspect"]').first().click();
  await page.waitForFunction(() => document.querySelector('.inspector-sub')?.textContent?.includes('!666634c6'));
  assert((await page.locator('.inspector').innerText()).includes('RiKrTrp MrsZg26'), 'Inspector click path failed at 125% scaling');
  await page.screenshot({path:path.join(outDir,'nodes-1920x1080-125pct.png'),fullPage:true});

  assert(errors.length === 0, `125% scale browser errors:\n${errors.join('\n')}`);
  fs.writeFileSync(path.join(outDir,'ui-check-1920x1080-125pct.json'), JSON.stringify({ok:true,physical:'1920x1080',windowsScalePercent:125,effectiveCssViewport:'1536x864',deviceScaleFactor:SCALE,usbPrompt:'visible-and-decline-tested'}, null, 2));
  console.log('1920x1080 @ 125% UI validation OK (1536x864 CSS viewport, DPR 1.25, USB prompt checked).');
} finally {
  if (browser) await browser.close();
  await new Promise(resolve => server.close(resolve));
}
