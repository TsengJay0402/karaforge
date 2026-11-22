import { useQuery } from '@tanstack/react-query'
import { type ClipboardEvent, type SyntheticEvent, useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'

import { api, toErrorBody } from '../api/client.ts'
import { isActive, useJobs } from '../api/events.ts'
import type { RemoteMedia } from '../api/types.ts'
import { ErrorBox, JobProgress } from '../components/common.tsx'
import { formatTime } from '../editor/timeline.ts'
import { formatBytes, type MessageKey, useT } from '../i18n/index.ts'

type LyricsMode = 'paste' | 'file' | 'none'

const LANGUAGES: [string, string][] = [
  ['zh-TW', '中文'],
  ['en', 'English'],
  ['ja', '日本語'],
  ['ko', '한국어'],
]
const MEDIA_ACCEPT = '.mp4,.mkv,.mov,.webm,.mp3,.wav,.flac,.m4a,.ogg,.opus,.aac,.avi,audio/*,video/*'
const LINK_PATTERN = /^https?:\/\/\S+$/i

function stem(name: string): string {
  const dot = name.lastIndexOf('.')
  return dot > 0 ? name.slice(0, dot) : name
}

/** The video a link points to, as the wizard shows it once yt-dlp has read it. */
function RemoteCard({ media, onRemove, disabled }: { media: RemoteMedia; onRemove: () => void; disabled: boolean }) {
  const t = useT()
  const details = [
    media.uploader,
    media.duration_ms !== null ? formatTime(media.duration_ms, false) : null,
    media.size_bytes !== null ? t('new.url.size', { size: formatBytes(media.size_bytes) }) : null,
    media.extractor,
  ].filter((item): item is string => Boolean(item))
  return (
    <div className="remote-card" data-testid="remote-media">
      {media.thumbnail ? (
        <img src={media.thumbnail} alt="" referrerPolicy="no-referrer" loading="lazy" />
      ) : (
        <span className="remote-art" aria-hidden="true">
          ♪
        </span>
      )}
      <div className="remote-body">
        <strong>{media.title || media.url}</strong>
        <small>{details.join(' · ')}</small>
        <small className="remote-notice">{t('new.url.notice')}</small>
      </div>
      <button type="button" className="ghost" onClick={onRemove} disabled={disabled}>
        {t('new.url.remove')}
      </button>
    </div>
  )
}

export function NewProject() {
  const t = useT()
  const navigate = useNavigate()
  const location = useLocation()
  const dropped = (location.state as { file?: File } | null)?.file ?? null
  const system = useQuery({ queryKey: ['system'], queryFn: api.system })
  const [media, setMedia] = useState<File | null>(dropped)
  const [title, setTitle] = useState(dropped ? stem(dropped.name) : '')
  const [artist, setArtist] = useState('')
  const [language, setLanguage] = useState('zh-TW')
  const [mode, setMode] = useState<LyricsMode>('paste')
  const [lyrics, setLyrics] = useState('')
  const [lyricsFile, setLyricsFile] = useState<File | null>(null)
  const [profile, setProfile] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<unknown>(null)
  const [dragging, setDragging] = useState(false)
  const [link, setLink] = useState('')
  const [remote, setRemote] = useState<RemoteMedia | null>(null)
  const [probing, setProbing] = useState(false)
  const [linkFailure, setLinkFailure] = useState<unknown>(null)
  const [importId, setImportId] = useState<string | null>(null)
  const importJob = useJobs((state) => (importId ? state.jobs[importId] : undefined))
  // A download runs on the server; what the wizard shows follows its job.
  const downloading = importJob !== undefined && (isActive(importJob) || importJob.state === 'done')
  const importError = importJob?.state === 'failed' ? importJob.error : null
  const input = useRef<HTMLInputElement>(null)
  // What the wizard filled in by itself: replaced by the next suggestion unless the user typed.
  const suggested = useRef({ title: dropped ? stem(dropped.name) : '', artist: '' })

  const chosenProfile = profile ?? system.data?.default_profile ?? 'balanced'
  const linksWork = system.data?.ytdlp.found ?? true

  const suggest = (next: { title: string; artist: string }) => {
    const previous = suggested.current
    suggested.current = next
    setTitle((current) => (current === '' || current === previous.title ? next.title : current))
    setArtist((current) => (current === '' || current === previous.artist ? next.artist : current))
  }

  const choose = (file: File | undefined | null) => {
    if (!file) return
    setMedia(file)
    setRemote(null)
    setLink('')
    setLinkFailure(null)
    suggest({ title: stem(file.name), artist: '' })
  }

  const load = async (value: string) => {
    const address = value.trim()
    if (address === '' || probing || remote?.url === address) return
    if (!LINK_PATTERN.test(address)) {
      setLinkFailure(new Error(t('new.url.invalid')))
      return
    }
    setProbing(true)
    setLinkFailure(null)
    try {
      const found = await api.probeUrl(address)
      setRemote(found)
      setLink(found.url)
      setMedia(null)
      suggest({ title: found.title, artist: found.artist })
    } catch (cause) {
      setRemote(null)
      setLinkFailure(cause)
    } finally {
      setProbing(false)
    }
  }

  const pasted = (event: ClipboardEvent<HTMLInputElement>) => {
    // A paste that replaces the whole field reads the link at once; editing waits for Enter.
    const field = event.currentTarget
    const whole = field.selectionStart === 0 && field.selectionEnd === field.value.length
    if (link.trim() !== '' && !whole) return
    const text = event.clipboardData.getData('text/plain').trim()
    if (!text) return
    event.preventDefault()
    setLink(text)
    void load(text)
  }

  // Once the download is done the project exists: open it.
  useEffect(() => {
    if (importJob?.state !== 'done') return
    const id = importJob.result?.project_id
    if (typeof id === 'string') void navigate(`/p/${encodeURIComponent(id)}`)
  }, [importJob, navigate])

  const submit = async (event: SyntheticEvent) => {
    event.preventDefault()
    if (!media && !remote) {
      setFailure(new Error(t('new.needMedia')))
      return
    }
    setBusy(true)
    setFailure(null)
    setImportId(null)
    const fields = {
      lyrics: mode === 'paste' ? lyrics : undefined,
      lyricsFile: mode === 'file' ? lyricsFile : null,
      title: title.trim(),
      artist: artist.trim(),
      language,
      profile: chosenProfile,
      start: true,
    }
    try {
      if (remote) {
        const job = await api.importProject({ ...fields, url: remote.url })
        useJobs.getState().put(job)
        setImportId(job.id)
        setBusy(false)
        return
      }
      if (!media) return
      const created = await api.createProject({ ...fields, media })
      await navigate(`/p/${encodeURIComponent(created.project.id)}`)
    } catch (cause) {
      setFailure(cause)
      setBusy(false)
    }
  }

  return (
    <form className="wizard" onSubmit={(event) => void submit(event)}>
      <div className="list-head">
        <h1>{t('new.title')}</h1>
        <Link to="/" className="button ghost">
          {t('app.back')}
        </Link>
      </div>

      <fieldset>
        <legend>{t('new.step.media')}</legend>
        {remote ? (
          <RemoteCard
            media={remote}
            disabled={busy || downloading}
            onRemove={() => {
              setRemote(null)
              setLink('')
            }}
          />
        ) : (
          <div
            className={dragging ? 'dropzone dragging' : 'dropzone'}
            role="button"
            tabIndex={0}
            onClick={() => input.current?.click()}
            onKeyDown={(event) => (event.key === 'Enter' || event.key === ' ') && input.current?.click()}
            onDragOver={(event) => {
              event.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault()
              setDragging(false)
              choose(event.dataTransfer.files[0])
            }}
          >
            <input
              ref={input}
              type="file"
              accept={MEDIA_ACCEPT}
              hidden
              data-testid="media-input"
              onChange={(event) => choose(event.target.files?.[0])}
            />
            {media ? (
              <strong>{t('new.chosen', { name: media.name, size: formatBytes(media.size) })}</strong>
            ) : (
              <>
                <strong>{t('new.drop')}</strong>
                <small>{t('new.dropHint')}</small>
              </>
            )}
          </div>
        )}
        <div className="link-row">
          <label>
            {t('new.url.label')}
            <input
              type="url"
              inputMode="url"
              value={link}
              placeholder="https://www.youtube.com/watch?v=…"
              disabled={!linksWork || busy || downloading}
              data-testid="media-link"
              onChange={(event) => setLink(event.target.value)}
              onPaste={pasted}
              onKeyDown={(event) => {
                if (event.key !== 'Enter') return
                event.preventDefault()
                void load(link)
              }}
            />
          </label>
          <button
            type="button"
            disabled={
              !linksWork || busy || downloading || probing || link.trim() === '' || remote?.url === link.trim()
            }
            onClick={() => void load(link)}
          >
            {t('new.url.load')}
          </button>
        </div>
        {!linksWork ? <p className="hint">{t('new.url.missing')}</p> : null}
        {probing ? <p className="hint">{t('new.url.loading')}</p> : null}
        {linkFailure ? <ErrorBox error={toErrorBody(linkFailure)} /> : null}
        <div className="field-row">
          <label>
            {t('new.songTitle')}
            <input value={title} onChange={(event) => setTitle(event.target.value)} />
          </label>
          <label>
            {t('new.artist')}
            <input value={artist} onChange={(event) => setArtist(event.target.value)} />
          </label>
          <label>
            {t('new.songLanguage')}
            <select value={language} onChange={(event) => setLanguage(event.target.value)}>
              {LANGUAGES.map(([code, label]) => (
                <option key={code} value={code}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </div>
      </fieldset>

      <fieldset>
        <legend>{t('new.step.lyrics')}</legend>
        <div className="tabs" role="radiogroup">
          {(['paste', 'file', 'none'] as const).map((item) => (
            <label key={item} className={mode === item ? 'tab active' : 'tab'}>
              <input type="radio" name="lyrics-mode" checked={mode === item} onChange={() => setMode(item)} />
              {t(`new.lyrics.${item}` as MessageKey)}
            </label>
          ))}
        </div>
        {mode === 'paste' ? (
          <textarea
            rows={10}
            value={lyrics}
            placeholder={t('new.lyrics.placeholder')}
            aria-label={t('new.lyrics.paste')}
            onChange={(event) => setLyrics(event.target.value)}
          />
        ) : null}
        {mode === 'file' ? (
          <label className="file-field">
            <input
              type="file"
              accept=".txt,.lrc,.srt,.ass,.ssa"
              onChange={(event) => setLyricsFile(event.target.files?.[0] ?? null)}
            />
            <small>{t('new.lyrics.fileHint')}</small>
          </label>
        ) : null}
        {mode === 'none' ? <p className="hint">{t('new.lyrics.noneHint')}</p> : null}
      </fieldset>

      <fieldset>
        <legend>{t('new.step.quality')}</legend>
        <div className="choices">
          {(system.data?.profiles ?? []).map((item) => {
            const missing = item.models.filter((model) => !model.installed)
            const size = missing.reduce((sum, model) => sum + model.bytes, 0)
            return (
              <label key={item.name} className={chosenProfile === item.name ? 'choice active' : 'choice'}>
                <input
                  type="radio"
                  name="profile"
                  checked={chosenProfile === item.name}
                  onChange={() => setProfile(item.name)}
                />
                <strong>{t(`new.quality.${item.name}` as MessageKey)}</strong>
                <small>{t(`new.quality.${item.name}.hint` as MessageKey)}</small>
                <small className="mono">
                  {item.asr_model} · {item.aligner}
                  {size > 0 ? ` · ↓ ${formatBytes(size)}` : ''}
                </small>
              </label>
            )
          })}
        </div>
      </fieldset>

      {failure ? <ErrorBox error={toErrorBody(failure)} /> : null}
      {importError ? <ErrorBox error={importError} /> : null}
      {importJob?.state === 'cancelled' ? <p className="hint">{t('new.url.cancelled')}</p> : null}
      {importJob && isActive(importJob) ? (
        <div className="import-progress" data-testid="import-progress">
          <p className="hint">{t('new.url.downloading')}</p>
          <JobProgress job={importJob} onCancel={() => void api.cancelJob(importJob.id)} />
        </div>
      ) : null}
      <div className="wizard-actions">
        <button type="submit" className="primary" disabled={busy || downloading || probing}>
          {busy || downloading ? (remote ? t('new.downloading') : t('new.creating')) : t('new.start')}
        </button>
      </div>
    </form>
  )
}
