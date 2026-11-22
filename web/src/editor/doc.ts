/**
 * Editing operations on a project document.
 *
 * Every function mutates the object it is given, so that it can be used as an immer recipe
 * (`produce(project, (draft) => setTokenStart(draft, ref, 1200))`); none of them touches
 * anything outside the document.  Times are integer milliseconds.
 */
import type { Line, Project, Token } from '../api/types.ts'

/** Shortest token an edit may create. */
export const MIN_TOKEN_MS = 30
/** Length given to a token whose end is not known yet (tapped start, nothing after it). */
export const PROVISIONAL_MS = 400
/** A pause longer than this is never bridged by extending the previous token. */
export const MAX_BRIDGE_MS = 2500

export interface TokenRef {
  line: number
  index: number
}

/** How the timing edits below treat the other lines. */
export interface TimingOptions {
  /**
   * Lines may overlap in time (a duet or a harmony: both rows are sung at once).  An edit is
   * then limited only by the tokens of its own line, and the end of the song; without it the
   * whole song is one sequence, so a token cannot pass the tokens of the neighbouring lines
   * either.
   */
  allowOverlap?: boolean
}

export const sameRef = (a: TokenRef, b: TokenRef) => a.line === b.line && a.index === b.index
export const refKey = (ref: TokenRef) => `${ref.line}:${ref.index}`

export function tokenAt(project: Project, ref: TokenRef): Token | undefined {
  return project.lines[ref.line]?.tokens[ref.index]
}

export function isTimed(token: Token | undefined): token is Token & {
  start_ms: number
  end_ms: number
} {
  return token != null && token.start_ms !== null && token.end_ms !== null
}

export function lineText(line: Line): string {
  return line.tokens.map((token) => token.text).join('')
}

export function lineStart(line: Line): number | null {
  for (const token of line.tokens) if (token.start_ms !== null) return token.start_ms
  return null
}

export function lineEnd(line: Line): number | null {
  for (let index = line.tokens.length - 1; index >= 0; index -= 1) {
    const end = line.tokens[index]?.end_ms
    if (end != null) return end
  }
  return null
}

/** Every token position in reading order. */
export function allRefs(project: Project): TokenRef[] {
  const refs: TokenRef[] = []
  project.lines.forEach((line, lineIndex) => {
    line.tokens.forEach((_token, index) => refs.push({ line: lineIndex, index }))
  })
  return refs
}

export function nextRef(project: Project, ref: TokenRef): TokenRef | null {
  const line = project.lines[ref.line]
  if (!line) return null
  if (ref.index + 1 < line.tokens.length) return { line: ref.line, index: ref.index + 1 }
  for (let lineIndex = ref.line + 1; lineIndex < project.lines.length; lineIndex += 1) {
    if ((project.lines[lineIndex]?.tokens.length ?? 0) > 0) return { line: lineIndex, index: 0 }
  }
  return null
}

export function previousRef(project: Project, ref: TokenRef): TokenRef | null {
  if (ref.index > 0) return { line: ref.line, index: ref.index - 1 }
  for (let lineIndex = ref.line - 1; lineIndex >= 0; lineIndex -= 1) {
    const count = project.lines[lineIndex]?.tokens.length ?? 0
    if (count > 0) return { line: lineIndex, index: count - 1 }
  }
  return null
}

/** The timed token before `ref`; with `withinLine` only one of the same line counts. */
function previousTimed(project: Project, ref: TokenRef, withinLine = false): TokenRef | null {
  let cursor = previousRef(project, ref)
  while (cursor && !isTimed(tokenAt(project, cursor))) cursor = previousRef(project, cursor)
  return cursor && withinLine && cursor.line !== ref.line ? null : cursor
}

/** The timed token after `ref`; with `withinLine` only one of the same line counts. */
function nextTimed(project: Project, ref: TokenRef, withinLine = false): TokenRef | null {
  let cursor = nextRef(project, ref)
  while (cursor && !isTimed(tokenAt(project, cursor))) cursor = nextRef(project, cursor)
  return cursor && withinLine && cursor.line !== ref.line ? null : cursor
}

/** The latest time a token may end at: the end of the song, when it is known. */
function songEnd(project: Project): number {
  return project.meta.duration_ms > 0 ? project.meta.duration_ms : Number.POSITIVE_INFINITY
}

/**
 * The token that is being sung at `timeMs`, or the last one that started before it.  Where
 * lines overlap, the one that started last; on a tie, the later one in reading order.
 */
export function refAtTime(project: Project, timeMs: number): TokenRef | null {
  let best: TokenRef | null = null
  let bestStart = Number.NEGATIVE_INFINITY
  for (const ref of allRefs(project)) {
    const token = tokenAt(project, ref)
    if (isTimed(token) && token.start_ms <= timeMs && token.start_ms >= bestStart) {
      best = ref
      bestStart = token.start_ms
    }
  }
  return best
}

function markManual(token: Token): void {
  token.locked = true
  token.source = 'manual'
  token.confidence = 1
}

const clamp = (value: number, low: number, high: number) => Math.min(Math.max(value, low), high)

/**
 * Move the start of a token.  The previous token keeps at least `MIN_TOKEN_MS`; if it ended
 * where this token started (or would now overlap it), its end follows.
 */
export function setTokenStart(project: Project, ref: TokenRef, startMs: number, options: TimingOptions = {}): void {
  const token = tokenAt(project, ref)
  if (!token) return
  const beforeRef = previousTimed(project, ref, options.allowOverlap === true)
  const before = beforeRef ? tokenAt(project, beforeRef) : undefined
  const oldStart = token.start_ms
  const low = isTimed(before) ? before.start_ms + MIN_TOKEN_MS : 0
  const high = token.end_ms !== null ? token.end_ms - MIN_TOKEN_MS : Number.POSITIVE_INFINITY
  const start = Math.round(clamp(startMs, low, Math.max(low, high)))
  token.start_ms = start
  token.end_ms = token.end_ms === null ? start + PROVISIONAL_MS : Math.max(token.end_ms, start)
  markManual(token)
  if (isTimed(before) && beforeRef) {
    const touching = oldStart !== null && Math.abs(before.end_ms - oldStart) <= 1
    const sameLine = beforeRef.line === ref.line
    if (before.end_ms > start || (touching && sameLine)) before.end_ms = start
  }
}

/**
 * Move the end of a token; it cannot pass the start of the next timed token (of the same line
 * when lines may overlap) or the end of the song.
 */
export function setTokenEnd(project: Project, ref: TokenRef, endMs: number, options: TimingOptions = {}): void {
  const token = tokenAt(project, ref)
  if (!token || token.start_ms === null) return
  const after = nextTimed(project, ref, options.allowOverlap === true)
  const afterToken = after ? tokenAt(project, after) : undefined
  const low = token.start_ms + MIN_TOKEN_MS
  const high = isTimed(afterToken) ? afterToken.start_ms : songEnd(project)
  token.end_ms = Math.round(clamp(endMs, low, Math.max(low, high)))
  markManual(token)
}

/** Shift a token as a whole, between its timed neighbours. */
export function moveToken(project: Project, ref: TokenRef, deltaMs: number, options: TimingOptions = {}): void {
  const token = tokenAt(project, ref)
  if (!isTimed(token)) return
  const withinLine = options.allowOverlap === true
  const beforeRef = previousTimed(project, ref, withinLine)
  const before = beforeRef ? tokenAt(project, beforeRef) : undefined
  const afterRef = nextTimed(project, ref, withinLine)
  const after = afterRef ? tokenAt(project, afterRef) : undefined
  const length = token.end_ms - token.start_ms
  const low = isTimed(before) ? before.start_ms + MIN_TOKEN_MS : 0
  const high = (isTimed(after) ? after.start_ms : songEnd(project)) - length
  const oldStart = token.start_ms
  const start = Math.round(clamp(oldStart + deltaMs, low, Math.max(low, high)))
  token.start_ms = start
  token.end_ms = start + length
  markManual(token)
  if (isTimed(before) && beforeRef) {
    const touching = Math.abs(before.end_ms - oldStart) <= 1 && beforeRef.line === ref.line
    if (before.end_ms > start || touching) before.end_ms = start
  }
}

/**
 * Drag a selection on the timeline: the start of every selected token moves by the same
 * amount, and each one is locked.
 *
 * Ends follow the rule of `nudgeTokens` (dragging is holding an arrow key, continuously): a
 * selected token that runs straight into a token that is not selected stays attached to it,
 * so the fill never pauses where it did not; the token before the selection follows in the
 * same way, or is cut back where the selection now overlaps it.  Tokens that are not selected
 * keep their start.  Unlike nudging, the amount is limited for the selection as a whole, so a
 * fast drag never squeezes it together: it stops where a token would become shorter than
 * `MIN_TOKEN_MS`, where a token followed by a pause would reach the next token, at 0 and at
 * the end of the song.  A limit that the document already breaks only stops the movement
 * towards it.
 */
export function moveSelection(
  project: Project,
  refs: TokenRef[],
  deltaMs: number,
  options: TimingOptions = {},
): void {
  const withinLine = options.allowOverlap === true
  const moving = new Map<string, TokenRef>()
  for (const ref of refs) if (isTimed(tokenAt(project, ref))) moving.set(refKey(ref), ref)
  if (moving.size === 0) return

  interface Plan {
    ref: TokenRef
    /** The token before it, when that one is not selected. */
    before: TokenRef | null
    /** The start of the token after it, when that one is not selected and this one runs into it. */
    attachedTo: number | null
  }
  const plans: Plan[] = []
  let low = Number.NEGATIVE_INFINITY
  let high = Number.POSITIVE_INFINITY
  for (const ref of moving.values()) {
    const token = tokenAt(project, ref)
    if (!isTimed(token)) continue
    const plan: Plan = { ref, before: null, attachedTo: null }
    const beforeRef = previousTimed(project, ref, withinLine)
    const before = beforeRef ? tokenAt(project, beforeRef) : undefined
    if (beforeRef && isTimed(before) && !moving.has(refKey(beforeRef))) {
      plan.before = beforeRef
      low = Math.max(low, before.start_ms + MIN_TOKEN_MS - token.start_ms)
    } else if (!beforeRef) {
      low = Math.max(low, -token.start_ms)
    }
    const afterRef = nextTimed(project, ref, withinLine)
    const after = afterRef ? tokenAt(project, afterRef) : undefined
    if (!afterRef) {
      high = Math.min(high, songEnd(project) - token.end_ms)
    } else if (isTimed(after) && !moving.has(refKey(afterRef))) {
      if (token.end_ms >= after.start_ms - 1) {
        plan.attachedTo = after.start_ms
        high = Math.min(high, after.start_ms - MIN_TOKEN_MS - token.start_ms)
      } else {
        high = Math.min(high, after.start_ms - token.end_ms)
      }
    }
    plans.push(plan)
  }
  const shift = Math.round(clamp(deltaMs, Math.min(0, low), Math.max(0, high)))

  for (const plan of plans) {
    const token = tokenAt(project, plan.ref)
    if (!isTimed(token)) continue
    const oldStart = token.start_ms
    token.start_ms = oldStart + shift
    // (The `max` only matters for a document that already broke the limits: a token never
    // ends before it starts.)
    token.end_ms = plan.attachedTo === null ? token.end_ms + shift : Math.max(plan.attachedTo, token.start_ms)
    markManual(token)
    const before = plan.before ? tokenAt(project, plan.before) : undefined
    if (plan.before && isTimed(before)) {
      const attached = plan.before.line === plan.ref.line && before.end_ms >= oldStart - 1
      if (attached || before.end_ms > token.start_ms) before.end_ms = Math.max(before.start_ms, token.start_ms)
    }
  }
}

/**
 * Shift tokens by a fixed amount without any clamping against neighbours (used for "shift
 * the whole song" and "shift this line").  Lock state is kept: the offset is a correction of
 * everything, not of one token.
 */
export function shiftTokens(project: Project, refs: Iterable<TokenRef>, deltaMs: number): void {
  for (const ref of refs) {
    const token = tokenAt(project, ref)
    if (!isTimed(token)) continue
    const length = token.end_ms - token.start_ms
    token.start_ms = Math.max(0, Math.round(token.start_ms + deltaMs))
    token.end_ms = token.start_ms + length
  }
  for (const line of project.lines) {
    if (line.time_hint) {
      const [start, end] = line.time_hint
      line.time_hint = [Math.max(0, start + deltaMs), end === null ? null : Math.max(0, end + deltaMs)]
    }
  }
}

export function lineRefs(project: Project, lineIndex: number): TokenRef[] {
  return (project.lines[lineIndex]?.tokens ?? []).map((_token, index) => ({ line: lineIndex, index }))
}

/**
 * Nudge the selected tokens (arrow keys): their *start* moves by `deltaMs`.
 *
 * What a nudge means for the end of a token depends on what follows it.  A token that runs
 * straight into the next one stays attached to it (so the fill never pauses where it did
 * not pause before); a token followed by a pause keeps its length.  The token before the
 * selection follows in the same way.  Nothing ever becomes shorter than `MIN_TOKEN_MS` or
 * ends after the song.
 */
export function nudgeTokens(project: Project, refs: TokenRef[], deltaMs: number, options: TimingOptions = {}): void {
  const withinLine = options.allowOverlap === true
  const ordered = refs
    .filter((ref) => isTimed(tokenAt(project, ref)))
    .sort((a, b) => a.line - b.line || a.index - b.index)
  if (ordered.length === 0 || deltaMs === 0) return
  const old = new Map<string, { start: number; end: number }>()
  for (const ref of allRefs(project)) {
    const token = tokenAt(project, ref)
    if (isTimed(token)) old.set(refKey(ref), { start: token.start_ms, end: token.end_ms })
  }
  // Later: handle the last token first, so that each one sees where its successor went.
  const sequence = deltaMs > 0 ? [...ordered].reverse() : ordered
  for (const ref of sequence) {
    const token = tokenAt(project, ref)
    const was = old.get(refKey(ref))
    if (!isTimed(token) || !was) continue
    const beforeRef = previousTimed(project, ref, withinLine)
    const before = beforeRef ? tokenAt(project, beforeRef) : undefined
    const afterRef = nextTimed(project, ref, withinLine)
    const after = afterRef ? tokenAt(project, afterRef) : undefined
    const afterWas = afterRef ? old.get(refKey(afterRef)) : undefined

    let end = was.end + deltaMs
    if (isTimed(after) && afterWas) {
      const attached = was.end >= afterWas.start - 1
      end = attached ? after.start_ms : Math.min(end, after.start_ms)
    } else {
      end = Math.min(end, songEnd(project))
    }
    const low = isTimed(before) ? before.start_ms + MIN_TOKEN_MS : 0
    const startAt = Math.round(clamp(was.start + deltaMs, low, Math.max(low, end - MIN_TOKEN_MS)))
    token.start_ms = startAt
    token.end_ms = Math.max(Math.round(end), startAt + MIN_TOKEN_MS)
    markManual(token)

    const beforeWas = beforeRef ? old.get(refKey(beforeRef)) : undefined
    if (isTimed(before) && beforeRef && beforeWas) {
      const attached = beforeRef.line === ref.line && beforeWas.end >= was.start - 1
      if (attached || before.end_ms > startAt) before.end_ms = startAt
    }
  }
}

export function setLocked(project: Project, refs: Iterable<TokenRef>, locked: boolean): void {
  for (const ref of refs) {
    const token = tokenAt(project, ref)
    if (token && (isTimed(token) || !locked)) token.locked = locked
  }
}

/**
 * The timed tokens that are sung at the same time as a token of another line (overlapping
 * lines: a duet, a harmony), in reading order.  Tokens that merely touch do not count.
 */
export function overlappingRefs(project: Project): TokenRef[] {
  const timed: { ref: TokenRef; start: number; end: number }[] = []
  for (const ref of allRefs(project)) {
    const token = tokenAt(project, ref)
    if (isTimed(token) && token.end_ms > token.start_ms) {
      timed.push({ ref, start: token.start_ms, end: token.end_ms })
    }
  }
  timed.sort((a, b) => a.start - b.start)
  const found = new Set<string>()
  let active: typeof timed = []
  for (const item of timed) {
    active = active.filter((other) => other.end > item.start)
    for (const other of active) {
      if (other.ref.line === item.ref.line) continue
      found.add(refKey(other.ref))
      found.add(refKey(item.ref))
    }
    active.push(item)
  }
  return allRefs(project).filter((ref) => found.has(refKey(ref)))
}

/** Remove the times of tokens (they will be placed by the next alignment). */
export function clearTiming(project: Project, refs: Iterable<TokenRef>): void {
  for (const ref of refs) {
    const token = tokenAt(project, ref)
    if (!token) continue
    token.start_ms = null
    token.end_ms = null
    token.locked = false
    token.confidence = null
    token.source = 'auto'
  }
}

export function setSinger(project: Project, lineIndex: number, singerId: string): void {
  const line = project.lines[lineIndex]
  if (line && project.singers.some((singer) => singer.id === singerId)) line.singer = singerId
}

/** Which kind the automatic readings of a project are in, if it has any. */
export function readingKind(project: Project): 'zhuyin' | 'pinyin' | null {
  let found: 'pinyin' | null = null
  for (const line of project.lines) {
    for (const token of line.tokens) {
      if (!token.ruby || token.ruby_source !== 'auto') continue
      if (/[\u3105-\u312F]/.test(token.ruby)) return 'zhuyin'
      found = 'pinyin'
    }
  }
  return found
}

/**
 * Take over the readings of `annotated` (the same lines, sent to the server a moment ago).
 * A line whose text changed in the meantime is left alone; returns how many lines were
 * updated.
 */
export function applyReadings(project: Project, annotated: Line[]): number {
  const byId = new Map(annotated.map((line) => [line.id, line]))
  let updated = 0
  for (const line of project.lines) {
    const source = byId.get(line.id)
    if (source?.tokens.length !== line.tokens.length) continue
    if (!line.tokens.every((token, index) => token.text === source.tokens[index]?.text)) continue
    line.tokens.forEach((token, index) => {
      const from = source.tokens[index]
      if (!from) return
      token.ruby = from.ruby
      token.ruby_source = from.ruby_source
    })
    updated += 1
  }
  return updated
}

export function setRuby(project: Project, ref: TokenRef, ruby: string | null): void {
  const token = tokenAt(project, ref)
  if (!token) return
  const value = ruby?.trim() ?? ''
  token.ruby = value === '' ? null : value
  token.ruby_source = value === '' ? null : 'manual'
}

export function replaceLine(project: Project, lineIndex: number, line: Line): void {
  if (lineIndex >= 0 && lineIndex < project.lines.length) project.lines[lineIndex] = line
}

function freshLineId(project: Project): string {
  const used = new Set(project.lines.map((line) => line.id))
  let number = project.lines.length + 1
  while (used.has(`L${String(number).padStart(3, '0')}`)) number += 1
  return `L${String(number).padStart(3, '0')}`
}

/** Insert an empty line after `lineIndex` (-1 inserts at the top); returns its index. */
export function insertLine(project: Project, lineIndex: number): number {
  const base = project.lines[lineIndex]
  const line: Line = {
    id: freshLineId(project),
    singer: base?.singer ?? project.singers[0]?.id ?? 'm',
    paragraph: base?.paragraph ?? 0,
    tokens: [],
    time_hint: null,
  }
  project.lines.splice(lineIndex + 1, 0, line)
  return lineIndex + 1
}

export function deleteLine(project: Project, lineIndex: number): void {
  if (lineIndex >= 0 && lineIndex < project.lines.length) project.lines.splice(lineIndex, 1)
}

/** Split a line in two before the given token. */
export function splitLine(project: Project, ref: TokenRef): void {
  const line = project.lines[ref.line]
  if (!line || ref.index <= 0 || ref.index >= line.tokens.length) return
  const tail = line.tokens.splice(ref.index)
  const last = line.tokens[line.tokens.length - 1]
  if (last) last.text = last.text.trimEnd()
  project.lines.splice(ref.line + 1, 0, {
    id: freshLineId(project),
    singer: line.singer,
    paragraph: line.paragraph,
    tokens: tail,
    time_hint: null,
  })
  line.time_hint = null
}

/** Join a line with the one after it. */
export function mergeWithNext(project: Project, lineIndex: number): void {
  const line = project.lines[lineIndex]
  const next = project.lines[lineIndex + 1]
  if (!line || !next) return
  const last = line.tokens[line.tokens.length - 1]
  const first = next.tokens[0]
  const latin = (text: string) => /[A-Za-z0-9']$/.test(text.trimEnd())
  if (last && first && !/\s$/.test(last.text) && (latin(last.text) || /^[A-Za-z0-9]/.test(first.text))) {
    last.text += ' '
  }
  line.tokens.push(...next.tokens)
  line.time_hint = null
  project.lines.splice(lineIndex + 1, 1)
}

/**
 * Tap mode, key down: the token starts now.
 *
 * With `bridge` (click mode, where nothing marks the end of a token) the token before it in
 * the same line ends here, unless a long pause lies in between.  Without it (hold mode, where
 * the key release already marked that end) the previous token is only cut if it overlaps.
 * When lines may overlap, only the tokens of the same line are cut or cleared.
 */
export function tapStart(
  project: Project,
  ref: TokenRef,
  timeMs: number,
  bridge = true,
  options: TimingOptions = {},
): void {
  const token = tokenAt(project, ref)
  if (!token) return
  const withinLine = options.allowOverlap === true
  const beforeRef = previousTimed(project, ref, withinLine)
  const before = beforeRef ? tokenAt(project, beforeRef) : undefined
  const low = isTimed(before) ? before.start_ms + MIN_TOKEN_MS : 0
  const start = Math.round(Math.max(timeMs, low))
  token.start_ms = start
  token.end_ms = start + PROVISIONAL_MS
  markManual(token)
  if (isTimed(before) && beforeRef) {
    const joins = bridge && beforeRef.line === ref.line && start - before.start_ms <= MAX_BRIDGE_MS
    if (before.end_ms > start || joins) before.end_ms = start
  }
  // Anything after this token that is now in the past loses its time.
  let cursor = nextRef(project, ref)
  while (cursor && (!withinLine || cursor.line === ref.line)) {
    const later: Token | undefined = tokenAt(project, cursor)
    if (later && later.start_ms !== null) {
      if (later.start_ms > start || later.locked) break
      later.start_ms = null
      later.end_ms = null
    }
    cursor = nextRef(project, cursor)
  }
}

/** Tap mode, key up (hold mode): the token ends now. */
export function tapEnd(project: Project, ref: TokenRef, timeMs: number): void {
  const token = tokenAt(project, ref)
  if (!token || token.start_ms === null) return
  token.end_ms = Math.round(Math.max(timeMs, token.start_ms + MIN_TOKEN_MS))
  markManual(token)
}

export interface TimingStats {
  tokens: number
  timed: number
  locked: number
  lowConfidence: number
}

export function timingStats(project: Project, lowThreshold = 0.5): TimingStats {
  const stats: TimingStats = { tokens: 0, timed: 0, locked: 0, lowConfidence: 0 }
  for (const line of project.lines) {
    for (const token of line.tokens) {
      stats.tokens += 1
      if (isTimed(token)) stats.timed += 1
      if (token.locked) stats.locked += 1
      if (isTimed(token) && !token.locked && token.confidence !== null && token.confidence < lowThreshold) {
        stats.lowConfidence += 1
      }
    }
  }
  return stats
}
