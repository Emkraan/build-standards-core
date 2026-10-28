// a tab left open across a deploy keeps running the old bundle against the new API. On
// 2026-10-22 a pre-bundle rendered a PR sign-off card as a non-PR card ("Written from
// undefined", "Real source" twice). Every few minutes this reads index.html, compares its entry script
// with the one this tab loaded, and reloads once they differ, at a moment that loses nothing: the tab is
// hidden, or nothing is being typed and no dialog is open.
const CHECK_MS = 3 * 60_000
const RETRY_MS = 30_000
const ENTRY_RE = /<script[^>]*type="module"[^>]*src="([^"]+)"/

function entryPath(src: string): string {
  return new URL(src, window.location.href).pathname
}

function loadedEntry(): string | null {
  const el = document.querySelector<HTMLScriptElement>('script[type="module"][src]')
  return el ? entryPath(el.src) : null
}

async function servedEntry(): Promise<string | null> {
  const res = await fetch(new URL('index.html', document.baseURI).toString(), { cache: 'no-store' })
  if (!res.ok) return null
  const m = ENTRY_RE.exec(await res.text())
  return m ? entryPath(m[1]) : null
}

function safeToReload(): boolean {
  if (document.visibilityState === 'hidden') return true
  const a = document.activeElement as HTMLElement | null
  const typing = !!a && (a.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(a.tagName))
  const dialog = document.querySelector('dialog[open], [role="dialog"], [role="alertdialog"]')
  return !typing && !dialog
}

export function watchStaleBundle(): void {
  const mine = loadedEntry()
  if (!import.meta.env.PROD || !mine) return
  let stale = false
  const tryReload = () => {
    if (safeToReload()) window.location.reload()
  }
  const check = async () => {
    if (stale) return tryReload()
    try {
      const served = await servedEntry()
      if (served && served !== mine) {
        stale = true
        tryReload()
      }
    } catch {
      // A failed read is not a new version. The next check tries again.
    }
  }
  window.setInterval(() => void check(), CHECK_MS)
  window.setInterval(() => {
    if (stale) tryReload()
  }, RETRY_MS)
  document.addEventListener('visibilitychange', () => void check())
}
