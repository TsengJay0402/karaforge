import { expect, test } from '@playwright/test'

import { openEditor, serverProject, timelinePoint, waitSaved } from './helpers.ts'

// The tests share one project on the server; each one leaves the document as it found it
// or changes a part that no later test looks at.
test.describe.configure({ mode: 'serial' })

test('the list shows the projects and opens the editor', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '我的專案' })).toBeVisible()
  const card = page.getByTestId('project-demo')
  await expect(card.getByRole('heading', { name: '示範歌曲' })).toBeVisible()
  await expect(card.getByText('已對齊')).toBeVisible()
  await expect(card.getByText('4 行 / 43 字')).toBeVisible()
  await card.getByRole('link').click()
  await expect(page).toHaveURL(/\/p\/demo$/)
  await expect(page.getByTestId('preview-canvas')).toHaveAttribute('data-status', 'ready', {
    timeout: 30_000,
  })
  await expect(page.getByTestId('token-0-0')).toHaveText('車')
  await expect(page.getByTestId('stats')).toContainText('43/43')
})

test('a typed start time is saved automatically and can be undone', async ({ page, request }) => {
  await openEditor(page, 'demo')
  await page.getByTestId('token-0-3').click()
  await expect(page.getByTestId('clock')).toContainText('00:06.170')
  const start = page.getByTestId('token-start')
  await expect(start).toHaveValue('6170')
  await start.fill('6120')
  await waitSaved(page)
  let line = (await serverProject(request, 'demo')).lines[0]!
  expect(line.tokens[3]).toMatchObject({ start_ms: 6120, locked: true, source: 'manual' })
  // The token before it ended after the new start, so it was cut back.
  expect(line.tokens[2]!.end_ms).toBeLessThanOrEqual(6120)

  await page.getByRole('button', { name: /復原/ }).click()
  await expect(start).toHaveValue('6170')
  await waitSaved(page)
  line = (await serverProject(request, 'demo')).lines[0]!
  expect(line.tokens[3]).toMatchObject({ start_ms: 6170, locked: false, source: 'auto' })
})

test('arrow keys nudge the selected token', async ({ page, request }) => {
  await openEditor(page, 'demo')
  const before = (await serverProject(request, 'demo')).lines[1]!.tokens[0]!
  await page.getByTestId('token-1-0').click()
  await page.keyboard.press('ArrowRight')
  await page.keyboard.press('ArrowRight')
  await page.keyboard.press('Shift+ArrowLeft')
  await waitSaved(page)
  const after = (await serverProject(request, 'demo')).lines[1]!.tokens[0]!
  expect(after.start_ms).toBe(before.start_ms! + 10 + 10 - 50)
  // The token runs straight into the next one: its end stays attached to it.
  expect(after.end_ms).toBe((await serverProject(request, 'demo')).lines[1]!.tokens[1]!.start_ms)
  expect(after.locked).toBe(true)
  // All of it is one undo step away (the nudges were folded together).
  await page.keyboard.press('Control+z')
  await waitSaved(page)
  expect((await serverProject(request, 'demo')).lines[1]!.tokens[0]!.start_ms).toBe(before.start_ms)
})

test('dragging a block on the timeline moves the token', async ({ page, request }) => {
  await openEditor(page, 'demo')
  const before = (await serverProject(request, 'demo')).lines[0]!.tokens[10]!
  // Bring the token into view by going to it, then drag its body 60 px to the right.
  await page.getByTestId('token-0-10').click()
  const middle = (before.start_ms! + before.end_ms!) / 2
  const from = await timelinePoint(page, middle, 0)
  await page.mouse.move(from.x, from.y)
  await page.mouse.down()
  await page.mouse.move(from.x + 30, from.y, { steps: 3 })
  await page.mouse.move(from.x + 60, from.y, { steps: 3 })
  await page.mouse.up()
  await waitSaved(page)
  const pxPerSec = Number(await page.getByTestId('timeline').getAttribute('data-px-per-sec'))
  const expected = before.start_ms! + (60 / pxPerSec) * 1000
  const after = (await serverProject(request, 'demo')).lines[0]!.tokens[10]!
  expect(Math.abs(after.start_ms! - expected)).toBeLessThanOrEqual(20)
  expect(after.end_ms! - after.start_ms!).toBe(before.end_ms! - before.start_ms!)
  await page.keyboard.press('Control+z')
  await waitSaved(page)
  expect((await serverProject(request, 'demo')).lines[0]!.tokens[10]!.start_ms).toBe(before.start_ms)
})

test('editing the text keeps the timing of the tokens that are still there', async ({ page, request }) => {
  await openEditor(page, 'demo')
  const before = (await serverProject(request, 'demo')).lines[2]!
  const text = before.tokens.map((token) => token.text).join('')
  await page.getByTestId('token-2-0').dblclick()
  const input = page.getByTestId('line-input-2')
  await expect(input).toHaveValue(text)
  await input.fill(text.replace('遙遠', '很遙遠'))
  await input.press('Enter')
  await expect(page.getByTestId(`token-2-${before.tokens.length}`)).toBeVisible()
  await waitSaved(page)
  const after = (await serverProject(request, 'demo')).lines[2]!
  expect(after.tokens.map((token) => token.text).join('')).toBe(text.replace('遙遠', '很遙遠'))
  const index = after.tokens.findIndex((token) => token.text.trim() === '很')
  expect(index).toBeGreaterThan(0)
  // Everything before and after the inserted character kept its time.
  expect(after.tokens.slice(0, index)).toEqual(before.tokens.slice(0, index))
  expect(after.tokens.slice(index + 1).map((token) => token.start_ms)).toEqual(
    before.tokens.slice(index).map((token) => token.start_ms),
  )
  await page.keyboard.press('Control+z')
  await waitSaved(page)
  expect((await serverProject(request, 'demo')).lines[2]!.tokens).toEqual(before.tokens)
})

test('shifting the whole song moves every token', async ({ page, request }) => {
  await openEditor(page, 'demo')
  const before = await serverProject(request, 'demo')
  await page.getByRole('button', { name: '時間位移' }).click()
  await page.getByTestId('shift-amount').fill('120')
  await page.getByTestId('shift-apply').click()
  await waitSaved(page)
  const after = await serverProject(request, 'demo')
  const starts = (project: typeof before) => project.lines.flatMap((line) => line.tokens.map((token) => token.start_ms!))
  expect(starts(after)).toEqual(starts(before).map((value) => value + 120))
  await page.keyboard.press('Control+z')
  await waitSaved(page)
  expect(starts(await serverProject(request, 'demo'))).toEqual(starts(before))
})

test('tap mode marks the start of each token while the song plays', async ({ page, request }) => {
  await openEditor(page, 'demo')
  const before = (await serverProject(request, 'demo')).lines[3]!
  // Start a little before the last line and tap its first three tokens.
  await page.getByTestId('token-3-0').click()
  await page.evaluate((time) => window.karaforge?.seek(time), before.tokens[0]!.start_ms! - 1500)
  await page.keyboard.press('1')
  await expect(page.getByTestId('tap-banner')).toBeVisible()
  await page.keyboard.press('Space') // starts playback
  await expect.poll(() => page.evaluate(() => window.karaforge?.now() ?? 0)).toBeGreaterThan(
    before.tokens[0]!.start_ms! - 1400,
  )
  const taps: number[] = []
  for (let count = 0; count < 3; count += 1) {
    await page.waitForTimeout(350)
    await page.keyboard.press('Space')
    taps.push(await page.evaluate(() => window.karaforge?.now() ?? 0))
  }
  await page.keyboard.press('Escape')
  await expect(page.getByTestId('tap-banner')).toBeHidden()
  await page.evaluate(() => window.karaforge?.pause())
  await waitSaved(page)
  const after = (await serverProject(request, 'demo')).lines[3]!
  const starts = after.tokens.slice(0, 3).map((token) => token.start_ms!)
  expect(after.tokens.slice(0, 3).every((token) => token.locked && token.source === 'manual')).toBe(true)
  for (let index = 0; index < 3; index += 1) {
    // The stored time is the playback time at the key press (read back a moment later).
    expect(taps[index]! - starts[index]!).toBeGreaterThanOrEqual(-20)
    expect(taps[index]! - starts[index]!).toBeLessThan(250)
  }
  expect(starts[1]! - starts[0]!).toBeGreaterThan(250)
  // Each tap ended the token before it.
  expect(after.tokens[0]!.end_ms).toBe(starts[1])
  expect(after.tokens[1]!.end_ms).toBe(starts[2])
})

test('the interface switches to English', async ({ page }) => {
  await openEditor(page, 'demo')
  await page.getByRole('combobox', { name: '語言' }).selectOption('en')
  await expect(page.getByTestId('open-export')).toHaveText('Export')
  await expect(page.getByRole('button', { name: 'Re-align' })).toBeVisible()
  await page.getByRole('button', { name: 'Shortcuts' }).click()
  await expect(page.getByRole('dialog', { name: 'Keyboard shortcuts' })).toContainText('Undo / redo')
  await page.keyboard.press('Escape')
  await page.getByRole('combobox', { name: 'Language' }).selectOption('zh-TW')
})

test('lyrics can be exported as LRC and downloaded', async ({ page, request }) => {
  await openEditor(page, 'demo')
  await page.getByTestId('open-export').click()
  await page.getByTestId('export-format').selectOption('lrc')
  await page.getByTestId('export-start').click()
  const file = page.getByTestId('export-files').getByText('示範歌曲.lrc')
  await expect(file).toBeVisible({ timeout: 30_000 })
  const listed = (await (await request.get('/api/projects/demo/exports')).json()) as {
    exports: { name: string; url: string }[]
  }
  const lrc = listed.exports.find((item) => item.name === '示範歌曲.lrc')
  expect(lrc).toBeDefined()
  const content = await (await request.get(lrc!.url)).text()
  expect(content).toContain('[ti:示範歌曲]')
  expect(content).toMatch(/\[00:\d\d\.\d\d\]車窗上的雨滴 排成一條線/)
})

test('theme changes are previewed, stored in the project and can be saved as a theme', async ({ page, request }) => {
  await openEditor(page, 'demo')
  await page.getByRole('button', { name: '主題', exact: true }).click()
  await expect(page.getByTestId('theme-panel')).toBeVisible()
  const rendered = page.waitForResponse(
    (response) => response.url().endsWith('/api/projects/demo/preview') && response.request().method() === 'POST',
  )
  await page.getByTestId('theme-font.size').fill('100')
  const preview = (await (await rendered).json()) as { ass: string }
  expect(preview.ass).toContain('[V4+ Styles]')
  await waitSaved(page)
  expect((await serverProject(request, 'demo')).style.overrides).toEqual({ 'font.size': 100 })

  await page.getByTestId('theme-name').fill('e2e-big')
  await page.getByTestId('theme-save').click()
  await expect(page.getByText('已另存為「e2e-big」')).toBeVisible()
  await expect(page.getByTestId('theme-select')).toHaveValue('e2e-big')
  await waitSaved(page)
  expect((await serverProject(request, 'demo')).style).toEqual({ theme: 'e2e-big', overrides: {} })
  const themes = (await (await request.get('/api/themes')).json()) as {
    themes: { name: string; builtin: boolean; theme: { font: { size: number } } }[]
  }
  const saved = themes.themes.find((item) => item.name === 'e2e-big')
  expect(saved).toMatchObject({ builtin: false, theme: { font: { size: 100 } } })

  // Put the project back on the built-in theme and remove the test theme.
  await page.getByTestId('theme-select').selectOption('classic-ktv')
  await waitSaved(page)
  expect((await request.delete('/api/themes/e2e-big')).status()).toBe(204)
})

test('a draft made by speech recognition is announced until it is acknowledged', async ({ page, request }) => {
  const before = await serverProject(request, 'demo')
  const stored = (await (await request.get('/api/projects/demo')).json()) as { project: Record<string, unknown> }
  const meta = stored.project.meta as Record<string, unknown>
  const mark = async (source: 'asr' | 'user', revision: number) => {
    const response = await request.put('/api/projects/demo', {
      data: { project: { ...stored.project, meta: { ...meta, lyrics_source: source } }, revision },
    })
    expect(response.ok()).toBe(true)
    return ((await response.json()) as { revision: number }).revision
  }
  const revision = await mark('asr', before.revision)
  try {
    await openEditor(page, 'demo')
    const banner = page.getByTestId('draft-banner')
    await expect(banner).toContainText('語音辨識產生的草稿')
    await banner.getByRole('button', { name: '知道了' }).click()
    await expect(banner).toBeHidden()
    // The acknowledgement is remembered in this browser.
    await page.reload()
    await expect(page.getByTestId('timeline')).toBeVisible()
    await expect(page.getByTestId('draft-banner')).toHaveCount(0)
  } finally {
    await mark('user', revision)
  }
})

test('readings are generated, shown when the theme asks for them, and switched to pinyin', async ({ page, request }) => {
  await openEditor(page, 'demo')
  // The theme panel takes the place of the lyrics, so it is opened and closed as needed.
  const openTheme = async () => {
    await page.getByRole('button', { name: '主題', exact: true }).click()
    await expect(page.getByTestId('theme-panel')).toBeVisible()
  }
  const closeTheme = async () => {
    await page.getByTestId('theme-panel').getByRole('button', { name: '關閉' }).click()
    await expect(page.getByTestId('token-0-0')).toBeVisible()
  }
  const reading = page.getByTestId('token-0-0').locator('rt')

  await openTheme()
  await page.getByTestId('readings-generate').click()
  await expect(page.getByTestId('readings-done')).toHaveText('已更新 4 行的讀音。')
  await waitSaved(page)
  const first = (await serverProject(request, 'demo')).lines[0]!.tokens[0]!
  expect(first).toMatchObject({ text: '車', ruby: 'ㄔㄜ', ruby_source: 'auto' })
  // Stored, but not shown in the lyrics until the theme displays readings.
  await closeTheme()
  await expect(reading).toHaveCount(0)

  await openTheme()
  const rendered = page.waitForResponse(
    (response) => response.url().endsWith('/api/projects/demo/preview') && response.request().method() === 'POST',
  )
  await page.getByLabel('顯示注音／拼音').check()
  const preview = (await (await rendered).json()) as { ass: string }
  expect(preview.ass).toContain('ㄔㄜ')
  await closeTheme()
  await expect(reading).toHaveText('ㄔㄜ')
  await page.evaluate(() => window.karaforge?.seek(6200))
  await page.waitForTimeout(800)
  await page.getByTestId('preview-stage').screenshot({ path: 'test-results/readings-zhuyin.png' })

  await openTheme()
  await page.getByTestId('readings-kind').selectOption('pinyin')
  await page.getByTestId('readings-generate').click()
  await closeTheme()
  await expect(reading).toHaveText('chē')
  await page.waitForTimeout(800)
  await page.getByTestId('preview-stage').screenshot({ path: 'test-results/readings-pinyin.png' })

  // A reading typed by hand survives regeneration and clearing.
  await page.getByTestId('token-0-0').click()
  await page.getByTestId('token-ruby').fill('ㄐㄩ')
  await openTheme()
  await page.getByTestId('readings-generate').click()
  await page.getByTestId('readings-clear').click()
  await closeTheme()
  await expect(page.getByTestId('token-0-1').locator('rt')).toHaveCount(0)
  await expect(reading).toHaveText('ㄐㄩ')
  await waitSaved(page)
  const stored = (await serverProject(request, 'demo')).lines[0]!.tokens
  expect(stored[0]).toMatchObject({ ruby: 'ㄐㄩ', ruby_source: 'manual' })
  expect(stored[1]).toMatchObject({ ruby: null, ruby_source: null })

  // Leave the project as it was.
  await page.getByTestId('token-0-0').click()
  await page.getByTestId('token-ruby').fill('')
  await openTheme()
  await page.getByRole('button', { name: '還原成主題的預設值' }).click()
  await waitSaved(page)
  const after = await serverProject(request, 'demo')
  expect(after.style.overrides).toEqual({})
  expect(after.lines[0]!.tokens[0]!.ruby).toBeNull()
})
