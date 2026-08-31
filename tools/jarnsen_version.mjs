#!/usr/bin/env node

import fs from "node:fs";
import { execFileSync } from "node:child_process";

const config = JSON.parse(fs.readFileSync("VERSION.json", "utf8"));
const required = ["major", "minor", "patch", "channel", "start_date", "start_sequence", "timezone"];
for (const key of required) {
  if (!(key in config)) {
    console.error(`VERSION.json missing key: ${key}`);
    process.exit(1);
  }
}

function localDate(iso, timeZone) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date(iso));
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

const base = `v${Number(config.major)}.${Number(config.minor)}.${Number(config.patch)}`;
const channel = String(config.channel).trim().toLowerCase();
let version = base;
let workDays = [];

if (!["", "final", "stable", "release"].includes(channel)) {
  if (!["alpha", "beta", "rc"].includes(channel)) {
    console.error("VERSION.json channel must be alpha, beta, rc or final");
    process.exit(1);
  }

  const history = execFileSync("git", ["log", "--format=%cI", "HEAD"], { encoding: "utf8" });
  const days = new Set();
  for (const raw of history.split(/\r?\n/)) {
    const value = raw.trim();
    if (!value) continue;
    const day = localDate(value, String(config.timezone));
    if (day >= String(config.start_date)) days.add(day);
  }
  workDays = [...days].sort();
  if (workDays.length === 0) {
    console.error(`No commits found on or after version start date ${config.start_date}`);
    process.exit(1);
  }

  const sequence = Number(config.start_sequence) + workDays.length - 1;
  if (!Number.isInteger(sequence) || sequence < 1) {
    console.error("Resolved prerelease sequence must be >= 1");
    process.exit(1);
  }
  version = `${base}-${channel}.${sequence}`;
}

if (process.argv.includes("--json")) {
  console.log(JSON.stringify({
    version,
    channel: config.channel,
    start_date: config.start_date,
    timezone: config.timezone,
    work_days: workDays,
  }, null, 2));
} else {
  console.log(version);
}
