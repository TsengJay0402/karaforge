import { useQuery } from '@tanstack/react-query'
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { LanguageSwitch } from '../App.tsx'
import { api } from '../api/client.ts'
import { activeJobOf, isActive, useJobs, useServerEvents } from '../api/events.ts'
import type { AnalysisData, ProjectDetail, ServerEvent } from '../api/types.ts'
import { ErrorBox, JobProgress } from '../components/common.tsx'
import { useT } from '../i18n/index.ts'
import { EditorContext, type EditorContextValue, useEditor, useEditorState } from './context.ts'
import { ExportDialog, HotkeyHelp, RealignDialog, ShiftDialog } from './Dialogs.tsx'
import {
  clearTiming,
  nextRef,
  nudgeTokens,
  previousRef,
  refAtTime,
  setLocked,
  setTokenEnd,
  tapEnd,
  tapStart,
  tokenAt,
} from './doc.ts'
import { isTyping } from './hotkeys.ts'
import { LyricsPanel } from './LyricsPanel.tsx'
import { Preview } from './Preview.tsx'
import { initialAllowOverlap } from './prefs.ts'
import { type AudioMode, createEditorStore } from './store.ts'
import { ThemePanel } from './ThemePanel.tsx'
import { Timeline } from './Timeline.tsx'
import { formatTime, MAX_ZOOM, MIN_ZOOM } from './timeline.ts'
import { Toolbar } from './Toolbar.tsx'
import { Transport } from './transport.ts'

export type Dialog = 'export' | 'help' | 'shift' | 'realign' | 'theme' | null

/** A small console API (`window.karaforge`) for scripting and for the browser tests. */
export interface ConsoleApi {
  seek: (timeMs: number) => void
  now: () => number
  play: () => Promise<void>
  pause: () => void
}

declare global {
  interface Window {
    karaforge?: ConsoleApi
  }
}

const EMPTY_ANALYSIS: AnalysisData = { onsets_ms: [] }

function sources(detail: ProjectDetail): Partial<Record<AudioMode, string>> {
  const result: Partial<Record<AudioMode, string>> = {}
  if (detail.media.instrumental) result.instrumental = detail.media.instrumental
  const original = detail.media.audio ?? detail.media.source
  if (original) result.original = original
  if (detail.media.vocals) result.vocals = detail.media.vocals
  return result
}

/** Keyboard shortcuts; see `hotkeys.ts` for the list shown to the user. */
function useHotkeys(openDialog: (dialog: Dialog) => void) {
  const { store, transport } = useEditor()
  useEffect(() => {
    const held = new Set<string>()

    const onKeyDown = (event: KeyboardEvent) => {
      if (isTyping(event.target)) return
      const state = store.getState()
      const doc = state.history.present
      const control = event.ctrlKey || event.metaKey
      const key = event.key

      if (control && key.toLowerCase() === 'z') {
        event.preventDefault()
        if (event.shiftKey) state.redo()
        else state.undo()
        return
      }
      if (control && key.toLowerCase() === 'y') {
        event.preventDefault()
        state.redo()
        return
      }
      if (control && key.toLowerCase() === 's') {
        event.preventDefault()
        void state.saveNow()
        return
      }
      if (control) return

      if (key === ' ') {
        event.preventDefault()
        if (state.tapMode === 'off') {
          void transport.toggle()
          return
        }
        const cursor = state.tapCursor
        if (!cursor || !transport.playing) {
          if (!transport.playing) void transport.play()
          return
        }
        if (state.tapMode === 'click') {
          if (event.repeat) return
          const time = transport.now()
          const options = { allowOverlap: state.allowOverlap }
          state.edit((draft) => tapStart(draft, cursor, time, true, options), { label: 'tap' })
          state.setTapCursor(nextRef(doc, cursor))
        } else if (!held.has(' ')) {
          held.add(' ')
          const time = transport.now()
          const options = { allowOverlap: state.allowOverlap }
          state.edit((draft) => tapStart(draft, cursor, time, false, options), { label: 'tap' })
        }
        return
      }

      if (key === 'Escape') {
        if (state.tapMode !== 'off') state.stopTap()
        else state.clearSelection()
        return
      }
      if (key === '?') {
        openDialog('help')
        return
      }
      if (key === '1' || key === '2') {
        const from = state.selection[0] ?? refAtTime(doc, transport.now())
        state.startTap(key === '1' ? 'click' : 'hold', from)
        return
      }
      if (key === '[' || key === ']') {
        transport.seek(transport.now() + (key === '[' ? -2000 : 2000))
        return
      }
      if (key === '+' || key === '=' || key === '-') {
        const factor = key === '-' ? 1 / 1.4 : 1.4
        state.set({ zoom: Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, state.zoom * factor)) })
        return
      }
      if (key === 'Tab') {
        event.preventDefault()
        const from = state.selection[state.selection.length - 1] ?? refAtTime(doc, transport.now())
        const target = from ? (event.shiftKey ? previousRef(doc, from) : nextRef(doc, from)) : null
        const chosen = target ?? from
        if (chosen) {
          state.select(chosen)
          const start = tokenAt(doc, chosen)?.start_ms
          if (start != null && !transport.playing) transport.seek(start)
        }
        return
      }
      if (state.selection.length === 0) return

      if (key === 'ArrowLeft' || key === 'ArrowRight') {
        event.preventDefault()
        const step = (event.shiftKey ? 50 : 10) * (key === 'ArrowLeft' ? -1 : 1)
        const selection = state.selection
        const options = { allowOverlap: state.allowOverlap }
        if (event.altKey) {
          state.edit(
            (draft) => {
              for (const ref of selection) {
                const end = tokenAt(draft, ref)?.end_ms
                if (end != null) setTokenEnd(draft, ref, end + step, options)
              }
            },
            { label: 'nudge end', mergeKey: 'nudge-end' },
          )
        } else {
          state.edit((draft) => nudgeTokens(draft, selection, step, options), { label: 'nudge', mergeKey: 'nudge' })
        }
        return
      }
      if (key === 'Home') {
        const start = state.selection[0] ? tokenAt(doc, state.selection[0])?.start_ms : null
        if (start != null) transport.seek(start)
        return
      }
      if (key.toLowerCase() === 'l') {
        const selection = state.selection
        const allLocked = selection.every((ref) => tokenAt(doc, ref)?.locked)
        state.edit((draft) => setLocked(draft, selection, !allLocked), { label: 'lock' })
        return
      }
      if (key === 'Delete' || key === 'Backspace') {
        event.preventDefault()
        const selection = state.selection
        state.edit((draft) => clearTiming(draft, selection), { label: 'clear timing' })
      }
    }

    const onKeyUp = (event: KeyboardEvent) => {
      if (event.key !== ' ' || !held.delete(' ')) return
      const state = store.getState()
      const cursor = state.tapCursor
      if (state.tapMode !== 'hold' || !cursor) return
      const time = transport.now()
      state.edit((draft) => tapEnd(draft, cursor, time), { label: 'tap' })
      state.setTapCursor(nextRef(state.history.present, cursor))
    }

    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('keyup', onKeyUp)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('keyup', onKeyUp)
    }
  }, [store, transport, openDialog])
}

/** Whether the "these lyrics are a draft" notice of a project was dismissed in this browser. */
function draftNoticeKey(id: string): string {
  return `karaforge.draft-notice.${id}`
}

function readDismissed(id: string): boolean {
  try {
    return window.localStorage.getItem(draftNoticeKey(id)) === '1'
  } catch {
    return false
  }
}

function Banners({ onReload }: { onReload: () => void }) {
  const t = useT()
  const { id, store } = useEditor()
  const isDraft = useEditorState((state) => state.history.present.meta.lyrics_source === 'asr')
  const [dismissed, setDismissed] = useState(() => readDismissed(id))
  const saveState = useEditorState((state) => state.saveState)
  const saveError = useEditorState((state) => state.saveError)
  const tapMode = useEditorState((state) => state.tapMode)
  const jobs = useJobs((state) => state.jobs)
  const job = activeJobOf(jobs, id)
  return (
    <>
      {saveState === 'conflict' ? (
        <div className="banner warning" role="alert">
          <span>{t('editor.conflict')}</span>
          <button type="button" onClick={onReload}>
            {t('editor.conflict.reload')}
          </button>
        </div>
      ) : null}
      {saveState === 'error' && saveError ? (
        <ErrorBox error={saveError}>
          <button type="button" onClick={() => void store.getState().saveNow()}>
            {t('app.retry')}
          </button>
        </ErrorBox>
      ) : null}
      {job && job.kind !== 'export' ? (
        <div className="banner info">
          <span>{t('editor.locked.job')}</span>
          <JobProgress job={job} onCancel={() => void api.cancelJob(job.id)} />
        </div>
      ) : null}
      {isDraft && !dismissed ? (
        <div className="banner info" data-testid="draft-banner">
          <span>{t('editor.draft')}</span>
          <button
            type="button"
            onClick={() => {
              setDismissed(true)
              try {
                window.localStorage.setItem(draftNoticeKey(id), '1')
              } catch {
                // Private windows may refuse storage; the notice then returns on reload.
              }
            }}
          >
            {t('editor.draft.dismiss')}
          </button>
        </div>
      ) : null}
      {tapMode !== 'off' ? (
        <div className="banner tap" data-testid="tap-banner">
          <span>{t(tapMode === 'click' ? 'editor.tap.hint.click' : 'editor.tap.hint.hold')}</span>
          <button type="button" onClick={() => store.getState().stopTap()}>
            {t('editor.tap.stop')}
          </button>
        </div>
      ) : null}
    </>
  )
}

function Workspace({ detail, onReload }: { detail: ProjectDetail; onReload: () => void }) {
  const t = useT()
  const { store, transport } = useEditor()
  const [dialog, setDialog] = useState<Dialog>(null)
  const openDialog = useCallback((next: Dialog) => setDialog(next), [])
  const title = useEditorState((state) => state.history.present.meta.title)
  const [clock, setClock] = useState(0)
  useHotkeys(openDialog)

  useEffect(() => {
    window.karaforge = {
      seek: (timeMs) => transport.seek(timeMs),
      now: () => transport.now(),
      play: () => transport.play(),
      pause: () => transport.pause(),
    }
    return () => {
      delete window.karaforge
    }
  }, [transport])

  useEffect(
    () =>
      transport.subscribe((time, playing) => {
        const state = store.getState()
        if (state.playing !== playing) state.set({ playing })
        state.setCurrent(refAtTime(state.history.present, time))
        setClock((previous) => (Math.abs(previous - time) >= 100 || !playing ? time : previous))
      }),
    [store, transport],
  )

  return (
    <div className="editor">
      <header className="app-header slim">
        <Link to="/" className="button ghost">
          ← {t('list.title')}
        </Link>
        <h1 className="editor-title">{title || detail.summary.id}</h1>
        <span className="mono clock" data-testid="clock">
          {formatTime(clock)} / {formatTime(transport.durationMs, false)}
        </span>
        <LanguageSwitch />
      </header>
      <Toolbar onDialog={openDialog} />
      <Banners onReload={onReload} />
      <div className="editor-top">
        <Preview />
        {dialog === 'theme' ? <ThemePanel onClose={() => setDialog(null)} /> : <LyricsPanel />}
      </div>
      <Timeline />
      {dialog === 'export' ? <ExportDialog onClose={() => setDialog(null)} /> : null}
      {dialog === 'help' ? <HotkeyHelp onClose={() => setDialog(null)} /> : null}
      {dialog === 'shift' ? <ShiftDialog onClose={() => setDialog(null)} /> : null}
      {dialog === 'realign' ? <RealignDialog onClose={() => setDialog(null)} /> : null}
    </div>
  )
}

export function Editor({ detail }: { detail: ProjectDetail }) {
  const id = detail.summary.id
  // Created once per mounted editor (the component is keyed by project id).  Neither
  // constructor has side effects — the transport creates its audio elements on first use —
  // so this is safe in a state initialiser, and both objects stay usable after the cleanup
  // below, which matters when React mounts twice in development.
  const [context] = useState<Omit<EditorContextValue, 'analysis'>>(() => ({
    id,
    media: detail.media,
    store: createEditorStore(detail.project, {
      save: (doc, revision) => api.saveProject(id, doc, revision),
      allowOverlap: initialAllowOverlap(id, detail.project),
    }),
    transport: new Transport({
      sources: sources(detail),
      durationMs: detail.project.meta.duration_ms,
      createAudio: (url) => {
        const audio = new Audio(url)
        audio.preload = 'auto'
        return audio
      },
    }),
  }))
  const analysis = useQuery({ queryKey: ['analysis', id], queryFn: () => api.analysis(id) })
  const jobs = useJobs((state) => state.jobs)
  const busy = (() => {
    const job = activeJobOf(jobs, id)
    return job !== null && job.kind !== 'export'
  })()

  useEffect(() => {
    const { store, transport } = context
    store.getState().set({ audioMode: transport.mode })
    const flush = () => void store.getState().saveNow()
    window.addEventListener('beforeunload', flush)
    return () => {
      window.removeEventListener('beforeunload', flush)
      void store.getState().saveNow()
      transport.stop()
    }
  }, [context])

  const reload = useCallback(async () => {
    const fresh = await api.getProject(id)
    context.store.getState().load(fresh.project)
  }, [context, id])

  useEffect(() => {
    context.store.getState().set({ readOnly: busy })
  }, [context, busy])

  useServerEvents(
    useCallback(
      (event: ServerEvent) => {
        // A job that finished may have rewritten the token times: take the new document.
        if (event.type === 'job' && event.job.project_id === id && event.job.kind === 'align' && !isActive(event.job)) {
          void reload()
        }
      },
      [id, reload],
    ),
  )

  const value: EditorContextValue = { ...context, analysis: analysis.data ?? EMPTY_ANALYSIS }
  return (
    <EditorContext.Provider value={value}>
      <Workspace detail={detail} onReload={() => void reload()} />
    </EditorContext.Provider>
  )
}
