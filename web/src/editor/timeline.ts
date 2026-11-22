/** Geometry and data helpers of the timeline: time ↔ pixels, hit testing, waveform columns. */
import type { PeakLevel, Peaks, Project } from '../api/types.ts'
import { isTimed, type TokenRef } from './doc.ts'

export interface View {
  /** Time at the left edge of the timeline, in milliseconds. */
  startMs: number
  /** Horizontal zoom: pixels per second. */
  pxPerSec: number
  width: number
}

export const MIN_ZOOM = 10
export const MAX_ZOOM = 1200
/** Width of the grab zone at each end of a token block, in pixels. */
export const EDGE_PX = 6

export const timeToX = (view: View, timeMs: number) => ((timeMs - view.startMs) / 1000) * view.pxPerSec
export const xToTime = (view: View, x: number) => view.startMs + (x / view.pxPerSec) * 1000
export const visibleMs = (view: View) => (view.width / view.pxPerSec) * 1000

export function clampView(view: View, durationMs: number): View {
  const pxPerSec = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, view.pxPerSec))
  const span = (view.width / pxPerSec) * 1000
  const maxStart = Math.max(0, durationMs - span * 0.5)
  return { ...view, pxPerSec, startMs: Math.min(Math.max(0, view.startMs), maxStart) }
}

/** Zoom by `factor` keeping the time under `anchorX` where it is on screen. */
export function zoomAt(view: View, factor: number, anchorX: number, durationMs: number): View {
  const anchorTime = xToTime(view, anchorX)
  const pxPerSec = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, view.pxPerSec * factor))
  const startMs = anchorTime - (anchorX / pxPerSec) * 1000
  return clampView({ ...view, pxPerSec, startMs }, durationMs)
}

/** Scroll so that `timeMs` is visible, keeping a margin; unchanged when it already is. */
export function follow(view: View, timeMs: number, durationMs: number): View {
  const span = visibleMs(view)
  const margin = span * 0.1
  if (timeMs >= view.startMs + margin && timeMs <= view.startMs + span - margin) return view
  return clampView({ ...view, startMs: timeMs - span * 0.25 }, durationMs)
}

/**
 * The view that shows `timeMs`: unchanged when the time is already visible, otherwise moved so
 * that it sits a quarter of the way in.  Used when the playhead jumps while paused (a token was
 * clicked in the lyrics): unlike `follow` it never moves a view that already shows the time.
 */
export function reveal(view: View, timeMs: number, durationMs: number): View {
  const span = visibleMs(view)
  if (timeMs >= view.startMs && timeMs <= view.startMs + span) return view
  return clampView({ ...view, startMs: timeMs - span * 0.25 }, durationMs)
}

export type HitPart = 'start' | 'end' | 'body'

export interface Hit {
  ref: TokenRef
  part: HitPart
}

export interface Block {
  ref: TokenRef
  x: number
  width: number
  row: number
}

/**
 * Screen rectangles of the timed tokens that are (partly) visible.  Lines alternate between
 * two rows so that the last token of one line and the first of the next never overlap.
 */
export function blocks(project: Project, view: View): Block[] {
  const result: Block[] = []
  const endMs = view.startMs + visibleMs(view)
  project.lines.forEach((line, lineIndex) => {
    line.tokens.forEach((token, index) => {
      if (!isTimed(token) || token.end_ms < view.startMs || token.start_ms > endMs) return
      const x = timeToX(view, token.start_ms)
      const width = Math.max(2, timeToX(view, token.end_ms) - x)
      result.push({ ref: { line: lineIndex, index }, x, width, row: lineIndex % 2 })
    })
  })
  return result
}

/**
 * Which token (and which part of it) is under the pointer.
 *
 * Where two tokens touch, their common boundary belongs to the *later* token's start: moving
 * that start takes the end of the token before it along, which is what dragging a boundary
 * should do.  Otherwise an edge beats a body, and the nearest one wins.
 */
export function hitTest(list: Block[], x: number, row: number): Hit | null {
  let best: Hit | null = null
  let bestRank = Number.POSITIVE_INFINITY
  for (const block of list) {
    if (block.row !== row || x < block.x - EDGE_PX / 2 || x > block.x + block.width + EDGE_PX / 2) continue
    const edge = Math.min(EDGE_PX, block.width / 3)
    let part: HitPart = 'body'
    if (x <= block.x + edge) part = 'start'
    else if (x >= block.x + block.width - edge) part = 'end'
    const centre = block.x + block.width / 2
    // Lower is better: starts before ends before bodies, then by distance.
    const rank =
      part === 'start'
        ? Math.abs(x - block.x)
        : part === 'end'
          ? 1000 + Math.abs(x - (block.x + block.width))
          : 2000 + Math.abs(x - centre)
    if (rank < bestRank) {
      best = { ref: block.ref, part }
      bestRank = rank
    }
  }
  return best
}

/**
 * The timed tokens that a selection box covers, in reading order: those drawn in one of
 * `rows` (lines alternate between rows 0 and 1, as in `blocks`) whose time overlaps
 * `[fromMs, toMs]`.  A box narrower than a token still takes the token it lies in.
 */
export function tokensInBox(project: Project, fromMs: number, toMs: number, rows: readonly number[]): TokenRef[] {
  const low = Math.min(fromMs, toMs)
  const high = Math.max(fromMs, toMs)
  const result: TokenRef[] = []
  project.lines.forEach((line, lineIndex) => {
    if (!rows.includes(lineIndex % 2)) return
    line.tokens.forEach((token, index) => {
      if (isTimed(token) && token.start_ms <= high && token.end_ms > low) result.push({ line: lineIndex, index })
    })
  })
  return result
}

/** The onset closest to `timeMs` within `toleranceMs`, or `timeMs` itself. */
export function snapToOnset(onsets: readonly number[], timeMs: number, toleranceMs: number): number {
  if (onsets.length === 0 || toleranceMs <= 0) return timeMs
  let low = 0
  let high = onsets.length
  while (low < high) {
    const middle = (low + high) >> 1
    if ((onsets[middle] ?? 0) < timeMs) low = middle + 1
    else high = middle
  }
  let best = timeMs
  let bestDistance = toleranceMs
  for (const index of [low - 1, low]) {
    const onset = onsets[index]
    if (onset === undefined) continue
    const distance = Math.abs(onset - timeMs)
    if (distance <= bestDistance) {
      best = onset
      bestDistance = distance
    }
  }
  return best
}

/** The peak level whose buckets are closest to (but not coarser than) one pixel. */
export function chooseLevel(peaks: Peaks, pxPerSec: number): PeakLevel | null {
  const samplesPerPixel = peaks.sample_rate / pxPerSec
  let chosen: PeakLevel | null = null
  for (const level of peaks.levels) {
    if (chosen === null || level.samples_per_bucket <= samplesPerPixel) chosen = level
  }
  return chosen
}

/** Minimum and maximum (each -127..127) of the waveform for every pixel column of the view. */
export function waveformColumns(peaks: Peaks, view: View): { min: Int8Array; max: Int8Array } {
  const width = Math.max(0, Math.floor(view.width))
  const min = new Int8Array(width)
  const max = new Int8Array(width)
  const level = chooseLevel(peaks, view.pxPerSec)
  if (!level) return { min, max }
  const bucketsPerMs = peaks.sample_rate / level.samples_per_bucket / 1000
  for (let x = 0; x < width; x += 1) {
    const first = Math.floor(xToTime(view, x) * bucketsPerMs)
    const last = Math.max(first + 1, Math.floor(xToTime(view, x + 1) * bucketsPerMs))
    let low = 0
    let high = 0
    for (let bucket = Math.max(0, first); bucket < last && bucket < level.min.length; bucket += 1) {
      low = Math.min(low, level.min[bucket] ?? 0)
      high = Math.max(high, level.max[bucket] ?? 0)
    }
    min[x] = low
    max[x] = high
  }
  return { min, max }
}

export function formatTime(ms: number, fraction = true): string {
  const total = Math.max(0, ms)
  const minutes = Math.floor(total / 60_000)
  const seconds = Math.floor((total % 60_000) / 1000)
  const base = `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
  return fraction ? `${base}.${String(Math.floor(total % 1000)).padStart(3, '0')}` : base
}

/** Spacing of the ruler's labelled ticks (milliseconds) so that they are ≥ 70 px apart. */
export function rulerStep(pxPerSec: number): number {
  const steps = [100, 200, 500, 1000, 2000, 5000, 10_000, 30_000, 60_000]
  return steps.find((step) => (step / 1000) * pxPerSec >= 70) ?? 120_000
}
