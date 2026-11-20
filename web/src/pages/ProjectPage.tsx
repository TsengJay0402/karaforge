import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { LanguageSwitch } from '../App.tsx'
import { api, toErrorBody } from '../api/client.ts'
import { activeJobOf, isActive, useJobs, useServerEvents } from '../api/events.ts'
import type { ProjectDetail, ServerEvent } from '../api/types.ts'
import { ErrorBox, JobProgress, Spinner } from '../components/common.tsx'
import { Editor } from '../editor/Editor.tsx'
import { type MessageKey, useT } from '../i18n/index.ts'

const STAGES = ['ingest', 'separate', 'analyze', 'asr', 'align'] as const

/** Shown while a project is being processed, or before it has been. */
function Processing({ detail, onChanged }: { detail: ProjectDetail; onChanged: () => void }) {
  const t = useT()
  const id = detail.summary.id
  const jobs = useJobs((state) => state.jobs)
  const job = activeJobOf(jobs, id) ?? (isActive(detail.summary.job) ? detail.summary.job : null)
  const last = detail.summary.last_job
  const [failure, setFailure] = useState<unknown>(null)
  const system = useQuery({ queryKey: ['system'], queryFn: api.system })
  const [profile, setProfile] = useState<string | null>(null)
  const chosen = profile ?? system.data?.default_profile ?? 'balanced'

  const start = async () => {
    try {
      setFailure(null)
      await api.startJob(id, { kind: 'process', profile: chosen })
      onChanged()
    } catch (cause) {
      setFailure(cause)
    }
  }

  const stageIndex = job?.stage ? STAGES.indexOf(job.stage as (typeof STAGES)[number]) : -1
  return (
    <main className="processing">
      <h1>{job ? t('job.processing.title', { title: detail.summary.title }) : detail.summary.title}</h1>
      {job ? (
        <>
          <ol className="stages">
            {STAGES.map((stage, index) => (
              <li
                key={stage}
                className={index < stageIndex ? 'done' : index === stageIndex ? 'active' : undefined}
              >
                {t(`job.stage.${stage}` as MessageKey)}
              </li>
            ))}
          </ol>
          <JobProgress job={job} onCancel={() => void api.cancelJob(job.id)} />
          <p className="hint">{t('job.processing.hint')}</p>
        </>
      ) : (
        <>
          {last?.state === 'failed' && last.error ? (
            <>
              <h2>{t('job.failed.title')}</h2>
              <ErrorBox error={last.error} />
            </>
          ) : (
            <p>{t('job.processing.notProcessed')}</p>
          )}
          {failure ? <ErrorBox error={toErrorBody(failure)} /> : null}
          <div className="field-row">
            <select value={chosen} onChange={(event) => setProfile(event.target.value)}>
              {(system.data?.profiles ?? []).map((item) => (
                <option key={item.name} value={item.name}>
                  {t(`new.quality.${item.name}` as MessageKey)}
                </option>
              ))}
            </select>
            <button type="button" className="primary" onClick={() => void start()}>
              {last?.state === 'failed' ? t('app.retry') : t('job.processing.start')}
            </button>
          </div>
        </>
      )}
    </main>
  )
}

export function ProjectPage() {
  const { id = '' } = useParams()
  const t = useT()
  const client = useQueryClient()
  const detail = useQuery({ queryKey: ['project', id], queryFn: () => api.getProject(id) })
  const jobs = useJobs((state) => state.jobs)
  const refresh = useCallback(() => {
    void client.invalidateQueries({ queryKey: ['project', id] })
  }, [client, id])

  useServerEvents(
    useCallback(
      (event: ServerEvent) => {
        // A finished processing job changes what this page shows; saves and re-alignments
        // inside the editor are handled by the editor itself.
        if (event.type === 'job' && event.job.project_id === id && event.job.kind === 'process' && !isActive(event.job)) {
          refresh()
        }
      },
      [id, refresh],
    ),
  )

  const header = (
    <header className="app-header slim">
      <Link to="/" className="button ghost">
        ← {t('list.title')}
      </Link>
      <LanguageSwitch />
    </header>
  )

  if (detail.isPending) {
    return (
      <>
        {header}
        <Spinner />
      </>
    )
  }
  if (detail.error) {
    return (
      <>
        {header}
        <main className="processing">
          <ErrorBox error={toErrorBody(detail.error)} />
        </main>
      </>
    )
  }
  const data = detail.data
  const active = activeJobOf(jobs, id) ?? (isActive(data.summary.job) ? data.summary.job : null)
  const processing = active?.kind === 'process'
  if (processing || !data.summary.processed) {
    return (
      <>
        {header}
        <Processing detail={data} onChanged={refresh} />
      </>
    )
  }
  return <Editor key={id} detail={data} />
}
