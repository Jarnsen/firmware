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
const usbFixture = () => ({ device:'COM7', identity:'Tracker V1.1', serial_number:'A1B2C3D4', mapped_node_id:'!666634c6' });
const state = {
  updated_at:now.toISOString(), backend_version:'3.1.1b-test', status:'Bereit', busy:false,
  summary:{nodes:4,ble:3,logs_due:1,updates:1,warnings:0},
  connections:{selected_usb_node_id:'!666634c6',usb:[usbFixture()]},
  nodes:[
    {node_id:'!666634c6',long_name:'RiKrTrp MrsZg26',short_name:'RK26',device_label:'Tracker V1.1',battery:100,voltage:4.32,firmware:'2.8.0',build:'36b3ba3b',ble_reachable:true,log_due:false,update:false,attention:false,captured_at:ago(2),sync_state:'Synchronisiert',position:{latitude:49.4812,longitude:8.4419}},
    {node_id:'!a4d2e3f1',long_name:'TAK-Repeater',short_name:'TAKR',device_label:'Heltec V3',battery:78,voltage:3.98,firmware:'2.8.0',ble_reachable:true,log_due:false,update:false,attention:false,captured_at:ago(9),sync_state:'Online',position:{latitude:49.4871,longitude:8.4562}},
    {node_id:'!b7f8c9d0',long_name:'Tracker Wald',short_name:'WALD',device_label:'Tracker V1.1',battery:56,voltage:3.76,firmware:'2.8.0',ble_reachable:true,log_due:true,update:false,attention:false,captured_at:ago(31),sync_state:'Log fällig'},
    {node_id:'!c1d2e3f4',long_name:'Test Node',short_name:'TEST',device_label:'Heltec V3',battery:41,voltage:3.65,firmware:'2.7.1',ble_reachable:false,log_due:false,update:true,attention:false,captured_at:ago(180),sync_state:'Offline'}
  ], mesh:{status:'Online'}, github:{remote_version:'v3.1.1b'}
};
const profiles={profiles:[{slot:0,name:'TAK Standard',empty:false},{slot:1,name:'Tracker Patrol',empty:false},{slot:2,name:'Leer',empty:true},{slot:3,name:'Leer',empty:true}]};
const sections={
  power:{is_power_saving:true,wait_bluetooth_secs:90,ls_secs:300,min_wake_secs:8},
  position:{position_broadcast_secs:3600,smart_position_enabled:true,broadcast_smart_minimum_distance:75,gps_update_interval:120},
  lora:{region:'US',modem_preset:'LONG_FAST',override_frequency:0,tx_power:20,hop_limit:7,use_preset:true,tx_enabled:true}
};
function json(res,status,body){const text=JSON.stringify(body);res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Content-Length':Buffer.byteLength(text),'Access-Control-Allow-Origin':'*','Access-Control-Allow-Headers':'*','Access-Control-Allow-Methods':'GET,POST,OPTIONS'});res.end(text);}
function mime(file){return ({'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.png':'image/png','.svg':'image/svg+xml','.json':'application/json; charset=utf-8'})[path.extname(file).toLowerCase()]||'application/octet-stream';}
async function bodyOf(req){const chunks=[];for await(const chunk of req)chunks.push(chunk);try{return JSON.parse(Buffer.concat(chunks).toString('utf8')||'{}');}catch{return {};}}
const server=http.createServer(async(req,res)=>{
  const url=new URL(req.url||'/','http://127.0.0.1');
  if(req.method==='OPTIONS')return json(res,200,{});
  if(url.pathname.startsWith('/api/')){
    const body=req.method==='POST'?await bodyOf(req):null;requestsSeen.push({method:req.method,path:url.pathname,body});
    if(url.pathname==='/api/state')return json(res,200,state);
    if(url.pathname==='/api/profiles')return json(res,200,profiles);
    if(/^\/api\/profile\/\d+\/config\/power$/.test(url.pathname))return json(res,200,{data:sections.power});
    if(/^\/api\/profile\/\d+\/config\/position$/.test(url.pathname))return json(res,200,{data:sections.position});
    if(/^\/api\/profile\/\d+\/config\/lora$/.test(url.pathname))return json(res,200,{data:sections.lora});
    if(url.pathname==='/api/profile/section')return json(res,200,{ok:true,data:body?.data||{}});
    if(url.pathname==='/api/profile/action')return json(res,200,{ok:true,message:'Profilaktion gestartet'});
    if(url.pathname==='/api/radio-authorization')return json(res,200,{frequency_a_mhz:914.8,frequency_b_mhz:915.6,frequency_a_hz:914800000,frequency_b_hz:915600000,standard_max_hops:7,authorized_max_hops:20,is_licensed:true});
    if(url.pathname==='/api/service-status')return json(res,200,{usb:state.connections.usb,serial:{active:false,status:'Bereit'},app_update:{available:false},critical:{serial_flash:true,diagnostic_bundle:true,app_update:true},security_profiles:[]});
    if(url.pathname==='/api/service/action')return json(res,200,{ok:true,message:'Serviceaktion gestartet'});
    if(/^\/api\/node\/[^/]+\/logs$/.test(url.pathname))return json(res,200,{logs:[]});
    if(url.pathname==='/api/positions')return json(res,200,{positions:[]});
    if(url.pathname==='/api/live/state')return json(res,200,{connected:false,width:128,height:64,frame:''});
    if(url.pathname==='/api/live/action')return json(res,200,{ok:true});
    if(url.pathname==='/api/action')return json(res,200,{ok:true,result:{started:true,target:'COM7'}});
    return json(res,200,{ok:true,result:{},settings:{},data:{}});
  }
  let rel=url.pathname==='/'?'index.html':url.pathname.replace(/^\/ui\/?/,'').replace(/^\/+/, '');
  const file=path.resolve(root,rel||'index.html');if(!file.startsWith(root)||!fs.existsSync(file)||!fs.statSync(file).isFile()){res.writeHead(404);res.end('not found');return;}
  const data=fs.readFileSync(file);res.writeHead(200,{'Content-Type':mime(file),'Content-Length':data.length,'Cache-Control':'no-store'});res.end(data);
});
function browserCandidates(){return [
  ['Chrome',path.join(process.env.PROGRAMFILES||'','Google','Chrome','Application','chrome.exe')],
  ['Chrome x86',path.join(process.env['PROGRAMFILES(X86)']||'','Google','Chrome','Application','chrome.exe')],
  ['Chrome Local',path.join(process.env.LOCALAPPDATA||'','Google','Chrome','Application','chrome.exe')],
  ['Edge',path.join(process.env.PROGRAMFILES||'','Microsoft','Edge','Application','msedge.exe')],
  ['Edge x86',path.join(process.env['PROGRAMFILES(X86)']||'','Microsoft','Edge','Application','msedge.exe')],
  ['Edge Local',path.join(process.env.LOCALAPPDATA||'','Microsoft','Edge','Application','msedge.exe')]
].filter(([,p])=>p&&fs.existsSync(p));}
async function launchBrowser(){const candidates=browserCandidates();if(!candidates.length)throw new Error('No Chrome/Edge executable found');let last;for(const [name,exe] of candidates){console.log(`[browser] trying ${name}: ${exe}`);try{const b=await chromium.launch({executablePath:exe,headless:true,timeout:15000,args:['--disable-gpu','--disable-background-timer-throttling','--disable-renderer-backgrounding']});console.log(`[browser] launched ${name}`);return {browser:b,name,exe};}catch(e){last=e;console.log(`[browser] ${name} failed: ${e}`);}}throw last||new Error('Browser launch failed');}
function assert(v,m){if(!v)throw new Error(m);}
async function waitForRequest(pred,timeout=5000){const start=Date.now();while(Date.now()-start<timeout){const x=requestsSeen.find(pred);if(x)return x;await new Promise(r=>setTimeout(r,50));}throw new Error('Expected UI API request not observed');}
async function closeBounded(browser){if(!browser)return;await Promise.race([browser.close().catch(()=>{}),new Promise(r=>setTimeout(r,5000))]);}
const port=await new Promise((resolve,reject)=>{server.listen(0,'127.0.0.1',()=>resolve(server.address().port));server.on('error',reject);});
console.log(`[phase] server-ready ${port}`);
let browser;let browserInfo;
try{
  browserInfo=await launchBrowser();browser=browserInfo.browser;
  console.log('[phase] page-create');
  const page=await browser.newPage({viewport:{width:1600,height:900},deviceScaleFactor:1});page.setDefaultTimeout(10000);page.setDefaultNavigationTimeout(15000);
  const errors=[];page.on('pageerror',e=>errors.push(String(e)));page.on('console',m=>{if(m.type()==='error')errors.push(`console: ${m.text()}`);});
  const url=`http://127.0.0.1:${port}/ui/index.html?api=${encodeURIComponent(`http://127.0.0.1:${port}`)}&token=ui-test&version=3.1.1b`;
  console.log('[phase] goto');await page.goto(url,{waitUntil:'domcontentloaded',timeout:15000});
  console.log('[phase] dashboard-wait');await page.waitForSelector('.rd-v323-dashboard',{timeout:10000});
  assert(await page.locator('.v323-metric').count()===4,'Dashboard KPI cards missing');assert(await page.locator('.v323-quick-grid button').count()>=6,'Dashboard quick actions missing');
  console.log('[phase] usb-prompt');const prompt=page.locator('#jarnsenUsbLogPrompt');await prompt.waitFor({state:'visible',timeout:7000});const ptxt=await prompt.innerText();assert(ptxt.includes('Nicht herunterladen')&&ptxt.includes('Log herunterladen'),'USB prompt actions missing');await prompt.getByRole('button',{name:'Nicht herunterladen',exact:true}).click();await prompt.waitFor({state:'detached',timeout:3000});
  console.log('[phase] nodes');await page.locator('.nav-item[data-rd-mode="nodes"]').click();await page.waitForSelector('.rd-v323-nodes');assert(await page.locator('.v323-node-row').count()===4,'Node rows missing');
  const first=page.locator('.v323-node-row').first();await first.locator('button[data-action="inspect"]').first().click();await page.waitForFunction(()=>document.querySelector('.inspector-sub')?.textContent?.includes('!666634c6'));assert((await page.locator('.inspector').innerText()).includes('RiKrTrp MrsZg26'),'Inspector selection failed');
  const beforeLog=requestsSeen.length;await first.locator('button[data-action="log"]').click();await waitForRequest(x=>x.path==='/api/action'&&x.body?.command==='download_log'&&requestsSeen.indexOf(x)>=beforeLog);
  console.log('[phase] power');await page.locator('.nav-item[data-view="power"]').click();await page.waitForSelector('.rd-power-page');const beforePower=requestsSeen.length;await page.locator('[data-rd-save="power"]').click();await waitForRequest(x=>x.path==='/api/profile/section'&&x.body?.name==='power'&&requestsSeen.indexOf(x)>=beforePower);
  console.log('[phase] network');await page.locator('.nav-item[data-view="network"]').click();await page.waitForSelector('.rd-network-page');assert(await page.locator('[data-rd-radio-mode]').count()===3,'Radio mode buttons missing');
  console.log('[phase] navigation');for(const [view,expected] of [['logs','Logs'],['firmware','Firmware'],['service','Profile'],['live','Live'],['tools','Tools'],['settings','Einstellungen']]){console.log(`[nav] ${view}`);await page.locator(`.nav-item[data-view="${view}"]`).first().click();await page.waitForTimeout(150);assert((await page.locator('#pageHost').innerText()).toLowerCase().includes(expected.toLowerCase()),`Navigation ${view} failed`);}
  assert(errors.length===0,`Browser console/page errors:\n${errors.join('\n')}`);
  fs.writeFileSync(path.join(outDir,'ui-check-summary.json'),JSON.stringify({ok:true,browser:browserInfo.name,executable:browserInfo.exe,mode:'functional-no-screenshot',requestsTested:requestsSeen.filter(x=>x.method==='POST')},null,2));
  console.log(`[phase] complete browser=${browserInfo.name} requests=${requestsSeen.length}`);
}finally{
  console.log('[phase] cleanup');await closeBounded(browser);server.closeIdleConnections?.();server.closeAllConnections?.();server.close();console.log('[phase] cleanup-complete');
}
