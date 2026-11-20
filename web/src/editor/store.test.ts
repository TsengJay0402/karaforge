import { ApiError } from '../api/client.ts'
import type { Project } from '../api/types.ts'
import { project, timedLine, times } from '../test/fixtures.ts'
import { setTokenStart } from './doc.ts'
import { createEditorStore, selectedLines } from './store.ts'

const song = () =>
  project([timedLine('L001', ['一', '二', '三'], 1000), timedLine('L002', ['四', '五'], 4000)])

function conflict(): ApiError {
  return new ApiError(409, {
    code: 'revision_conflict',
    message_zh: '衝突',
    message_en: 'Conflict',
    hint_zh: null,
    hint_en: null,
    detail: null,
  })
}

function setup(save?: (doc: Project, revision: number) => Promise<{ revision: number }>) {
  const calls: { doc: Project; revision: number }[] = []
  const store = createEditorStore(song(), {
    autosaveMs: 500,
    save:
      save ??
      ((doc, revision) => {
        calls.push({ doc, revision })
        return Promise.resolve({ revision: revision + 1 })
      }),
  })
  const move = (ms: number) => {
    store.getState().edit((draft) => setTokenStart(draft, { line: 0, index: 1 }, ms), {
      label: 'move',
      mergeKey: 'drag',
    })
  }
  return { store, calls, move }
}

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

describe('editing and undo', () => {
  it('applies edits, undoes and redoes them', () => {
    const { store, move } = setup()
    move(1500)
    expect(times(store.getState().history.present.lines[0])[1]).toEqual(['二', 1500, 1800])
    expect(store.getState().saveState).toBe('dirty')
    store.getState().undo()
    expect(times(store.getState().history.present.lines[0])[1]).toEqual(['二', 1400, 1800])
    store.getState().redo()
    expect(times(store.getState().history.present.lines[0])[1]).toEqual(['二', 1500, 1800])
    expect(store.getState().saveState).toBe('dirty')
    store.getState().dispose()
  })

  it('refuses edits while a background job owns the project', () => {
    const { store, move } = setup()
    store.getState().set({ readOnly: true })
    move(1500)
    store.getState().undo()
    expect(store.getState().history.past).toHaveLength(0)
    expect(store.getState().saveState).toBe('saved')
  })
})

describe('autosave', () => {
  it('saves once after a burst of edits, with the revision it knows', async () => {
    const { store, calls, move } = setup()
    move(1450)
    vi.advanceTimersByTime(300)
    move(1500)
    vi.advanceTimersByTime(300)
    expect(calls).toHaveLength(0)
    await vi.advanceTimersByTimeAsync(300)
    expect(calls).toHaveLength(1)
    expect(calls[0]?.revision).toBe(0)
    expect(store.getState()).toMatchObject({ saveState: 'saved', revision: 1 })

    move(1600)
    await vi.advanceTimersByTimeAsync(600)
    expect(calls[1]?.revision).toBe(1)
    expect(store.getState().revision).toBe(2)
  })

  it('saves again when the document changed while a save was on its way', async () => {
    let release: (() => void) | undefined
    const revisions: number[] = []
    const { store, move } = setup((_doc, revision) => {
      revisions.push(revision)
      return new Promise((resolve) => {
        release = () => resolve({ revision: revision + 1 })
      })
    })
    move(1500)
    await vi.advanceTimersByTimeAsync(600)
    expect(store.getState().saveState).toBe('saving')
    move(1600)
    release?.()
    await vi.advanceTimersByTimeAsync(0)
    expect(store.getState().saveState).toBe('dirty')
    await vi.advanceTimersByTimeAsync(600)
    release?.()
    await vi.advanceTimersByTimeAsync(0)
    expect(revisions).toEqual([0, 1])
    expect(store.getState()).toMatchObject({ saveState: 'saved', revision: 2 })
  })

  it('stops saving on a revision conflict until the project is reloaded', async () => {
    let attempts = 0
    const { store, move } = setup(() => {
      attempts += 1
      return Promise.reject(conflict())
    })
    move(1500)
    await vi.advanceTimersByTimeAsync(600)
    expect(store.getState().saveState).toBe('conflict')
    expect(store.getState().saveError?.code).toBe('revision_conflict')
    move(1600)
    await vi.advanceTimersByTimeAsync(2000)
    expect(attempts).toBe(1)

    const fresh = { ...song(), revision: 7 }
    store.getState().load(fresh)
    expect(store.getState()).toMatchObject({ saveState: 'saved', revision: 7 })
    expect(store.getState().history.past).toHaveLength(0)
  })

  it('reports other failures and retries with the next edit', async () => {
    let fail = true
    const { store, move } = setup((_doc, revision) =>
      fail ? Promise.reject(new Error('offline')) : Promise.resolve({ revision: revision + 1 }),
    )
    move(1500)
    await vi.advanceTimersByTimeAsync(600)
    expect(store.getState().saveState).toBe('error')
    expect(store.getState().saveError?.detail).toBe('offline')
    fail = false
    move(1600)
    await vi.advanceTimersByTimeAsync(600)
    expect(store.getState().saveState).toBe('saved')
  })

  it('saves immediately on request and does nothing when clean', async () => {
    const { store, calls, move } = setup()
    await store.getState().saveNow()
    expect(calls).toHaveLength(0)
    move(1500)
    await store.getState().saveNow()
    expect(calls).toHaveLength(1)
    await vi.advanceTimersByTimeAsync(2000)
    expect(calls).toHaveLength(1)
  })
})

describe('selection', () => {
  it('replaces, toggles and extends', () => {
    const { store } = setup()
    const { select } = store.getState()
    select({ line: 0, index: 1 })
    expect(store.getState().selection).toEqual([{ line: 0, index: 1 }])
    select({ line: 1, index: 0 }, 'range')
    expect(store.getState().selection).toEqual([
      { line: 0, index: 1 },
      { line: 0, index: 2 },
      { line: 1, index: 0 },
    ])
    expect(selectedLines(store.getState().selection)).toEqual([0, 1])
    select({ line: 0, index: 2 }, 'toggle')
    expect(store.getState().selection).toHaveLength(2)
    select({ line: 0, index: 0 }, 'toggle')
    expect(store.getState().selection).toHaveLength(3)
    store.getState().selectLine(1)
    expect(store.getState().selection).toEqual([
      { line: 1, index: 0 },
      { line: 1, index: 1 },
    ])
    store.getState().clearSelection()
    expect(store.getState().selection).toEqual([])
  })

  it('drops selected tokens that no longer exist', () => {
    const { store } = setup()
    store.getState().selectLine(1)
    store.getState().edit((draft) => void draft.lines.splice(1, 1), { label: 'delete line' })
    expect(store.getState().selection).toEqual([])
  })
})

describe('tap mode', () => {
  it('starts at the given token or at the beginning', () => {
    const { store } = setup()
    store.getState().startTap('click', null)
    expect(store.getState()).toMatchObject({ tapMode: 'click', tapCursor: { line: 0, index: 0 } })
    store.getState().setTapCursor({ line: 0, index: 1 })
    expect(store.getState().selection).toEqual([{ line: 0, index: 1 }])
    store.getState().stopTap()
    expect(store.getState()).toMatchObject({ tapMode: 'off', tapCursor: null })
    store.getState().startTap('hold', { line: 1, index: 1 })
    expect(store.getState().tapCursor).toEqual({ line: 1, index: 1 })
  })
})
