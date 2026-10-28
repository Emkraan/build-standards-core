import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Build stamps for the sidebar build card (web-ui.md section 6): version from package.json, the
// commit (GITHUB_SHA in CI, else the local HEAD) and the build time.
const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8')) as { version?: string }
function buildSha(): string {
  if (process.env.GITHUB_SHA) return process.env.GITHUB_SHA.slice(0, 7)
  try {
    return execFileSync('git', ['rev-parse', '--short', 'HEAD'], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim()
  } catch {
    return ''
  }
}

// Base is relative so the built app works whether served by the Ops Center
// static server or opened from a file path. No external CDNs; everything bundles.
// @kit points at the synced build-standards-core React kit (kit-core/, never hand-edited).
export default defineConfig({
  base: './',
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version || '0.0.0'),
    __BUILD_SHA__: JSON.stringify(buildSha()),
    __BUILD_TIME__: JSON.stringify(new Date().toISOString()),
  },
  resolve: {
    alias: {
      '@kit': fileURLToPath(new URL('../../kit/src', import.meta.url)),
    },
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1200,
    // web-client-runtime.md 4.3: assets above 4 KB become hashed files, never base64 in the script.
    assetsInlineLimit: 4096,
    rollupOptions: {
      output: {
        // web-client-runtime.md 4.2: the framework builds into its own named chunk so an app-only
        // release keeps its hash. This app has no auth library (the shell sits behind the platform
        // sign-in), so there is no auth chunk to name. The chart library stays out of the manual
        // chunks on purpose: naming it pulled it into the first load (241 KB gzip against 139 KB).
        manualChunks(id: string) {
          if (!id.includes('/node_modules/')) return undefined
          if (/\/node_modules\/(react|react-dom|react-router|react-router-dom|scheduler)\//.test(id)) return 'vendor-react'
          return undefined
        },
      },
    },
  },
})
