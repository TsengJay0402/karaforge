/**
 * The whole way with real models: create a project by uploading a song with lyrics, watch it
 * being processed, land in the editor, drag one token on the timeline, re-align around it,
 * export a video and check the file that comes out.
 *
 * This downloads nothing by itself but needs the models of the `cpu-lite` profile to be
 * installed, and takes a minute or two of CPU.  It is therefore opt-in:
 *
 *     KARAFORGE_E2E_MODELS=1 npm run e2e -- process
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { expect, test } from '@playwright/test'

import { serverProject, timelinePoint, waitSaved } from './helpers.ts'

const here = path.dirname(fileURLToPath(import.meta.url))
const fixture = path.resolve(here, '..', '..', 'tests', 'fixtures', 'songs', 'zh-2000')

test.skip(process.env.KARAFORGE_E2E_MODELS !== '1', 'needs installed models; set KARAFORGE_E2E_MODELS=1')
test.setTimeout(900_000)

test('upload, process with real models, edit and re-align', async ({ page, request }) => {
  const lyrics = fs.readFileSync(path.join(fixture, 'lyrics.txt'), 'utf-8')
  await page.goto('/new')
  await page.getByTestId('media-input').setInputFiles(path.join(fixture, 'mix_snr10.mp3'))
  await page.getByLabel('歌名').fill('端對端測試')
  await page.getByRole('textbox', { name: '貼上歌詞' }).fill(lyrics)
  await page.getByText('快速', { exact: true }).click()
  await page.getByRole('button', { name: '開始處理' }).click()

  // The processing view names the stages as they run.
  await expect(page).toHaveURL(/\/p\//)
  const id = decodeURIComponent(new URL(page.url()).pathname.split('/').pop() ?? '')
  await expect(page.getByText(/正在處理/)).toBeVisible()
  await expect(page.getByTestId('job-progress')).toBeVisible()
  const seen = new Set<string>()
  const stages = ['讀取媒體', '分離人聲與伴奏', '分析人聲', '語音辨識', '對齊歌詞']
  const deadline = Date.now() + 600_000
  while (!(await page.getByTestId('timeline').isVisible())) {
    for (const stage of stages) {
      if ((await page.locator('.stages .active', { hasText: stage }).count()) > 0) seen.add(stage)
    }
    expect(Date.now(), 'processing takes too long').toBeLessThan(deadline)
    await page.waitForTimeout(250)
  }
  expect(seen.size, `stages seen: ${[...seen].join(', ')}`).toBeGreaterThanOrEqual(2)

  // The editor opens by itself with every token timed.
  await expect(page.getByTestId('preview-canvas')).toHaveAttribute('data-status', 'ready', { timeout: 60_000 })
  const aligned = await serverProject(request, id)
  const tokens = aligned.lines.flatMap((line) => line.tokens)
  expect(tokens.length).toBe(43)
  expect(tokens.every((token) => token.start_ms !== null && token.end_ms !== null)).toBe(true)
  const starts = tokens.map((token) => token.start_ms ?? 0)
  expect([...starts].sort((a, b) => a - b)).toEqual(starts)
  await expect(page.getByTestId('stats')).toContainText('43/43')

  // Drag one token on the timeline: it moves and becomes a locked anchor.
  const before = aligned.lines[1]!.tokens[4]!
  await page.getByTestId('token-1-4').click()
  const from = await timelinePoint(page, ((before.start_ms ?? 0) + (before.end_ms ?? 0)) / 2, 1)
  await page.mouse.move(from.x, from.y)
  await page.mouse.down()
  await page.mouse.move(from.x + 12, from.y, { steps: 3 })
  await page.mouse.move(from.x + 24, from.y, { steps: 3 })
  await page.mouse.up()
  await waitSaved(page)
  const dragged = (await serverProject(request, id)).lines[1]!.tokens[4]!
  expect(dragged.locked).toBe(true)
  expect(dragged.source).toBe('manual')
  expect(dragged.start_ms).toBeGreaterThan(before.start_ms ?? 0)

  // Re-align: the editor is read-only meanwhile, then takes the new times.
  await page.getByRole('button', { name: '重新對齊' }).click()
  await page.getByTestId('realign-all').click()
  await expect(page.getByText('背景工作執行中')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByText('背景工作執行中')).toBeHidden({ timeout: 300_000 })
  const realigned = await serverProject(request, id)
  const anchor = realigned.lines[1]!.tokens[4]!
  // The dragged token is exactly where it was put; the others were aligned again.
  expect(anchor).toMatchObject({ start_ms: dragged.start_ms, end_ms: dragged.end_ms, locked: true })
  expect(realigned.revision).toBeGreaterThan(aligned.revision)
  const realignedTokens = realigned.lines.flatMap((line) => line.tokens)
  expect(realignedTokens.every((token) => token.start_ms !== null)).toBe(true)
  // The editor shows what the server has now.
  await page.getByTestId('token-1-4').click()
  await expect(page.getByTestId('token-start')).toHaveValue(String(dragged.start_ms))
  await expect(page.getByTestId('save-state')).toHaveText('已儲存')

  // Export a video from the dialog and check the file.
  await page.getByTestId('open-export').click()
  await page.getByTestId('export-format').selectOption('mp4')
  await page.getByTestId('export-start').click()
  const exported = page.getByTestId('export-files').getByText('端對端測試.mp4')
  await expect(exported).toBeVisible({ timeout: 300_000 })
  const listing = (await (await request.get(`/api/projects/${encodeURIComponent(id)}/exports`)).json()) as {
    exports: { name: string; url: string; bytes: number }[]
  }
  const video = listing.exports.find((item) => item.name === '端對端測試.mp4')
  expect(video).toBeDefined()
  expect(video!.bytes).toBeGreaterThan(200_000)
  const head = await request.get(video!.url, { headers: { Range: 'bytes=0-11' } })
  expect(head.status()).toBe(206)
  // An MP4 file starts with a box whose type is "ftyp".
  expect((await head.body()).subarray(4, 8).toString('latin1')).toBe('ftyp')
  await page.keyboard.press('Escape')

  // Clean up: the project is deleted from the list.
  await page.goto('/')
  page.once('dialog', (dialog) => void dialog.accept())
  await page.getByTestId(`project-${id}`).getByRole('button', { name: '刪除' }).click()
  await expect(page.getByTestId(`project-${id}`)).toHaveCount(0)
})
