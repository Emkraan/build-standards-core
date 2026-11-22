// One headless browser for a whole test run, and one fresh tab per test. A test used to launch its own Chrome (about 50 launches for the three browser
// test files), which on a developer's desktop opens and closes windows all day and takes the keyboard focus. Now the first test launches ONE instance,
// every later test opens a tab in it and closes the tab at the end, and a single after() hook kills the browser's process group and deletes its profile.
// Run through tests/browser.test.mjs, the three files share the one instance; run alone, each file launches its own, once.
import { spawn } from 'node:child_process'
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { after } from 'node:test'
import { chromeArgs } from './browserGate.mjs'

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
let shared = null

async function launch(chromePath) {
  const profile = mkdtempSync(join(tmpdir(), 'oc-browser-'))
  const port = 9300 + Math.floor(Math.random() * 600)
  // Own process group, so the cleanup can stop the browser's helper processes too, not only the parent.
  const child = spawn(chromePath, chromeArgs({ port, profile }), { stdio: 'ignore', detached: true })
  const exited = new Promise((r) => child.once('exit', r))
  return { child, exited, profile, port }
}

/** The one browser, launched on first use. */
export function sharedBrowser(chromePath) {
  shared ??= launch(chromePath)
  return shared
}

/** A new blank tab in the shared browser: its id and the address of its DevTools socket. */
export async function openTab(browser) {
  for (let i = 0; i < 60; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${browser.port}/json/new?about:blank`, { method: 'PUT' })
      if (res.ok) {
        const t = await res.json()
        return { id: t.id, wsUrl: t.webSocketDebuggerUrl }
      }
    } catch {}
    await sleep(250)
  }
  throw new Error('headless Chrome did not open a tab')
}

export async function closeTab(browser, id) {
  try {
    await fetch(`http://127.0.0.1:${browser.port}/json/close/${id}`)
  } catch {}
}

/** Kill the browser and its helpers and delete its profile. Safe to call twice. */
export async function stopBrowser() {
  if (!shared) return
  const p = shared
  shared = null
  const b = await p
  try {
    process.kill(-b.child.pid, 'SIGKILL')
  } catch {
    b.child.kill('SIGKILL')
  }
  await Promise.race([b.exited, sleep(5000)])
  // A helper can still be flushing the profile for a moment; a leftover temp folder is reported, not a failure of the behaviour under test.
  try {
    rmSync(b.profile, { recursive: true, force: true, maxRetries: 20, retryDelay: 100 })
  } catch (e) {
    console.warn(`could not remove the browser profile ${b.profile}: ${e.code || e.message}`)
  }
}

// Registered once per process, whichever file imports this first. The exit hook covers a crash or a Ctrl-C between tests.
after(stopBrowser)
process.on('exit', () => {
  if (shared) shared.then((b) => { try { process.kill(-b.child.pid, 'SIGKILL') } catch {} })
})
