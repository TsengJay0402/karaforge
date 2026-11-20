import { useQuery } from '@tanstack/react-query'
import { type FormEvent, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'

import { api } from '../api/client.ts'
import { ErrorBox, toErrorBody } from '../components/common.tsx'
import { formatBytes, type MessageKey, useT } from '../i18n/index.ts'

type LyricsMode = 'paste' | 'file' | 'none'

const LANGUAGES: [string, string][] = [
  ['zh-TW', '中文'],
  ['en', 'English'],
  ['ja', '日本語'],
  ['ko', '한국어'],
]
const MEDIA_ACCEPT = '.mp4,.mkv,.mov,.webm,.mp3,.wav,.flac,.m4a,.ogg,.opus,.aac,.avi,audio/*,video/*'

function stem(name: string): string {
  const dot = name.lastIndexOf('.')
  return dot > 0 ? name.slice(0, dot) : name
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
  const input = useRef<HTMLInputElement>(null)

  const chosenProfile = profile ?? system.data?.default_profile ?? 'balanced'

  const choose = (file: File | undefined | null) => {
    if (!file) return
    setMedia(file)
    setTitle((current) => current || stem(file.name))
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!media) {
      setFailure(new Error(t('new.needMedia')))
      return
    }
    setBusy(true)
    setFailure(null)
    try {
      const created = await api.createProject({
        media,
        lyrics: mode === 'paste' ? lyrics : undefined,
        lyricsFile: mode === 'file' ? lyricsFile : null,
        title: title.trim(),
        artist: artist.trim(),
        language,
        profile: chosenProfile,
        start: true,
      })
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
      <div className="wizard-actions">
        <button type="submit" className="primary" disabled={busy}>
          {busy ? t('new.creating') : t('new.start')}
        </button>
      </div>
    </form>
  )
}
