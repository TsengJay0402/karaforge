/// <reference types="vitest/config" />
import { fileURLToPath } from 'node:url'

import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'

const apiTarget = process.env.KARAFORGE_API ?? 'http://127.0.0.1:8765'

/** An identifier that only exists in the GPL-licensed `rvfc-polyfill` package. */
const GPL_POLYFILL_MARKER = '_rvfcpolyfillmap'

/**
 * Fail the build if the GPL-licensed polyfill is in the output.
 *
 * JASSUB imports `rvfc-polyfill` (GPL-3.0); the alias below replaces it with an empty module
 * (`src/shims/rvfc-polyfill.ts` explains why that is safe).  Should an upgrade ever import
 * it by another path, the distributed bundle must not silently pick it up again.
 */
function forbidGplPolyfill(): Plugin {
  return {
    name: 'karaforge:forbid-gpl-polyfill',
    generateBundle(_options, bundle) {
      for (const [fileName, output] of Object.entries(bundle)) {
        const text =
          output.type === 'chunk'
            ? output.code
            : typeof output.source === 'string'
              ? output.source
              : ''
        if (text.includes(GPL_POLYFILL_MARKER)) {
          this.error(
            `${fileName} contains code from the GPL-licensed rvfc-polyfill package; ` +
              'check the alias in vite.config.ts.',
          )
        }
      }
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), forbidGplPolyfill()],
  resolve: {
    alias: {
      'rvfc-polyfill': fileURLToPath(new URL('./src/shims/rvfc-polyfill.ts', import.meta.url)),
    },
  },
  server: {
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: false,
  },
})
