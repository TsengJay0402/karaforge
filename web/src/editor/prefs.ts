/**
 * Editor preferences of one project, kept in this browser.  Storage may be refused (private
 * windows); the editor then falls back to its defaults.
 */
import type { Project } from '../api/types.ts'
import { overlappingRefs } from './doc.ts'

const overlapKey = (id: string) => `karaforge.allow-overlap.${id}`

/**
 * Whether lines may overlap in the editor of a project: what was last chosen for it in this
 * browser, otherwise whether its lines already overlap (a duet that was timed before).
 */
export function initialAllowOverlap(id: string, project: Project): boolean {
  try {
    const stored = window.localStorage.getItem(overlapKey(id))
    if (stored !== null) return stored === '1'
  } catch {
    // Fall through to the document.
  }
  return overlappingRefs(project).length > 0
}

export function storeAllowOverlap(id: string, value: boolean): void {
  try {
    window.localStorage.setItem(overlapKey(id), value ? '1' : '0')
  } catch {
    // Not remembered; the next visit starts from the document again.
  }
}
