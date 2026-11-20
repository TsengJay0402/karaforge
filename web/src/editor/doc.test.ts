import { produce } from 'immer'

import { project, timedLine, times, token } from '../test/fixtures.ts'
import {
  allRefs,
  applyReadings,
  clearTiming,
  deleteLine,
  insertLine,
  lineEnd,
  lineStart,
  lineText,
  mergeWithNext,
  moveToken,
  nextRef,
  nudgeTokens,
  previousRef,
  readingKind,
  refAtTime,
  setLocked,
  setRuby,
  setSinger,
  setTokenEnd,
  setTokenStart,
  shiftTokens,
  splitLine,
  tapEnd,
  tapStart,
  timingStats,
} from './doc.ts'

const song = () =>
  project([
    timedLine('L001', ['夜', '空', '裡'], 1000),
    timedLine('L002', ['so ', 'bright'], 5000, 500, 'f'),
  ])

describe('navigation', () => {
  it('walks tokens in reading order across lines', () => {
    const doc = song()
    expect(allRefs(doc)).toHaveLength(5)
    expect(nextRef(doc, { line: 0, index: 2 })).toEqual({ line: 1, index: 0 })
    expect(nextRef(doc, { line: 1, index: 1 })).toBeNull()
    expect(previousRef(doc, { line: 1, index: 0 })).toEqual({ line: 0, index: 2 })
    expect(previousRef(doc, { line: 0, index: 0 })).toBeNull()
  })

  it('finds the token that is being sung', () => {
    const doc = song()
    expect(refAtTime(doc, 500)).toBeNull()
    expect(refAtTime(doc, 1450)).toEqual({ line: 0, index: 1 })
    expect(refAtTime(doc, 3000)).toEqual({ line: 0, index: 2 })
    expect(refAtTime(doc, 99_000)).toEqual({ line: 1, index: 1 })
  })

  it('describes lines', () => {
    const doc = song()
    expect(lineText(doc.lines[1]!)).toBe('so bright')
    expect([lineStart(doc.lines[0]!), lineEnd(doc.lines[0]!)]).toEqual([1000, 2200])
    expect(lineStart({ ...doc.lines[0]!, tokens: [token('啊', null, null)] })).toBeNull()
  })
})

describe('setTokenStart', () => {
  it('moves the start, locks the token and keeps the previous token attached', () => {
    const doc = produce(song(), (draft) => setTokenStart(draft, { line: 0, index: 1 }, 1500))
    expect(times(doc.lines[0])).toEqual([
      ['夜', 1000, 1500],
      ['空', 1500, 1800],
      ['裡', 1800, 2200],
    ])
    const moved = doc.lines[0]!.tokens[1]!
    expect([moved.locked, moved.source, moved.confidence]).toEqual([true, 'manual', 1])
    expect(doc.lines[0]!.tokens[0]!.locked).toBe(false)
  })

  it('cannot pass the token end or squeeze the previous token away', () => {
    const late = produce(song(), (draft) => setTokenStart(draft, { line: 0, index: 1 }, 9999))
    expect(times(late.lines[0])[1]).toEqual(['空', 1770, 1800])
    const early = produce(song(), (draft) => setTokenStart(draft, { line: 0, index: 1 }, 0))
    expect(times(early.lines[0]).slice(0, 2)).toEqual([
      ['夜', 1000, 1030],
      ['空', 1030, 1800],
    ])
  })

  it('does not drag the end of the previous line along', () => {
    const doc = produce(song(), (draft) => setTokenStart(draft, { line: 1, index: 0 }, 5200))
    expect(times(doc.lines[0])[2]).toEqual(['裡', 1800, 2200])
    expect(times(doc.lines[1])[0]).toEqual(['so ', 5200, 5500])
  })

  it('gives an untimed token a provisional length', () => {
    const base = project([{ ...timedLine('L001', ['一'], 1000), tokens: [token('一', 1000, 1400), token('二', null, null)] }])
    const doc = produce(base, (draft) => setTokenStart(draft, { line: 0, index: 1 }, 2000))
    expect(times(doc.lines[0])).toEqual([
      ['一', 1000, 1400],
      ['二', 2000, 2400],
    ])
  })
})

describe('setTokenEnd and moveToken', () => {
  it('ends a token between its start and the next token', () => {
    const shorter = produce(song(), (draft) => setTokenEnd(draft, { line: 0, index: 0 }, 1200))
    expect(times(shorter.lines[0])[0]).toEqual(['夜', 1000, 1200])
    const clamped = produce(song(), (draft) => setTokenEnd(draft, { line: 0, index: 0 }, 9000))
    expect(times(clamped.lines[0])[0]).toEqual(['夜', 1000, 1400])
    const lastOfLine = produce(song(), (draft) => setTokenEnd(draft, { line: 0, index: 2 }, 9000))
    expect(times(lastOfLine.lines[0])[2]).toEqual(['裡', 1800, 5000])
    const lastOfSong = produce(song(), (draft) => setTokenEnd(draft, { line: 1, index: 1 }, 99_000))
    expect(times(lastOfSong.lines[1])[1]).toEqual(['bright', 5500, 60_000])
  })

  it('moves a token as a whole between its neighbours', () => {
    const doc = produce(song(), (draft) => moveToken(draft, { line: 0, index: 2 }, 600))
    expect(times(doc.lines[0])).toEqual([
      ['夜', 1000, 1400],
      ['空', 1400, 2400],
      ['裡', 2400, 2800],
    ])
    const blocked = produce(song(), (draft) => moveToken(draft, { line: 0, index: 2 }, 99_000))
    expect(times(blocked.lines[0])[2]).toEqual(['裡', 4600, 5000])
    const back = produce(song(), (draft) => moveToken(draft, { line: 0, index: 1 }, -99_000))
    expect(times(back.lines[0]).slice(0, 2)).toEqual([
      ['夜', 1000, 1030],
      ['空', 1030, 1430],
    ])
  })
})

describe('batch operations', () => {
  it('shifts every token without locking anything', () => {
    const base = song()
    base.lines[0]!.time_hint = [900, null]
    const doc = produce(base, (draft) => shiftTokens(draft, allRefs(draft), -1200))
    expect(times(doc.lines[0])).toEqual([
      ['夜', 0, 400],
      ['空', 200, 600],
      ['裡', 600, 1000],
    ])
    expect(times(doc.lines[1])[0]).toEqual(['so ', 3800, 4300])
    expect(doc.lines[0]!.time_hint).toEqual([0, null])
    expect(doc.lines.flatMap((line) => line.tokens).some((item) => item.locked)).toBe(false)
  })

  it('nudges the start of the selected tokens and keeps attached tokens attached', () => {
    const refs = [
      { line: 0, index: 0 },
      { line: 0, index: 1 },
      { line: 0, index: 2 },
    ]
    // A whole line moves as a block (the last token is followed by a pause).
    const later = produce(song(), (draft) => nudgeTokens(draft, refs, 10))
    expect(times(later.lines[0])).toEqual([
      ['夜', 1010, 1410],
      ['空', 1410, 1810],
      ['裡', 1810, 2210],
    ])
    const earlier = produce(song(), (draft) => nudgeTokens(draft, refs, -10))
    expect(times(earlier.lines[0])).toEqual([
      ['夜', 990, 1390],
      ['空', 1390, 1790],
      ['裡', 1790, 2190],
    ])
    expect(later.lines[0]!.tokens.every((item) => item.locked)).toBe(true)

    // One token inside a line: its start moves, both neighbours stay attached to it.
    const middle = produce(song(), (draft) => nudgeTokens(draft, [{ line: 0, index: 1 }], 50))
    expect(times(middle.lines[0])).toEqual([
      ['夜', 1000, 1450],
      ['空', 1450, 1800],
      ['裡', 1800, 2200],
    ])
    expect(middle.lines[0]!.tokens.map((item) => item.locked)).toEqual([false, true, false])
    const backwards = produce(song(), (draft) => nudgeTokens(draft, [{ line: 0, index: 1 }], -50))
    expect(times(backwards.lines[0])).toEqual([
      ['夜', 1000, 1350],
      ['空', 1350, 1800],
      ['裡', 1800, 2200],
    ])

    // A token followed by a pause keeps its length.
    const lastOfLine = produce(song(), (draft) => nudgeTokens(draft, [{ line: 1, index: 1 }], 400))
    expect(times(lastOfLine.lines[1])).toEqual([
      ['so ', 5000, 5900],
      ['bright', 5900, 6400],
    ])
    const beforePause = produce(song(), (draft) => nudgeTokens(draft, [{ line: 0, index: 2 }], 99_000))
    expect(times(beforePause.lines[0])[2]).toEqual(['裡', 4970, 5000])
  })

  it('never squeezes a token below the minimum length', () => {
    const tooFar = produce(song(), (draft) => nudgeTokens(draft, [{ line: 0, index: 1 }], 5000))
    expect(times(tooFar.lines[0]).slice(0, 2)).toEqual([
      ['夜', 1000, 1770],
      ['空', 1770, 1800],
    ])
    const tooEarly = produce(song(), (draft) => nudgeTokens(draft, [{ line: 0, index: 1 }], -5000))
    expect(times(tooEarly.lines[0]).slice(0, 2)).toEqual([
      ['夜', 1000, 1030],
      ['空', 1030, 1800],
    ])
    const first = produce(song(), (draft) => nudgeTokens(draft, [{ line: 0, index: 0 }], -5000))
    expect(times(first.lines[0])[0]).toEqual(['夜', 0, 1400])
    // Untimed tokens and an empty nudge change nothing.
    expect(produce(song(), (draft) => nudgeTokens(draft, [{ line: 0, index: 0 }], 0))).toEqual(song())
  })

  it('takes over readings from the server unless the text changed meanwhile', () => {
    const base = song()
    expect(readingKind(base)).toBeNull()
    const annotated = produce(base, (draft) => {
      draft.lines[0]!.tokens.forEach((item, index) => {
        item.ruby = ['ㄧㄝˋ', 'ㄎㄨㄥ', 'ㄌㄧˇ'][index] ?? null
        item.ruby_source = 'auto'
      })
      draft.lines[1]!.tokens[0]!.ruby = 'x'
      draft.lines[1]!.tokens[0]!.ruby_source = 'auto'
    })
    // The second line was edited while the request was under way: it is skipped.
    const edited = produce(base, (draft) => {
      draft.lines[1]!.tokens[0]!.text = 'too '
    })
    let count = 0
    const result = produce(edited, (draft) => {
      count = applyReadings(draft, annotated.lines)
    })
    expect(count).toBe(1)
    expect(result.lines[0]!.tokens.map((item) => [item.ruby, item.ruby_source])).toEqual([
      ['ㄧㄝˋ', 'auto'],
      ['ㄎㄨㄥ', 'auto'],
      ['ㄌㄧˇ', 'auto'],
    ])
    expect(result.lines[1]!.tokens[0]!.ruby).toBeNull()
    // Timing is never touched.
    expect(times(result.lines[0])).toEqual(times(base.lines[0]))
    expect(readingKind(result)).toBe('zhuyin')

    const pinyin = produce(base, (draft) => {
      draft.lines[0]!.tokens[0]!.ruby = 'yè'
      draft.lines[0]!.tokens[0]!.ruby_source = 'auto'
    })
    expect(readingKind(pinyin)).toBe('pinyin')
    // Readings typed by hand say nothing about the kind of the automatic ones.
    const manual = produce(base, (draft) => {
      draft.lines[0]!.tokens[0]!.ruby = 'ㄧㄝˋ'
      draft.lines[0]!.tokens[0]!.ruby_source = 'manual'
    })
    expect(readingKind(manual)).toBeNull()
  })

  it('locks, unlocks and clears timing', () => {
    const refs = [{ line: 0, index: 0 }]
    const locked = produce(song(), (draft) => setLocked(draft, refs, true))
    expect(locked.lines[0]!.tokens[0]!.locked).toBe(true)
    const cleared = produce(locked, (draft) => clearTiming(draft, refs))
    expect(cleared.lines[0]!.tokens[0]).toMatchObject({ start_ms: null, end_ms: null, locked: false })
    // An untimed token cannot be locked.
    const stillOpen = produce(cleared, (draft) => setLocked(draft, refs, true))
    expect(stillOpen.lines[0]!.tokens[0]!.locked).toBe(false)
    expect(timingStats(locked)).toEqual({ tokens: 5, timed: 5, locked: 1, lowConfidence: 0 })
  })
})

describe('lines', () => {
  it('changes the singer only to one that exists', () => {
    const doc = produce(song(), (draft) => {
      setSinger(draft, 0, 'all')
      setSinger(draft, 1, 'nobody')
    })
    expect(doc.lines.map((line) => line.singer)).toEqual(['all', 'f'])
  })

  it('sets and removes readings', () => {
    const ref = { line: 0, index: 0 }
    const set = produce(song(), (draft) => setRuby(draft, ref, ' ㄧㄝˋ '))
    expect(set.lines[0]!.tokens[0]).toMatchObject({ ruby: 'ㄧㄝˋ', ruby_source: 'manual' })
    const unset = produce(set, (draft) => setRuby(draft, ref, ''))
    expect(unset.lines[0]!.tokens[0]).toMatchObject({ ruby: null, ruby_source: null })
  })

  it('inserts, deletes, splits and merges lines', () => {
    const inserted = produce(song(), (draft) => {
      expect(insertLine(draft, 0)).toBe(1)
    })
    expect(inserted.lines.map((line) => line.id)).toEqual(['L001', 'L003', 'L002'])
    expect(inserted.lines[1]).toMatchObject({ singer: 'm', tokens: [] })
    const deleted = produce(inserted, (draft) => deleteLine(draft, 1))
    expect(deleted.lines.map((line) => line.id)).toEqual(['L001', 'L002'])

    const split = produce(song(), (draft) => splitLine(draft, { line: 1, index: 1 }))
    expect(split.lines.map(lineText)).toEqual(['夜空裡', 'so', 'bright'])
    expect(split.lines[2]).toMatchObject({ singer: 'f', id: 'L003' })
    const merged = produce(split, (draft) => mergeWithNext(draft, 1))
    expect(merged.lines.map(lineText)).toEqual(['夜空裡', 'so bright'])
    const mixed = produce(song(), (draft) => mergeWithNext(draft, 0))
    expect(mixed.lines.map(lineText)).toEqual(['夜空裡 so bright'])
    // Nothing happens at the edges.
    expect(produce(song(), (draft) => splitLine(draft, { line: 0, index: 0 }))).toEqual(song())
    expect(produce(song(), (draft) => mergeWithNext(draft, 1))).toEqual(song())
  })
})

describe('tap mode', () => {
  const untimed = () =>
    project([
      { ...timedLine('L001', [], 0), tokens: ['一', '二', '三'].map((text) => token(text, null, null)) },
      { ...timedLine('L002', [], 0), tokens: [token('四', null, null)] },
    ])

  it('click mode: every tap starts a token and ends the one before it', () => {
    const doc = produce(untimed(), (draft) => {
      tapStart(draft, { line: 0, index: 0 }, 1000)
      tapStart(draft, { line: 0, index: 1 }, 1350)
      tapStart(draft, { line: 0, index: 2 }, 1800)
    })
    expect(times(doc.lines[0])).toEqual([
      ['一', 1000, 1350],
      ['二', 1350, 1800],
      ['三', 1800, 2200],
    ])
    expect(doc.lines[0]!.tokens.every((item) => item.locked && item.source === 'manual')).toBe(true)
  })

  it('does not stretch a token across a long pause or into the next line', () => {
    const doc = produce(untimed(), (draft) => {
      tapStart(draft, { line: 0, index: 0 }, 1000)
      tapStart(draft, { line: 0, index: 1 }, 6000)
      tapStart(draft, { line: 0, index: 2 }, 6400)
      tapStart(draft, { line: 1, index: 0 }, 7000)
    })
    expect(times(doc.lines[0])).toEqual([
      ['一', 1000, 1400],
      ['二', 6000, 6400],
      ['三', 6400, 6800],
    ])
    expect(times(doc.lines[1])).toEqual([['四', 7000, 7400]])
  })

  it('hold mode: the key release ends the token', () => {
    const doc = produce(untimed(), (draft) => {
      tapStart(draft, { line: 0, index: 0 }, 1000, false)
      tapEnd(draft, { line: 0, index: 0 }, 2900)
      tapStart(draft, { line: 0, index: 1 }, 3100, false)
      tapEnd(draft, { line: 0, index: 1 }, 3105)
    })
    expect(times(doc.lines[0]).slice(0, 2)).toEqual([
      ['一', 1000, 2900],
      ['二', 3100, 3130],
    ])
  })

  it('re-tapping earlier tokens clears stale automatic times after them', () => {
    const doc = produce(song(), (draft) => tapStart(draft, { line: 0, index: 0 }, 1700))
    expect(times(doc.lines[0])).toEqual([
      ['夜', 1700, 2100],
      ['空', null, null],
      ['裡', 1800, 2200],
    ])
  })
})
