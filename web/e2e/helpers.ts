import { type APIRequestContext, expect, type Page } from '@playwright/test'

export interface TokenData {
  text: string
  start_ms: number | null
  end_ms: number | null
  locked: boolean
  source: string
  ruby: string | null
  ruby_source: 'auto' | 'manual' | null
}

export interface ProjectData {
  revision: number
  lines: { id: string; singer: string; tokens: TokenData[] }[]
  style: { theme: string; overrides: Record<string, unknown> }
}

/** The project as the server has it stored. */
export async function serverProject(request: APIRequestContext, id: string): Promise<ProjectData> {
  const response = await request.get(`/api/projects/${id}`)
  expect(response.ok()).toBe(true)
  const body = (await response.json()) as { project: ProjectData }
  return body.project
}

/** Open the editor of a project and wait until the subtitle renderer is running. */
export async function openEditor(page: Page, id: string): Promise<void> {
  await page.goto(`/p/${id}`)
  await expect(page.getByTestId('timeline')).toBeVisible()
  await expect(page.getByTestId('preview-canvas')).toHaveAttribute('data-status', 'ready', {
    timeout: 30_000,
  })
}

/** Wait until the editor says everything is saved. */
export async function waitSaved(page: Page): Promise<void> {
  await expect(page.getByTestId('save-state')).toHaveText('已儲存')
}

export async function seek(page: Page, timeMs: number): Promise<void> {
  await page.evaluate((time) => window.karaforge?.seek(time), timeMs)
}

export async function now(page: Page): Promise<number> {
  return page.evaluate(() => window.karaforge?.now() ?? -1)
}

/** Page coordinates of a time on a token row of the timeline canvas. */
export async function timelinePoint(page: Page, timeMs: number, row: 0 | 1): Promise<{ x: number; y: number }> {
  const canvas = page.getByTestId('timeline')
  const box = await canvas.boundingBox()
  if (!box) throw new Error('the timeline is not visible')
  const startMs = Number(await canvas.getAttribute('data-start-ms'))
  const pxPerSec = Number(await canvas.getAttribute('data-px-per-sec'))
  const rowsTop = Number(await canvas.getAttribute('data-rows-top'))
  const rowHeight = Number(await canvas.getAttribute('data-row-height'))
  const rowGap = Number(await canvas.getAttribute('data-row-gap'))
  return {
    x: box.x + ((timeMs - startMs) / 1000) * pxPerSec,
    y: box.y + rowsTop + row * (rowHeight + rowGap) + rowHeight / 2,
  }
}

declare global {
  interface Window {
    karaforge?: {
      seek: (timeMs: number) => void
      now: () => number
      play: () => Promise<void>
      pause: () => void
    }
  }
}
