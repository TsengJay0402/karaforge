/** Reading and writing values of nested objects by dotted paths (`layout.rows.0.y`). */

export function getPath(root: unknown, path: string): unknown {
  let cursor: unknown = root
  for (const part of path.split('.')) {
    if (cursor === null || typeof cursor !== 'object') return undefined
    cursor = (cursor as Record<string, unknown>)[part]
  }
  return cursor
}

/** A deep copy of `root` with the value at `path` replaced. */
export function withPath<T>(root: T, path: string, value: unknown): T {
  const copy = structuredClone(root)
  const parts = path.split('.')
  let cursor: unknown = copy
  for (const part of parts.slice(0, -1)) {
    if (cursor === null || typeof cursor !== 'object') return copy
    cursor = (cursor as Record<string, unknown>)[part]
  }
  const last = parts[parts.length - 1]
  if (last !== undefined && cursor !== null && typeof cursor === 'object') {
    ;(cursor as Record<string, unknown>)[last] = value
  }
  return copy
}

/** Apply dotted-key overrides to a copy of `root`. */
export function applyOverrides<T>(root: T, overrides: Record<string, unknown>): T {
  let result = root
  for (const [path, value] of Object.entries(overrides)) result = withPath(result, path, value)
  return result
}
