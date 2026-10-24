#!/usr/bin/env node
/*
 * overflow-probe.mjs: the rendered check for web-ui.md rule 0.10 (content stays inside its box).
 *
 * Usage (from kit/, against any running app):
 *   node scripts/overflow-probe.mjs <out.json> <widths> <name>=<url> [<name>=<url> ...]
 *   node scripts/overflow-probe.mjs out.json 1440,1024 home=http://127.0.0.1:5173/ list=http://127.0.0.1:5173/list
 *
 * It drives a browser that is already running with a DevTools endpoint (PROBE_CDP, default
 * http://127.0.0.1:9222) and never starts one, so a signed-in session works as it is. Each page
 * opens in a new tab, loads at the first width, settles (PROBE_SETTLE ms, default 5000), then the
 * detector in visual/overflow.ts runs at every width in turn. It only reads pages. Findings print
 * per page and the full result is written to <out.json>.
 *
 * Needs Node 22.18 or later (it imports the TypeScript detector with built-in type stripping).
 * Exit codes: 0 no finding, 1 findings, 2 bad arguments or the browser could not be reached.
 */
import { writeFileSync } from 'node:fs';
import { findOverflow } from '../visual/overflow.ts';

const [outFile, widthsCsv, ...pages] = process.argv.slice(2);
const widths = (widthsCsv ?? '').split(',').map(Number).filter((w) => w > 0);
if (!outFile || !widths.length || !pages.length || pages.some((p) => !p.includes('='))) {
  console.error('usage: overflow-probe.mjs <out.json> <widths csv> <name>=<url> ...');
  process.exit(2);
}
const CDP = process.env.PROBE_CDP || 'http://127.0.0.1:9222';
const SETTLE = Number(process.env.PROBE_SETTLE || 5000);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const DETECT = `(${findOverflow.toString()})()`;

async function probe(name, url) {
  const tab = await (await fetch(`${CDP}/json/new?about:blank`, { method: 'PUT' })).json();
  const ws = new WebSocket(tab.webSocketDebuggerUrl);
  let seq = 0;
  const pending = new Map();
  ws.addEventListener('message', (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  });
  await new Promise((r) => ws.addEventListener('open', r));
  const send = (method, params = {}) => new Promise((r) => {
    seq += 1; pending.set(seq, r); ws.send(JSON.stringify({ id: seq, method, params }));
  });
  const results = [];
  try {
    await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] });
    await send('Page.enable');
    for (const [i, width] of widths.entries()) {
      await send('Emulation.setDeviceMetricsOverride', { width, height: 900, deviceScaleFactor: 1, mobile: false });
      if (i === 0) { await send('Page.navigate', { url }); await sleep(SETTLE); } else await sleep(1000);
      const r = await send('Runtime.evaluate', { expression: DETECT, returnByValue: true });
      const value = r.result?.result?.value;
      if (!Array.isArray(value)) throw new Error(`detector failed on ${url}: ${JSON.stringify(r.result?.exceptionDetails ?? r).slice(0, 300)}`);
      results.push({ width, findings: value });
    }
  } finally {
    ws.close();
    await fetch(`${CDP}/json/close/${tab.id}`);
  }
  return { name, url, results };
}

const all = [];
let total = 0;
try {
  for (const page of pages) {
    const at = page.indexOf('=');
    const r = await probe(page.slice(0, at), page.slice(at + 1));
    all.push(r);
    for (const { width, findings } of r.results) {
      total += findings.length;
      for (const f of findings) console.log(`${r.name} @${width} ${f.kind} +${f.over}px ${f.box} "${f.text}"`);
    }
    writeFileSync(outFile, `${JSON.stringify(all, null, 1)}\n`);
  }
} catch (err) {
  console.error(String(err instanceof Error ? err.message : err));
  process.exit(2);
}
console.log(`overflow-probe: ${pages.length} page(s), ${widths.length} width(s), ${total} finding(s)`);
process.exit(total ? 1 : 0);
