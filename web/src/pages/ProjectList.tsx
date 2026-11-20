import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { api, toErrorBody } from '../api/client.ts'
import { isActive, useJobs, useServerEvents } from '../api/events.ts'
import type { ProjectSummary, ServerEvent, SystemInfo } from '../api/types.ts'
import { ErrorBox, JobProgress, Spinner } from '../components/common.tsx'
import { formatTime } from '../editor/timeline.ts'
import { formatBytes, type MessageKey, useI18n, useT } from '../i18n/index.ts'
import { listState } from './listState.ts'

export function SystemNotices({ system }: { system: SystemInfo }) {
  const t = useT()
  const lang = useI18n((state) => state.lang)
  const notices: string[] = []
  if (!system.ffmpeg.found) notices.push(t('system.noFfmpeg'))
  else if (!system.ffmpeg.libass) notices.push(t('system.noLibass'))
  const fallback = lang === 'zh-TW' ? system.device.fallback_reason_zh : system.device.fallback_reason_en
  if (fallback) notices.push(fallback)
  const profile = system.profiles.find((item) => item.name === system.default_profile)
  const missing = profile?.models.filter((model) => !model.installed) ?? []
  if (missing.length > 0) {
    notices.push(
      t('system.modelsMissing', {
        profile: t(`new.quality.${system.default_profile}` as MessageKey),
        count: missing.length,
        size: formatBytes(missing.reduce((sum, model) => sum + model.bytes, 0)),
      }),
    )
  }
  if (notices.length === 0) return null
  return (
    <ul className="notices">
      {notices.map((notice) => (
        <li key={notice}>{notice}</li>
      ))}
    </ul>
  )
}

function Card({ summary, onDelete }: { summary: ProjectSummary; onDelete: () => void }) {
  const t = useT()
  const lang = useI18n((state) => state.lang)
  const live = useJobs((state) => (summary.job ? state.jobs[summary.job.id] : undefined))
  const job = live ?? summary.job
  const state = listState({ ...summary, job: isActive(job) ? job : null })
  const modified = new Date(summary.modified_at * 1000).toLocaleString(lang)
  return (
    <li className="card" data-testid={`project-${summary.id}`}>
      <Link to={`/p/${encodeURIComponent(summary.id)}`} className="card-link" aria-label={summary.title}>
        <div className="card-art">
          {summary.has_thumbnail ? (
            <img src={api.thumbnailUrl(summary.id)} alt="" loading="lazy" />
          ) : (
            <span aria-hidden="true">{summary.title.slice(0, 1).toUpperCase() || '♪'}</span>
          )}
          {summary.duration_ms > 0 ? <time>{formatTime(summary.duration_ms, false)}</time> : null}
        </div>
        <div className="card-body">
          <h3>{summary.title}</h3>
          <p className="card-artist">{summary.artist || ' '}</p>
          <span className={`badge badge-${state}`}>{t(`list.state.${state}` as MessageKey)}</span>
          {isActive(job) ? <JobProgress job={job} /> : null}
          {state === 'ready' || state === 'partial' ? (
            <p className="card-stats">
              {t('list.lines', { lines: summary.stats.lines, tokens: summary.stats.tokens })}
              {summary.stats.low_confidence > 0
                ? ` · ${t('list.lowConfidence', { count: summary.stats.low_confidence })}`
                : ''}
            </p>
          ) : null}
          <p className="card-date">
            {t('list.modified')} {modified}
          </p>
        </div>
      </Link>
      <button type="button" className="ghost danger card-delete" onClick={onDelete} aria-label={t('app.delete')}>
        🗑
      </button>
    </li>
  )
}

export function ProjectList() {
  const t = useT()
  const navigate = useNavigate()
  const client = useQueryClient()
  const [dragging, setDragging] = useState(false)
  const [failure, setFailure] = useState<unknown>(null)
  const projects = useQuery({ queryKey: ['projects'], queryFn: api.listProjects })
  const system = useQuery({ queryKey: ['system'], queryFn: api.system })

  useServerEvents(
    useCallback(
      (event: ServerEvent) => {
        const finished = event.type === 'job' && !isActive(event.job)
        if (event.type === 'project' || finished) void client.invalidateQueries({ queryKey: ['projects'] })
      },
      [client],
    ),
  )

  const remove = async (summary: ProjectSummary) => {
    if (!window.confirm(t('list.deleteConfirm', { title: summary.title }))) return
    try {
      await api.deleteProject(summary.id)
      setFailure(null)
    } catch (cause) {
      setFailure(cause)
    }
    await client.invalidateQueries({ queryKey: ['projects'] })
  }

  return (
    <section
      className={dragging ? 'project-list dragging' : 'project-list'}
      onDragOver={(event) => {
        event.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(event) => {
        event.preventDefault()
        setDragging(false)
        const file = event.dataTransfer.files[0]
        if (file) void navigate('/new', { state: { file } })
      }}
    >
      <div className="list-head">
        <h1>{t('list.title')}</h1>
        <Link to="/new" className="button primary">
          + {t('list.new')}
        </Link>
      </div>
      {system.data ? <SystemNotices system={system.data} /> : null}
      {failure ? <ErrorBox error={toErrorBody(failure)} /> : null}
      {projects.isPending ? <Spinner /> : null}
      {projects.error ? <ErrorBox error={toErrorBody(projects.error)} /> : null}
      {projects.data?.length === 0 ? <p className="empty">{t('list.empty')}</p> : null}
      <ul className="cards">
        {projects.data?.map((summary) => (
          <Card key={summary.id} summary={summary} onDelete={() => void remove(summary)} />
        ))}
      </ul>
    </section>
  )
}
