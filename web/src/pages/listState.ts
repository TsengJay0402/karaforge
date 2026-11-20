import type { ProjectSummary } from '../api/types.ts'

export type ListState =
  | 'broken'
  | 'queued'
  | 'processing'
  | 'failed'
  | 'noLyrics'
  | 'new'
  | 'partial'
  | 'ready'

export function listState(summary: ProjectSummary): ListState {
  if (summary.broken) return 'broken'
  if (summary.job) return summary.job.state === 'queued' ? 'queued' : 'processing'
  const last = summary.last_job
  if (last?.state === 'failed' && last.kind !== 'export') return 'failed'
  if (!summary.processed) return 'new'
  if (summary.stats.tokens === 0) return 'noLyrics'
  if (summary.stats.timed_tokens === summary.stats.tokens) return 'ready'
  return summary.stats.timed_tokens > 0 ? 'partial' : 'new'
}
