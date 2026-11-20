import type { ReactNode } from 'react'

import type { ApiErrorBody, Job } from '../api/types.ts'
import { errorText, type MessageKey, useI18n, useT } from '../i18n/index.ts'

export function ErrorBox({ error, children }: { error: ApiErrorBody; children?: ReactNode }) {
  const lang = useI18n((state) => state.lang)
  const t = useT()
  const { message, hint } = errorText(lang, error)
  return (
    <div className="error-box" role="alert">
      <strong>{message}</strong>
      {hint ? <p>{hint}</p> : null}
      {error.detail ? (
        <details>
          <summary>{t('app.detail')}</summary>
          <pre>{error.detail}</pre>
        </details>
      ) : null}
      {children}
    </div>
  )
}

export function Spinner({ label }: { label?: string }) {
  const t = useT()
  return (
    <div className="spinner" role="status">
      <span className="spinner-dot" aria-hidden="true" />
      {label ?? t('app.loading')}
    </div>
  )
}

const STAGE_KEYS: Record<string, MessageKey> = {
  ingest: 'job.stage.ingest',
  separate: 'job.stage.separate',
  analyze: 'job.stage.analyze',
  asr: 'job.stage.asr',
  align: 'job.stage.align',
  pitch: 'job.stage.pitch',
  subtitles: 'job.stage.subtitles',
  export: 'job.stage.export',
}

/** Progress bar of a job with its current stage and a cancel button. */
export function JobProgress({ job, onCancel }: { job: Job; onCancel?: () => void }) {
  const t = useT()
  const percent = Math.round(job.progress * 100)
  const stageKey = job.stage ? STAGE_KEYS[job.stage] : undefined
  const label =
    job.state === 'queued'
      ? t('job.state.queued')
      : stageKey
        ? t(stageKey)
        : t(`job.kind.${job.kind}` as MessageKey)
  return (
    <div className="job-progress" data-testid="job-progress">
      <div className="job-progress-head">
        <span>{label}</span>
        <span>{job.state === 'running' ? `${percent}%` : ''}</span>
      </div>
      <progress max={100} value={job.state === 'running' ? percent : undefined} />
      {job.message && job.state === 'running' ? <small>{job.message}</small> : null}
      {onCancel ? (
        <button type="button" className="ghost" onClick={onCancel}>
          {t('job.cancel')}
        </button>
      ) : null}
    </div>
  )
}

export function Modal({
  title,
  onClose,
  children,
  wide,
}: {
  title: string
  onClose: () => void
  children: ReactNode
  wide?: boolean
}) {
  const t = useT()
  return (
    <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <div className={wide ? 'modal wide' : 'modal'} role="dialog" aria-modal="true" aria-label={title}>
        <header>
          <h2>{title}</h2>
          <button type="button" className="ghost" onClick={onClose} aria-label={t('app.close')}>
            ✕
          </button>
        </header>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  )
}
