/** Shapes of the JSON the server sends and accepts.  Mirrors the engine's pydantic models. */

export interface Token {
  text: string
  start_ms: number | null
  end_ms: number | null
  ruby: string | null
  ruby_source: 'auto' | 'manual' | null
  confidence: number | null
  locked: boolean
  source: 'auto' | 'manual' | 'import'
}

export interface Line {
  id: string
  singer: string
  paragraph: number
  tokens: Token[]
  time_hint: [number, number | null] | null
}

export interface Singer {
  id: string
  label: string
  theme_slot: string
}

export interface Meta {
  title: string
  artist: string
  lyricist: string
  composer: string
  language: string
  duration_ms: number
}

export interface Media {
  source: string | null
  audio: string | null
  vocals: string | null
  instrumental: string | null
  has_video: boolean
}

export interface Analysis {
  tempo_bpm: number | null
  beats_ms: number[]
  vocal_regions: [number, number][]
}

export type BackgroundType = 'video' | 'image' | 'color' | 'blur'

export interface Project {
  schema_version: number
  revision: number
  meta: Meta
  media: Media
  analysis: Analysis
  singers: Singer[]
  lines: Line[]
  style: { theme: string; overrides: Record<string, unknown> }
  render: {
    resolution: [number, number]
    fps: number
    background: { type: BackgroundType; color: string | null; image: string | null }
  }
}

export interface ApiErrorBody {
  code: string
  message_zh: string
  message_en: string
  hint_zh: string | null
  hint_en: string | null
  detail: string | null
}

export type JobState = 'queued' | 'running' | 'done' | 'failed' | 'cancelled'
export type JobKind = 'process' | 'align' | 'export' | 'models'

export interface Job {
  id: string
  kind: JobKind
  project_id: string | null
  params: Record<string, unknown>
  state: JobState
  progress: number
  stage: string | null
  message: string
  error: ApiErrorBody | null
  result: Record<string, unknown> | null
  created_at: number
  started_at: number | null
  finished_at: number | null
}

export interface ProjectStats {
  lines: number
  tokens: number
  timed_tokens: number
  locked_tokens: number
  low_confidence: number
}

export interface ProjectSummary {
  id: string
  title: string
  artist: string
  language: string
  duration_ms: number
  has_video: boolean
  has_thumbnail: boolean
  processed: boolean
  stats: ProjectStats
  revision: number
  modified_at: number
  broken: ApiErrorBody | null
  job: Job | null
  last_job: Job | null
}

export interface ExportFile {
  name: string
  bytes: number
  modified_at: number
  url: string
}

export type MediaName = 'source' | 'audio' | 'vocals' | 'instrumental'

export interface ProjectDetail {
  summary: ProjectSummary
  project: Project
  media: Record<MediaName, string | null>
  exports: ExportFile[]
}

export interface FontEntry {
  family: string
  file: string
  url: string
}

export interface PreviewResult {
  ass: string
  fonts: FontEntry[]
  width: number
  height: number
  lines: number
}

export interface PeakLevel {
  samples_per_bucket: number
  min: number[]
  max: number[]
}

export interface Peaks {
  sample_rate: number
  length: number
  levels: PeakLevel[]
}

export interface AnalysisData {
  onsets_ms: number[]
  regions_ms?: [number, number][]
  beats_ms?: number[]
  tempo_bpm?: number | null
}

export interface ProfileInfo {
  name: string
  asr_model: string
  aligner: string
  models: { id: string; bytes: number; installed: boolean }[]
}

export interface ExportFormat {
  id: string
  suffix: string
  video: boolean
  title_zh: string
  title_en: string
}

export interface SystemInfo {
  version: string
  workspace: string
  default_profile: string
  profiles: ProfileInfo[]
  device: {
    kind: string
    name: string
    fallback_reason_zh: string | null
    fallback_reason_en: string | null
  }
  ffmpeg: { found: boolean; version: string | null; libass: boolean; error: ApiErrorBody | null }
  qwen: boolean
  formats: ExportFormat[]
}

/** A theme as the server sends it; the editor only touches the fields it knows. */
export interface ThemeColorPair {
  fill: string
  outline: string
}

export interface Theme {
  name: string
  title?: string
  reference_height: number
  font: { family: string; fallback: string; size: number; [key: string]: unknown }
  text: { outline: number; shadow: number; letter_spacing: number; [key: string]: unknown }
  colors: Record<string, unknown>
  layout: Record<string, unknown>
  ruby: { enabled: boolean; [key: string]: unknown }
  countdown: Record<string, unknown>
  title_card: Record<string, unknown>
  background: { color: string; dim_bottom: number; [key: string]: unknown }
  [key: string]: unknown
}

export interface ThemeEntry {
  name: string
  builtin: boolean
  theme: Theme | null
  error: ApiErrorBody | null
}

export type ServerEvent =
  | { type: 'hello'; version: string; jobs: Job[] }
  | { type: 'job'; job: Job }
  | { type: 'project'; id: string; revision: number | null; reason: string }
