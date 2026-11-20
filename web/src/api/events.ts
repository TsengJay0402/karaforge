/**
 * One shared `EventSource` on `/api/events`.
 *
 * Job states are collected in a small store that any component can read; other events (a
 * project was saved or changed by a job) are passed to whoever subscribed with
 * `onServerEvent`.  The browser reconnects by itself when the connection drops.
 */
import { useEffect } from 'react'
import { create } from 'zustand'

import type { Job, ServerEvent } from './types.ts'

type Handler = (event: ServerEvent) => void

interface JobsState {
  jobs: Record<string, Job>
  connected: boolean
  put: (job: Job) => void
  putAll: (jobs: Job[]) => void
  setConnected: (connected: boolean) => void
}

export const useJobs = create<JobsState>((set) => ({
  jobs: {},
  connected: false,
  put: (job) => set((state) => ({ jobs: { ...state.jobs, [job.id]: job } })),
  putAll: (jobs) =>
    set((state) => {
      const next = { ...state.jobs }
      for (const job of jobs) next[job.id] = job
      return { jobs: next }
    }),
  setConnected: (connected) => set({ connected }),
}))

export const isActive = (job: Job | null | undefined): job is Job =>
  job != null && (job.state === 'queued' || job.state === 'running')

/** The queued or running job of a project (the oldest one), if any. */
export function activeJobOf(jobs: Record<string, Job>, projectId: string): Job | null {
  const active = Object.values(jobs).filter((job) => job.project_id === projectId && isActive(job))
  active.sort((a, b) => a.created_at - b.created_at)
  return active[0] ?? null
}

const handlers = new Set<Handler>()
let source: EventSource | null = null

function dispatch(event: ServerEvent): void {
  const { put, putAll } = useJobs.getState()
  if (event.type === 'job') put(event.job)
  else if (event.type === 'hello') putAll(event.jobs)
  for (const handler of handlers) handler(event)
}

/** Open the event stream (idempotent).  Returns a function that closes it. */
export function connectEvents(url = '/api/events'): () => void {
  if (source === null && typeof EventSource !== 'undefined') {
    const stream = new EventSource(url)
    stream.onopen = () => useJobs.getState().setConnected(true)
    stream.onerror = () => useJobs.getState().setConnected(false)
    stream.onmessage = (message: MessageEvent<string>) => {
      try {
        dispatch(JSON.parse(message.data) as ServerEvent)
      } catch {
        // A malformed event is ignored; the next one will still arrive.
      }
    }
    source = stream
  }
  return () => {
    source?.close()
    source = null
  }
}

/** Call `handler` for every server event while the component is mounted. */
export function useServerEvents(handler: Handler): void {
  useEffect(() => {
    handlers.add(handler)
    return () => {
      handlers.delete(handler)
    }
  }, [handler])
}

/** For tests: deliver an event as if the server had sent it. */
export function emitServerEvent(event: ServerEvent): void {
  dispatch(event)
}
