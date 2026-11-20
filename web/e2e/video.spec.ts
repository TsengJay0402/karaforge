import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { type APIRequestContext, expect, test } from '@playwright/test'

import { now, openEditor, seek } from './helpers.ts'

const here = path.dirname(fileURLToPath(import.meta.url))
const repo = path.resolve(here, '..', '..')
const python = process.env.KARAFORGE_E2E_PYTHON ?? path.join(repo, '.venv', 'bin', 'python')
const workspace = path.join(repo, '.pytest_tmp', 'e2e-workspace')

interface JobData {
  id: string
  state: string
  error: { message_en: string; detail: string | null } | null
  result: { file: string } | null
}

async function waitJob(request: APIRequestContext, id: string, timeoutMs: number): Promise<JobData> {
  const deadline = Date.now() + timeoutMs
  for (;;) {
    const body = (await (await request.get(`/api/jobs/${id}`)).json()) as { job: JobData }
    if (!['queued', 'running'].includes(body.job.state)) return body.job
    if (Date.now() > deadline) throw new Error(`job ${id} is still ${body.job.state}`)
    await new Promise((resolve) => setTimeout(resolve, 500))
  }
}

interface Box {
  left: number
  right: number
  top: number
  bottom: number
  share: number
}

interface Measured {
  size: [number, number]
  sung: Box | null
  unsung: Box | null
}

test('a video project shows its thumbnail and plays its picture in step with the audio', async ({ page }) => {
  await page.goto('/')
  const thumbnail = page.getByTestId('project-clip').locator('img')
  await expect(thumbnail).toBeVisible()
  await expect.poll(() => thumbnail.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(100)

  await openEditor(page, 'clip')
  const video = page.locator('.preview-stage video')
  await expect(video).toHaveCount(1)
  await page.getByTestId('play').click()
  await expect.poll(() => now(page), { timeout: 15_000 }).toBeGreaterThan(1200)
  const drift = await video.evaluate(
    (element: HTMLVideoElement) => Math.abs(element.currentTime * 1000 - (window.karaforge?.now() ?? 0)),
  )
  expect(drift).toBeLessThan(250)
  expect(await video.evaluate((element: HTMLVideoElement) => element.muted)).toBe(true)
  // The token under the playhead is highlighted in the lyrics.
  await expect(page.locator('.token.playing')).toHaveCount(1)
  await page.getByTestId('play').click()
  const stopped = await now(page)
  await page.waitForTimeout(400)
  expect(await now(page)).toBe(stopped)

  // Switching the mix keeps the place.
  await page.getByTestId('audio-mode').selectOption('vocals')
  expect(Math.abs((await now(page)) - stopped)).toBeLessThan(60)
})

test('the preview shows the same picture as the exported video', async ({ page, request }) => {
  // 6.2 s is exactly frame 186 at 30 fps; the fourth token of the first line (6170-6278 ms)
  // is then partly filled.
  const timeMs = 6200
  await openEditor(page, 'demo')
  await seek(page, timeMs)
  await page.waitForTimeout(600)
  const shot = path.join(workspace, 'preview-shot.png')
  await page.getByTestId('preview-stage').screenshot({ path: shot })

  const started = (await (
    await request.post('/api/projects/demo/exports', {
      data: { format: 'mp4', audio: 'instrumental', resolution: [960, 540], background: 'color', name: 'e2e-compare' },
    })
  ).json()) as { job: JobData }
  const job = await waitJob(request, started.job.id, 240_000)
  expect(job.error?.detail ?? job.error?.message_en ?? job.state).toBe('done')
  const video = path.join(workspace, 'demo.kfproj', 'exports', 'e2e-compare.mp4')
  expect(fs.existsSync(video)).toBe(true)

  const output = execFileSync(python, [
    path.join(here, 'compare_frames.py'),
    '--preview', shot,
    '--video', video,
    '--time', String(timeMs / 1000),
    '--sung', '#2F7BFF',
    '--unsung', '#FFFFFF',
  ], { encoding: 'utf-8' })
  const measured = JSON.parse(output.trim().split('\n').at(-1) ?? '{}') as { preview: Measured; video: Measured }
  const { preview, video: frame } = measured
  expect(preview.sung, 'sung colour in the preview').not.toBeNull()
  expect(frame.sung, 'sung colour in the video').not.toBeNull()
  expect(preview.unsung).not.toBeNull()
  expect(frame.unsung).not.toBeNull()
  // The fill has reached the same place: left and right edge of the sung colour agree to
  // within 1 % of the picture width, the rows to within 1.5 % of its height.
  for (const key of ['left', 'right'] as const) {
    expect(Math.abs(preview.sung![key] - frame.sung![key]), `sung ${key}`).toBeLessThan(0.01)
    expect(Math.abs(preview.unsung![key] - frame.unsung![key]), `unsung ${key}`).toBeLessThan(0.012)
  }
  for (const key of ['top', 'bottom'] as const) {
    expect(Math.abs(preview.sung![key] - frame.sung![key]), `sung ${key}`).toBeLessThan(0.015)
    expect(Math.abs(preview.unsung![key] - frame.unsung![key]), `unsung ${key}`).toBeLessThan(0.015)
  }
  // And the fill really is in the middle of the line, not at one of its ends.
  expect(frame.sung!.right - frame.sung!.left).toBeGreaterThan(0.05)
  expect(frame.unsung!.right).toBeGreaterThan(frame.sung!.right + 0.1)
})
