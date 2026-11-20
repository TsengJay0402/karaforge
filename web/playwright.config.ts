import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { defineConfig } from '@playwright/test'

/**
 * Browser tests against the real server.
 *
 * The server is started on a workspace that `e2e/make_workspace.py` builds without running
 * any model (it needs ffmpeg, like the engine itself).  Build the web app first:
 * `npm run build && npm run e2e`.
 *
 * Environment:
 *   KARAFORGE_E2E_PYTHON   Python of the environment that has KaraForge (default ../.venv)
 *   KARAFORGE_E2E_PORT     Port for the test server (default 18765)
 */
const here = path.dirname(fileURLToPath(import.meta.url))
const repo = path.resolve(here, '..')
const python = process.env.KARAFORGE_E2E_PYTHON ?? path.join(repo, '.venv', 'bin', 'python')
const port = Number(process.env.KARAFORGE_E2E_PORT ?? 18765)
export const workspace = path.join(repo, '.pytest_tmp', 'e2e-workspace')
const builder = path.join(here, 'e2e', 'make_workspace.py')

export default defineConfig({
  testDir: './e2e',
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  outputDir: 'test-results',
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    viewport: { width: 1440, height: 900 },
    locale: 'zh-TW',
    trace: 'retain-on-failure',
  },
  webServer: {
    command: `"${python}" "${builder}" "${workspace}" && "${python}" -m karaforge.cli serve --workspace "${workspace}" --port ${port}`,
    url: `http://127.0.0.1:${port}/api/health`,
    reuseExistingServer: false,
    timeout: 180_000,
    env: { KARAFORGE_WEB_DIST: path.join(here, 'dist'), KARAFORGE_LANG: 'zh' },
  },
})
