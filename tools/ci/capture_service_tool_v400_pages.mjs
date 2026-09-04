import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { chromium } from 'playwright-core';

const root=path.resolve('tools/service_tool_web');
const out=path.resolve('artifact/ui-checks');
fs.mkdirSync(out,{recursive:true});
const now=new Date();const ago=m=>new Date(now.getTime()-m*60000).toISOString();
const state={updated_at:now.toISOString(),backend_version:'3.1.1b-v4',status:'Bereit',busy:false,summary:{nodes:4,ble:3,logs_due:1,updates:1,warnings:0},connections:{selected_usb_node_id:'!666634c6',usb:[{device:'COM7',mapped_node_id:'!666634c6',identity:'Tracker V1.1',serial_number:'A1B2C3D4'}]},mesh:{status:'Online'},github:{remote_version:'2.8.1'},nodes:[
{node_id:'!666634c6',long_name:'RiKrTrp MrsZg26',short_name:'RK26',device_label:'Tracker V1.1',battery:100,voltage:4.32,firmware:'2.8.0',build:'36b3ba3b',ble_reachable:true,log_due:false,update:false,captured_at:ago(2),sync_state:'Synchronisiert',position:{latitude:49.4812,longitude:8.4419},metrics:{snr:7.2}},
{node_id:'!a4d2e3f1',long_name:'TAK-Repeater',short_name:'TAKR',device_label:'Heltec V3',battery:78,voltage:3.98,firmware:'2.8.0',build:'4cc3105c',ble_reachable:true,log_due:false,update:false,captured_at:ago(5),sync_state:'Online'},
{node_id:'!b7f8c9d0',long_name:'Tracker Wald',short_name:'WALD',device_label:'Tracker V1.1',battery:56,voltage:3.76,firmware:'2.8.0',build:'aa5f59c7',ble_reachable:true,log_due:true,update:false,captured_at:ago(12),sync_state:'Log fällig'},
{node_id:'!c1d2e3f4',long_name:'Test Node',short_name:'TEST',device_label:'Heltec V3',battery:null,firmware:'2.7.1',ble_reachable:false,log_due:false,update:true,captured_at:ago(180),sync_state:'Offline'}]};
const profiles={profiles:[{slot:0,name:'Standard',empty:false},{slot:1,name:'Tracker',empty:false},{slot:2,name:'Repeater',empty:false},{slot:3,name:'Spezial',empty:false}]};
const radio={frequency_a_mhz:914.8,frequency_b_mhz:915.6,frequency_a_hz:914800000,frequency_b_hz:915600000,standard_max_hops:7,authorized_max_hops:20,is_licensed:true};
const sections={power:{is_power_saving:true,wait_bluetooth_secs:90,ls_secs:300,min_wake_secs:8},position:{position_broadcast_secs:3600,smart_position_enabled:true,broadcast_smart_minimum_distance:75,gps_update_interval:120},lora:{region:'EU_868',modem_preset:'LONG_FAST',override_frequency:0,tx_power:20,hop_limit:7,use_preset:true,tx_enabled:true}};
function json(res,status,body){const text=JSON.stringify(body);res.writeHead(status,{'Content-Type':'application/json; charset=utf-8','Content-Length':Buffer.byteLength(text),'Access-Control-Allow-Origin':'*','Access-Control-Allow-Headers':'*','Access-Control-Allow-Methods':'GET,POST,OPTIONS'});res.end(text)}
function mime(file){return({'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.svg':'image/svg+xml','.png':'image/png'})[path.extname(file).toLowerCase()]||'application/octet-stream'}
const server=http.createServer((req,res)=>{const u=new URL(req.url||'/','http://127.0.0.1');if(req.method==='OPTIONS')return json(res,200,{});if(u.pathname==='/api/state')return json(res,200,state);if(u.pathname==='/api/profiles')return json(res,200,profiles);if(u.pathname==='/api/radio-authorization')return json(res,200,radio);if(/^\/api\/profile\/\d+\/config\/power$/.test(u.pathname))return json(res,200,{data:sections.power});if(/^\/api\/profile\/\d+\/config\/position$/.test(u.pathname))return json(res,200,{data:sections.position});if(/^\/api\/profile\/\d+\/config\/lora$/.test(u.pathname))return json(res,200,{data:sections.lora});if(u.pathname==='/api/service-status')return json(res,200,{usb:state.connections.usb,serial:{active:false},app_update:{available:true,remote_version:'2.8.1'},critical:{serial_flash:true,diagnostic_bundle:true},security_profiles:[]});if(u.pathname.startsWith('/api/'))return json(res,200,{ok:true,result:{target:'COM7'},message:'OK',data:{}});let rel=u.pathname==='/'?'index.html':u.pathname.replace(/^\/ui\/?/,'').replace(/^\/+/, '');const file=path.resolve(root,rel||'index.html');if(!file.startsWith(root)||!fs.existsSync(file)){res.writeHead(404);res.end('not found');return}const data=fs.readFileSync(file);res.writeHead(200,{'Content-Type':mime(file),'Content-Length':data.length,'Cache-Control':'no-store'});res.end(data)});
function browserPath(){const c=[path.join(process.env['PROGRAMFILES(X86)']||'','Microsoft','Edge','Application','msedge.exe'),path.join(process.env.PROGRAMFILES||'','Microsoft','Edge','Application','msedge.exe'),path.join(process.env.LOCALAPPDATA||'','Microsoft','Edge','Application','msedge.exe'),path.join(process.env.PROGRAMFILES||'','Google','Chrome','Application','chrome.exe')];const f=c.find(x=>x&&fs.existsSync(x));if(!f)throw new Error('Edge/Chrome not found');return f}
function assert(value,message){if(!value)throw new Error(message)}
const port=await new Promise((resolve,reject)=>{server.listen(0,'127.0.0.1',()=>resolve(server.address().port));server.on('error',reject)});
let browser;
try{
 browser=await chromium.launch({executablePath:browserPath(),headless:true,args:['--disable-gpu']});
 const page=await browser.newPage({viewport:{width:1536,height:864},deviceScaleFactor:1.25});
 const errors=[];page.on('pageerror',e=>errors.push(String(e)));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});
 await page.goto(`http://127.0.0.1:${port}/ui/index.html?api=${encodeURIComponent(`http://127.0.0.1:${port}`)}&token=v4-ref&version=3.1.1b`,{waitUntil:'domcontentloaded'});
 await page.waitForSelector('.neo-dashboard',{timeout:10000});
 const prompt=page.locator('#jarnsenUsbLogPrompt');if(await prompt.count()){await prompt.waitFor({state:'visible',timeout:7000});await prompt.getByRole('button',{name:'Nicht herunterladen',exact:true}).click();await prompt.waitFor({state:'detached',timeout:3000});}

 const auditPage=async(name,{minPanels=0,specialSelector='',specialCount=0}={})=>{
   await page.waitForTimeout(120);
   const data=await page.evaluate(()=>{
     const visible=el=>{const s=getComputedStyle(el),r=el.getBoundingClientRect();return s.display!=='none'&&s.visibility!=='hidden'&&Number(s.opacity)>0&&r.width>0&&r.height>0};
     const sidebar=document.querySelector('.sidebar')?.getBoundingClientRect();
     const main=document.querySelector('.main-column')?.getBoundingClientRect();
     const pageHost=document.getElementById('pageHost');
     const neo=document.querySelector('#pageHost .neo-page');
     const oldVisible=[...document.querySelectorAll('#pageHost .node-card,#pageHost .generic-card,#pageHost .page-header,#pageHost .rd-page')].filter(visible).map(el=>el.className);
     const visibleButtons=[...document.querySelectorAll('#pageHost button')].filter(visible);
     const unbound=visibleButtons.filter(button=>!button.matches('[data-neo-action],[data-neo-page],[data-action],[data-rd-radio-mode],[data-neo-live],[data-neo-filter],[data-neo-profile-slot]')).map(button=>(button.textContent||'').trim().slice(0,60));
     const bg=getComputedStyle(document.body).backgroundColor;
     return {innerWidth,innerHeight,docScroll:document.documentElement.scrollWidth,hostClient:pageHost?.clientWidth||0,hostScroll:pageHost?.scrollWidth||0,sidebar:sidebar?{width:sidebar.width,right:sidebar.right}:null,main:main?{width:main.width,right:main.right}:null,neo:Boolean(neo),oldVisible,visibleButtons:visibleButtons.length,unbound,bg};
   });
   assert(data.innerWidth===1536&&data.innerHeight===864,`${name}: expected 1536x864 effective viewport, got ${data.innerWidth}x${data.innerHeight}`);
   assert(data.docScroll<=1538,`${name}: document horizontal overflow ${data.docScroll}px`);
   assert(data.hostScroll<=data.hostClient+2,`${name}: page content horizontal overflow ${data.hostScroll} > ${data.hostClient}`);
   assert(data.sidebar?.width>=200&&data.sidebar?.width<=240,`${name}: sidebar width outside v4 target: ${data.sidebar?.width}`);
   assert(data.main?.width>=1100,`${name}: main content unexpectedly narrow: ${data.main?.width}`);
   assert(data.neo,`${name}: v4 .neo-page root missing`);
   assert(data.oldVisible.length===0,`${name}: visible legacy renderer elements detected: ${data.oldVisible.join(', ')}`);
   assert(data.unbound.length===0,`${name}: visible buttons without v4/legacy handler contract: ${data.unbound.join(' | ')}`);
   const panels=await page.locator('#pageHost .neo-panel').count();
   assert(panels>=minPanels,`${name}: expected at least ${minPanels} v4 panels, got ${panels}`);
   if(specialSelector){const count=await page.locator(specialSelector).count();assert(count>=specialCount,`${name}: expected ${specialCount} ${specialSelector}, got ${count}`)}
   return data;
 };
 const capture=async(name,selector,quality={})=>{await page.waitForSelector(selector,{timeout:8000});const geometry=await auditPage(name,quality);await page.screenshot({path:path.join(out,`v400-${name}-1920x1080-125pct.png`),fullPage:true});return geometry;};
 const geometry={};
 geometry.dashboard=await capture('01-dashboard','.neo-dashboard',{minPanels:4,specialSelector:'.neo-kpi',specialCount:4});
 await page.locator('[data-neo-page="nodes"]').click();geometry.nodes=await capture('02-nodes','.neo-nodes',{specialSelector:'.v323-node-row',specialCount:4});
 assert(await page.locator('.v323-node-row').first().locator('button[data-action="log"]:visible').count()===1,'Nodes: visible per-row Log action missing');
 await page.locator('.v323-node-row').first().locator('button[data-action="inspect"]').click();geometry.details=await capture('03-node-details','.neo-details',{minPanels:3});
 const pages=[
   ['logs','04-logs','.neo-logs-grid',{minPanels:2}],
   ['firmware','05-firmware','.neo-firmware-grid',{minPanels:4}],
   ['power','06-power','.rd-power-page',{minPanels:4}],
   ['profiles','07-profiles','.neo-profiles',{specialSelector:'.neo-profile-card',specialCount:4}],
   ['network','08-network','.rd-network-page',{minPanels:4,specialSelector:'[data-rd-radio-mode]',specialCount:3}],
   ['display','09-display','.neo-display-grid',{minPanels:2}],
   ['tools','10-tools','.neo-tools-grid',{specialSelector:'.neo-tool-card',specialCount:8}],
   ['settings','11-settings','.neo-settings-grid',{minPanels:2}],
 ];
 for(const [pageId,name,selector,quality] of pages){await page.locator(`[data-neo-page="${pageId}"]`).click();geometry[pageId]=await capture(name,selector,quality)}
 if(errors.length)throw new Error(`v4 reference capture browser errors:\n${errors.join('\n')}`);
 const shots=fs.readdirSync(out).filter(n=>n.startsWith('v400-')&&n.endsWith('.png'));if(shots.length<11)throw new Error(`Expected 11 v4 reference screenshots, got ${shots.length}`);
 fs.writeFileSync(path.join(out,'v400-page-reference-summary.json'),JSON.stringify({ok:true,physical:'1920x1080',windowsScalePercent:125,effectiveCssViewport:'1536x864',pages:shots,geometry},null,2));
 console.log(`Captured and audited ${shots.length} real v4 page references: no visible legacy renderer, no unbound visible buttons, no horizontal overflow.`);
}finally{if(browser)await browser.close();await new Promise(resolve=>server.close(resolve))}
