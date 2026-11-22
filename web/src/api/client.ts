import type {
  AnalysisData,
  ApiErrorBody,
  ExportFile,
  FontEntry,
  Job,
  Line,
  Peaks,
  PreviewResult,
  Project,
  ProjectDetail,
  ProjectSummary,
  RemoteMedia,
  SystemInfo,
  Theme,
  ThemeEntry,
} from './types.ts'

/** An error response of the API, with the server's bilingual message. */
export class ApiError extends Error {
  readonly status: number
  readonly body: ApiErrorBody

  constructor(status: number, body: ApiErrorBody) {
    super(body.message_en)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }

  get conflict(): boolean {
    return this.status === 409
  }
}

/** Whatever was thrown, as an error the UI can show in both languages. */
export function toErrorBody(cause: unknown): ApiErrorBody {
  if (cause instanceof ApiError) return cause.body
  return {
    code: 'client_error',
    message_zh: '發生沒有預期到的錯誤。',
    message_en: 'An unexpected error occurred.',
    hint_zh: null,
    hint_en: null,
    detail: cause instanceof Error ? cause.message : String(cause),
  }
}

function fallbackBody(status: number, text: string): ApiErrorBody {
  return {
    code: 'http_error',
    message_zh: `伺服器回應錯誤（${status}）`,
    message_en: `The server answered with an error (${status})`,
    hint_zh: null,
    hint_en: null,
    detail: text.slice(0, 500) || null,
  }
}

function isErrorEnvelope(value: unknown): value is { error: ApiErrorBody } {
  if (typeof value !== 'object' || value === null || !('error' in value)) return false
  const error = (value).error
  return typeof error === 'object' && error !== null && 'message_zh' in error
}

async function fail(response: Response): Promise<never> {
  const text = await response.text()
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch {
    parsed = undefined
  }
  if (isErrorEnvelope(parsed)) throw new ApiError(response.status, parsed.error)
  throw new ApiError(response.status, fallbackBody(response.status, text))
}

async function request(path: string, init?: RequestInit): Promise<Response> {
  let response: Response
  try {
    response = await fetch(path, init)
  } catch (cause) {
    throw new ApiError(0, {
      code: 'network_error',
      message_zh: '無法連線到 KaraForge 伺服器。',
      message_en: 'Cannot reach the KaraForge server.',
      hint_zh: '請確認 kf serve 還在執行。',
      hint_en: 'Check that kf serve is still running.',
      detail: cause instanceof Error ? cause.message : null,
    })
  }
  if (!response.ok) return fail(response)
  return response
}

async function getJson<T>(path: string): Promise<T> {
  return (await (await request(path)).json()) as T
}

async function sendJson<T>(method: string, path: string, body: unknown): Promise<T> {
  const response = await request(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return (await response.json()) as T
}

const project = (id: string) => `/api/projects/${encodeURIComponent(id)}`

export interface NewProjectInput {
  media: File
  lyrics?: string
  lyricsFile?: File | null
  title?: string
  artist?: string
  language?: string
  profile?: string
  start: boolean
}

/** A project made from a video link: the same choices as an upload, a link instead of a file. */
export interface ImportProjectInput extends Omit<NewProjectInput, 'media'> {
  url: string
}

/** The fields an upload and a link import share. */
function projectFields(form: FormData, input: Omit<NewProjectInput, 'media'>): FormData {
  if (input.lyricsFile) form.set('lyrics_file', input.lyricsFile)
  else if (input.lyrics?.trim()) form.set('lyrics', input.lyrics)
  if (input.title) form.set('title', input.title)
  if (input.artist) form.set('artist', input.artist)
  if (input.language) form.set('language', input.language)
  if (input.profile) form.set('profile', input.profile)
  form.set('start', input.start ? 'true' : 'false')
  return form
}

export interface ExportInput {
  format: string
  audio: string
  resolution: [number, number] | null
  background: string | null
}

export const api = {
  system: () => getJson<SystemInfo>('/api/system'),

  listProjects: async () =>
    (await getJson<{ projects: ProjectSummary[] }>('/api/projects')).projects,

  getProject: (id: string) => getJson<ProjectDetail>(project(id)),

  createProject: async (input: NewProjectInput) => {
    const form = new FormData()
    form.set('media', input.media)
    const response = await request('/api/projects', { method: 'POST', body: projectFields(form, input) })
    return (await response.json()) as { project: ProjectSummary; job: Job | null }
  },

  /** What a video link points to; nothing is downloaded yet. */
  probeUrl: async (url: string) =>
    (await sendJson<{ media: RemoteMedia }>('POST', '/api/media/probe', { url })).media,

  /** Start a job that downloads the video, then makes (and processes) the project. */
  importProject: async (input: ImportProjectInput) => {
    const form = new FormData()
    form.set('url', input.url)
    const response = await request('/api/projects/import', { method: 'POST', body: projectFields(form, input) })
    return ((await response.json()) as { job: Job }).job
  },

  saveProject: (id: string, doc: Project, revision: number) =>
    sendJson<{ revision: number; summary: ProjectSummary }>('PUT', project(id), {
      project: doc,
      revision,
    }),

  replaceLyrics: (id: string, text: string, filename: string, revision: number) =>
    sendJson<{ revision: number; project: Project }>('PUT', `${project(id)}/lyrics`, {
      text,
      filename,
      revision,
    }),

  deleteProject: async (id: string) => {
    await request(project(id), { method: 'DELETE' })
  },

  retokenize: async (line: Line, text: string, language?: string) =>
    (await sendJson<{ line: Line }>('POST', '/api/tools/retokenize', { line, text, language })).line,

  /** Automatic readings for `lines`; `none` removes them.  Manual readings are kept. */
  readings: async (lines: Line[], kind: 'zhuyin' | 'pinyin' | 'none', language: string) =>
    (await sendJson<{ lines: Line[] }>('POST', '/api/tools/ruby', { lines, kind, language })).lines,

  preview: (id: string, doc: Project | null, resolution?: [number, number]) =>
    sendJson<PreviewResult>('POST', `${project(id)}/preview`, {
      project: doc,
      resolution: resolution ?? null,
    }),

  peaks: (id: string, stem: string) => getJson<Peaks>(`${project(id)}/peaks/${stem}`),

  analysis: (id: string) => getJson<AnalysisData>(`${project(id)}/analysis`),

  spectrogramUrl: (id: string, stem: string, startMs: number, endMs: number, width: number) =>
    `${project(id)}/spectrogram/${stem}?start_ms=${Math.round(startMs)}&end_ms=${Math.round(endMs)}` +
    `&width=${Math.round(width)}&height=96`,

  thumbnailUrl: (id: string) => `${project(id)}/thumbnail`,

  startJob: async (
    id: string,
    body: { kind: 'process' | 'align'; profile?: string; from_stage?: string; lines?: string[] },
  ) => (await sendJson<{ job: Job }>('POST', `${project(id)}/jobs`, body)).job,

  startExport: async (id: string, body: ExportInput) =>
    (await sendJson<{ job: Job }>('POST', `${project(id)}/exports`, body)).job,

  listExports: async (id: string) =>
    (await getJson<{ exports: ExportFile[] }>(`${project(id)}/exports`)).exports,

  cancelJob: async (jobId: string) => {
    const response = await request(`/api/jobs/${jobId}`, { method: 'DELETE' })
    return ((await response.json()) as { job: Job }).job
  },

  listJobs: async () => (await getJson<{ jobs: Job[] }>('/api/jobs')).jobs,

  themes: async () => (await getJson<{ themes: ThemeEntry[] }>('/api/themes')).themes,

  saveTheme: (name: string, theme: Theme) =>
    sendJson<ThemeEntry>('PUT', `/api/themes/${encodeURIComponent(name)}`, theme),

  fonts: async () => (await getJson<{ fonts: FontEntry[] }>('/api/fonts')).fonts,

  downloadModels: async (profile: string) =>
    (await sendJson<{ job: Job }>('POST', '/api/models/download', { profile })).job,
}

export type Api = typeof api
