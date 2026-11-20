import type { Line, Token } from '../api/types.ts'

export function confidenceClass(token: Token): string {
  if (token.start_ms === null) return 'untimed'
  if (token.locked) return 'locked'
  if (token.confidence === null) return 'ok'
  if (token.confidence < 0.5) return 'low'
  if (token.confidence < 0.8) return 'mid'
  return 'ok'
}

/** The text of a line in the lyrics-file syntax, so that readings survive an edit. */
export function editableText(line: Line): string {
  return line.tokens
    .map((token) => {
      if (token.ruby === null || token.ruby_source !== 'manual') return token.text
      const core = token.text.trimEnd()
      return `${core}{${token.ruby}}${token.text.slice(core.length)}`
    })
    .join('')
}
