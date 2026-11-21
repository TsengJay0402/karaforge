import { project, timedLine } from '../test/fixtures.ts'
import {
  blocks,
  chooseLevel,
  clampView,
  follow,
  formatTime,
  hitTest,
  reveal,
  rulerStep,
  snapToOnset,
  timeToX,
  type View,
  visibleMs,
  waveformColumns,
  xToTime,
  zoomAt,
} from './timeline.ts'

const view: View = { startMs: 2000, pxPerSec: 100, width: 800 }

describe('time and pixels', () => {
  it('converts both ways', () => {
    expect(timeToX(view, 2000)).toBe(0)
    expect(timeToX(view, 3500)).toBe(150)
    expect(xToTime(view, 150)).toBe(3500)
    expect(visibleMs(view)).toBe(8000)
  })

  it('zooms around the pointer', () => {
    const zoomed = zoomAt(view, 2, 400, 60_000)
    expect(zoomed.pxPerSec).toBe(200)
    expect(xToTime(zoomed, 400)).toBeCloseTo(xToTime(view, 400))
    expect(zoomAt(view, 1000, 0, 60_000).pxPerSec).toBe(1200)
    expect(zoomAt(view, 0.0001, 0, 60_000).pxPerSec).toBe(10)
  })

  it('keeps the view inside the song', () => {
    expect(clampView({ ...view, startMs: -500 }, 60_000).startMs).toBe(0)
    expect(clampView({ ...view, startMs: 99_000 }, 60_000).startMs).toBe(56_000)
  })

  it('reveals a time that is out of view and leaves a visible one alone', () => {
    // Visible: nothing moves, even right at the edge (unlike follow, which keeps a margin).
    expect(reveal(view, 5000, 60_000)).toBe(view)
    expect(reveal(view, view.startMs + 1, 60_000)).toBe(view)
    expect(reveal(view, 9900, 60_000)).toBe(view)
    // Out of view: the time ends up a quarter of the way in.
    const later = reveal(view, 30_000, 60_000)
    expect(later.startMs).toBe(30_000 - visibleMs(view) * 0.25)
    expect(reveal({ ...view, startMs: 20_000 }, 1000, 60_000).startMs).toBe(0)
    // Never further than the view is allowed to go at the end of the song.
    expect(reveal(view, 59_900, 60_000).startMs).toBe(56_000)
  })

  it('follows the playhead only when it leaves the comfortable area', () => {
    expect(follow(view, 5000, 60_000)).toBe(view)
    expect(follow(view, 9900, 60_000).startMs).toBe(7900)
    expect(follow(view, 1000, 60_000).startMs).toBe(0)
  })

  it('formats times and picks ruler steps', () => {
    expect(formatTime(83_456)).toBe('01:23.456')
    expect(formatTime(83_456, false)).toBe('01:23')
    expect(formatTime(-5)).toBe('00:00.000')
    expect(rulerStep(100)).toBe(1000)
    expect(rulerStep(1000)).toBe(100)
    expect(rulerStep(10)).toBe(10_000)
  })
})

describe('token blocks', () => {
  const doc = project([
    timedLine('L001', ['一', '二', '三'], 2500, 500),
    timedLine('L002', ['四'], 4000, 1000),
    timedLine('L003', ['五'], 30_000, 400),
  ])

  it('lists the visible tokens with alternating rows per line', () => {
    const list = blocks(doc, view)
    expect(list.map((block) => [block.ref.line, block.ref.index, block.x, block.width, block.row])).toEqual([
      [0, 0, 50, 50, 0],
      [0, 1, 100, 50, 0],
      [0, 2, 150, 50, 0],
      [1, 0, 200, 100, 1],
    ])
  })

  it('tells the body of a token from its edges', () => {
    const list = blocks(doc, view)
    expect(hitTest(list, 75, 0)).toEqual({ ref: { line: 0, index: 0 }, part: 'body' })
    expect(hitTest(list, 52, 0)).toEqual({ ref: { line: 0, index: 0 }, part: 'start' })
    // Where two tokens touch, the boundary is the start of the later one, from either side.
    expect(hitTest(list, 148, 0)).toEqual({ ref: { line: 0, index: 2 }, part: 'start' })
    expect(hitTest(list, 152, 0)).toEqual({ ref: { line: 0, index: 2 }, part: 'start' })
    // The end of a token nothing follows on its row is its own.
    expect(hitTest(list, 198, 0)).toEqual({ ref: { line: 0, index: 2 }, part: 'end' })
    expect(hitTest(list, 296, 1)).toEqual({ ref: { line: 1, index: 0 }, part: 'end' })
    expect(hitTest(list, 250, 1)).toEqual({ ref: { line: 1, index: 0 }, part: 'body' })
    expect(hitTest(list, 250, 0)).toBeNull()
    expect(hitTest(list, 700, 1)).toBeNull()
  })
})

describe('snapping', () => {
  const onsets = [1000, 1400, 2000]

  it('moves to the nearest onset within the tolerance', () => {
    expect(snapToOnset(onsets, 1030, 60)).toBe(1000)
    expect(snapToOnset(onsets, 1380, 60)).toBe(1400)
    expect(snapToOnset(onsets, 1200, 60)).toBe(1200)
    expect(snapToOnset(onsets, 2500, 60)).toBe(2500)
    expect(snapToOnset(onsets, 950, 60)).toBe(1000)
    expect(snapToOnset([], 950, 60)).toBe(950)
    expect(snapToOnset(onsets, 1030, 0)).toBe(1030)
  })
})

describe('waveform', () => {
  const peaks = {
    sample_rate: 1000,
    length: 8000,
    levels: [
      { samples_per_bucket: 10, min: Array.from({ length: 800 }, (_v, i) => -(i % 100)), max: Array.from({ length: 800 }, (_v, i) => i % 100) },
      { samples_per_bucket: 100, min: Array.from({ length: 80 }, () => -99), max: Array.from({ length: 80 }, () => 99) },
    ],
  }

  it('uses the finest level that is not finer than a pixel', () => {
    expect(chooseLevel(peaks, 100)?.samples_per_bucket).toBe(10)
    expect(chooseLevel(peaks, 10)?.samples_per_bucket).toBe(100)
    expect(chooseLevel(peaks, 5000)?.samples_per_bucket).toBe(10)
    expect(chooseLevel({ ...peaks, levels: [] }, 100)).toBeNull()
  })

  it('reduces buckets to one minimum and maximum per pixel', () => {
    const columns = waveformColumns(peaks, { startMs: 0, pxPerSec: 100, width: 4 })
    // 100 px/s at 1 kHz: 10 samples = 1 bucket per pixel.
    expect(Array.from(columns.max)).toEqual([0, 1, 2, 3])
    expect(Array.from(columns.min)).toEqual([0, -1, -2, -3])
    const coarse = waveformColumns(peaks, { startMs: 0, pxPerSec: 50, width: 2 })
    expect(Array.from(coarse.max)).toEqual([1, 3])
    const beyond = waveformColumns(peaks, { startMs: 7990, pxPerSec: 100, width: 3 })
    expect(Array.from(beyond.max)).toEqual([99, 0, 0])
  })
})
