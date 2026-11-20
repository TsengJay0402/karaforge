import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { App } from './App.tsx'
import { emitServerEvent } from './api/events.ts'
import { useI18n } from './i18n/index.ts'
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
        project: {},
        media: { source: null, audio: null, vocals: null, instrumental: null },
        exports: [],
      }),
    })
    window.history.pushState({}, '', '/new')
    render(<App />)
    const file = new File(['abc'], '我的歌.mp3', { type: 'audio/mpeg' })
    await userEvent.upload(screen.getByTestId('media-input'), file)
    expect(screen.getByText(/已選擇:我的歌.mp3/)).toBeInTheDocument()
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
  })

  it('asks for a media file first', async () => {
    mockApi({ 'GET /api/system': () => system })
    window.history.pushState({}, '', '/new')
    render(<App />)
    await userEvent.click(screen.getByRole('button', { name: '開始處理' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('請先選擇一個媒體檔')
  })
})
