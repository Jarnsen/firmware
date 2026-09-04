import fs from 'node:fs';

const index = fs.readFileSync('tools/service_tool_web/index.html','utf8');
const js = fs.readFileSync('tools/service_tool_web/neo-ui-v400.js','utf8');
const hardening = fs.readFileSync('tools/service_tool_web/neo-ui-v400-hardening.js','utf8');
const css = fs.readFileSync('tools/service_tool_web/neo-ui-v400.css','utf8');
const fixes = fs.readFileSync('tools/service_tool_web/neo-ui-v400-fixes.css','utf8');

function assert(value,message){if(!value)throw new Error(message)}

for (const asset of ['neo-ui-v400.css','neo-ui-v400-fixes.css','neo-ui-v400-controls.css','neo-ui-v400.js','neo-ui-v400-hardening.js']) {
  assert(index.includes(asset),`v4 asset missing from index: ${asset}`);
}
for (const preserved of ['usb-attach-v322.js','legacy-compat-v34.js','parity-v35.js','radio-auth-v33.js','app-v31.js']) {
  assert(index.includes(preserved),`critical legacy functional layer was removed: ${preserved}`);
}

const renders = ['renderDashboard','renderNodes','renderDetails','renderLogs','renderFirmware','renderPower','renderProfiles','renderNetwork','renderDisplay','renderTools','renderSettings'];
for (const name of renders) assert(js.includes(`function ${name}`) || js.includes(`async function ${name}`),`v4 page renderer missing: ${name}`);

const pages = ['dashboard','nodes','logs','firmware','power','profiles','network','display','tools','settings'];
for (const page of pages) assert(js.includes(`'${page}'`) || js.includes(`\"${page}\"`),`v4 navigation page missing: ${page}`);

const actionHandlers = ['scan','bulk-log','bulk-ota','log-selected','ota-selected','firmware-check','wake-selected','diagnostic-bundle','serial-flash','capture-profile','apply-profile','save-power','save-position','save-lora','configure-selected','nodes-page','power-page','display-page','tools-page','profiles-page','network-page','live-start','live-stop'];
for (const action of actionHandlers) assert(js.includes(`cmd==='${action}'`) || js.includes(`cmd === '${action}'`),`v4 action has no explicit handler contract: ${action}`);

for (const api of ['/api/state','/api/action','/api/service/action','/api/profile/action','/api/profile/section','/api/radio-authorization','/api/live/action']) {
  assert(js.includes(api),`v4 backend route missing: ${api}`);
}

for (const critical of ['selected_usb_node_id','USB','BLE','Jarnsen 1','Jarnsen 2','frequency_a_mhz','frequency_b_mhz']) {
  assert(js.includes(critical),`v4 critical transport/radio marker missing: ${critical}`);
}

for (const marker of ['.neo-dashboard','.neo-node-table','.neo-details-grid','.neo-logs-grid','.neo-firmware-grid','.neo-power-grid','.neo-profiles','.neo-network-grid','.neo-display-grid','.neo-tools-grid','.neo-settings-grid']) {
  assert(css.includes(marker),`v4 visual marker missing: ${marker}`);
}
assert(fixes.includes('1920x1080 @ 125%') || fixes.includes('125%'), 'v4 scaling fix marker missing');
assert(hardening.includes("scan.dataset.neoAction = 'scan'"),'replacement scan button is not rebound');
assert(hardening.includes('button.neo-tab:not([data-neo-action])'),'decorative tab hardening missing');
assert(hardening.includes('[data-neo-action="noop"]'),'placeholder action hardening missing');
assert(hardening.includes("document.getElementById('themeButton')?.remove()"),'dead dark-theme button is not removed');

console.log(`JARNSEN Service Tool v4 audit OK: ${renders.length} page renderers, ${actionHandlers.length} explicit action contracts, critical USB/profile/radio layers preserved.`);
