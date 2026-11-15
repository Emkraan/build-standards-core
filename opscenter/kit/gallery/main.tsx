/* Gallery entry. Import order is the contract every app follows: tokens.css, then hub-layer.css,
   then kit.css. Release notes come from scripts/gen-changelog.mjs (npm run gallery:changelog).
   The visual gate loads the page with ?gate. The build card then shows the fixed sample notes and
   version instead of git history, so screenshots do not change with every commit. The gate also
   freezes the clock and forces reduced motion from the browser side (kit/visual). */

import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '../../tokens/tokens.css';
import '../../tokens/hub-layer.css';
import '../src/styles/kit.css';
import '../src/graph/graph.css';
import '../src/api-reference/api-reference.css';
import './gallery.css';
import { GalleryApp, SAMPLE_RELEASES } from './App';
import kitPackage from '../package.json';
import type { ReleaseNote } from '../src/index';

const generated = import.meta.glob<ReleaseNote[]>('./generated/changelog.json', { eager: true, import: 'default' });
const gate = new URLSearchParams(window.location.search).has('gate');
const releases = gate ? SAMPLE_RELEASES : (Object.values(generated)[0] ?? []);
const version = gate ? '0.0.0' : kitPackage.version;

const root = document.getElementById('root');
if (root) {
  createRoot(root).render(
    <StrictMode>
      <GalleryApp releases={releases} version={version} />
    </StrictMode>,
  );
}
