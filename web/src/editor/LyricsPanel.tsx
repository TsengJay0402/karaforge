import { type MouseEvent, useEffect, useRef, useState } from 'react'

import { api, toErrorBody } from '../api/client.ts'
import type { Line } from '../api/types.ts'
import { ErrorBox } from '../components/common.tsx'
import { useT } from '../i18n/index.ts'
import { useEditor, useEditorState } from './context.ts'
import {
  clearTiming,
  deleteLine,
  insertLine,
  lineText,
  mergeWithNext,
  replaceLine,
  sameRef,
  setLocked,
  setRuby,
  setSinger,
  setTokenEnd,
  setTokenStart,
  splitLine,
  type TokenRef,
  tokenAt,
} from './doc.ts'
import type { SelectMode } from './store.ts'
import { confidenceClass, editableText } from './tokens.ts'

function selectMode(event: MouseEvent): SelectMode {
  if (event.shiftKey) return 'range'
  return event.ctrlKey || event.metaKey ? 'toggle' : 'replace'
}

function LineRow({ line, index }: { line: Line; index: number }) {
  const t = useT()
  const { store, transport } = useEditor()
  const singers = useEditorState((state) => state.history.present.singers)
  const selection = useEditorState((state) => state.selection)
  const current = useEditorState((state) => state.current)
  const tapCursor = useEditorState((state) => state.tapCursor)
  const readOnly = useEditorState((state) => state.readOnly)
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState('')
  const [failure, setFailure] = useState<unknown>(null)
  const row = useRef<HTMLLIElement>(null)
  const isCurrent = current?.line === index

  useEffect(() => {
    if (isCurrent) row.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [isCurrent])

  const begin = () => {
    if (readOnly) return
    setText(editableText(line))
    setFailure(null)
    setEditing(true)
  }

  const commit = async () => {
    if (text === editableText(line)) {
      setEditing(false)
      return
    }
    try {
      const updated = await api.retokenize(line, text)
      store.getState().edit((draft) => replaceLine(draft, index, updated), { label: 'edit text' })
      setEditing(false)
    } catch (cause) {
      setFailure(cause)
    }
  }

  const edit = store.getState().edit
  return (
    <li ref={row} className={isCurrent ? 'line current' : 'line'} data-testid={`line-${index}`}>
      <select
        className="singer"
        value={line.singer}
        disabled={readOnly}
        aria-label={t('editor.lyrics.singer')}
        onChange={(event) => edit((draft) => setSinger(draft, index, event.target.value), { label: 'singer' })}
      >
        {singers.map((singer) => (
          <option key={singer.id} value={singer.id}>
            {singer.label}
          </option>
        ))}
      </select>
      {editing ? (
        <span className="line-edit">
          <input
            value={text}
            autoFocus
            data-testid={`line-input-${index}`}
            aria-label={t('editor.lyrics.edit')}
            onChange={(event) => setText(event.target.value)}
            onBlur={() => void commit()}
            onKeyDown={(event) => {
              if (event.key === 'Enter') void commit()
              if (event.key === 'Escape') setEditing(false)
            }}
          />
          {failure ? <ErrorBox error={toErrorBody(failure)} /> : null}
        </span>
      ) : (
        <span className="tokens" onDoubleClick={begin}>
          {line.tokens.length === 0 ? <em className="hint">{t('editor.lyrics.empty')}</em> : null}
          {line.tokens.map((token, tokenIndex) => {
            const ref: TokenRef = { line: index, index: tokenIndex }
            const classes = ['token', confidenceClass(token)]
            if (selection.some((item) => sameRef(item, ref))) classes.push('selected')
            if (current && sameRef(current, ref)) classes.push('playing')
            if (tapCursor && sameRef(tapCursor, ref)) classes.push('tap-next')
            return (
              <button
                type="button"
                key={tokenIndex}
                className={classes.join(' ')}
                data-testid={`token-${index}-${tokenIndex}`}
                onClick={(event) => {
                  store.getState().select(ref, selectMode(event))
                  if (store.getState().tapMode !== 'off') store.getState().setTapCursor(ref)
                  if (token.start_ms !== null) transport.seek(token.start_ms)
                }}
              >
                {token.ruby ? <ruby>{token.text}<rt>{token.ruby}</rt></ruby> : token.text}
              </button>
            )
          })}
        </span>
      )}
      <span className="line-actions">
        <button type="button" className="ghost" disabled={readOnly} onClick={begin} title={t('editor.lyrics.edit')}>
          ✎
        </button>
        <button
          type="button"
          className="ghost"
          disabled={readOnly}
          title={t('editor.lyrics.addLine')}
          onClick={() => edit((draft) => void insertLine(draft, index), { label: 'insert line' })}
        >
          ＋
        </button>
        <button
          type="button"
          className="ghost"
          disabled={readOnly}
          title={t('editor.lyrics.merge')}
          onClick={() => edit((draft) => mergeWithNext(draft, index), { label: 'merge lines' })}
        >
          ⤵
        </button>
        <button
          type="button"
          className="ghost danger"
          disabled={readOnly}
          title={t('editor.lyrics.deleteLine')}
          onClick={() => edit((draft) => deleteLine(draft, index), { label: 'delete line' })}
        >
          ✕
        </button>
      </span>
    </li>
  )
}

/** Details of the single selected token: exact times, reading, lock. */
function Inspector() {
  const t = useT()
  const { store } = useEditor()
  const selection = useEditorState((state) => state.selection)
  const doc = useEditorState((state) => state.history.present)
  const readOnly = useEditorState((state) => state.readOnly)
  const ref = selection.length === 1 ? selection[0] : undefined
  const token = ref ? tokenAt(doc, ref) : undefined
  const edit = store.getState().edit
  if (selection.length === 0) {
    return (
      <div className="inspector legend">
        <span className="token low">{t('editor.legend.low')}</span>
        <span className="token mid">{t('editor.legend.mid')}</span>
        <span className="token locked">{t('editor.legend.locked')}</span>
        <span className="token untimed">{t('editor.legend.untimed')}</span>
      </div>
    )
  }
  const allLocked = selection.every((item) => tokenAt(doc, item)?.locked)
  return (
    <div className="inspector" data-testid="inspector">
      {ref && token ? (
        <>
          <strong className="inspector-text">{token.text.trim()}</strong>
          <label>
            ▶
            <input
              type="number"
              step={10}
              disabled={readOnly}
              data-testid="token-start"
              value={token.start_ms ?? ''}
              onChange={(event) => {
                const value = Number(event.target.value)
                if (event.target.value !== '' && Number.isFinite(value)) {
                  edit((draft) => setTokenStart(draft, ref, value), { label: 'start', mergeKey: 'type-start' })
                }
              }}
            />
          </label>
          <label>
            ■
            <input
              type="number"
              step={10}
              disabled={readOnly || token.start_ms === null}
              data-testid="token-end"
              value={token.end_ms ?? ''}
              onChange={(event) => {
                const value = Number(event.target.value)
                if (event.target.value !== '' && Number.isFinite(value)) {
                  edit((draft) => setTokenEnd(draft, ref, value), { label: 'end', mergeKey: 'type-end' })
                }
              }}
            />
          </label>
          <label title={t('editor.lyrics.rubyHint')}>
            {t('editor.lyrics.ruby')}
            <input
              className="ruby-input"
              disabled={readOnly}
              value={token.ruby ?? ''}
              data-testid="token-ruby"
              onChange={(event) =>
                edit((draft) => setRuby(draft, ref, event.target.value), { label: 'ruby', mergeKey: 'type-ruby' })
              }
            />
          </label>
          <button
            type="button"
            disabled={readOnly || ref.index === 0}
            onClick={() => edit((draft) => splitLine(draft, ref), { label: 'split line' })}
          >
            {t('editor.lyrics.split')}
          </button>
        </>
      ) : (
        <strong>{selection.length}</strong>
      )}
      <button
        type="button"
        disabled={readOnly}
        data-testid="toggle-lock"
        onClick={() => edit((draft) => setLocked(draft, selection, !allLocked), { label: 'lock' })}
      >
        {allLocked ? t('editor.lyrics.unlock') : t('editor.lyrics.lock')}
      </button>
      <button
        type="button"
        disabled={readOnly}
        onClick={() => edit((draft) => clearTiming(draft, selection), { label: 'clear timing' })}
      >
        {t('editor.lyrics.clear')}
      </button>
    </div>
  )
}

export function LyricsPanel() {
  const t = useT()
  const { store } = useEditor()
  const lines = useEditorState((state) => state.history.present.lines)
  const readOnly = useEditorState((state) => state.readOnly)
  return (
    <section className="lyrics" aria-label="lyrics">
      <Inspector />
      <ol className="lines" data-testid="lyrics">
        {lines.map((line, index) => (
          <LineRow key={line.id} line={line} index={index} />
        ))}
      </ol>
      {lines.length === 0 ? (
        <button
          type="button"
          disabled={readOnly}
          onClick={() => store.getState().edit((draft) => void insertLine(draft, -1), { label: 'insert line' })}
        >
          ＋ {t('editor.lyrics.addLine')}
        </button>
      ) : null}
      <p className="hint lyrics-count">{lines.map(lineText).join('').length > 0 ? '' : t('editor.lyrics.empty')}</p>
    </section>
  )
}
