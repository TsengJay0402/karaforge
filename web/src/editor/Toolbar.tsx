import { useT } from '../i18n/index.ts'
import { useEditor, useEditorState } from './context.ts'
import { refAtTime, timingStats } from './doc.ts'
import type { Dialog } from './Editor.tsx'
import { canRedo, canUndo } from './history.ts'
import type { AudioMode } from './store.ts'

const RATES = [0.5, 0.75, 1, 1.25, 1.5]

export function Toolbar({ onDialog }: { onDialog: (dialog: Dialog) => void }) {
  const t = useT()
  const { store, transport } = useEditor()
  const playing = useEditorState((state) => state.playing)
  const audioMode = useEditorState((state) => state.audioMode)
  const rate = useEditorState((state) => state.rate)
  const snap = useEditorState((state) => state.snap)
  const trackView = useEditorState((state) => state.trackView)
  const tapMode = useEditorState((state) => state.tapMode)
  const saveState = useEditorState((state) => state.saveState)
  const readOnly = useEditorState((state) => state.readOnly)
  const undoable = useEditorState((state) => canUndo(state.history))
  const redoable = useEditorState((state) => canRedo(state.history))
  const doc = useEditorState((state) => state.history.present)
  const stats = timingStats(doc)
  const state = store.getState()

  const startTap = (mode: 'click' | 'hold') => {
    if (tapMode === mode) {
      state.stopTap()
      return
    }
    const current = store.getState()
    current.startTap(mode, current.selection[0] ?? refAtTime(doc, transport.now()))
  }

  const saveLabel =
    saveState === 'saved'
      ? t('editor.saved')
      : saveState === 'saving'
        ? t('editor.saving')
        : saveState === 'dirty'
          ? t('editor.unsaved')
          : t('editor.saveFailed')

  return (
    <div className="toolbar" role="toolbar">
      <button
        type="button"
        className="primary play"
        data-testid="play"
        onClick={() => void transport.toggle()}
        aria-label={playing ? t('editor.pause') : t('editor.play')}
      >
        {playing ? '❚❚' : '▶'}
      </button>
      <label>
        {t('editor.audio')}
        <select
          value={audioMode}
          data-testid="audio-mode"
          onChange={(event) => {
            const mode = event.target.value as AudioMode
            void transport.setMode(mode).then(() => store.getState().set({ audioMode: transport.mode }))
          }}
        >
          {transport.modes.map((mode) => (
            <option key={mode} value={mode}>
              {t(`editor.audio.${mode}`)}
            </option>
          ))}
        </select>
      </label>
      <label>
        {t('editor.rate')}
        <select
          value={rate}
          onChange={(event) => {
            const value = Number(event.target.value)
            transport.setRate(value)
            state.set({ rate: value })
          }}
        >
          {RATES.map((value) => (
            <option key={value} value={value}>
              {value}x
            </option>
          ))}
        </select>
      </label>
      <span className="separator" />
      <button type="button" disabled={!undoable || readOnly} onClick={() => state.undo()} title="Ctrl+Z">
        ↶ {t('editor.undo')}
      </button>
      <button type="button" disabled={!redoable || readOnly} onClick={() => state.redo()} title="Ctrl+Shift+Z">
        ↷ {t('editor.redo')}
      </button>
      <span className="separator" />
      <button
        type="button"
        className={tapMode === 'click' ? 'active' : undefined}
        disabled={readOnly}
        data-testid="tap-click"
        onClick={() => startTap('click')}
        title="1"
      >
        {t('editor.tap.click')}
      </button>
      <button
        type="button"
        className={tapMode === 'hold' ? 'active' : undefined}
        disabled={readOnly}
        data-testid="tap-hold"
        onClick={() => startTap('hold')}
        title="2"
      >
        {t('editor.tap.hold')}
      </button>
      <button type="button" disabled={readOnly} onClick={() => onDialog('realign')}>
        {t('editor.realign')}
      </button>
      <button type="button" disabled={readOnly} onClick={() => onDialog('shift')}>
        {t('editor.shift')}
      </button>
      <span className="separator" />
      <label className="check">
        <input type="checkbox" checked={snap} onChange={(event) => state.set({ snap: event.target.checked })} />
        {t('editor.snap')}
      </label>
      <label className="check">
        <input
          type="checkbox"
          checked={trackView === 'spectrogram'}
          onChange={(event) => state.set({ trackView: event.target.checked ? 'spectrogram' : 'waveform' })}
        />
        {t('editor.spectrogram')}
      </label>
      <span className="spacer" />
      <span className="stats" data-testid="stats">
        {t('editor.stats', {
          timed: stats.timed,
          tokens: stats.tokens,
          locked: stats.locked,
          low: stats.lowConfidence,
        })}
      </span>
      <span className={`save-state save-${saveState}`} data-testid="save-state">
        {saveLabel}
      </span>
      <button type="button" onClick={() => onDialog('theme')}>
        {t('editor.theme')}
      </button>
      <button type="button" className="primary" data-testid="open-export" onClick={() => onDialog('export')}>
        {t('editor.export')}
      </button>
      <button type="button" className="ghost" onClick={() => onDialog('help')} aria-label={t('editor.help')}>
        ?
      </button>
    </div>
  )
}
