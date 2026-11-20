/**
 * The theme editor.  Changes are stored as overrides in the project (`style.overrides`), so
 * the preview updates as you type; "save as" turns the result into a reusable theme file.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api, toErrorBody } from '../api/client.ts'
import type { Theme } from '../api/types.ts'
import { ErrorBox, Spinner } from '../components/common.tsx'
import { type MessageKey, useT } from '../i18n/index.ts'
import { useEditor, useEditorState } from './context.ts'
import { applyReadings, readingKind } from './doc.ts'
import { applyOverrides, getPath } from './paths.ts'

const SLOTS = ['male', 'female', 'duet'] as const
const NAME_PATTERN = /^[a-z0-9][a-z0-9-]{0,39}$/

function asNumber(value: unknown, fallback = 0): number {
  return typeof value === 'number' ? value : fallback
}

function asString(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}

export function ThemePanel({ onClose }: { onClose: () => void }) {
  const t = useT()
  const client = useQueryClient()
  const { store } = useEditor()
  const style = useEditorState((state) => state.history.present.style)
  const readOnly = useEditorState((state) => state.readOnly)
  const themes = useQuery({ queryKey: ['themes'], queryFn: api.themes })
  const fonts = useQuery({ queryKey: ['fonts'], queryFn: api.fonts })
  const [name, setName] = useState('')
  const [failure, setFailure] = useState<unknown>(null)
  const [saved, setSaved] = useState<string | null>(null)
  const language = useEditorState((state) => state.history.present.meta.language)
  const existingKind = useEditorState((state) => readingKind(state.history.present))
  const [chosenKind, setChosenKind] = useState<'zhuyin' | 'pinyin' | null>(null)
  const [readingsDone, setReadingsDone] = useState<number | null>(null)

  const entry = themes.data?.find((item) => item.name === style.theme)
  const base = entry?.theme ?? null
  if (themes.isPending) return <aside className="theme-panel"><Spinner /></aside>
  if (!base) {
    return (
      <aside className="theme-panel">
        {entry?.error ? <ErrorBox error={entry.error} /> : null}
        {themes.error ? <ErrorBox error={toErrorBody(themes.error)} /> : null}
        <button type="button" onClick={onClose}>
          {t('app.close')}
        </button>
      </aside>
    )
  }
  const theme: Theme = applyOverrides(base, style.overrides)
  const edit = store.getState().edit

  const set = (path: string, value: unknown) =>
    edit(
      (draft) => {
        draft.style.overrides[path] = value
      },
      { label: 'theme', mergeKey: `theme:${path}` },
    )

  const number = (path: string, label: string, min: number, max: number, step: number) => (
    <label key={path}>
      {label}
      <input
        type="number"
        min={min}
        max={max}
        step={step}
        disabled={readOnly}
        data-testid={`theme-${path}`}
        value={asNumber(getPath(theme, path))}
        onChange={(event) => {
          const value = Number(event.target.value)
          if (event.target.value !== '' && Number.isFinite(value)) set(path, value)
        }}
      />
    </label>
  )

  const slider = (path: string, label: string) => (
    <label key={path}>
      {label}
      <input
        type="range"
        min={0}
        max={1}
        step={0.01}
        disabled={readOnly}
        value={asNumber(getPath(theme, path))}
        onChange={(event) => set(path, Number(event.target.value))}
      />
      <output>{asNumber(getPath(theme, path)).toFixed(2)}</output>
    </label>
  )

  const color = (path: string, label: string) => {
    const value = asString(getPath(theme, path), '#FFFFFF')
    return (
      <label key={path} className="color">
        {label}
        <input
          type="color"
          disabled={readOnly}
          data-testid={`theme-${path}`}
          value={value.slice(0, 7).toLowerCase()}
          onChange={(event) => set(path, event.target.value.toUpperCase() + value.slice(7))}
        />
      </label>
    )
  }

  const toggle = (path: string, label: string) => (
    <label key={path} className="check">
      <input
        type="checkbox"
        disabled={readOnly}
        checked={getPath(theme, path) === true}
        onChange={(event) => set(path, event.target.checked)}
      />
      {label}
    </label>
  )

  const kind = chosenKind ?? existingKind ?? (language.toLowerCase().startsWith('zh-cn') ? 'pinyin' : 'zhuyin')
  const readings = async (wanted: 'zhuyin' | 'pinyin' | 'none') => {
    try {
      setFailure(null)
      const annotated = await api.readings(store.getState().history.present.lines, wanted, language)
      let count = 0
      edit(
        (draft) => {
          count = applyReadings(draft, annotated)
        },
        { label: 'ruby' },
      )
      setReadingsDone(count)
    } catch (cause) {
      setFailure(cause)
    }
  }

  const saveAs = async () => {
    try {
      setFailure(null)
      const stored = await api.saveTheme(name, { ...theme, name })
      edit(
        (draft) => {
          draft.style.theme = stored.name
          draft.style.overrides = {}
        },
        { label: 'theme' },
      )
      await client.invalidateQueries({ queryKey: ['themes'] })
      setSaved(stored.name)
      setName('')
    } catch (cause) {
      setFailure(cause)
    }
  }

  return (
    <aside className="theme-panel" aria-label={t('theme.title')} data-testid="theme-panel">
      <header>
        <h2>{t('theme.title')}</h2>
        <button type="button" className="ghost" onClick={onClose} aria-label={t('app.close')}>
          ✕
        </button>
      </header>
      <label>
        {t('theme.choose')}
        <select
          value={style.theme}
          disabled={readOnly}
          data-testid="theme-select"
          onChange={(event) =>
            edit(
              (draft) => {
                draft.style.theme = event.target.value
                draft.style.overrides = {}
              },
              { label: 'theme' },
            )
          }
        >
          {(themes.data ?? []).map((item) => (
            <option key={item.name} value={item.name}>
              {asString(item.theme?.title) || item.name} ({t(item.builtin ? 'theme.builtin' : 'theme.custom')})
            </option>
          ))}
        </select>
      </label>

      <fieldset>
        <legend>{t('theme.font')}</legend>
        <label>
          {t('theme.font')}
          <select
            value={theme.font.family}
            disabled={readOnly}
            onChange={(event) => set('font.family', event.target.value)}
          >
            {(fonts.data ?? []).map((font) => (
              <option key={font.file} value={font.family}>
                {font.family}
              </option>
            ))}
          </select>
        </label>
        {number('font.size', t('theme.size'), 20, 240, 2)}
        {number('font.letter_spacing', t('theme.spacing'), 0, 40, 0.5)}
        {number('text.outline', t('theme.outline'), 0, 20, 0.5)}
      </fieldset>

      <fieldset>
        <legend>{t('theme.position')}</legend>
        {slider('layout.rows.0.y', t('theme.rowTop'))}
        {slider('layout.rows.1.y', t('theme.rowBottom'))}
        {slider('background.dim_bottom', t('theme.dimBottom'))}
      </fieldset>

      <fieldset>
        <legend>{t('theme.colors')}</legend>
        <div className="color-row">
          <span>{t('theme.unsung')}</span>
          {color('colors.unsung.fill', t('theme.fill'))}
          {color('colors.unsung.outline', t('theme.outlineColor'))}
        </div>
        {SLOTS.map((slot) => (
          <div className="color-row" key={slot}>
            <span>
              {t(`theme.slot.${slot}` as MessageKey)} · {t('theme.sung')}
            </span>
            {color(`colors.slots.${slot}.fill`, t('theme.fill'))}
            {color(`colors.slots.${slot}.outline`, t('theme.outlineColor'))}
          </div>
        ))}
      </fieldset>

      <fieldset>
        <legend>{t('theme.readings')}</legend>
        {toggle('ruby.enabled', t('theme.ruby'))}
        <label>
          {t('theme.readings.kind')}
          <select
            value={kind}
            disabled={readOnly}
            data-testid="readings-kind"
            onChange={(event) => setChosenKind(event.target.value === 'pinyin' ? 'pinyin' : 'zhuyin')}
          >
            <option value="zhuyin">{t('theme.readings.zhuyin')}</option>
            <option value="pinyin">{t('theme.readings.pinyin')}</option>
          </select>
        </label>
        <div className="button-row">
          <button type="button" disabled={readOnly} data-testid="readings-generate" onClick={() => void readings(kind)}>
            {t('theme.readings.generate')}
          </button>
          <button type="button" disabled={readOnly} data-testid="readings-clear" onClick={() => void readings('none')}>
            {t('theme.readings.clear')}
          </button>
        </div>
        {readingsDone === null ? null : (
          <p className="hint" data-testid="readings-done">
            {t('theme.readings.done', { count: readingsDone })}
          </p>
        )}
        <p className="hint">{t('theme.readings.hint')}</p>
      </fieldset>

      <fieldset>
        {toggle('countdown.enabled', t('theme.countdown'))}
        {toggle('title_card.enabled', t('theme.titleCard'))}
      </fieldset>

      <button
        type="button"
        disabled={readOnly || Object.keys(style.overrides).length === 0}
        onClick={() =>
          edit(
            (draft) => {
              draft.style.overrides = {}
            },
            { label: 'theme' },
          )
        }
      >
        {t('theme.reset')}
      </button>

      <fieldset>
        <legend>{t('theme.saveAs')}</legend>
        <label>
          {t('theme.saveAs.name')}
          <input value={name} data-testid="theme-name" onChange={(event) => setName(event.target.value)} />
        </label>
        <button
          type="button"
          className="primary"
          disabled={!NAME_PATTERN.test(name)}
          data-testid="theme-save"
          onClick={() => void saveAs()}
        >
          {t('theme.saveAs')}
        </button>
        {saved ? <p className="hint">{t('theme.saved', { name: saved })}</p> : null}
        {failure ? <ErrorBox error={toErrorBody(failure)} /> : null}
      </fieldset>
    </aside>
  )
}
