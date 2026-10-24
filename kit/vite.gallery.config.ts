import { fileURLToPath } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

const kitDir = fileURLToPath(new URL('.', import.meta.url));
const repoDir = fileURLToPath(new URL('..', import.meta.url));

// The gallery is a small Vite app that renders every kit component on one page. It imports the
// token sheets from the repo root, so the dev server may read one level above the kit.
export default defineConfig({
  root: fileURLToPath(new URL('./gallery', import.meta.url)),
  base: './',
  plugins: [react()],
  server: {
    fs: { allow: [kitDir, repoDir] },
  },
  build: {
    outDir: fileURLToPath(new URL('./dist-gallery', import.meta.url)),
    emptyOutDir: true,
  },
});
