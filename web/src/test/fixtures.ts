import type { Line, Project, Token } from '../api/types.ts'

export function token(text: string, start: number | null, end: number | null, extra: Partial<Token> = {}): Token {
  return {
    text,
    start_ms: start,
    end_ms: end,
    ruby: null,
    ruby_source: null,
    confidence: start === null ? null : 0.9,
    locked: false,
    source: 'auto',
    ...extra,
  }
}

/** A line whose tokens are sung back to back, `each` milliseconds long, from `start`. */
export function timedLine(id: string, texts: string[], start: number, each = 400, singer = 'm'): Line {
  return {
    id,
    singer,
    paragraph: 0,
    tokens: texts.map((text, index) => token(text, start + index * each, start + (index + 1) * each)),
    time_hint: null,
  }
}

export function project(lines: Line[], durationMs = 60_000): Project {
  return {
    schema_version: 2,
    revision: 0,
    meta: {
      title: '測試歌曲',
      artist: '某歌手',
      lyricist: '',
      composer: '',
      language: 'zh-TW',
      duration_ms: durationMs,
    },
    media: { source: 'media/source.mp3', audio: 'media/audio.wav', vocals: null, instrumental: null, has_video: false },
    analysis: { tempo_bpm: null, beats_ms: [], vocal_regions: [] },
    singers: [
      { id: 'm', label: '男', theme_slot: 'male' },
      { id: 'f', label: '女', theme_slot: 'female' },
      { id: 'all', label: '合', theme_slot: 'duet' },
    ],
    lines,
    style: { theme: 'classic-ktv', overrides: {} },
    render: { resolution: [1920, 1080], fps: 30, background: { type: 'video', color: null, image: null } },
  }
}

export function times(line: Line | undefined): [string, number | null, number | null][] {
  return (line?.tokens ?? []).map((item) => [item.text, item.start_ms, item.end_ms])
}
