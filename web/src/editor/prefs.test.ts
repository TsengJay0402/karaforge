import { project, timedLine } from '../test/fixtures.ts'
import { initialAllowOverlap, storeAllowOverlap } from './prefs.ts'

const solo = () => project([timedLine('L001', ['一', '二'], 1000), timedLine('L002', ['三'], 3000)])
const duet = () => project([timedLine('L001', ['一', '二'], 1000), timedLine('L002', ['三'], 1200, 400, 'f')])

describe('overlapping lines preference', () => {
  beforeEach(() => localStorage.clear())

  it('follows the document until something was chosen for the project', () => {
    expect(initialAllowOverlap('solo', solo())).toBe(false)
    expect(initialAllowOverlap('duet', duet())).toBe(true)
    storeAllowOverlap('duet', false)
    storeAllowOverlap('solo', true)
    expect(initialAllowOverlap('duet', duet())).toBe(false)
    expect(initialAllowOverlap('solo', solo())).toBe(true)
    // Each project remembers its own choice.
    expect(initialAllowOverlap('other', solo())).toBe(false)
  })

  it('falls back to the document when storage is refused', () => {
    const spy = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied')
    })
    try {
      expect(initialAllowOverlap('duet', duet())).toBe(true)
    } finally {
      spy.mockRestore()
    }
  })
})
