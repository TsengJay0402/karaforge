import type { Job, Project, ProjectSummary, SystemInfo } from '../api/types.ts'

export const system: SystemInfo = {
  version: '0.1.0',
  workspace: '/tmp/work',
  default_profile: 'balanced',
  profiles: [
    { name: 'cpu-lite', asr_model: 'whisper-base', aligner: 'whisper-attn', models: [] },
    {
      name: 'balanced',
      asr_model: 'whisper-small',
      aligner: 'ctc',
      models: [
        { id: 'whisper-small', bytes: 486_000_000, installed: true },
        { id: 'wav2vec2-zh', bytes: 1_276_000_000, installed: false },
      ],
    },
    { name: 'gpu-quality', asr_model: 'whisper-large-v3-turbo', aligner: 'ctc', models: [] },
  ],
  device: { kind: 'cpu', name: 'CPU', fallback_reason_zh: null, fallback_reason_en: null },
  ffmpeg: { found: true, version: '7.1', libass: true, error: null },
  ytdlp: { found: true, version: '2026.10.26' },
  qwen: false,
  formats: [
    { id: 'mp4', suffix: '.mp4', video: true, title_zh: 'MP4 影片', title_en: 'MP4 video' },
    { id: 'lrc', suffix: '.lrc', video: false, title_zh: 'LRC 歌詞', title_en: 'LRC lyrics' },
  ],
}

export function summary(id: string, extra: Partial<ProjectSummary> = {}): ProjectSummary {
  return {
    id,
    title: id,
    artist: '',
    language: 'zh-TW',
    duration_ms: 60_000,
    has_video: false,
    has_thumbnail: false,
    processed: true,
    stats: { lines: 2, tokens: 10, timed_tokens: 10, locked_tokens: 0, low_confidence: 1 },
    revision: 1,
    modified_at: 1_700_000_000,
    broken: null,
    job: null,
    last_job: null,
    ...extra,
  }
}

export function job(extra: Partial<Job> = {}): Job {
  return {
    id: 'job1',
    kind: 'process',
    project_id: 'demo',
    params: {},
    state: 'running',
    progress: 0.4,
    stage: 'separate',
    message: '',
    error: null,
    result: null,
    created_at: 1,
    started_at: 2,
    finished_at: null,
    ...extra,
  }
}

type Handler = (url: URL, init: RequestInit | undefined) => unknown

/** Thrown by a handler to answer with an error status and body. */
export class HttpFailure extends Error {
  readonly status: number
  readonly error: unknown

  constructor(status: number, error: unknown) {
    super(`HTTP ${status}`)
    this.status = status
    this.error = error
  }
}

/**
 * Replace `fetch` with a table of handlers keyed by `"METHOD /path"`.  A handler returns the
 * JSON body; throwing an `HttpFailure` produces an error response.  Returns the list of
 * requests that were made.
 */
export function mockApi(routes: Record<string, Handler>): { method: string; path: string; body: unknown }[] {
  const calls: { method: string; path: string; body: unknown }[] = []
  const fake = (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, 'http://localhost')
    const method = (init?.method ?? 'GET').toUpperCase()
    const path = decodeURIComponent(url.pathname)
    const handler = routes[`${method} ${path}`]
    let body: unknown = null
    if (typeof init?.body === 'string') body = JSON.parse(init.body)
    else if (init?.body instanceof FormData) body = Object.fromEntries(init.body.entries())
    calls.push({ method, path, body })
    if (!handler) {
      return Promise.resolve(
        new Response(JSON.stringify({ error: { code: 'not_found', message_zh: '找不到', message_en: 'Not found', hint_zh: null, hint_en: null, detail: null } }), { status: 404 }),
      )
    }
    try {
      const result = handler(url, init)
      return Promise.resolve(new Response(result === undefined ? null : JSON.stringify(result), { status: 200 }))
    } catch (thrown) {
      if (!(thrown instanceof HttpFailure)) throw thrown
      return Promise.resolve(new Response(JSON.stringify({ error: thrown.error }), { status: thrown.status }))
    }
  }
  vi.stubGlobal('fetch', vi.fn(fake))
  return calls
}

export type { Project }
