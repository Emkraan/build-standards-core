import { fileURLToPath } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  resolve: {
    // The shell packages sit outside the kit folder; their bare imports resolve to the kit's copies.
    dedupe: ['react', 'react-dom', '@azure/msal-browser'],
    alias: { '@shell/kit': fileURLToPath(new URL('./src/index.ts', import.meta.url)) },
  },
  test: {
    environment: 'jsdom',
    include: ['tests/**/*.test.{ts,tsx}'],
    setupFiles: ['tests/setup.ts'],
    restoreMocks: true,
    testTimeout: 20000,
  },
});
