import { ShortcutLayer, ThemeProvider, Toaster } from '@kit'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { HashRouter } from 'react-router-dom'
// Core token sheet, then the hub recipes and the kit's base styles, then the app's own CSS
// (index.css here, App.css, shell.css and the page sheets through App.tsx and the pages) so app
// rules win ties.
import './layers.css'
import '../../../tokens/tokens.css'
import '../../../tokens/hub-layer.css'
import '@kit/styles/kit.css'
import './index.css'
import App from './App.tsx'
import { watchStaleBundle } from './lib/staleBundle'

const rootEl = document.getElementById('root')
if (!rootEl) throw new Error('missing #root element')
// Theme: light, dark or the OS (kit key shell.theme, applied before paint by the script in
// index.html). The accent is set once on <html> as data-app-accent="indigo".
createRoot(rootEl).render(
  <StrictMode>
    <ThemeProvider>
      <ShortcutLayer>
        <HashRouter>
          <Toaster>
            <App />
          </Toaster>
        </HashRouter>
      </ShortcutLayer>
    </ThemeProvider>
  </StrictMode>,
)
watchStaleBundle()
