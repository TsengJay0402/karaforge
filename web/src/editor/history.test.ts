import { applyEdit, canRedo, canUndo, createHistory, MAX_STEPS, redo, undo } from './history.ts'

interface Doc {
  values: number[]
  title: string
}

const start = (): Doc => ({ values: [1, 2, 3], title: 'a' })

describe('history', () => {
  it('records edits and walks back and forth through them', () => {
    let state = createHistory(start())
    expect([canUndo(state), canRedo(state)]).toEqual([false, false])
    state = applyEdit(state, (draft) => void (draft.values[0] = 10), { label: 'first' })
    state = applyEdit(state, (draft) => void (draft.title = 'b'), { label: 'second' })
    expect(state.present).toEqual({ values: [10, 2, 3], title: 'b' })
    expect(state.past.map((step) => step.label)).toEqual(['first', 'second'])

    state = undo(state)
    expect(state.present).toEqual({ values: [10, 2, 3], title: 'a' })
    state = undo(state)
    expect(state.present).toEqual(start())
    expect(undo(state)).toBe(state)
    state = redo(state)
    state = redo(state)
    expect(state.present).toEqual({ values: [10, 2, 3], title: 'b' })
    expect(redo(state)).toBe(state)
  })

  it('drops the redo branch when a new edit is made', () => {
    let state = createHistory(start())
    state = applyEdit(state, (draft) => void (draft.title = 'b'), { label: 'x' })
    state = undo(state)
    state = applyEdit(state, (draft) => void (draft.title = 'c'), { label: 'y' })
    expect(canRedo(state)).toBe(false)
    expect(undo(state).present.title).toBe('a')
  })

  it('ignores recipes that change nothing', () => {
    const state = createHistory(start())
    expect(applyEdit(state, () => undefined, { label: 'noop' })).toBe(state)
    expect(applyEdit(state, (draft) => void (draft.title = 'a'), { label: 'same' })).toBe(state)
  })

  it('folds a quick series with the same key into one step', () => {
    let state = createHistory(start())
    for (let step = 1; step <= 5; step += 1) {
      state = applyEdit(state, (draft) => void (draft.values[1] = 2 + step), {
        label: 'drag',
        mergeKey: 'token:0:1',
        now: 1000 + step * 100,
      })
    }
    expect(state.past).toHaveLength(1)
    expect(state.present.values[1]).toBe(7)
    expect(undo(state).present).toEqual(start())
    expect(redo(undo(state)).present.values[1]).toBe(7)
  })

  it('starts a new step after a pause, for another key, or after an undo', () => {
    let state = createHistory(start())
    state = applyEdit(state, (draft) => void (draft.values[0] = 5), { label: 'a', mergeKey: 'k', now: 0 })
    state = applyEdit(state, (draft) => void (draft.values[0] = 6), { label: 'a', mergeKey: 'k', now: 5000 })
    state = applyEdit(state, (draft) => void (draft.values[0] = 7), { label: 'b', mergeKey: 'other', now: 5010 })
    expect(state.past).toHaveLength(3)
    state = redo(undo(state))
    state = applyEdit(state, (draft) => void (draft.values[0] = 8), { label: 'b', mergeKey: 'other', now: 5020 })
    expect(state.past).toHaveLength(4)
  })

  it('keeps a bounded number of steps', () => {
    let state = createHistory(start())
    for (let step = 0; step < MAX_STEPS + 20; step += 1) {
      state = applyEdit(state, (draft) => void (draft.values[2] = step + 100), { label: 'edit' })
    }
    expect(state.past).toHaveLength(MAX_STEPS)
  })
})
