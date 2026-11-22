import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { App } from './App.tsx'
import { emitServerEvent } from './api/events.ts'
import type { RemoteMedia } from './api/types.ts'
import { useI18n } from './i18n/index.ts'
import { project, token } from './test/fixtures.ts'
import { HttpFailure, job, mockApi, summary, system } from './test/server.ts'

beforeEach(() => {
  window.history.pushState({}, '', '/')
  useI18n.getState().setLang('zh-TW')
})
afterEach(() => vi.unstubAllGlobals())

describe('project list', () => {
  it('shows the projects with their state and the system notices', async () => {
    mockApi({
      'GET /api/system': () => system,
      'GET /api/projects': () => ({
        projects: [
          summary('晴天', { artist: '某歌手' }),
          summary('new-song', { processed: false, stats: { lines: 0, tokens: 0, timed_tokens: 0, locked_tokens: 0, low_confidence: 0 } }),
          summary('busy', { job: job({ project_id: 'busy' }) }),
        ],
      }),
    })
    render(<App />)
    expect(screen.getByRole('heading', { name: '我的專案' })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: '晴天' })).toBeInTheDocument()
    expect(screen.getByText('已對齊')).toBeInTheDocument()
    expect(screen.getByText('尚未處理')).toBeInTheDocument()
    expect(screen.getByText('2 行 / 10 字 · 1 個字建議檢查')).toBeInTheDocument()
    // The running job shows its stage and progress.
    expect(screen.getByText('分離人聲與伴奏')).toBeInTheDocument()
    expect(screen.getByText('40%')).toBeInTheDocument()
    // One model of the default profile is missing.
    expect(await screen.findByText('還缺 1 個模型', { exact: false })).toHaveTextContent('1.2 GB')
  })

  it('updates a running job from server events and switches language', async () => {
    mockApi({
      'GET /api/system': () => system,
      'GET /api/projects': () => ({ projects: [summary('busy', { job: job({ project_id: 'busy' }) })] }),
    })
    render(<App />)
    expect(await screen.findByText('40%')).toBeInTheDocument()
    emitServerEvent({ type: 'job', job: job({ project_id: 'busy', progress: 0.75, stage: 'align' }) })
    expect(await screen.findByText('75%')).toBeInTheDocument()
    expect(screen.getByText('對齊歌詞')).toBeInTheDocument()

    await userEvent.selectOptions(screen.getByRole('combobox', { name: '語言' }), 'en')
    expect(screen.getByRole('heading', { name: 'My projects' })).toBeInTheDocument()
    expect(screen.getByText('Aligning the lyrics')).toBeInTheDocument()
  })

  it('shows videos that are being downloaded and can cancel them', async () => {
    const calls = mockApi({
      'GET /api/system': () => system,
      'GET /api/projects': () => ({ projects: [] }),
      'DELETE /api/jobs/imp9': () => ({ job: job({ id: 'imp9', kind: 'import', project_id: null, state: 'cancelled' }) }),
    })
    render(<App />)
    emitServerEvent({
      type: 'job',
      job: job({ id: 'imp9', kind: 'import', project_id: null, stage: null, progress: 0.3, params: { title: '晴天', url: 'https://youtu.be/x' } }),
    })
    const download = await screen.findByTestId('import-job')
    expect(download).toHaveTextContent('正在下載「晴天」')
    expect(download).toHaveTextContent('30%')
    await userEvent.click(within(download).getByRole('button', { name: '取消' }))
    expect(calls.some((call) => call.method === 'DELETE' && call.path === '/api/jobs/imp9')).toBe(true)
    emitServerEvent({ type: 'job', job: job({ id: 'imp9', kind: 'import', project_id: null, state: 'cancelled' }) })
    await waitFor(() => expect(screen.queryByTestId('import-job')).not.toBeInTheDocument())
  })

  it('explains an empty workspace and server failures', async () => {
    mockApi({ 'GET /api/system': () => system, 'GET /api/projects': () => ({ projects: [] }) })
    const first = render(<App />)
    expect(await screen.findByText(/還沒有專案/)).toBeInTheDocument()
    first.unmount()

    mockApi({
      'GET /api/system': () => system,
      'GET /api/projects': () => {
        throw new HttpFailure(500, {
          code: 'x',
          message_zh: '伺服器壞了',
          message_en: 'Broken',
          hint_zh: '重新啟動',
          hint_en: null,
          detail: 'trace',
        })
      },
    })
    render(<App />)
    expect(await screen.findByRole('alert')).toHaveTextContent('伺服器壞了')
    expect(screen.getByRole('alert')).toHaveTextContent('重新啟動')
  })

  it('deletes a project after confirmation', async () => {
    let projects = [summary('old')]
    const calls = mockApi({
      'GET /api/system': () => system,
      'GET /api/projects': () => ({ projects }),
      'DELETE /api/projects/old': () => {
        projects = []
        return undefined
      },
    })
    vi.stubGlobal('confirm', vi.fn(() => true))
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: '刪除' }))
    await waitFor(() => expect(screen.queryByRole('heading', { name: 'old' })).not.toBeInTheDocument())
    expect(calls.some((call) => call.method === 'DELETE')).toBe(true)
  })
})

describe('new project wizard', () => {
  it('uploads the media with pasted lyrics and opens the project', async () => {
    const calls = mockApi({
      'GET /api/system': () => system,
      'GET /api/projects': () => ({ projects: [] }),
      'POST /api/projects': () => ({ project: summary('我的歌', { processed: false }), job: job({ project_id: '我的歌' }) }),
      'GET /api/projects/我的歌': () => ({
        summary: summary('我的歌', { processed: false, job: job({ project_id: '我的歌' }) }),
        project: project([{ id: 'L001', singer: 'm', paragraph: 0, tokens: [token('第', null, null)], time_hint: null }]),
        media: { source: null, audio: null, vocals: null, instrumental: null },
        exports: [],
      }),
    })
    window.history.pushState({}, '', '/new')
    render(<App />)
    const file = new File(['abc'], '我的歌.mp3', { type: 'audio/mpeg' })
    await userEvent.upload(screen.getByTestId('media-input'), file)
    expect(screen.getByText(/已選擇：我的歌.mp3/)).toBeInTheDocument()
    expect(screen.getByLabelText('歌名')).toHaveValue('我的歌')
    await userEvent.type(screen.getByRole('textbox', { name: '貼上歌詞' }), '第一句')
    await userEvent.click(await screen.findByText('快速'))
    await userEvent.click(screen.getByRole('button', { name: '開始處理' }))

    await waitFor(() => expect(window.location.pathname).toBe('/p/%E6%88%91%E7%9A%84%E6%AD%8C'))
    const upload = calls.find((call) => call.method === 'POST')
    expect(upload?.body).toMatchObject({ lyrics: '第一句', title: '我的歌', profile: 'cpu-lite', start: 'true' })
    // The project page shows the processing view with its stages.
    expect(await screen.findByText(/正在處理「我的歌」/)).toBeInTheDocument()
    // The current stage is named in the list of stages and above the progress bar.
    expect(screen.getAllByText('分離人聲與伴奏')).toHaveLength(2)
    expect(screen.getByText('40%')).toBeInTheDocument()
    // The lyrics were given, so no draft has to be made.
    expect(screen.queryByText('產生歌詞草稿')).not.toBeInTheDocument()
  })

  it('creates a project without lyrics and shows that they will be drafted', async () => {
    const calls = mockApi({
      'GET /api/system': () => system,
      'GET /api/projects': () => ({ projects: [] }),
      'POST /api/projects': () => ({ project: summary('清唱', { processed: false }), job: job({ project_id: '清唱' }) }),
      'GET /api/projects/清唱': () => ({
        summary: summary('清唱', { processed: false, job: job({ project_id: '清唱', stage: 'draft' }) }),
        project: project([]),
        media: { source: null, audio: null, vocals: null, instrumental: null },
        exports: [],
      }),
    })
    window.history.pushState({}, '', '/new')
    render(<App />)
    await userEvent.upload(screen.getByTestId('media-input'), new File(['abc'], '清唱.mp3', { type: 'audio/mpeg' }))
    await userEvent.click(screen.getByRole('radio', { name: '沒有歌詞，用 AI 辨識' }))
    expect(screen.getByText(/只是草稿/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '開始處理' }))

    await waitFor(() => expect(window.location.pathname).toBe(`/p/${encodeURIComponent('清唱')}`))
    const upload = calls.find((call) => call.method === 'POST')
    expect(upload?.body).not.toHaveProperty('lyrics')
    expect(await screen.findByText(/正在處理「清唱」/)).toBeInTheDocument()
    // The drafting stage is part of the list and is the one running.
    expect(screen.getAllByText('產生歌詞草稿')).toHaveLength(2)
    expect(document.querySelector('.stages .active')).toHaveTextContent('產生歌詞草稿')
  })

  const video: RemoteMedia = {
    url: 'https://www.youtube.com/watch?v=abc123',
    id: 'abc123',
    title: '晴天',
    artist: '周杰倫',
    uploader: '周杰倫 - Topic',
    duration_ms: 269_000,
    thumbnail: 'https://example.com/thumb.jpg',
    extractor: 'Youtube',
    has_video: true,
    size_bytes: 52_428_800,
  }
  const importing = (extra: Partial<Parameters<typeof job>[0]> = {}) =>
    job({ id: 'imp1', kind: 'import', project_id: null, stage: null, state: 'queued', progress: 0, ...extra })

  it('reads a pasted video link, follows the download and opens the project', async () => {
    const calls = mockApi({
      'GET /api/system': () => system,
      'GET /api/projects': () => ({ projects: [] }),
      'POST /api/media/probe': () => ({ media: video }),
      'POST /api/projects/import': () => ({ job: importing({ params: { url: video.url, title: '晴天' } }) }),
      'GET /api/projects/晴天': () => ({
        summary: summary('晴天', { processed: false, job: job({ project_id: '晴天' }) }),
        project: project([]),
        media: { source: null, audio: null, vocals: null, instrumental: null },
        exports: [],
      }),
    })
    window.history.pushState({}, '', '/new')
    render(<App />)
    await userEvent.click(await screen.findByLabelText('或貼上影片網址（YouTube 等網站）'))
    await userEvent.paste('https://youtu.be/abc123')

    const card = await screen.findByTestId('remote-media')
    expect(card).toHaveTextContent('晴天')
    expect(card).toHaveTextContent('周杰倫 - Topic · 04:29 · 約 50.0 MB · Youtube')
    expect(calls.find((call) => call.path === '/api/media/probe')?.body).toEqual({ url: 'https://youtu.be/abc123' })
    // The link field now holds the full address, and title and artist are filled in.
    expect(screen.getByTestId('media-link')).toHaveValue(video.url)
    expect(screen.getByLabelText('歌名')).toHaveValue('晴天')
    expect(screen.getByLabelText('歌手')).toHaveValue('周杰倫')

    await userEvent.type(screen.getByRole('textbox', { name: '貼上歌詞' }), '故事的小黃花')
    await userEvent.click(screen.getByRole('button', { name: '開始處理' }))
    expect(await screen.findByTestId('import-progress')).toHaveTextContent('正在下載影片')
    expect(calls.find((call) => call.path === '/api/projects/import')?.body).toMatchObject({
      url: video.url,
      title: '晴天',
      artist: '周杰倫',
      lyrics: '故事的小黃花',
      start: 'true',
    })
    emitServerEvent({ type: 'job', job: importing({ state: 'running', progress: 0.5, message: '下載中 / downloading 25.0 / 50.0 MB' }) })
    expect(await screen.findByText('50%')).toBeInTheDocument()
    expect(screen.getByText('下載影片')).toBeInTheDocument()
    expect(screen.getByText('下載中 / downloading 25.0 / 50.0 MB')).toBeInTheDocument()

    emitServerEvent({ type: 'job', job: importing({ state: 'done', progress: 1, result: { project_id: '晴天', job: 'job1' } }) })
    await waitFor(() => expect(window.location.pathname).toBe(`/p/${encodeURIComponent('晴天')}`))
    expect(await screen.findByText(/正在處理「晴天」/)).toBeInTheDocument()
  })

  it('explains a link that cannot be read and a download that failed or was cancelled', async () => {
    let readable = false
    mockApi({
      'GET /api/system': () => system,
      'POST /api/media/probe': () => {
        if (readable) return { media: video }
        throw new HttpFailure(400, {
          code: 'download_failed',
          message_zh: '無法讀取這個網址的影片：Video unavailable',
          message_en: 'Could not read the video at this link: Video unavailable',
          hint_zh: null,
          hint_en: null,
          detail: null,
        })
      },
      'POST /api/projects/import': () => ({ job: importing() }),
      'DELETE /api/jobs/imp1': () => ({ job: importing({ state: 'cancelled' }) }),
    })
    window.history.pushState({}, '', '/new')
    render(<App />)
    const field = await screen.findByTestId('media-link')
    await userEvent.type(field, 'youtube.com/watch{Enter}')
    expect(await screen.findByRole('alert')).toHaveTextContent('http:// 或 https://')
    await userEvent.clear(field)
    await userEvent.type(field, 'https://youtu.be/gone{Enter}')
    expect(await screen.findByText(/Video unavailable/)).toBeInTheDocument()
    expect(screen.queryByTestId('remote-media')).not.toBeInTheDocument()

    readable = true
    await userEvent.click(screen.getByRole('button', { name: '讀取' }))
    expect(await screen.findByTestId('remote-media')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '開始處理' }))
    await screen.findByTestId('import-progress')
    emitServerEvent({
      type: 'job',
      job: importing({
        state: 'failed',
        error: {
          code: 'download_failed',
          message_zh: '無法下載這部影片：HTTP Error 403',
          message_en: 'Could not download the video: HTTP Error 403',
          hint_zh: '先把 yt-dlp 更新到最新版',
          hint_en: null,
          detail: null,
        },
      }),
    })
    expect(await screen.findByText(/無法下載這部影片：HTTP Error 403/)).toBeInTheDocument()
    expect(screen.queryByTestId('import-progress')).not.toBeInTheDocument()
    // The form can be sent again; this time the download is cancelled.
    await userEvent.click(screen.getByRole('button', { name: '開始處理' }))
    await userEvent.click(within(await screen.findByTestId('import-progress')).getByRole('button', { name: '取消' }))
    emitServerEvent({ type: 'job', job: importing({ state: 'cancelled' }) })
    expect(await screen.findByText('已取消下載。')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '開始處理' })).toBeEnabled()
    // Choosing a file instead brings the drop zone back.
    await userEvent.click(screen.getByRole('button', { name: '改用檔案' }))
    expect(screen.getByText(/把影片或音檔拖到這裡/)).toBeInTheDocument()
  })

  it('says how to install yt-dlp when it is missing', async () => {
    mockApi({ 'GET /api/system': () => ({ ...system, ytdlp: { found: false, version: null } }) })
    window.history.pushState({}, '', '/new')
    render(<App />)
    expect(await screen.findByText(/需要先安裝 yt-dlp/)).toBeInTheDocument()
    expect(screen.getByTestId('media-link')).toBeDisabled()
  })

  it('asks for a media file first', async () => {
    mockApi({ 'GET /api/system': () => system })
    window.history.pushState({}, '', '/new')
    render(<App />)
    await userEvent.click(screen.getByRole('button', { name: '開始處理' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('請先選擇一個媒體檔')
  })
})
