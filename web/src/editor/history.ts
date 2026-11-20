/**
 * Undo / redo built on immer patches.
 *
 * Every edit is applied through `History.apply`, which records the patches and their
 * inverses.  Edits that carry the same `mergeKey` within a short time (dragging a token,
 * holding an arrow key) are folded into one step, so one undo reverts the whole gesture.
 */
import { applyPatches, enablePatches, type Patch, produceWithPatches } from 'immer'

enablePatches()

export interface Step {
  label: string
  mergeKey: string | null
  at: number
  patches: Patch[]
  inverse: Patch[]
}

export interface HistoryState<T> {
  present: T
  past: Step[]
  future: Step[]
}

export const MERGE_WINDOW_MS = 800
export const MAX_STEPS = 300

export function createHistory<T>(present: T): HistoryState<T> {
  return { present, past: [], future: [] }
}

export interface EditOptions {
  label: string
  /** Edits with the same key that follow each other quickly become one undo step. */
  mergeKey?: string
  now?: number
}

export function applyEdit<T>(
  state: HistoryState<T>,
  recipe: (draft: T) => void,
  options: EditOptions,
): HistoryState<T> {
  const [next, patches, inverse] = produceWithPatches(state.present, recipe as (draft: unknown) => void) as [
    T,
    Patch[],
    Patch[],
  ]
  if (patches.length === 0) return state
  const now = options.now ?? Date.now()
  const last = state.past[state.past.length - 1]
  const mergeKey = options.mergeKey ?? null
  if (last && mergeKey !== null && last.mergeKey === mergeKey && now - last.at <= MERGE_WINDOW_MS) {
    const merged: Step = {
      ...last,
      at: now,
      patches: [...last.patches, ...patches],
      inverse: [...inverse, ...last.inverse],
    }
    return { present: next, past: [...state.past.slice(0, -1), merged], future: [] }
  }
  const step: Step = { label: options.label, mergeKey, at: now, patches, inverse }
  return { present: next, past: [...state.past, step].slice(-MAX_STEPS), future: [] }
}

export function undo<T>(state: HistoryState<T>): HistoryState<T> {
  const step = state.past[state.past.length - 1]
  if (!step) return state
  return {
    present: applyPatches(state.present as object, step.inverse) as T,
    past: state.past.slice(0, -1),
    future: [...state.future, { ...step, mergeKey: null }],
  }
}

export function redo<T>(state: HistoryState<T>): HistoryState<T> {
  const step = state.future[state.future.length - 1]
  if (!step) return state
  return {
    present: applyPatches(state.present as object, step.patches) as T,
    past: [...state.past, { ...step, mergeKey: null }],
    future: state.future.slice(0, -1),
  }
}

export const canUndo = <T,>(state: HistoryState<T>) => state.past.length > 0
export const canRedo = <T,>(state: HistoryState<T>) => state.future.length > 0
