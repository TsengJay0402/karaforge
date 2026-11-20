/**
 * Takes the screenshots used in the README (docs/images/).  Not a test of anything: run it on
 * purpose with
 *
 *     KARAFORGE_E2E_SHOTS=1 npm run e2e -- screenshots
 */
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { expect, test } from '@playwright/test'

import { openEditor, seek } from './helpers.ts'

const images = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'docs', 'images')

test.skip(process.env.KARAFORGE_E2E_SHOTS !== '1', 'set KARAFORGE_E2E_SHOTS=1 to take the README screenshots')
test.use({ viewport: { width: 1440, height: 900 } })

test('screenshots for the documentation', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByTestId('project-demo')).toBeVisible()
  const thumbnail = page.getByTestId('project-clip').locator('img')
  await expect.poll(() => thumbnail.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(100)
  await page.screenshot({ path: path.join(images, 'project-list.png') })

  await openEditor(page, 'demo')
  await page.getByTestId('token-0-3').click()
  await seek(page, 6200)
  await page.waitForTimeout(1200)
  await page.screenshot({ path: path.join(images, 'editor.png') })

  await page.getByRole('button', { name: '主題', exact: true }).click()
  await expect(page.getByTestId('theme-panel')).toBeVisible()
  await page.waitForTimeout(500)
  await page.screenshot({ path: path.join(images, 'editor-theme.png') })

  await page.goto('/new')
  await expect(page.getByRole('button', { name: '開始處理' })).toBeVisible()
  await page.screenshot({ path: path.join(images, 'new-project.png') })
})
