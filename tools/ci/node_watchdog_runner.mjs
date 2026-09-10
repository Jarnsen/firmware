import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import util from 'node:util';
import { pathToFileURL } from 'node:url';

const [scriptArg, timeoutArg = '150', labelArg = 'node-ci'] = process.argv.slice(2);
if (!scriptArg) {
  console.error('Usage: node_watchdog_runner.mjs <script> <timeout-seconds> <label>');
  process.exit(2);
}

const timeoutSeconds = Math.max(1, Number.parseInt(timeoutArg, 10) || 150);
const label = labelArg || path.basename(scriptArg);
const safe = label.replace(/[^A-Za-z0-9_.-]/g, '_');
const logDir = path.resolve('ci-logs');
fs.mkdirSync(logDir, { recursive: true });
const stdoutLog = path.join(logDir, `browser-${safe}.out.log`);
const stderrLog = path.join(logDir, `browser-${safe}.err.log`);
fs.writeFileSync(stdoutLog, '');
fs.writeFileSync(stderrLog, '');

const originalLog = console.log.bind(console);
const originalWarn = console.warn.bind(console);
const originalError = console.error.bind(console);
const render = args => `${util.format(...args)}\n`;
console.log = (...args) => {
  try { fs.appendFileSync(stdoutLog, render(args)); } catch {}
  originalLog(...args);
};
console.warn = (...args) => {
  try { fs.appendFileSync(stderrLog, render(args)); } catch {}
  originalWarn(...args);
};
console.error = (...args) => {
  try { fs.appendFileSync(stderrLog, render(args)); } catch {}
  originalError(...args);
};

const scriptPath = path.resolve(scriptArg);
if (!fs.existsSync(scriptPath)) {
  console.error(`CI script not found: ${scriptArg}`);
  process.exit(2);
}

const started = Date.now();
console.log(`=== START ${label} ===`);
console.log(`Script: ${scriptArg}`);
console.log(`Timeout: ${timeoutSeconds}s`);

const watchdog = setTimeout(() => {
  const elapsed = Math.round((Date.now() - started) / 1000);
  console.error(`::error::${label} exceeded hard timeout after ${elapsed}s. Forcing Node exit.`);
  process.exit(124);
}, timeoutSeconds * 1000);

try {
  await import(`${pathToFileURL(scriptPath).href}?ci_run=${Date.now()}`);
  clearTimeout(watchdog);
  const elapsed = Math.round((Date.now() - started) / 1000);
  console.log(`=== OK ${label} (${elapsed}s) ===`);
  process.exit(0);
} catch (error) {
  clearTimeout(watchdog);
  const elapsed = Math.round((Date.now() - started) / 1000);
  console.error(error?.stack || error);
  console.error(`::error::${label} failed after ${elapsed}s.`);
  process.exit(1);
}
