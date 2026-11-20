/**
 * The timeline: ruler, waveform (or spectrogram) of the vocal stem, detected onsets, and one
 * draggable block per token.  Everything is drawn on a single canvas; the pure geometry
 * (time ↔ pixels, hit testing, waveform columns) lives in `timeline.ts`.
 */
import { useQuery } from '@tanstack/react-query'
import { type PointerEvent, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'

import { api } from '../api/client.ts'
import type { Project, Token } from '../api/types.ts'
import { useEditor, useEditorState } from './context.ts'
import { isTimed, moveToken, refKey, sameRef, setTokenEnd, setTokenStart, type TokenRef, tokenAt } from './doc.ts'
import type { SelectMode } from './store.ts'
import { confidenceClass } from './tokens.ts'
import {
  type Block,
  blocks,
  clampView,
  follow,
  formatTime,
  type Hit,
  hitTest,
  rulerStep,
  snapToOnset,
  timeToX,
  type View,
  visibleMs,
  waveformColumns,
  xToTime,
  zoomAt,
} from './timeline.ts'

const RULER_H = 22
const WAVE_H = 92
const ROW_H = 30
const ROW_GAP = 4
const ROWS_TOP = RULER_H + WAVE_H + 6
export const TIMELINE_HEIGHT = ROWS_TOP + 2 * ROW_H + ROW_GAP + 6
const SNAP_PX = 8
const DRAG_THRESHOLD_PX = 3

const COLORS = {
  background: '#14161d',
  ruler: '#1c1f29',
  rulerText: '#9aa3b5',
  grid: '#262a36',
  wave: '#4f8cff',
  onset: 'rgba(255, 225, 77, 0.55)',
  playhead: '#ff5b5b',
  text: '#f2f4f8',
  selected: '#ffffff',
  ok: '#2c8f7b',
  mid: '#b7892b',
  low: '#b8463f',
  locked: '#3d6fd1',
  current: '#ffe14d',
} as const

function rowOf(y: number): number | null {
  if (y < ROWS_TOP) return null
  const offset = y - ROWS_TOP
  if (offset < ROW_H) return 0
  if (offset >= ROW_H + ROW_GAP && offset < 2 * ROW_H + ROW_GAP) return 1
  return null
}

function blockColor(token: Token): string {
  const kind = confidenceClass(token)
  if (kind === 'locked') return COLORS.locked
  if (kind === 'low') return COLORS.low
  if (kind === 'mid') return COLORS.mid
  return COLORS.ok
}

interface Drag {
  kind: 'token' | 'scrub'
  hit?: Hit
  originX: number
  startMs: number
  endMs: number
  moved: boolean
}

interface Tile {
  image: HTMLImageElement
  ready: boolean
}

function tileDuration(pxPerSec: number): number {
  return [10_000, 5000, 2000, 1000].find((ms) => (ms / 1000) * pxPerSec <= 2048) ?? 1000
}

function selectModeOf(event: PointerEvent): SelectMode {
  if (event.shiftKey) return 'range'
  return event.ctrlKey || event.metaKey ? 'toggle' : 'replace'
}

export function Timeline() {
  const { id, store, transport, media, analysis } = useEditor()
  const doc = useEditorState((state) => state.history.present)
  const selection = useEditorState((state) => state.selection)
  const current = useEditorState((state) => state.current)
  const zoom = useEditorState((state) => state.zoom)
  const snap = useEditorState((state) => state.snap)
  const trackView = useEditorState((state) => state.trackView)
  const readOnly = useEditorState((state) => state.readOnly)
  const stem = media.vocals ? 'vocals' : 'audio'
  const hasStem = media.vocals !== null || media.audio !== null
  const peaks = useQuery({
    queryKey: ['peaks', id, stem],
    queryFn: () => api.peaks(id, stem),
    enabled: hasStem,
  })

  const canvas = useRef<HTMLCanvasElement>(null)
  const drag = useRef<Drag | null>(null)
  const tiles = useRef(new Map<string, Tile>())
  const [width, setWidth] = useState(800)
  const [startMs, setStartMs] = useState(0)
  const [cursor, setCursor] = useState('default')
  const [, setTileTick] = useState(0)
  const durationMs = Math.max(doc.meta.duration_ms, 1000)
  const view: View = clampView({ startMs, pxPerSec: zoom, width }, durationMs)

  // Keep everything the draw function needs in a ref, so that the animation-frame loop
  // always sees the latest values without being re-created.
  const latest = useRef({ doc, selection, current, view, snap, trackView, peaks: peaks.data, analysis })

  const draw = useCallback(() => {
    const element = canvas.current
    const context = element?.getContext('2d')
    if (!element || !context) return
    const state = latest.current
    const ratio = window.devicePixelRatio || 1
    const pixelWidth = Math.round(state.view.width * ratio)
    const pixelHeight = Math.round(TIMELINE_HEIGHT * ratio)
    if (element.width !== pixelWidth || element.height !== pixelHeight) {
      element.width = pixelWidth
      element.height = pixelHeight
    }
    context.setTransform(ratio, 0, 0, ratio, 0, 0)
    const w = state.view.width
    context.fillStyle = COLORS.background
    context.fillRect(0, 0, w, TIMELINE_HEIGHT)

    // Ruler.
    context.fillStyle = COLORS.ruler
    context.fillRect(0, 0, w, RULER_H)
    const step = rulerStep(state.view.pxPerSec)
    const firstTick = Math.floor(state.view.startMs / step) * step
    context.font = '11px ui-monospace, monospace'
    context.textBaseline = 'middle'
    for (let tick = firstTick; tick < state.view.startMs + visibleMs(state.view); tick += step) {
      const x = Math.round(timeToX(state.view, tick)) + 0.5
      context.strokeStyle = COLORS.grid
      context.beginPath()
      context.moveTo(x, RULER_H - 6)
      context.lineTo(x, TIMELINE_HEIGHT)
      context.stroke()
      context.fillStyle = COLORS.rulerText
      context.fillText(formatTime(tick, step < 1000).replace(/\.(\d)\d\d$/, '.$1'), x + 4, RULER_H / 2)
    }

    // Waveform or spectrogram.
    if (state.trackView === 'spectrogram') {
      const duration = tileDuration(state.view.pxPerSec)
      const first = Math.floor(state.view.startMs / duration)
      const last = Math.floor((state.view.startMs + visibleMs(state.view)) / duration)
      for (let index = first; index <= last; index += 1) {
        const tile = tiles.current.get(`${duration}:${index}`)
        if (!tile?.ready) continue
        const x = timeToX(state.view, index * duration)
        const tileWidth = (duration / 1000) * state.view.pxPerSec
        context.drawImage(tile.image, x, RULER_H, tileWidth, WAVE_H)
      }
    } else if (state.peaks) {
      const columns = waveformColumns(state.peaks, state.view)
      const middle = RULER_H + WAVE_H / 2
      const scale = WAVE_H / 2 / 127
      context.fillStyle = COLORS.wave
      for (let x = 0; x < columns.max.length; x += 1) {
        const top = (columns.max[x] ?? 0) * scale
        const bottom = (columns.min[x] ?? 0) * scale
        context.fillRect(x, middle - top, 1, Math.max(1, top - bottom))
      }
    }

    // Onsets.
    context.fillStyle = COLORS.onset
    const endMs = state.view.startMs + visibleMs(state.view)
    for (const onset of state.analysis.onsets_ms) {
      if (onset < state.view.startMs) continue
      if (onset > endMs) break
      context.fillRect(Math.round(timeToX(state.view, onset)), RULER_H + WAVE_H - 10, 1, 10)
    }

    // Token blocks.
    const selected = new Set(state.selection.map(refKey))
    context.font = '14px system-ui, sans-serif'
    for (const block of blocks(state.doc, state.view)) {
      const token = tokenAt(state.doc, block.ref)
      if (!token) continue
      const y = ROWS_TOP + block.row * (ROW_H + ROW_GAP)
      const isCurrent = state.current !== null && sameRef(state.current, block.ref)
      context.fillStyle = blockColor(token)
      context.globalAlpha = isCurrent ? 1 : 0.82
      context.fillRect(block.x, y, Math.max(1, block.width - 1), ROW_H)
      context.globalAlpha = 1
      if (selected.has(refKey(block.ref)) || isCurrent) {
        context.strokeStyle = isCurrent ? COLORS.current : COLORS.selected
        context.lineWidth = 2
        context.strokeRect(block.x + 1, y + 1, Math.max(1, block.width - 3), ROW_H - 2)
        context.lineWidth = 1
      }
      if (block.width >= 14) {
        context.save()
        context.beginPath()
        context.rect(block.x, y, block.width - 1, ROW_H)
        context.clip()
        context.fillStyle = COLORS.text
        context.fillText(token.text.trim(), block.x + 4, y + ROW_H / 2 + 1)
        context.restore()
      }
    }

    // Playhead.
    const playX = Math.round(timeToX(state.view, transport.now())) + 0.5
    context.strokeStyle = COLORS.playhead
    context.lineWidth = 2
    context.beginPath()
    context.moveTo(playX, 0)
    context.lineTo(playX, TIMELINE_HEIGHT)
    context.stroke()
    context.lineWidth = 1
  }, [transport])

  // After every render: remember what is shown now, and redraw.
  useLayoutEffect(() => {
    latest.current = { doc, selection, current, view, snap, trackView, peaks: peaks.data, analysis }
    draw()
  })

  // Follow the canvas width.
  useEffect(() => {
    const element = canvas.current?.parentElement
    if (!element) return
    const observer = new ResizeObserver(() => setWidth(Math.max(200, element.clientWidth)))
    observer.observe(element)
    setWidth(Math.max(200, element.clientWidth))
    return () => observer.disconnect()
  }, [])

  // The playhead: redraw on every tick and keep it in view while playing.
  useEffect(
    () =>
      transport.subscribe((time, playing) => {
        if (playing && drag.current === null) {
          const state = latest.current
          const followed = follow(state.view, time, Math.max(state.doc.meta.duration_ms, 1000))
          if (followed !== state.view) setStartMs(followed.startMs)
        }
        draw()
      }),
    [transport, draw],
  )

  // Spectrogram tiles are fetched for what is visible.
  useEffect(() => {
    if (trackView !== 'spectrogram' || !hasStem) return
    const duration = tileDuration(view.pxPerSec)
    const first = Math.floor(view.startMs / duration)
    const last = Math.floor((view.startMs + visibleMs(view)) / duration)
    for (let index = Math.max(0, first); index <= last && index * duration < durationMs; index += 1) {
      const key = `${duration}:${index}`
      if (tiles.current.has(key)) continue
      const image = new Image()
      const tile: Tile = { image, ready: false }
      tiles.current.set(key, tile)
      image.onload = () => {
        tile.ready = true
        setTileTick((value) => value + 1)
      }
      const tileWidth = Math.min(2048, Math.round((duration / 1000) * view.pxPerSec))
      image.src = api.spectrogramUrl(id, stem, index * duration, (index + 1) * duration, Math.max(64, tileWidth))
    }
  }, [trackView, hasStem, view.startMs, view.pxPerSec, view.width, durationMs, id, stem, view])

  // Ctrl + wheel zooms around the pointer, a plain wheel scrolls.
  useEffect(() => {
    const element = canvas.current
    if (!element) return
    const onWheel = (event: WheelEvent) => {
      event.preventDefault()
      const state = latest.current
      const duration = Math.max(state.doc.meta.duration_ms, 1000)
      if (event.ctrlKey || event.metaKey) {
        const rect = element.getBoundingClientRect()
        const zoomed = zoomAt(state.view, event.deltaY < 0 ? 1.25 : 0.8, event.clientX - rect.left, duration)
        store.getState().set({ zoom: zoomed.pxPerSec })
        setStartMs(zoomed.startMs)
      } else {
        const deltaPx = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY
        const moved = clampView(
          { ...state.view, startMs: state.view.startMs + (deltaPx / state.view.pxPerSec) * 1000 },
          duration,
        )
        setStartMs(moved.startMs)
      }
    }
    element.addEventListener('wheel', onWheel, { passive: false })
    return () => element.removeEventListener('wheel', onWheel)
  }, [store])

  const position = (event: PointerEvent): { x: number; y: number } => {
    const rect = event.currentTarget.getBoundingClientRect()
    return { x: event.clientX - rect.left, y: event.clientY - rect.top }
  }

  const hitAt = (x: number, y: number): Hit | null => {
    const row = rowOf(y)
    if (row === null) return null
    const list: Block[] = blocks(doc, view)
    return hitTest(list, x, row)
  }

  const snapped = (timeMs: number): number => {
    if (!snap) return timeMs
    return snapToOnset(analysis.onsets_ms, timeMs, (SNAP_PX / view.pxPerSec) * 1000)
  }

  const onPointerDown = (event: PointerEvent<HTMLCanvasElement>) => {
    if (event.button !== 0) return
    const { x, y } = position(event)
    const hit = hitAt(x, y)
    event.currentTarget.setPointerCapture(event.pointerId)
    if (hit) {
      const token = tokenAt(doc, hit.ref)
      const state = store.getState()
      const already = state.selection.some((item) => sameRef(item, hit.ref))
      const mode = selectModeOf(event)
      if (mode !== 'replace' || !already) state.select(hit.ref, mode)
      if (state.tapMode !== 'off') state.setTapCursor(hit.ref)
      if (isTimed(token)) {
        drag.current = {
          kind: 'token',
          hit,
          originX: x,
          startMs: token.start_ms,
          endMs: token.end_ms,
          moved: false,
        }
      }
      return
    }
    drag.current = { kind: 'scrub', originX: x, startMs: 0, endMs: 0, moved: false }
    transport.seek(xToTime(view, x))
  }

  const onPointerMove = (event: PointerEvent<HTMLCanvasElement>) => {
    const { x, y } = position(event)
    const active = drag.current
    if (!active) {
      const hit = hitAt(x, y)
      setCursor(hit ? (hit.part === 'body' ? 'grab' : 'ew-resize') : 'default')
      return
    }
    if (active.kind === 'scrub') {
      transport.seek(xToTime(view, x))
      return
    }
    const hit = active.hit
    if (!hit || readOnly) return
    if (!active.moved && Math.abs(x - active.originX) < DRAG_THRESHOLD_PX) return
    active.moved = true
    const delta = ((x - active.originX) / view.pxPerSec) * 1000
    const ref: TokenRef = hit.ref
    const mergeKey = `drag:${refKey(ref)}:${hit.part}`
    const edit = store.getState().edit
    if (hit.part === 'start') {
      const target = snapped(active.startMs + delta)
      edit((draft: Project) => setTokenStart(draft, ref, target), { label: 'drag start', mergeKey })
    } else if (hit.part === 'end') {
      const target = snapped(active.endMs + delta)
      edit((draft: Project) => setTokenEnd(draft, ref, target), { label: 'drag end', mergeKey })
    } else {
      const target = snapped(active.startMs + delta)
      edit(
        (draft: Project) => {
          const now = tokenAt(draft, ref)?.start_ms
          if (now != null) moveToken(draft, ref, target - now)
        },
        { label: 'drag', mergeKey },
      )
    }
  }

  const onPointerUp = (event: PointerEvent<HTMLCanvasElement>) => {
    const active = drag.current
    drag.current = null
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
    if (active?.kind === 'token' && !active.moved && active.hit) {
      // A plain click on a block: go there.
      const mode = selectModeOf(event)
      if (mode === 'replace') store.getState().select(active.hit.ref)
      transport.seek(active.startMs)
    }
  }

  const onDoubleClick = () => {
    void transport.play()
  }

  return (
    <section className="timeline" aria-label="timeline">
      <canvas
        ref={canvas}
        data-testid="timeline"
        data-start-ms={Math.round(view.startMs)}
        data-px-per-sec={view.pxPerSec}
        data-rows-top={ROWS_TOP}
        data-row-height={ROW_H}
        data-row-gap={ROW_GAP}
        style={{ width: '100%', height: TIMELINE_HEIGHT, cursor, touchAction: 'none' }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onDoubleClick={onDoubleClick}
      />
      <input
        className="timeline-scroll"
        type="range"
        aria-label="scroll"
        min={0}
        max={Math.max(0, Math.round(durationMs - visibleMs(view) * 0.5))}
        step={10}
        value={Math.round(view.startMs)}
        onChange={(event) => setStartMs(Number(event.target.value))}
      />
    </section>
  )
}
