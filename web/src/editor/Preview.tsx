/**
 * The preview: picture (source video or the theme's background), with the lyrics rendered by
 * JASSUB — libass compiled to WebAssembly — from the very ASS script an export burns in.
 *
 * JASSUB is used in "canvas" mode and told the time of every frame, so the preview follows
 * the editor's own clock (the selected audio mix), not a video element.
 */
import { useEffect, useRef, useState } from 'react'

import { api, toErrorBody } from '../api/client.ts'
import type { ApiErrorBody, FontEntry } from '../api/types.ts'
import { ErrorBox } from '../components/common.tsx'
import { useT } from '../i18n/index.ts'
import { useEditor, useEditorState } from './context.ts'

const PREVIEW_DELAY_MS = 250

interface Renderer {
  /** Replace the script; fonts it needs are loaded first, so that the next frame has them. */
  setTrack: (ass: string, fonts: FontEntry[]) => Promise<void>
  render: (timeMs: number, repaint: boolean) => void
  destroy: () => void
}

/**
 * Start JASSUB on `canvas`.
 *
 * `used` are the fonts the script needs: they are loaded before the first frame.  (Fonts
 * that are only *available* are fetched when a frame first asks for them, and that frame is
 * drawn without them — invisible lyrics while paused.)  `all` can be picked up later.
 */
async function createRenderer(
  canvas: HTMLCanvasElement,
  ass: string,
  used: FontEntry[],
  all: FontEntry[],
  size: [number, number],
): Promise<Renderer> {
  const { default: JASSUB } = await import('jassub')
  const available: Record<string, string> = {}
  for (const font of all) available[font.family.toLowerCase()] = font.url
  const loaded = new Set(used.map((font) => font.url))
  const instance = new JASSUB({
    canvas,
    subContent: ass,
    fonts: [...loaded],
    availableFonts: available,
    defaultFont: (used[0] ?? all[0])?.family.toLowerCase(),
    queryFonts: false,
  })
  await instance.ready
  return {
    setTrack: async (content, fonts) => {
      const missing = fonts.map((font) => font.url).filter((url) => !loaded.has(url))
      if (missing.length > 0) {
        await instance.renderer.addFonts(missing)
        for (const url of missing) loaded.add(url)
      }
      await instance.renderer.setTrack(content)
    },
    render: (timeMs, repaint) =>
      void instance.manualRender(
        {
          expectedDisplayTime: performance.now(),
          width: size[0],
          height: size[1],
          mediaTime: timeMs / 1000,
        },
        repaint,
      ),
    destroy: () => void instance.destroy(),
  }
}

export function Preview() {
  const t = useT()
  const { id, store, transport, media } = useEditor()
  const doc = useEditorState((state) => state.history.present)
  const canvas = useRef<HTMLCanvasElement>(null)
  const video = useRef<HTMLVideoElement>(null)
  const renderer = useRef<Renderer | null>(null)
  const [ready, setReady] = useState(false)
  const [failure, setFailure] = useState<ApiErrorBody | null>(null)
  const [width, height] = doc.render.resolution
  const hasVideo = doc.media.has_video && media.source !== null
  const hasTiming = doc.lines.some((line) => line.tokens.some((token) => token.start_ms !== null))
  const status = !hasTiming ? 'empty' : ready ? 'ready' : 'loading'

  // The picture follows the transport.
  useEffect(() => {
    const element = video.current
    transport.attachVideo(element)
    return () => transport.attachVideo(null)
  }, [transport, hasVideo])

  // Lyrics are drawn for every tick of the transport.
  useEffect(
    () => transport.subscribe((time) => renderer.current?.render(time, false)),
    [transport],
  )

  // Re-render the script shortly after the document changes.
  useEffect(() => {
    if (!hasTiming) return
    const run = { cancelled: false }
    // Read through a function: the flag changes while this effect's async work is waiting.
    const cancelled = () => run.cancelled
    const timer = window.setTimeout(() => {
      void (async () => {
        try {
          const result = await api.preview(id, store.getState().history.present)
          if (cancelled()) return
          const target = canvas.current
          if (!target) return
          if (renderer.current) {
            await renderer.current.setTrack(result.ass, result.fonts)
            if (cancelled()) return
          } else {
            const fonts = await api.fonts()
            if (cancelled()) return
            const created = await createRenderer(target, result.ass, result.fonts, fonts, [
              result.width,
              result.height,
            ])
            if (cancelled()) {
              created.destroy()
              return
            }
            renderer.current = created
          }
          setFailure(null)
          setReady(true)
          renderer.current.render(transport.now(), true)
        } catch (cause) {
          if (!cancelled()) setFailure(toErrorBody(cause))
        }
      })()
    }, PREVIEW_DELAY_MS)
    return () => {
      run.cancelled = true
      window.clearTimeout(timer)
    }
  }, [doc, hasTiming, id, store, transport])

  useEffect(
    () => () => {
      renderer.current?.destroy()
      renderer.current = null
    },
    [],
  )

  return (
    <section className="preview" aria-label="preview">
      <div
        className="preview-stage"
        data-testid="preview-stage"
        style={{ aspectRatio: `${width} / ${height}` }}
        onClick={() => void transport.toggle()}
      >
        {hasVideo && media.source ? (
          <video ref={video} src={media.source} muted playsInline preload="auto" />
        ) : (
          <div className="preview-backdrop" />
        )}
        <canvas ref={canvas} data-testid="preview-canvas" data-status={status} />
        {status === 'loading' && !failure ? <p className="preview-note">{t('editor.preview.loading')}</p> : null}
        {status === 'empty' ? <p className="preview-note">{t('editor.noTiming')}</p> : null}
      </div>
      {failure ? (
        <ErrorBox error={failure}>
          <small>{t('editor.preview.failed')}</small>
        </ErrorBox>
      ) : null}
    </section>
  )
}
