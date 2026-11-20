/**
 * State of one open project in the editor.
 *
 * The document only ever changes through `edit`, which records undo steps, marks the
 * document dirty and schedules an autosave.  Saving sends the revision the document was
 * loaded with (or last saved as); if the server has a newer one — another window or a
 * background job changed the project — nothing is overwritten and the editor shows the
 * conflict instead.
 */
import { createStore, type StoreApi } from 'zustand/vanilla'

import { ApiError } from '../api/client.ts'
import type { ApiErrorBody, Project } from '../api/types.ts'
import { allRefs, refKey, sameRef, type TokenRef, tokenAt } from './doc.ts'
import {
  applyEdit,
  canRedo,
  canUndo,
  createHistory,
  type EditOptions,
  type HistoryState,
  redo,
  undo,
} from './history.ts'

export type SaveState = 'saved' | 'dirty' | 'saving' | 'error' | 'conflict'
export type TapMode = 'off' | 'click' | 'hold'
export type AudioMode = 'instrumental' | 'original' | 'vocals'
export type TrackView = 'waveform' | 'spectrogram'
export type SelectMode = 'replace' | 'toggle' | 'range'

export interface EditorDeps {
  save: (doc: Project, revision: number) => Promise<{ revision: number }>
  autosaveMs?: number
}

export interface EditorState {
  history: HistoryState<Project>
  revision: number
  saved: Project
  saveState: SaveState
  saveError: ApiErrorBody | null
  selection: TokenRef[]
  anchor: TokenRef | null
  current: TokenRef | null
  playing: boolean
  audioMode: AudioMode
  rate: number
  snap: boolean
  trackView: TrackView
  /** Timeline zoom in pixels per second. */
  zoom: number
  tapMode: TapMode
  tapCursor: TokenRef | null
  readOnly: boolean

  edit: (recipe: (draft: Project) => void, options: EditOptions) => void
  undo: () => void
  redo: () => void
  select: (ref: TokenRef, mode?: SelectMode) => void
  selectLine: (lineIndex: number) => void
  setSelection: (refs: TokenRef[]) => void
  clearSelection: () => void
  setCurrent: (ref: TokenRef | null) => void
  set: (
    partial: Partial<
      Pick<EditorState, 'playing' | 'audioMode' | 'rate' | 'snap' | 'trackView' | 'readOnly' | 'zoom'>
    >,
  ) => void
  startTap: (mode: Exclude<TapMode, 'off'>, from: TokenRef | null) => void
  stopTap: () => void
  setTapCursor: (ref: TokenRef | null) => void
  saveNow: () => Promise<void>
  /** Replace the document with what the server has (after a job, or to resolve a conflict). */
  load: (doc: Project) => void
  dispose: () => void
}

export type EditorStore = StoreApi<EditorState>

function unexpected(cause: unknown): ApiErrorBody {
  return {
    code: 'client_error',
    message_zh: '儲存時發生沒有預期到的錯誤。',
    message_en: 'An unexpected error occurred while saving.',
    hint_zh: null,
    hint_en: null,
    detail: cause instanceof Error ? cause.message : String(cause),
  }
}

/** Selected line indices, ascending. */
export function selectedLines(selection: TokenRef[]): number[] {
  return [...new Set(selection.map((ref) => ref.line))].sort((a, b) => a - b)
}

export function createEditorStore(doc: Project, deps: EditorDeps): EditorStore {
  const autosaveMs = deps.autosaveMs ?? 1000
  let timer: ReturnType<typeof setTimeout> | null = null
  let saving: Promise<void> | null = null
  let disposed = false

  const store = createStore<EditorState>((set, get) => {
    const schedule = () => {
      if (timer !== null) clearTimeout(timer)
      if (disposed) return
      timer = setTimeout(() => {
        timer = null
        void get().saveNow()
      }, autosaveMs)
    }

    const afterChange = (history: HistoryState<Project>) => {
      const state = get()
      // Keep the selection valid: tokens may have disappeared.
      const selection = state.selection.filter((ref) => tokenAt(history.present, ref) !== undefined)
      const dirty = history.present !== state.saved
      const blocked = state.saveState === 'conflict'
      set({
        history,
        selection,
        saveState: blocked ? 'conflict' : dirty ? 'dirty' : 'saved',
      })
      if (dirty && !blocked) schedule()
    }

    return {
      history: createHistory(doc),
      revision: doc.revision,
      saved: doc,
      saveState: 'saved',
      saveError: null,
      selection: [],
      anchor: null,
      current: null,
      playing: false,
      audioMode: 'instrumental',
      rate: 1,
      snap: true,
      trackView: 'waveform',
      zoom: 120,
      tapMode: 'off',
      tapCursor: null,
      readOnly: false,

      edit: (recipe, options) => {
        const state = get()
        if (state.readOnly) return
        const next = applyEdit(state.history, recipe, options)
        if (next !== state.history) afterChange(next)
      },
      undo: () => {
        const state = get()
        if (!state.readOnly && canUndo(state.history)) afterChange(undo(state.history))
      },
      redo: () => {
        const state = get()
        if (!state.readOnly && canRedo(state.history)) afterChange(redo(state.history))
      },

      select: (ref, mode = 'replace') => {
        const state = get()
        if (mode === 'toggle') {
          const exists = state.selection.some((item) => sameRef(item, ref))
          set({
            selection: exists
              ? state.selection.filter((item) => !sameRef(item, ref))
              : [...state.selection, ref],
            anchor: ref,
          })
          return
        }
        if (mode === 'range' && state.anchor) {
          const order = allRefs(state.history.present)
          const from = order.findIndex((item) => sameRef(item, state.anchor as TokenRef))
          const to = order.findIndex((item) => sameRef(item, ref))
          if (from >= 0 && to >= 0) {
            set({ selection: order.slice(Math.min(from, to), Math.max(from, to) + 1) })
            return
          }
        }
        set({ selection: [ref], anchor: ref })
      },
      selectLine: (lineIndex) => {
        const line = get().history.present.lines[lineIndex]
        if (!line) return
        const refs = line.tokens.map((_token, index) => ({ line: lineIndex, index }))
        set({ selection: refs, anchor: refs[0] ?? null })
      },
      setSelection: (refs) => {
        const unique = new Map(refs.map((ref) => [refKey(ref), ref]))
        set({ selection: [...unique.values()], anchor: refs[0] ?? null })
      },
      clearSelection: () => set({ selection: [], anchor: null }),
      setCurrent: (ref) => {
        const current = get().current
        if (ref === current || (ref && current && sameRef(ref, current))) return
        set({ current: ref })
      },
      set: (partial) => set(partial),

      startTap: (mode, from) => {
        const doc = get().history.present
        const first = from ?? allRefs(doc)[0] ?? null
        set({ tapMode: mode, tapCursor: first, selection: first ? [first] : [] })
      },
      stopTap: () => set({ tapMode: 'off', tapCursor: null }),
      setTapCursor: (ref) => set({ tapCursor: ref, selection: ref ? [ref] : [] }),

      saveNow: async () => {
        if (timer !== null) {
          clearTimeout(timer)
          timer = null
        }
        if (saving) {
          await saving
        }
        const state = get()
        if (state.saveState === 'conflict' || state.history.present === state.saved) return
        const sending = state.history.present
        set({ saveState: 'saving', saveError: null })
        saving = (async () => {
          try {
            const result = await deps.save(sending, get().revision)
            const now = get()
            const still = now.history.present !== sending
            set({ revision: result.revision, saved: sending, saveState: still ? 'dirty' : 'saved' })
            if (still) schedule()
          } catch (cause) {
            if (cause instanceof ApiError && cause.conflict) {
              set({ saveState: 'conflict', saveError: cause.body })
            } else {
              set({
                saveState: 'error',
                saveError: cause instanceof ApiError ? cause.body : unexpected(cause),
              })
            }
          } finally {
            saving = null
          }
        })()
        await saving
      },

      load: (fresh) => {
        if (timer !== null) {
          clearTimeout(timer)
          timer = null
        }
        const state = get()
        set({
          history: createHistory(fresh),
          revision: fresh.revision,
          saved: fresh,
          saveState: 'saved',
          saveError: null,
          selection: state.selection.filter((ref) => tokenAt(fresh, ref) !== undefined),
          tapMode: 'off',
          tapCursor: null,
        })
      },

      dispose: () => {
        disposed = true
        if (timer !== null) clearTimeout(timer)
        timer = null
      },
    }
  })
  return store
}
