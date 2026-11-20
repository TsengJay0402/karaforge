import { applyOverrides, getPath, withPath } from './paths.ts'

const theme = { font: { size: 84 }, layout: { rows: [{ y: 0.74 }, { y: 0.88 }] }, ruby: { enabled: false } }

describe('dotted paths', () => {
  it('reads nested values and list items', () => {
    expect(getPath(theme, 'font.size')).toBe(84)
    expect(getPath(theme, 'layout.rows.1.y')).toBe(0.88)
    expect(getPath(theme, 'layout.rows.5.y')).toBeUndefined()
    expect(getPath(theme, 'font.size.nope')).toBeUndefined()
  })

  it('writes into a copy', () => {
    const changed = withPath(theme, 'layout.rows.0.y', 0.5)
    expect(changed.layout.rows[0]?.y).toBe(0.5)
    expect(theme.layout.rows[0]?.y).toBe(0.74)
    expect(withPath(theme, 'nope.deeper.x', 1)).toEqual(theme)
  })

  it('applies several overrides', () => {
    const merged = applyOverrides(theme, { 'font.size': 96, 'ruby.enabled': true })
    expect(merged).toMatchObject({ font: { size: 96 }, ruby: { enabled: true } })
    expect(applyOverrides(theme, {})).toBe(theme)
  })
})
