import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import { api, toErrorBody } from '../api/client.ts'
import { isActive, useJobs } from '../api/events.ts'
import type { Job } from '../api/types.ts'
import { ErrorBox, JobProgress, Modal } from '../components/common.tsx'
import { formatBytes, type MessageKey, useI18n, useT } from '../i18n/index.ts'
import { useEditor, useEditorState } from './context.ts'
import { allRefs, lineRefs, overlappingRefs, setLocked, shiftTokens, tokenAt } from './doc.ts'
import { HOTKEYS, MOUSE_ACTIONS } from './hotkeys.ts'
import { selectedLines } from './store.ts'

export function HotkeyHelp({ onClose }: { onClose: () => void }) {
  const t = useT()
  return (
    <Modal title={t('help.title')} onClose={onClose}>
      <table className="hotkeys">
        <tbody>
          {HOTKEYS.map((item) => (
            <tr key={item.description}>
              <th>
                {item.keys.map((key) => (
                  <kbd key={key}>{key}</kbd>
                ))}
              </th>
              <td>{t(item.description)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h3>{t('help.mouse')}</h3>
      <table className="hotkeys">
        <tbody>
          {MOUSE_ACTIONS.map((item) => (
            <tr key={item.action}>
              <th>{t(item.action)}</th>
              <td>{t(item.description)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Modal>
  )
}

export function ShiftDialog({ onClose }: { onClose: () => void }) {
  const t = useT()
  const { store } = useEditor()
  const selection = useEditorState((state) => state.selection)
  const lines = selectedLines(selection)
  const [amount, setAmount] = useState('0')
  const [scope, setScope] = useState<'all' | 'lines'>(lines.length > 0 ? 'lines' : 'all')

  const apply = () => {
    const delta = Math.round(Number(amount))
    if (!Number.isFinite(delta) || delta === 0) {
      onClose()
      return
    }
    store.getState().edit(
      (draft) => {
        const refs = scope === 'all' ? allRefs(draft) : lines.flatMap((line) => lineRefs(draft, line))
        shiftTokens(draft, refs, delta)
      },
      { label: 'shift' },
    )
    onClose()
  }

  return (
    <Modal title={t('editor.shift')} onClose={onClose}>
      <div className="form">
        <label className="check">
          <input type="radio" checked={scope === 'all'} onChange={() => setScope('all')} />
          {t('editor.shift.all')}
        </label>
        <label className="check">
          <input
            type="radio"
            checked={scope === 'lines'}
            disabled={lines.length === 0}
            onChange={() => setScope('lines')}
          />
          {t('editor.shift.line')} ({lines.length})
        </label>
        <label>
          {t('editor.shift.amount')}
          <input
            type="number"
            step={10}
            value={amount}
            data-testid="shift-amount"
            autoFocus
            onChange={(event) => setAmount(event.target.value)}
            onKeyDown={(event) => event.key === 'Enter' && apply()}
          />
        </label>
        <div className="quick">
          {[-500, -100, -50, 50, 100, 500].map((value) => (
            <button type="button" key={value} onClick={() => setAmount(String(value))}>
              {value > 0 ? `+${value}` : value}
            </button>
          ))}
        </div>
        <button type="button" className="primary" data-testid="shift-apply" onClick={apply}>
          {t('editor.shift.apply')}
        </button>
      </div>
    </Modal>
  )
}

export function RealignDialog({ onClose }: { onClose: () => void }) {
  const t = useT()
  const { id, store } = useEditor()
  const selection = useEditorState((state) => state.selection)
  const doc = useEditorState((state) => state.history.present)
  const allowOverlap = useEditorState((state) => state.allowOverlap)
  const lines = selectedLines(selection)
  const [failure, setFailure] = useState<unknown>(null)
  // The aligner keeps every line clear of the locked tokens of the others, so an unlocked
  // token that overlaps another line on purpose (a duet) would be pushed out of the way.
  const unlockedOverlaps = allowOverlap
    ? overlappingRefs(doc).filter((ref) => tokenAt(doc, ref)?.locked === false)
    : []

  const start = async (onlySelected: boolean) => {
    try {
      if (unlockedOverlaps.length > 0) {
        store.getState().edit((draft) => setLocked(draft, unlockedOverlaps, true), { label: 'lock overlaps' })
      }
      // The server aligns what is saved: make sure it has the latest corrections.
      await store.getState().saveNow()
      const ids = onlySelected ? lines.map((line) => doc.lines[line]?.id).filter((x): x is string => !!x) : undefined
      await api.startJob(id, { kind: 'align', lines: ids })
      onClose()
    } catch (cause) {
      setFailure(cause)
    }
  }

  return (
    <Modal title={t('editor.realign')} onClose={onClose}>
      <p className="hint">{t('editor.realign.hint')}</p>
      {unlockedOverlaps.length > 0 ? (
        <p className="hint" data-testid="realign-overlap">
          {t('editor.realign.overlap', { count: unlockedOverlaps.length })}
        </p>
      ) : null}
      {failure ? <ErrorBox error={toErrorBody(failure)} /> : null}
      <div className="form">
        <button type="button" className="primary" data-testid="realign-all" onClick={() => void start(false)}>
          {t('editor.realign.all')}
        </button>
        <button type="button" disabled={lines.length === 0} onClick={() => void start(true)}>
          {t('editor.realign.lines', { count: lines.length })}
        </button>
      </div>
    </Modal>
  )
}

const RESOLUTIONS: [string, [number, number]][] = [
  ['720p', [1280, 720]],
  ['1080p', [1920, 1080]],
  ['1440p', [2560, 1440]],
  ['4K', [3840, 2160]],
]

export function ExportDialog({ onClose }: { onClose: () => void }) {
  const t = useT()
  const lang = useI18n((state) => state.lang)
  const client = useQueryClient()
  const { id, store } = useEditor()
  const doc = useEditorState((state) => state.history.present)
  const system = useQuery({ queryKey: ['system'], queryFn: api.system })
  const exportsQuery = useQuery({ queryKey: ['exports', id], queryFn: () => api.listExports(id) })
  const jobs = useJobs((state) => state.jobs)
  const [format, setFormat] = useState('mp4')
  const [resolution, setResolution] = useState('project')
  const [audio, setAudio] = useState('instrumental')
  const [guide, setGuide] = useState(-12)
  const [background, setBackground] = useState<string>(doc.render.background.type)
  const [jobId, setJobId] = useState<string | null>(null)
  const [failure, setFailure] = useState<unknown>(null)
  const formats = system.data?.formats ?? []
  const chosen = formats.find((item) => item.id === format)
  const job: Job | undefined = jobId ? jobs[jobId] : undefined
  const finished = job !== undefined && !isActive(job)

  // A finished export means there is a new file to list.
  useEffect(() => {
    if (finished) void client.invalidateQueries({ queryKey: ['exports', id] })
  }, [finished, client, id])

  const start = async () => {
    try {
      setFailure(null)
      await store.getState().saveNow()
      const size = RESOLUTIONS.find(([name]) => name === resolution)?.[1] ?? null
      const started = await api.startExport(id, {
        format,
        audio: audio === 'guide' ? `guide:${guide}db` : audio,
        resolution: chosen?.video ? size : null,
        background: chosen?.video ? background : null,
      })
      setJobId(started.id)
    } catch (cause) {
      setFailure(cause)
    }
  }

  return (
    <Modal title={t('export.title')} onClose={onClose} wide>
      <div className="form two-columns">
        <label>
          {t('export.format')}
          <select value={format} data-testid="export-format" onChange={(event) => setFormat(event.target.value)}>
            {formats.map((item) => (
              <option key={item.id} value={item.id}>
                {lang === 'zh-TW' ? item.title_zh : item.title_en}
              </option>
            ))}
          </select>
        </label>
        {chosen?.video ? (
          <>
            <label>
              {t('export.resolution')}
              <select value={resolution} onChange={(event) => setResolution(event.target.value)}>
                <option value="project">
                  {t('export.resolution.project', {
                    width: doc.render.resolution[0],
                    height: doc.render.resolution[1],
                  })}
                </option>
                {RESOLUTIONS.map(([name, [width, height]]) => (
                  <option key={name} value={name}>
                    {name} ({width}×{height})
                  </option>
                ))}
              </select>
            </label>
            <label>
              {t('export.audio')}
              <select value={audio} onChange={(event) => setAudio(event.target.value)}>
                {(['instrumental', 'guide', 'original'] as const).map((item) => (
                  <option key={item} value={item}>
                    {t(`export.audio.${item}` as MessageKey)}
                  </option>
                ))}
              </select>
            </label>
            {audio === 'guide' ? (
              <label>
                {t('export.guideLevel')}
                <input
                  type="number"
                  max={0}
                  min={-40}
                  value={guide}
                  onChange={(event) => setGuide(Number(event.target.value))}
                />
              </label>
            ) : null}
            <label>
              {t('export.background')}
              <select value={background} onChange={(event) => setBackground(event.target.value)}>
                {(['video', 'color', 'image', 'blur'] as const).map((item) => (
                  <option key={item} value={item}>
                    {t(`export.background.${item}` as MessageKey)}
                  </option>
                ))}
              </select>
            </label>
          </>
        ) : null}
      </div>
      {format === 'ultrastar' ? <p className="hint">{t('export.ultrastarHint')}</p> : null}
      {failure ? <ErrorBox error={toErrorBody(failure)} /> : null}
      {job && isActive(job) ? (
        <JobProgress job={job} onCancel={() => void api.cancelJob(job.id)} />
      ) : (
        <button type="button" className="primary" data-testid="export-start" onClick={() => void start()}>
          {t('export.start')}
        </button>
      )}
      {job?.state === 'failed' && job.error ? <ErrorBox error={job.error} /> : null}
      <h3>{t('export.files')}</h3>
      {exportsQuery.data?.length === 0 ? <p className="hint">{t('export.none')}</p> : null}
      <ul className="export-files" data-testid="export-files">
        {exportsQuery.data?.map((file) => (
          <li key={file.name}>
            <span>{file.name}</span>
            <small>{formatBytes(file.bytes)}</small>
            <a className="button" href={file.url} download={file.name}>
              {t('export.download')}
            </a>
          </li>
        ))}
      </ul>
    </Modal>
  )
}
